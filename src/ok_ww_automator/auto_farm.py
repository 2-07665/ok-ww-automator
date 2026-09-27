"""Farm in the current game until the chosen system-local time, then shut down."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import subprocess
import time

from .time_utils import parse_time_of_day
from .farm_progress import FarmProgress, emit_progress


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ww-root", type=Path, default=Path(__file__).resolve().parents[3] / "ok-wuthering-waves")
    parser.add_argument("--stop-time", type=parse_time_of_day, default="03:00", help="System-local time (HH:MM), default 03:00.")
    args = parser.parse_args(argv)

    now = dt.datetime.now()
    target = dt.datetime.combine(now.date(), args.stop_time)
    if target <= now:
        target += dt.timedelta(days=1)
    remaining = target.timestamp() - now.timestamp()
    stop_at = time.monotonic() + remaining
    print(f"Auto Farm: use current game; stop and shut down at {target:%Y-%m-%d %H:%M} system-local time.", flush=True)
    emit_progress(FarmProgress("connecting", remaining=remaining))

    from .ok_launcher import run_auto_farm

    try:
        run_auto_farm(args.ww_root.resolve(), stop_at=stop_at, on_progress=emit_progress)
        subprocess.run(["shutdown.exe", "/s", "/t", "5"], check=True)
    except Exception as exc:
        emit_progress(FarmProgress("failed", message=str(exc)))
        raise
    emit_progress(FarmProgress("shutdown", message="已到结束时间，系统将在 5 秒后关机。"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
