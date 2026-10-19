from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from ok_ww_automator import diagnostics
from ok_ww_automator.game_clients import ensure_main_with_evidence


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        # Core CI intentionally has no game/desktop dependencies installed.
        self.pil = ModuleType("PIL")
        self.pil.ImageGrab = Mock()
        modules = patch.dict(sys.modules, {"PIL": self.pil})
        modules.start()
        self.addCleanup(modules.stop)

    def test_screenshot_failure_preserves_navigation_error(self):
        task = Mock()
        task.ensure_main.side_effect = RuntimeError("not in world")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(diagnostics, "_directory", Path(directory)), \
                patch.object(self.pil.ImageGrab, "grab", side_effect=OSError("desktop unavailable")):
            with self.assertRaisesRegex(RuntimeError, "not in world"):
                ensure_main_with_evidence(task)

    def test_capture_includes_attempt_label_and_precedes_error_return(self):
        task = Mock()
        task.ensure_main.side_effect = RuntimeError("not in world")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(diagnostics, "_directory", Path(directory)), \
                patch.object(diagnostics, "_label", "CN-stamina-read"), \
                patch.object(self.pil.ImageGrab, "grab") as grab:
            with self.assertRaisesRegex(RuntimeError, "not in world"):
                ensure_main_with_evidence(task)
            grab.assert_called_once_with(all_screens=True)
            path = grab.return_value.save.call_args.args[0]
            self.assertEqual(path.parent, Path(directory))
            self.assertIn("CN-stamina-read", path.name)
            self.assertTrue(path.name.endswith("-wait-main.png"))

    def test_success_does_not_capture(self):
        with patch("ok_ww_automator.game_clients.save_failure_screenshot") as capture:
            ensure_main_with_evidence(Mock())
        capture.assert_not_called()

    def test_missing_pillow_preserves_navigation_error(self):
        task = Mock()
        task.ensure_main.side_effect = RuntimeError("not in world")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(diagnostics, "_directory", Path(directory)), \
                patch.dict(sys.modules, {"PIL": None}), \
                self.assertLogs(diagnostics.logger, level="WARNING") as logs:
            with self.assertRaisesRegex(RuntimeError, "not in world"):
                ensure_main_with_evidence(task)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertIn("Could not save failure screenshot", logs.output[0])
