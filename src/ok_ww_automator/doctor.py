"""Read-only upstream contract checks; never import or start the game runtime."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import hashlib
from importlib import metadata
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

from .console import console_print


CONTRACTS = Path(__file__).with_name("upstream_contracts.json")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Finding:
    status: str
    check: str
    detail: str


def fingerprint(node: ast.AST) -> str:
    """Ignore formatting/comments, but surface semantic changes for human review."""
    # ast.dump's empty-field formatting changed in Python 3.13. Canonicalize
    # fields ourselves so Linux source review agrees with Windows Python 3.12.
    def canonical(value):
        if isinstance(value, ast.AST):
            return {"node": type(value).__name__, **{
                name: canonical(child) for name, child in ast.iter_fields(value)
                if child is not None and child != []}}
        if isinstance(value, list):
            return [canonical(child) for child in value]
        if isinstance(value, (bytes, complex)) or value is Ellipsis:
            return repr(value)
        return value

    data = json.dumps(canonical(node), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(data.encode()).hexdigest()


def find_node(tree: ast.AST, symbol: str) -> ast.AST:
    node = tree
    for name in symbol.split("."):
        node = next((child for child in getattr(node, "body", [])
                     if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                     and child.name == name), None)
        if node is None:
            raise ValueError(f"missing symbol {symbol}")
    return node


def check_call(node: ast.FunctionDef, positional: int, keywords: list[str]) -> None:
    """Bind the real call shape, including newly required upstream arguments."""
    args = node.args
    positional_args = args.posonlyargs + args.args
    defaults_start = len(positional_args) - len(args.defaults)
    parameters = []
    for index, arg in enumerate(positional_args):
        if index == 0 and arg.arg in {"self", "cls"}:
            continue
        kind = (inspect.Parameter.POSITIONAL_ONLY if index < len(args.posonlyargs)
                else inspect.Parameter.POSITIONAL_OR_KEYWORD)
        default = None if index >= defaults_start else inspect.Parameter.empty
        parameters.append(inspect.Parameter(arg.arg, kind, default=default))
    if args.vararg:
        parameters.append(inspect.Parameter(args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parameters.append(inspect.Parameter(
            arg.arg, inspect.Parameter.KEYWORD_ONLY,
            default=None if default is not None else inspect.Parameter.empty))
    if args.kwarg:
        parameters.append(inspect.Parameter(args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    inspect.Signature(parameters).bind(*([None] * positional), **dict.fromkeys(keywords))


def assignments(tree: ast.AST, target: str) -> list[ast.AST]:
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
            and any(ast.unparse(item) == target for item in node.targets)]


def check_contract(tree: ast.AST, contract: dict) -> list[Finding]:
    name = contract["id"]
    location = contract["file"]
    try:
        node = find_node(tree, contract["symbol"]) if "symbol" in contract else tree
        kind = contract["kind"]
        if kind == "call":
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                raise ValueError("symbol is no longer callable")
            check_call(node, contract.get("positional", 0), contract.get("keywords", []))
        elif kind == "assignment":
            values = assignments(node, contract["target"])
            if not values or ast.literal_eval(values[-1]) != contract["value"]:
                raise ValueError(f"{contract['target']} changed; expected {contract['value']!r}")
        elif kind == "dict_keys":
            keys = {item.value for value in ast.walk(node) if isinstance(value, ast.Dict)
                    for item in value.keys if isinstance(item, ast.Constant)}
            missing = set(contract["values"]) - keys
            if missing:
                raise ValueError(f"missing dictionary keys: {sorted(missing)}")
        elif kind == "lazy_exports":
            values = assignments(tree, contract["target"])
            mapping = ast.literal_eval(values[-1]) if values else {}
            if not isinstance(mapping, dict):
                raise ValueError("lazy exports are no longer a dictionary literal")
            changed = []
            for exported, expected in contract["values"].items():
                actual = mapping.get(exported)
                if not isinstance(actual, (tuple, list)) or list(actual) != expected:
                    changed.append(exported)
            if changed:
                raise ValueError(f"missing or redirected public exports: {sorted(changed)}")
        elif kind == "literals":
            values = {item.value for item in ast.walk(node) if isinstance(item, ast.Constant)
                      and isinstance(item.value, (str, int, float))}
            missing = set(contract["values"]) - values
            if missing:
                raise ValueError(f"missing contract values: {sorted(missing, key=str)}")
        elif kind == "registrations":
            config = assignments(tree, "config")
            if not config or not isinstance(config[-1], ast.Dict):
                raise ValueError("config is no longer a dictionary literal; review registration")
            pairs = zip(config[-1].keys, config[-1].values)
            tasks = next(value for key, value in pairs
                         if isinstance(key, ast.Constant) and key.value == "onetime_tasks")
            registered = ast.literal_eval(tasks)
            missing = [item for item in contract["values"] if item not in registered]
            if missing:
                raise ValueError(f"missing one-time task registrations: {missing}")
        elif kind != "symbol":
            raise ValueError(f"unknown contract kind {kind}")
        if contract.get("sha256") and fingerprint(node) != contract["sha256"]:
            return [Finding("WARN", name, f"{location}: implementation changed; {contract['reason']}")]
        return [Finding("PASS", name, location)]
    except (ValueError, TypeError, StopIteration, SyntaxError) as exc:
        return [Finding("FAIL", name, f"{location}: {exc}. {contract['reason']}")]


def inspect_sources(roots: dict[str, Path], manifest: dict) -> list[Finding]:
    findings = []
    parsed: dict[Path, ast.AST | Exception] = {}
    for contract in manifest["checks"]:
        path = roots[contract["root"]] / contract["file"]
        if path not in parsed:
            try:
                parsed[path] = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            except (OSError, UnicodeError, SyntaxError) as exc:
                parsed[path] = exc
        tree = parsed[path]
        if isinstance(tree, Exception):
            findings.append(Finding("FAIL", contract["id"], f"cannot read {path}: {tree}"))
        else:
            findings.extend(check_contract(tree, contract))
    return findings


def git_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def installed_ok_root() -> Path | None:
    # Follow editable installs through import discovery without executing ok/__init__.py.
    import importlib.util
    try:
        spec = importlib.util.find_spec("ok")
        if spec and spec.origin:
            return Path(spec.origin).resolve().parent.parent
    except (ImportError, ValueError):
        pass
    return None


def check_environment(ww_root: Path) -> list[Finding]:
    results = [Finding("PASS" if sys.version_info[:2] == (3, 12) else "FAIL", "python",
                       f"{sys.version.split()[0]} at {sys.executable}; Python 3.12 required"),
               Finding("PASS" if os.name == "nt" else "FAIL", "platform",
                       "Game execution and launcher require Windows")]
    try:
        import re
        requirements = (ww_root / "requirements.txt").read_text(encoding="utf-8-sig")
        match = re.search(r"(?mi)^ok-script(?:\[[^]]+\])?==([^\s;]+)", requirements)
        installed = metadata.version("ok-script")
        if match is None:
            results.append(Finding("WARN", "ok-script.version", "Upstream no longer pins ok-script; review dependency policy"))
        else:
            results.append(Finding("PASS" if match[1] == installed else "FAIL", "ok-script.version",
                                   f"installed {installed}; upstream requires {match[1]}"))
    except (OSError, metadata.PackageNotFoundError) as exc:
        results.append(Finding("FAIL", "ok-script.version", str(exc)))
    for package in ("PySide6", "PySide6-Fluent-Widgets", "psutil", "onnxocr-ppocrv5", "opencv-python"):
        try:
            results.append(Finding("PASS", f"dependency.{package}", metadata.version(package)))
        except metadata.PackageNotFoundError:
            results.append(Finding("FAIL", f"dependency.{package}", "Install upstream requirements into this interpreter"))
    return results


def check_remote(manifest: dict) -> list[Finding]:
    results = []
    for name, baseline in manifest["upstreams"].items():
        try:
            proc = subprocess.run(["git", "ls-remote", baseline["url"], "HEAD"],
                                  capture_output=True, text=True, timeout=30, check=False,
                                  env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
            if proc.returncode or not proc.stdout.strip():
                raise ValueError("remote HEAD unavailable; check network and Git access")
            head = proc.stdout.split()[0]
            results.append(Finding("PASS" if head == baseline["revision"] else "WARN",
                                   f"remote.{name}", f"HEAD {head}; reviewed {baseline['revision']}"))
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            results.append(Finding("WARN", f"remote.{name}", str(exc)))
    return results


def diagnose(*, ww_root: Path, ok_root: Path | None, source_only: bool,
             remote: bool = False, manifest: dict | None = None) -> list[Finding]:
    if manifest is None:
        manifest = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    findings = [] if source_only else check_environment(ww_root)
    if ok_root is None:
        findings.append(Finding("FAIL", "ok-script.source", "Cannot locate installed ok. Install upstream requirements, or supply --ok-script-root for source review."))
        # Still check the game checkout when the dependency is missing.
        manifest = {**manifest, "checks": [c for c in manifest["checks"] if c["root"] == "ww"]}
    roots = {"ww": ww_root, "ok": ok_root}
    for name, root in roots.items():
        if root is None:
            continue
        findings.append(Finding("PASS" if root.is_dir() else "FAIL", f"source.{name}",
                                f"{root}; Git HEAD {git_revision(root) or 'not a Git checkout'}"))
    findings.extend(inspect_sources(roots, manifest))
    try:
        data = json.loads((ww_root / "assets/coco_annotations.json").read_text(encoding="utf-8"))
        names = {entry["name"] for entry in data["categories"]}
        missing = set(manifest["features"]) - names
        findings.append(Finding("FAIL" if missing else "PASS", "game.features",
                                f"missing {sorted(missing)}" if missing else "Required feature labels are present"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        findings.append(Finding("FAIL", "game.features", str(exc)))
    if remote:
        findings.extend(check_remote(manifest))
    for item in manifest["manual_checks"]:
        findings.append(Finding("MANUAL", item["id"], item["reason"]))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ww-root", type=Path, default=PROJECT_ROOT.parent / "ok-wuthering-waves")
    parser.add_argument("--ok-script-root", type=Path, help="Checkout/package parent containing ok/. Default: actual interpreter's installed ok.")
    parser.add_argument("--source-only", action="store_true", help="Skip Windows/interpreter/dependency checks for offline source review")
    parser.add_argument("--check-remote", action="store_true", help="Compare reviewed revisions with remote HEAD (network, read-only)")
    parser.add_argument("--strict", action="store_true", help="Return 1 on warnings as well as failures")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable findings")
    args = parser.parse_args(argv)
    results = diagnose(ww_root=args.ww_root.resolve(),
                       ok_root=args.ok_script_root.resolve() if args.ok_script_root else installed_ok_root(),
                       source_only=args.source_only, remote=args.check_remote)
    if args.json:
        console_print(json.dumps([asdict(item) for item in results], ensure_ascii=True, indent=2))
    else:
        for item in results:
            console_print(f"[{item.status}] {item.check}: {item.detail}")
        counts = {status: sum(item.status == status for item in results)
                  for status in ("PASS", "WARN", "FAIL", "MANUAL")}
        console_print("\n" + ", ".join(f"{count} {status}" for status, count in counts.items()))
        console_print("Source checks cannot verify live capture, OCR, combat, or external services. See docs/maintenance.md.")
    return int(any(item.status == "FAIL" or (args.strict and item.status == "WARN") for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
