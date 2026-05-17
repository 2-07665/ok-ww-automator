import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import GoogleSheetsConfig
from ok_ww_automator.models import FastFarmResult, RunResult
from ok_ww_automator.sheets import ConfigSheetParser, GoogleSheetsStore, SheetsError, column_to_a1
from ok_ww_automator.time_utils import BEIJING_TZ


class FakeWorksheet:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.updates = []
        self.appended_rows = []

    def get_all_values(self):
        return self.rows

    def update(self, values, range_name, **kwargs):
        self.updates.append((values, range_name, kwargs))

    def append_row(self, values, **kwargs):
        self.appended_rows.append((values, kwargs))


class FakeSpreadsheet:
    def __init__(self, worksheets):
        self.worksheets = worksheets

    def worksheet(self, title):
        return self.worksheets[title]


class SheetsTest(unittest.TestCase):
    def test_column_to_a1(self) -> None:
        self.assertEqual(column_to_a1(1), "A")
        self.assertEqual(column_to_a1(26), "Z")
        self.assertEqual(column_to_a1(27), "AA")

    def test_parser_reads_unique_pairwise_labels(self) -> None:
        rows = [
            ["日常任务", "TRUE", "体力任务", "FALSE"],
            ["日常跳过一次", "FALSE", "体力跳过一次", "TRUE"],
            ["日常后关机", "FALSE", "体力后关机", "TRUE"],
            ["刷什么", "无音区"],
            ["无音区设置", "加拉尔冠阶", "无音区序号", "3"],
            ["无音区套装1", "长路启航之星", "无音区套装2", "斑驳粉饰之沫"],
            ["凝素领域设置", "荒蔓旧殿", "凝素领域序号", "1"],
            ["凝素领域武器类型", "讯刀", "凝素领域版本", "3.0"],
            ["模拟领域设置", "贝币"],
            ["梦魇祓除", "是"],
        ]

        config = ConfigSheetParser().to_run_config(ConfigSheetParser().parse(rows))

        self.assertTrue(config.run_daily)
        self.assertFalse(config.run_stamina)
        self.assertFalse(config.skip_daily_once)
        self.assertTrue(config.skip_stamina_once)
        self.assertFalse(config.shutdown_after_daily)
        self.assertTrue(config.shutdown_after_stamina)
        self.assertEqual(config.which_to_farm, "无音区")
        self.assertEqual(config.tacet_name, "加拉尔冠阶")
        self.assertEqual(config.tacet_serial, 3)
        self.assertEqual(config.tacet_set1, "长路启航之星")
        self.assertEqual(config.tacet_set2, "斑驳粉饰之沫")
        self.assertEqual(config.forgery_name, "荒蔓旧殿")
        self.assertEqual(config.forgery_serial, 1)
        self.assertEqual(config.forgery_weapon_type, "讯刀")
        self.assertEqual(config.forgery_version, "3.0")
        self.assertEqual(config.simulation_material, "贝币")
        self.assertTrue(config.run_nightmare)

    def test_parser_rejects_duplicate_labels(self) -> None:
        rows = [["日常任务", "TRUE"], ["日常任务", "FALSE"]]

        with self.assertRaisesRegex(SheetsError, "Duplicate config label"):
            ConfigSheetParser().parse(rows)

    def test_store_clears_skip_once_by_discovered_cell(self) -> None:
        config_sheet = FakeWorksheet(
            [
                ["日常跳过一次", "TRUE", "体力跳过一次", "TRUE"],
            ]
        )
        store = GoogleSheetsStore(
            GoogleSheetsConfig(),
            spreadsheet=FakeSpreadsheet({"Config": config_sheet}),
        )

        self.assertTrue(store.clear_skip_once("stamina"))

        self.assertEqual(config_sheet.updates, [([["FALSE"]], "D1", {"value_input_option": "USER_ENTERED"})])

    def test_fetch_run_config_or_default_returns_error_text(self) -> None:
        store = GoogleSheetsStore(
            GoogleSheetsConfig(config_sheet="Missing"),
            spreadsheet=FakeSpreadsheet({}),
        )

        config, error = store.fetch_run_config_or_default()

        self.assertTrue(config.run_daily)
        self.assertIsNotNone(error)

    def test_store_appends_result_log_rows(self) -> None:
        daily_sheet = FakeWorksheet()
        stamina_sheet = FakeWorksheet()
        fast_farm_sheet = FakeWorksheet()
        store = GoogleSheetsStore(
            GoogleSheetsConfig(),
            spreadsheet=FakeSpreadsheet(
                {
                    "DailyRuns": daily_sheet,
                    "StaminaRuns": stamina_sheet,
                    "5to1": fast_farm_sheet,
                }
            ),
        )
        started = dt.datetime(2026, 5, 16, 3, 0, tzinfo=BEIJING_TZ)
        ended = dt.datetime(2026, 5, 16, 3, 1, tzinfo=BEIJING_TZ)

        store.append_daily_result(RunResult("daily", started, ended, "success", daily_points=100))
        store.append_stamina_result(RunResult("stamina", started, ended, "skipped"))
        store.append_fast_farm_result(FastFarmResult(started, ended, "success", fight_count=1))

        self.assertEqual(daily_sheet.appended_rows[0][0][:4], ["2026-05-16 03:00:00", "2026-05-16 03:01:00", "1m", "success"])
        self.assertEqual(stamina_sheet.appended_rows[0][0][:4], ["2026-05-16 03:00:00", "2026-05-16 03:01:00", "1m", "skipped"])
        self.assertEqual(fast_farm_sheet.appended_rows[0][0][:4], ["2026-05-16 03:00:00", "2026-05-16 03:01:00", "1m", "success"])


if __name__ == "__main__":
    unittest.main()
