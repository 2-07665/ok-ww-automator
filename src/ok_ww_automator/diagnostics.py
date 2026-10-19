"""Best-effort desktop evidence for isolated game attempts."""

from datetime import datetime
import logging
import os
from pathlib import Path
import re

logger = logging.getLogger(__name__)
_directory: Path | None = None
_label = ""


def configure_screenshots(directory: Path, label: str) -> None:
    global _directory, _label
    _directory = directory
    _label = re.sub(r"[^\w.-]", "_", label)


def save_failure_screenshot(stage: str) -> Path | None:
    # Only the isolated entry point opts in; imports and offline tests do not
    # access the desktop. Capture independently of a broken OK runtime.
    if _directory is None:
        return None
    try:
        from PIL import ImageGrab

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = _directory / f"{stamp}-{_label}-{os.getpid()}-{stage}.png"
        _directory.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(all_screens=True).save(path)
        logger.warning("Failure screenshot saved: %s", path)
        return path
    except Exception:
        logger.warning("Could not save failure screenshot (%s)", stage, exc_info=True)
        return None
