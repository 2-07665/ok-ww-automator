"""Farm until the chosen time, wait in place, merge echoes, then shut down."""

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
    print(f"Auto Farm: stop farming at {target:%Y-%m-%d %H:%M} system-local time; wait 300 seconds, merge echoes, then shut down.", flush=True)
    emit_progress(FarmProgress("connecting", remaining=remaining))

    from .ok_launcher import run_auto_farm

    try:
        merge_error = run_auto_farm(args.ww_root.resolve(), stop_at=stop_at, on_progress=emit_progress)
        if merge_error:
            emit_progress(FarmProgress("failed", message=f"五合一失败：{merge_error}"))
        subprocess.run(["shutdown.exe", "/s", "/t", "5"], check=True)
    except Exception as exc:
        emit_progress(FarmProgress("failed", message=str(exc)))
        raise
    message = f"五合一失败：{merge_error}；系统将在 5 秒后关机。" if merge_error else "五合一已完成，系统将在 5 秒后关机。"
    emit_progress(FarmProgress("shutdown", message=message))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
