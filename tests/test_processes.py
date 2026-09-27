import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.processes import run_with_timeout


class ProcessTimeoutTest(unittest.TestCase):
    def test_cleanup_failure_preserves_original_timeout_and_kills_parent(self):
        deadline_error = subprocess.TimeoutExpired("worker", 1)
        process = Mock(pid=123)
        process.wait.side_effect = [deadline_error, 1]
        process.poll.return_value = None
        with (
            patch("ok_ww_automator.processes.os.name", "nt"),
            patch("ok_ww_automator.processes.subprocess.Popen", return_value=process),
            patch("ok_ww_automator.processes.subprocess.run", side_effect=OSError("taskkill unavailable")),
            self.assertRaises(subprocess.TimeoutExpired) as caught,
        ):
            run_with_timeout(["worker"], timeout=1)
        self.assertIs(caught.exception, deadline_error)
        self.assertIn("taskkill unavailable", " ".join(caught.exception.__notes__))
        process.kill.assert_called_once()
        process.wait.assert_called_with(timeout=5)
