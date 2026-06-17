"""Run one game-client operation in an isolated child process."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import traceback

from .config import load_config
from .game_clients import OkDailyGameClient, OkStaminaGameClient
from .models import SheetRunConfig
from .ok_launcher import OkLauncher


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = Path(args.output)
    try:
        sheet_config = read_sheet_config(Path(args.input))
        app_config = load_config(
            project_root=Path(args.project_root),
            env_file=Path(args.env_file),
        )
        launcher = OkLauncher.from_app_config(app_config, ww_root=Path(args.ww_root))
        payload = run_operation(args.mode, args.operation, launcher, sheet_config)
        write_payload(output_path, payload)
        return 0
    except Exception as exc:
        write_payload(
            output_path,
            {"error": "".join(traceback.format_exception_only(type(exc), exc)).strip()},
        )
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one isolated ok-ww game attempt.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--ww-root", required=True)
    parser.add_argument("--mode", choices=["daily", "stamina"], required=True)
    parser.add_argument("--operation", choices=["run", "read"], required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def read_sheet_config(input_path: Path) -> SheetRunConfig:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    return SheetRunConfig(**payload["sheet_config"])


def run_operation(mode: str, operation: str, launcher: OkLauncher, sheet_config: SheetRunConfig) -> dict:
    if mode == "daily" and operation == "run":
        return asdict(OkDailyGameClient(launcher).run_daily(sheet_config))
    if mode == "stamina" and operation == "read":
        client = OkStaminaGameClient(launcher)
        try:
            stamina, backup_stamina = client.read_stamina(sheet_config)
            return {"stamina": stamina, "backup_stamina": backup_stamina}
        finally:
            client.close(sheet_config)
    if mode == "stamina" and operation == "run":
        client = OkStaminaGameClient(launcher)
        try:
            return asdict(client.run_stamina(sheet_config))
        finally:
            client.close(sheet_config)
    raise RuntimeError(f"Unsupported game attempt: {mode}/{operation}")


def write_payload(output_path: Path, payload: dict) -> None:
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
