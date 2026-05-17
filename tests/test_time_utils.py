import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.time_utils import (
    BEIJING_TZ,
    BurnDecision,
    calculate_burn,
    format_date,
    format_duration,
    format_timestamp,
    minutes_until_stamina_full,
    minutes_until_target_time,
    predict_future_stamina,
    stamina_after_consume,
)


class TimeUtilsTest(unittest.TestCase):
    def test_format_helpers(self) -> None:
        value = dt.datetime(2026, 5, 16, 8, 9, 10, tzinfo=dt.timezone.utc)

        self.assertEqual(format_timestamp(value), "2026-05-16 08:09:10")
        self.assertEqual(format_date(value), "2026-05-16")
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(65), "1m 5s")
        self.assertEqual(format_duration(90061), "1d 1h 1m 1s")
        self.assertEqual(format_duration(-1), "0s")

    def test_predict_future_stamina_fills_current_before_backup(self) -> None:
        self.assertEqual(predict_future_stamina(230, 10, 60), (240, 10))
        self.assertEqual(predict_future_stamina(240, 10, 60), (240, 15))
        self.assertEqual(predict_future_stamina(-20, 999, -1), (0, 480))

    def test_minutes_until_target_time_uses_beijing_timezone(self) -> None:
        start = dt.datetime(2026, 5, 16, 4, 30, tzinfo=BEIJING_TZ)

        self.assertEqual(minutes_until_target_time(5, 0, start), 30)
        self.assertEqual(minutes_until_target_time(4, 30, start), 24 * 60)

    def test_minutes_until_stamina_full_clamps_values(self) -> None:
        self.assertEqual(minutes_until_stamina_full(230), 60)
        self.assertEqual(minutes_until_stamina_full(500), 0)
        self.assertEqual(minutes_until_stamina_full(-5), 1440)

    def test_stamina_after_consume_uses_current_then_backup(self) -> None:
        self.assertEqual(stamina_after_consume(100, 50, 120), (0, 30))
        self.assertEqual(stamina_after_consume(100, 50, 20), (80, 50))

    def test_calculate_burn_handles_missing_stamina(self) -> None:
        self.assertEqual(calculate_burn(None, None), BurnDecision(False, 0, False, "无法读取体力，不执行任务"))

    def test_calculate_burn_skips_when_no_overflow(self) -> None:
        start = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)

        decision = calculate_burn(100, 0, start_time=start)

        self.assertFalse(decision.should_run)
        self.assertEqual(decision.burn_amount, 0)
        self.assertTrue(decision.is_expected)
        self.assertIn("不会溢出", decision.reason)

    def test_calculate_burn_requests_exact_burn_when_possible(self) -> None:
        start = dt.datetime(2026, 5, 15, 9, 0, tzinfo=BEIJING_TZ)

        decision = calculate_burn(60, 0, start_time=start)

        self.assertTrue(decision.should_run)
        self.assertEqual(decision.burn_amount, 60)
        self.assertTrue(decision.is_expected)
        self.assertIn("消耗 60", decision.reason)

    def test_calculate_burn_marks_overburn(self) -> None:
        start = dt.datetime(2026, 5, 15, 22, 0, tzinfo=BEIJING_TZ)

        decision = calculate_burn(180, 0, start_time=start)

        self.assertTrue(decision.should_run)
        self.assertEqual(decision.burn_amount, 180)
        self.assertFalse(decision.is_expected)
        self.assertIn("过量消耗 180", decision.reason)

    def test_calculate_burn_handles_full_current_and_backup(self) -> None:
        start = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)

        decision = calculate_burn(240, 480, start_time=start)

        self.assertTrue(decision.should_run)
        self.assertEqual(decision.burn_amount, 240)
        self.assertFalse(decision.is_expected)
        self.assertIn("溢出 10", decision.reason)


if __name__ == "__main__":
    unittest.main()
