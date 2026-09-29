from contextlib import redirect_stderr, redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ok_ww_automator import doctor, scheduler, sheets
from ok_ww_automator.config import AppConfig, RetryConfig, WeeklyRunConfig
from ok_ww_automator.game_clients import WeeklyGameOutcome
from ok_ww_automator.models import RunResult, SheetRunConfig
from ok_ww_automator.time_utils import BEIJING_TZ
from ok_ww_automator.weekly import WeeklyRunner


class ConsoleOutputTest(unittest.TestCase):
    def stream(self, encoding="cp1252"):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding=encoding, errors="strict", write_through=True)
        self.addCleanup(stream.close)
        return stream, buffer

    def test_weekly_reporting_preserves_results_and_durable_success_on_legacy_stdout(self):
        stamp = dt.datetime(2026, 9, 28, 5, tzinfo=BEIJING_TZ)
        for encoding in ("cp1252", "utf-8"):
            for completed in (True, False):
                with self.subTest(encoding=encoding, completed=completed), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    config = AppConfig(root, root / "账号.env", game_server="CN", retry=RetryConfig(1, 0),
                                       weekly_run=WeeklyRunConfig(notice_day=1))
                    game = Mock()
                    game.run_weekly.return_value = WeeklyGameOutcome(completed, "奖励读取失败😀")
                    runner = WeeklyRunner(config, game, clock=lambda: stamp)
                    stream, buffer = self.stream(encoding)
                    with redirect_stdout(stream):
                        result = runner.run()
                        if completed:
                            self.assertEqual(runner.run().status, "skipped")
                    self.assertEqual(result.status, "success" if completed else "failure")
                    game.run_weekly.assert_called_once()
                    text = buffer.getvalue().decode(encoding)
                    self.assertIn("奖励读取失败😀" if encoding == "utf-8" else r"\u5956", text)
                    self.assertEqual((stream.encoding, stream.errors), (encoding, "strict"))

    def test_scheduler_unicode_accounts_and_errors_do_not_change_exit_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "自动化"
            (root / "env").mkdir(parents=True)
            (root / "env" / "账号.env").touch()
            stamp = dt.datetime(2026, 9, 28, tzinfo=BEIJING_TZ)
            for fails in (False, True):
                with self.subTest(fails=fails):
                    stream, buffer = self.stream()
                    with (
                        redirect_stdout(stream), redirect_stderr(stream),
                        patch.object(scheduler, "run_mode", return_value=RunResult("daily", stamp, stamp, "success"),
                                     side_effect=RuntimeError("任务失败😀") if fails else None),
                    ):
                        code = scheduler.main(["--project-root", str(root), "--mode", "daily", "--skip-update"])
                    self.assertEqual(code, int(fails))
                    self.assertIn(r"\u8d26\u53f7", buffer.getvalue().decode("cp1252"))
                    if fails:
                        self.assertIn("ERROR:", buffer.getvalue().decode("cp1252"))

    def test_doctor_json_round_trips_non_ascii_and_supplementary_characters(self):
        detail = "接口不匹配😀"
        stream, buffer = self.stream()
        with redirect_stdout(stream), patch.object(doctor, "diagnose", return_value=[doctor.Finding("FAIL", "api", detail)]):
            code = doctor.main(["--json", "--source-only", "--ok-script-root", "."])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buffer.getvalue())[0]["detail"], detail)

    def test_doctor_human_report_handles_legacy_stdout(self):
        stream, buffer = self.stream()
        with redirect_stdout(stream), patch.object(doctor, "diagnose", return_value=[doctor.Finding("WARN", "api", "接口变更😀")]):
            code = doctor.main(["--strict", "--source-only", "--ok-script-root", "."])
        self.assertEqual(code, 1)
        self.assertIn(b"1 WARN", buffer.getvalue())

    def test_sheets_cli_json_keeps_unicode_values_on_legacy_stdout(self):
        store = Mock()
        store.parser.to_run_config.return_value = SheetRunConfig(tacet_name="无音区😀")
        stream, buffer = self.stream()
        with (
            redirect_stdout(stream), patch.object(sheets, "load_config"),
            patch.object(sheets.GoogleSheetsStore, "from_config", return_value=store),
        ):
            code = sheets.main([])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["tacet_name"], "无音区😀")
