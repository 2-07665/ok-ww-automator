import base64
from contextlib import redirect_stdout
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import GoogleSheetsConfig
from ok_ww_automator.models import RunResult


SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/debug-automator/scripts/recent_results.py"
spec = importlib.util.spec_from_file_location("recent_results", SCRIPT)
reports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reports)
DAY = dt.date(2026, 9, 27)


def result_row(start="2026-09-27 10:00:00", end="2026-09-27 10:10:00", status="failure", mode="daily",
               error="OCR failed", decision="retry exhausted"):
    result = RunResult(mode, dt.datetime.fromisoformat(start), dt.datetime.fromisoformat(end), status,
                       stamina_start=240, backup_stamina_start=100, stamina_used=40,
                       stamina_left=200, backup_stamina_left=100, daily_points=80,
                       sign_in_success=True, decision=decision, error=error)
    return result.as_daily_row() if mode == "daily" else result.as_stamina_row()


class Worksheet:
    """Fake supports reads only; occupied length must not come from grid capacity."""

    def __init__(self, rows, detail_rows=None, fail_batch=None):
        self.rows = rows
        self.detail_rows = detail_rows or {}
        self.fail_batch = fail_batch
        self.calls = []

    @property
    def row_count(self):
        raise AssertionError("allocated grid length is not occupied length")

    def get(self, range_name, **options):
        assert range_name == "A:D"
        assert options == {"value_render_option": "UNFORMATTED_VALUE", "date_time_render_option": "SERIAL_NUMBER"}
        return [row[:4] for row in self.rows]

    def batch_get(self, ranges, **options):
        assert options == {"value_render_option": "UNFORMATTED_VALUE", "date_time_render_option": "SERIAL_NUMBER"}
        self.calls.append(ranges)
        if self.fail_batch == len(self.calls):
            raise RuntimeError("request https://oauth.example/?token=TOP_SECRET; private response: TOP_SECRET")
        values = []
        for range_name in ranges:
            match = re.fullmatch(r"A(\d+):[MP]\1", range_name)
            assert match, range_name
            number = int(match[1])
            row = self.detail_rows.get(number, self.rows[number - 1])
            values.append([row] if row else [])
        return values


def read(worksheet, **overrides):
    args = dict(mode="daily", day=DAY, limit=5, max_scan_rows=200, failures=False)
    args.update(overrides)
    return reports.read_reports(worksheet, **args)


