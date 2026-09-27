"""Farm in the current game until the chosen Beijing time, then shut down."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import subprocess
import time

from .time_utils import BEIJING_TZ, parse_time_of_day


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ww-root", type=Path, default=Path(__file__).resolve().parents[3] / "ok-wuthering-waves")
    parser.add_argument("--stop-time", type=parse_time_of_day, default="03:00", help="Beijing time (HH:MM), default 03:00.")
    args = parser.parse_args(argv)

    now = dt.datetime.now(BEIJING_TZ)
    target = dt.datetime.combine(now.date(), args.stop_time, tzinfo=BEIJING_TZ)
    if target <= now:
        target += dt.timedelta(days=1)
    stop_at = time.monotonic() + (target - now).total_seconds()
    print(f"Auto Farm: use current game; stop and shut down at {target:%Y-%m-%d %H:%M} Beijing time.", flush=True)

    from .ok_launcher import run_auto_farm

    run_auto_farm(args.ww_root.resolve(), stop_at=stop_at)
    print("Auto Farm complete. Shutting down in 5 seconds.", flush=True)
    subprocess.run(["shutdown.exe", "/s", "/t", "5"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
