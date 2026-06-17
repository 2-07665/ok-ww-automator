"""Manual OK GUI launcher with ok-ww-automator extra tasks."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
from typing import Any

from .ok_launcher import ww_runtime_context

DEFAULT_WW_ROOT = Path(__file__).resolve().parents[3] / "ok-wuthering-waves"

EXTRA_ONETIME_TASKS: tuple[tuple[str, str], ...] = (
    ("ok_ww_automator.ok_tasks.fast_farm_echo", "FastFarmEchoTask"),
    ("ok_ww_automator.ok_tasks.five_to_one", "FiveToOneTask"),
    ("ok_ww_automator.ok_tasks.echo_ocr", "EchoOCRTask"),
)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ww_root = Path(args.ww_root).resolve() if args.ww_root else DEFAULT_WW_ROOT.resolve()

    with ww_runtime_context(ww_root):
        config_module = importlib.import_module("config")
        ok_module = importlib.import_module("ok")
        config = build_ok_config(config_module.config)
        ok = ok_module.OK(config)
        ok.start()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch upstream OK-WW with ok-ww-automator extra tasks.")
    parser.add_argument("--ww-root", help="Path to ok-wuthering-waves. Defaults beside this repo.")
    return parser.parse_args(argv)


def build_ok_config(base_config: dict[str, Any]) -> dict[str, Any]:
    config = dict(base_config)
    onetime_tasks = [list(task) for task in config.get("onetime_tasks", [])]
    existing = {tuple(task) for task in onetime_tasks if isinstance(task, (list, tuple)) and len(task) == 2}

    for task in EXTRA_ONETIME_TASKS:
        if task not in existing:
            onetime_tasks.append(list(task))
            existing.add(task)

    config["onetime_tasks"] = onetime_tasks
    return config


if __name__ == "__main__":
    raise SystemExit(main())
