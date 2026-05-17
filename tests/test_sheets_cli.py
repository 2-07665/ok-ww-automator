from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import AppConfig, DailyRunTimeConfig, GoogleSheetsConfig, NoticeConfig, WavesApiConfig
from ok_ww_automator.sheets import main
from test_sheets import FakeSpreadsheet, FakeWorksheet


class SheetsCliTest(unittest.TestCase):
    def test_main_prints_parsed_config(self) -> None:
        app_config = AppConfig(
            project_root=Path("/tmp/project"),
            env_path=Path("/tmp/project/env/cn.env"),
            daily_run_time=DailyRunTimeConfig(),
            google_sheets=GoogleSheetsConfig(
                spreadsheet_id="sheet",
                service_account_json_base64="secret",
            ),
            waves_api=WavesApiConfig(),
            notice=NoticeConfig(),
        )
        config_sheet = FakeWorksheet([["日常任务", "TRUE", "体力任务", "FALSE"]])
        fake_spreadsheet = FakeSpreadsheet({"Config": config_sheet})

        with patch("ok_ww_automator.sheets.load_config", return_value=app_config), patch(
            "ok_ww_automator.sheets._open_spreadsheet",
            return_value=fake_spreadsheet,
        ), patch("sys.stdout"):
            code = main(["--env-file", "cn.env", "--show-cells"])

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