class RecentResultsTests(unittest.TestCase):
    def test_auth_uses_only_readonly_scope_and_sanitizes_rejected_credentials(self):
        credentials_factory = Mock(return_value=object())
        service_account = ModuleType("google.oauth2.service_account")
        service_account.Credentials = SimpleNamespace(from_service_account_info=credentials_factory)
        client = Mock()
        gspread = ModuleType("gspread")
        gspread.authorize = Mock(return_value=client)
        credential_data = {"private_key": "fixture secret", "client_email": "test@example.invalid"}
        config = GoogleSheetsConfig("sheet-id", base64.b64encode(json.dumps(credential_data).encode()).decode())
        with patch.dict(sys.modules, {"gspread": gspread, "google": ModuleType("google"),
                                     "google.oauth2": ModuleType("google.oauth2"),
                                     "google.oauth2.service_account": service_account}):
            self.assertIs(reports.open_readonly_spreadsheet(config), client.open_by_key.return_value)
            credentials_factory.assert_called_once_with(
                credential_data, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
            client.open_by_key.assert_called_once_with("sheet-id")
            credentials_factory.side_effect = ValueError("fixture secret")
            with self.assertRaises(reports.ReportError) as raised:
                reports.open_readonly_spreadsheet(config)
            self.assertNotIn("fixture secret", str(raised.exception))

    def test_midnight_serial_dates_and_uncertain_rows_keep_real_row_numbers(self):
        crossing = result_row("2026-09-26 23:50:00", "2026-09-27 00:10:00")
        epoch = dt.datetime(1899, 12, 30)
        crossing[:2] = [(dt.datetime.fromisoformat(value) - epoch).total_seconds() / 86400 for value in crossing[:2]]
        success = result_row(status="success")
        future = result_row("2026-09-28 00:00:00", "2026-09-28 00:10:00")
        uncertain = ["", "", "", "needs review"]  # Trailing cells legitimately omitted by Sheets.
        sheet = Worksheet([["started_at", "ended_at", "duration", "status"], crossing, [], success,
                           future, uncertain] + [[]] * 1000)
        output = read(sheet, failures=True)
        self.assertEqual([item["row"] for item in output["results"]], [2, 6])
        self.assertEqual(output["results"][0]["started_at"], "2026-09-26 23:50:00")
        self.assertFalse(output["results"][1]["timestamps_valid"])
        self.assertEqual(output["results"][1]["error"], "")
        self.assertEqual(output["indexed_rows"], 4)
        self.assertEqual(output["invalid_timestamp_rows"], 1)
        self.assertTrue(output["incomplete"])
        self.assertEqual(output["rows_read"], 3)

    def test_recency_uses_timestamps_and_writer_wall_time_not_sheet_sort_or_host_zone(self):
        latest = result_row("2026-09-27 23:00:00", "2026-09-27 23:10:00")
        offset = result_row()
        offset[:2] = ["2026-09-27T00:01:00+08:00", "2026-09-27T00:10:00+08:00"]
        oldest = result_row("2026-09-26 23:58:00", "2026-09-27 00:00:00")
        sheet = Worksheet([latest, [], offset, oldest])
        output = read(sheet, limit=2)
        self.assertEqual([item["row"] for item in output["results"]], [1, 3])
        self.assertEqual(output["results"][1]["started_at"], "2026-09-27 00:01:00")
        self.assertFalse(output["incomplete"])
        self.assertEqual(output["rows_read"], 2)

    def test_scan_budget_is_explicit_and_details_are_rechecked_after_index(self):
        old_failure = result_row("2026-09-27 09:00:00", "2026-09-27 09:10:00")
        sheet = Worksheet([old_failure, result_row(status="success"), result_row(status="success")])
        output = read(sheet, failures=True, max_scan_rows=2)
        self.assertEqual(output["results"], [])
        self.assertEqual(output["rows_read"], 2)
        self.assertTrue(output["incomplete"])
        self.assertIn("--max-scan-rows", " ".join(output["warnings"]))

        moved = result_row("2026-09-28 00:00:00", "2026-09-28 00:10:00")
        sheet = Worksheet([old_failure, result_row()], detail_rows={1: result_row(status="success"), 2: moved})
        output = read(sheet, failures=True)
        self.assertEqual(output["results"], [])
        self.assertEqual(output["changed_rows"], 2)
        self.assertTrue(output["incomplete"])

    def test_partial_batch_failure_preserves_previous_reports_without_raw_exception(self):
        rows = [result_row(status="failure" if index in (0, 50) else "success") for index in range(51)]
        output = read(Worksheet(rows, fail_batch=2), failures=True)
        self.assertEqual([item["row"] for item in output["results"]], [51])
        self.assertEqual(output["rows_read"], 50)
        self.assertTrue(output["incomplete"])
        self.assertIn("error", output)
        self.assertNotIn("TOP_SECRET", json.dumps(output))
        self.assertNotIn("oauth.example", json.dumps(output))

    def test_real_model_schemas_and_redaction_before_truncation(self):
        secret = "configured-token-secret"
        private_key = "-----BEGIN PRIVATE KEY-----\nfixture-private-value\n-----END PRIVATE KEY-----\n"
        encoded = base64.b64encode(json.dumps({"private_key": private_key}).encode()).decode()
        secrets = reports.configured_secrets({"GOOGLE_SERVICE_ACCOUNT_JSON_BASE64": encoded, "WAVES_TOKEN": secret})
        error = "x" * (reports.TEXT_LIMIT - 5) + secret + " remaining" * 100
        decision = (f"Bearer unknown-token https://a.invalid/?api_key=query-secret {private_key} {encoded} "
                    "-----BEGIN PRIVATE KEY-----\\nold-unconfigured-truncated-key")
        for mode in ("daily", "stamina"):
            with self.subTest(mode=mode):
                sheet = Worksheet([result_row(mode=mode, error=error, decision=decision)])
                output = read(sheet, mode=mode, secrets=secrets)
                item = output["results"][0]
                self.assertEqual(item["metrics"]["stamina_used"], "40")
                self.assertEqual("daily_points" in item["metrics"], mode == "daily")
                self.assertEqual(len(item["error"]), reports.TEXT_LIMIT)
                self.assertIn("error", item["truncated_fields"])
                self.assertIn("[REDACTED]", item["decision"])
                for value in (secret, secret[:6], "unknown-token", "query-secret", "fixture-private-value", encoded,
                              "old-unconfigured-truncated-key"):
                    self.assertNotIn(value, json.dumps(output))

    def test_profiles_respect_overrides_flag_unselected_shared_destinations_and_ignore_unrelated_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "env").mkdir()
            for account in ("CN", "US"):
                (root / "env" / f"{account}.env").write_text(
                    f"GOOGLE_SHEET_ID={account}-sheet\nGOOGLE_SERVICE_ACCOUNT_JSON_BASE64={account}-secret\n"
                    "SHEET_NAME_DAILY=Shared\nRETRY_MAX_ATTEMPTS=invalid\nDAILY_HOUR=invalid\n", encoding="utf-8")
            opened = []
            def opener(config):
                opened.append(config)
                return SimpleNamespace(worksheet=lambda title: Worksheet([result_row(error="overridden-secret")]))
            output = reports.collect_reports(
                root, accounts=["CN"], mode="daily", env={"GOOGLE_SHEET_ID": "shared-sheet",
                "GOOGLE_SERVICE_ACCOUNT_JSON_BASE64": "overridden-secret"}, opener=opener)
            self.assertEqual(len(opened), 1)
            self.assertEqual(opened[0].spreadsheet_id, "shared-sheet")
            self.assertEqual(opened[0].service_account_json_base64, "overridden-secret")
            self.assertEqual(output["reports"][0]["shared_destination_with"], ["US/daily"])
            self.assertEqual(set(output["environment_overrides"]), {"GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON_BASE64"})
            self.assertEqual(output["reports"][0]["results"][0]["error"], "[REDACTED]")
            self.assertNotIn("overridden-secret", json.dumps(output))

    def test_account_failure_keeps_other_accounts_and_cli_emits_unicode_json_on_legacy_stdout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "env").mkdir()
            for account in ("CN", "US"):
                (root / "env" / f"{account}.env").write_text(f"GOOGLE_SHEET_ID={account}\n", encoding="utf-8")
            def opener(config):
                if config.spreadsheet_id == "CN":
                    raise RuntimeError("DO_NOT_PRINT_CREDENTIAL")
                return SimpleNamespace(worksheet=lambda title: Worksheet([result_row(error="读取失败😀")]))
            output = reports.collect_reports(root, mode="daily", env={}, opener=opener)
            self.assertEqual([item["account"] for item in output["reports"]], ["CN", "US"])
            self.assertTrue(output["reports"][0]["incomplete"])
            self.assertEqual(output["reports"][1]["results"][0]["error"], "读取失败😀")
            buffer = io.BytesIO()
            stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", write_through=True)
            with redirect_stdout(stream), patch.object(reports, "collect_reports", return_value=output) as collect:
                code = reports.main(["--account", "CN", "--account", "US", "--date", "today", "--limit", "50",
                                     "--max-scan-rows", "300"])
            self.assertEqual(code, 1)
            self.assertEqual(collect.call_args.kwargs["day"], dt.date.today())
            self.assertEqual(collect.call_args.kwargs["accounts"], ["CN", "US"])
            decoded = json.loads(buffer.getvalue())
            self.assertEqual(decoded["reports"][1]["results"][0]["error"], "读取失败😀")
            self.assertNotIn("DO_NOT_PRINT_CREDENTIAL", buffer.getvalue().decode("ascii"))
            stream.close()


if __name__ == "__main__":
    unittest.main()
