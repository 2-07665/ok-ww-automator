import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ok_ww_automator.ok_main import main


if __name__ == "__main__":
    raise SystemExit(main())
