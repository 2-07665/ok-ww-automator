import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.models import FastFarmResult, RunResult, SheetRunConfig
from ok_ww_automator.time_utils import BEIJING_TZ


class ModelsTest(unittest.TestCase):
    def test_sheet_run_config_defaults_match_legacy_automation(self) -> None:
        config = SheetRunConfig()

        self.assertTrue(config.run_daily)
        self.assertFalse(config.skip_daily_once)
        self.assertTrue(config.run_stamina)
        self.assertEqual(config.which_to_farm, "无音区")
        self.assertEqual(config.simulation_material, "贝币")

    def test_run_result_derives_report_fields(self) -> None:
        started = dt.datetime(2026, 5, 16, 3, 0, tzinfo=BEIJING_TZ)
        ended = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)
        result = RunResult(
            task_type="daily",
            started_at=started,
            ended_at=ended,
            status="needs review",
            stamina_left=230,
            backup_stamina_left=10,
            decision="check",
        )

        derived = result.derive()

        self.assertEqual(derived.started_at_text, "2026-05-16 03:00:00")
        self.assertEqual(derived.ended_at_text, "2026-05-16 04:00:00")
        self.assertEqual(derived.duration_text, "1h")
        self.assertEqual(derived.next_daily_stamina, "240")
        self.assertEqual(derived.next_daily_backup_stamina, "10")
        self.assertTrue(derived.notes_visible)

    def test_fill_stamina_used_rounds_to_legacy_consume_unit(self) -> None:
        result = RunResult(
            task_type="stamina",
            started_at=dt.datetime(2026, 5, 16, tzinfo=BEIJING_TZ),
            ended_at=None,
            status="running",
        )
        result.fill_stamina_start(240, 20)
        result.fill_stamina_left(190, 20)

        result.fill_stamina_used()

        self.assertEqual(result.stamina_used, 40)

    def test_daily_row_layout_is_explicit_and_compatible(self) -> None:
        started = dt.datetime(2026, 5, 16, 3, 0, tzinfo=BEIJING_TZ)
        ended = dt.datetime(2026, 5, 16, 3, 2, tzinfo=BEIJING_TZ)
        result = RunResult(
            task_type="daily",
            started_at=started,
            ended_at=ended,
            status="success",
            stamina_start=240,
            backup_stamina_start=0,
            stamina_used=180,
            stamina_left=60,
            backup_stamina_left=0,
            run_nightmare=True,
            daily_points=100,
            sign_in_success=True,
            decision="done",
            error="",
        )

        self.assertEqual(
            result.as_daily_row(),
            [
                "2026-05-16 03:00:00",
                "2026-05-16 03:02:00",
                "2m",
                "success",
                "240",
                "0",
                "180",
                "60",
                "0",
                "100",
                "79",
                "0",
                "成功",
                "是",
                "done",
                "",
            ],
        )

    def test_stamina_row_layout_is_explicit_and_compatible(self) -> None:
        started = dt.datetime(2026, 5, 16, 3, 0, tzinfo=BEIJING_TZ)
        ended = dt.datetime(2026, 5, 16, 3, 2, tzinfo=BEIJING_TZ)
        result = RunResult(
            task_type="stamina",
            started_at=started,
            ended_at=ended,
            status="skipped",
            stamina_start=60,
            backup_stamina_start=0,
            stamina_used=0,
            stamina_left=60,
            backup_stamina_left=0,
            decision="不会溢出",
        )

        self.assertEqual(
            result.as_stamina_row(),
            [
                "2026-05-16 03:00:00",
                "2026-05-16 03:02:00",
                "2m",
                "skipped",
                "60",
                "0",
                "0",
                "60",
                "0",
                "79",
                "0",
                "不会溢出",
                "",
            ],
        )

    def test_fast_farm_row_computes_speed_and_echo_gain(self) -> None:
        started = dt.datetime(2026, 5, 16, 3, 0, tzinfo=BEIJING_TZ)
        ended = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)
        result = FastFarmResult(
            started_at=started,
            ended_at=ended,
            status="success",
            fight_count=20,
            echo_number_start=100,
            echo_number_end=117,
            merge_count=2,
            info="ok",
        )

        self.assertEqual(
            result.as_row(),
            [
                "2026-05-16 03:00:00",
                "2026-05-16 04:00:00",
                "1h",
                "success",
                "20",
                "20",
                "100",
                "117",
                "17",
                "2",
                "ok",
            ],
        )


if __name__ == "__main__":
    unittest.main()
