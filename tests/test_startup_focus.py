import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ok_ww_automator.ok_launcher import focus_game_window


class StartupFocusTests(unittest.TestCase):
    def setUp(self):
        self.window = Mock(hwnd=123)
        self.manager = SimpleNamespace(hwnd_window=self.window)
        self.gui = Mock()
        self.enterContext(patch.dict(sys.modules, {
            "win32gui": self.gui, "win32con": SimpleNamespace(SW_RESTORE=9),
        }))

    def test_minimized_window_is_restored_and_focus_verified(self):
        self.window.is_foreground.side_effect = [False, True]
        self.gui.IsIconic.return_value = True
        self.assertTrue(focus_game_window(self.manager))
        self.gui.ShowWindow.assert_called_once_with(123, 9)
        self.gui.SetForegroundWindow.assert_called_once_with(123)
        self.assertEqual(self.window.is_foreground.call_count, 2)

    def test_focus_request_without_actual_focus_is_not_success(self):
        self.window.is_foreground.return_value = False
        self.assertFalse(focus_game_window(self.manager))

    def test_foreground_window_is_not_disturbed(self):
        self.window.is_foreground.return_value = True
        self.assertTrue(focus_game_window(self.manager))
        self.gui.SetForegroundWindow.assert_not_called()
        self.gui.ShowWindow.assert_not_called()

    def test_denied_activation_is_retryable(self):
        self.window.is_foreground.return_value = False
        self.gui.SetForegroundWindow.side_effect = OSError("denied")
        with self.assertLogs("ok_ww_automator.ok_launcher", level="WARNING"):
            self.assertFalse(focus_game_window(self.manager))

    def test_missing_window_is_not_ready(self):
        self.assertFalse(focus_game_window(SimpleNamespace()))
        self.gui.SetForegroundWindow.assert_not_called()
