import datetime as dt
from dataclasses import replace
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import AppConfig, NoticeConfig, RetryConfig, WeeklyRunConfig
from ok_ww_automator.models import RunResult, SheetRunConfig
from ok_ww_automator.runners import (
    DailyRunner,
    StaminaRunner,
)
from ok_ww_automator.game_clients import (
    DailyGameOutcome,
    StaminaGameOutcome,
    WeeklyGameOutcome,
)
from ok_ww_automator.time_utils import BEIJING_TZ
from ok_ww_automator.waves_api import WavesDailyInfo
from ok_ww_automator.weekly import WeeklyRunner, week_start, weekly_notice_start


class WeeklyRunnerTest(unittest.TestCase):
    def test_run_days_are_per_account_and_manual_bypasses_them(self):
        monday = replace(self.config, weekly_run=WeeklyRunConfig(run_days=(1,)))
        tuesday = replace(monday, env_path=monday.env_path.with_name("us.env"),
                          weekly_run=WeeklyRunConfig(run_days=(2,)))
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.assertEqual(self.run_at("2026-09-28T05:00", config=tuesday).status, "skipped")
        self.game.run_weekly.assert_not_called()
        self.prepare.assert_not_called()
        self.assertEqual(self.run_at("2026-09-28T05:00", config=monday).status, "success")
        self.assertEqual(self.run_at("2026-09-28T05:00", config=tuesday, run_now=True).status, "success")
        self.assertEqual(self.run_at("2026-09-29T05:00", config=tuesday).status, "skipped")
        self.assertEqual(self.game.run_weekly.call_count, 2)
        self.wx.notify.assert_not_called()

    def test_notice_on_excluded_day_without_launching_game(self):
        config = replace(self.config, weekly_run=WeeklyRunConfig(notice_day=5, run_days=(1,)))
        self.assertEqual(self.run_at("2026-09-30T05:00", config=config).status, "skipped")
        self.wx.notify.assert_not_called()
        self.assertEqual(self.run_at("2026-10-02T05:00", config=config).status, "failure")
        self.run_at("2026-10-03T05:00", config=config)
        self.wx.notify.assert_called_once()
        self.prepare.assert_not_called()
        self.game.run_weekly.assert_not_called()

    def test_run_day_uses_beijing_calendar_day(self):
        config = replace(self.config, weekly_run=WeeklyRunConfig(run_days=(2,)))
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        # Still Monday in UTC, already Tuesday in Beijing.
        stamp = dt.datetime(2026, 9, 28, 16, tzinfo=dt.timezone.utc)
        result = WeeklyRunner(config, self.game, clock=lambda: stamp).run()
        self.assertEqual(result.status, "success")
        self.game.run_weekly.assert_called_once()

    def test_total_budget_is_shared_by_preparation_retries_and_game_subprocesses(self):
        elapsed = 0.0
        stamp = dt.datetime(2026, 10, 2, 5, tzinfo=BEIJING_TZ)
        config = replace(self.config, retry=RetryConfig(3, 10))
        def prepare(timeout):
            nonlocal elapsed
            self.assertEqual(timeout, 60)
            elapsed += 10
        def game(*, timeout):
            nonlocal elapsed
            if elapsed == 10:
                elapsed += 20
                return WeeklyGameOutcome(task_error="first failed")
            elapsed += timeout
            raise subprocess.TimeoutExpired("game", timeout)
        def sleep(seconds):
            nonlocal elapsed
            elapsed += seconds
        self.game.run_weekly.side_effect = game
        runner = WeeklyRunner(config, self.game, prepare=prepare, clock=lambda: stamp,
                              monotonic=lambda: elapsed, sleep=sleep, timeout_seconds=60)
        result = runner.run()
        self.assertEqual(result.status, "failure")
        self.assertIn("总时限", result.error)
        self.assertEqual([call.kwargs["timeout"] for call in self.game.run_weekly.call_args_list], [50, 20])
        self.assertEqual(elapsed, 60)
        self.wx.notify.assert_called_once()

    def test_preparation_timeout_does_not_launch_game(self):
        elapsed = 0.0
        stamp = dt.datetime(2026, 10, 2, 5, tzinfo=BEIJING_TZ)
        def prepare(timeout):
            nonlocal elapsed
            elapsed = timeout
            raise subprocess.TimeoutExpired("update", timeout)
        result = WeeklyRunner(self.config, self.game, prepare=prepare, clock=lambda: stamp,
                              monotonic=lambda: elapsed, timeout_seconds=60).run()
        self.assertEqual(result.status, "failure")
        self.assertIn("总时限", result.error)
        self.game.run_weekly.assert_not_called()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = AppConfig(
            root, root / "env" / "cn.env",
            weekly_run=WeeklyRunConfig(notice_day=5),
            retry=RetryConfig(2, 0),
            notice=NoticeConfig(enabled=True, channels=("wxpusher",), wxpusher_spt="test"),
        )
        self.game = Mock()
        self.game.run_weekly.return_value = WeeklyGameOutcome(task_error="garden failed")
        self.prepare = Mock()
        self.wx_patch = patch("ok_ww_automator.weekly.WxPusherNoticeClient")
        self.wx = self.wx_patch.start().return_value
        self.addCleanup(self.wx_patch.stop)

    def run_at(self, value, *, run_now=False, config=None):
        current = dt.datetime.fromisoformat(value).replace(tzinfo=BEIJING_TZ)
        return WeeklyRunner(config or self.config, self.game, run_now=run_now,
                            prepare=self.prepare, clock=lambda: current, sleep=lambda _: None).run()

    def test_weekly_allows_at_most_one_retry_per_invocation(self):
        config = replace(self.config, retry=RetryConfig(10, 0))
        self.run_at("2026-09-28T05:00", config=config)
        self.assertEqual(self.game.run_weekly.call_count, 2)
        self.run_at("2026-09-28T09:00", config=config)
        self.assertEqual(self.game.run_weekly.call_count, 4)

    def test_failed_days_retry_then_success_skips_scheduled_but_not_manual(self):
        self.assertEqual(self.run_at("2026-09-28T05:00").status, "needs review")
        self.assertEqual(self.game.run_weekly.call_count, 2)
        self.run_at("2026-09-28T09:00")
        self.run_at("2026-09-29T05:00")
        self.assertEqual(self.game.run_weekly.call_count, 6)
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.assertEqual(self.run_at("2026-09-30T05:00").status, "success")
        self.assertEqual(self.run_at("2026-10-02T05:00").status, "skipped")
        self.assertEqual(self.run_at("2026-10-02T05:00", run_now=True).status, "success")
        self.assertEqual(self.game.run_weekly.call_count, 8)
        self.assertEqual(self.prepare.call_count, 5)
        self.wx.notify.assert_not_called()

    def test_failed_manual_rerun_preserves_prior_success_without_weekly_failure_notice(self):
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.run_at("2026-09-28T05:00")
        self.game.run_weekly.return_value = WeeklyGameOutcome(task_error="manual failed")
        result = self.run_at("2026-10-02T05:00", run_now=True)
        self.assertEqual(result.status, "failure")
        self.assertIn("保留", result.decision)
        self.assertEqual(self.run_at("2026-10-02T05:05").status, "skipped")
        self.assertEqual(self.game.run_weekly.call_count, 3)
        self.wx.notify.assert_not_called()

    def test_final_day_failure_notifies_once(self):
        self.run_at("2026-09-28T05:00")
        self.wx.notify.assert_not_called()
        result = self.run_at("2026-10-02T05:00")
        self.assertEqual(result.status, "failure")
        self.wx.notify.assert_called_once()
        self.assertIn("2026-09-28", result.decision)
        self.run_at("2026-10-02T05:05")
        self.run_at("2026-10-03T05:00")
        self.assertEqual(self.game.run_weekly.call_count, 8)
        self.wx.notify.assert_called_once()

    def test_failed_notice_retries_on_later_runs(self):
        self.wx.notify.side_effect = [RuntimeError("offline"), None]
        self.assertEqual(self.run_at("2026-10-02T05:00").status, "failure")
        self.run_at("2026-10-02T05:05")
        self.run_at("2026-10-02T05:10")
        self.assertEqual(self.game.run_weekly.call_count, 6)
        self.assertEqual(self.wx.notify.call_count, 2)

    def test_after_notice_day_still_runs_game_before_reporting_failure(self):
        result = self.run_at("2026-10-03T05:00")
        self.assertEqual(result.status, "failure")
        self.assertEqual(self.game.run_weekly.call_count, 2)
        self.prepare.assert_called_once()
        self.wx.notify.assert_called_once()

    def test_recorded_unfinished_previous_week_reports_after_reset(self):
        self.run_at("2026-09-28T05:00")
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        result = self.run_at("2026-10-05T05:00")
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error)
        self.wx.notify.assert_called_once()
        self.assertIn("2026-09-28", self.wx.notify.call_args.args[0].decision)

    def test_disabled_notifications_do_not_prevent_later_game_attempts(self):
        config = replace(self.config, notice=NoticeConfig())
        self.assertEqual(self.run_at("2026-10-02T05:00", config=config).status, "failure")
        self.run_at("2026-10-02T05:05", config=config)
        self.assertEqual(self.game.run_weekly.call_count, 4)
        self.wx.notify.assert_not_called()

    def test_any_trigger_can_run_without_env_schedule(self):
        config = replace(self.config, weekly_run=WeeklyRunConfig())
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.assertEqual(self.run_at("2026-09-29T01:00", config=config).status, "success")
        self.prepare.assert_called_once()

    def test_success_on_notice_day_does_not_notify(self):
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.assertEqual(self.run_at("2026-10-02T05:00").status, "success")
        self.wx.notify.assert_not_called()

    def test_confirmed_completion_with_error_is_saved_without_retry_or_notice(self):
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True, task_error="reward failed")
        self.assertEqual(self.run_at("2026-10-02T05:00").status, "success")
        self.assertEqual(self.run_at("2026-10-02T06:00").status, "skipped")
        self.game.run_weekly.assert_called_once()
        self.wx.notify.assert_not_called()

    def test_manual_failure_does_not_prevent_next_scheduled_attempt(self):
        self.run_at("2026-09-28T04:30", run_now=True)
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.assertEqual(self.run_at("2026-09-28T05:00").status, "success")
        self.assertEqual(self.game.run_weekly.call_count, 3)

    def test_account_completion_is_isolated(self):
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.run_at("2026-09-28T05:00")
        other = replace(self.config, env_path=self.config.env_path.with_name("global.env"))
        self.assertEqual(self.run_at("2026-09-28T05:00", config=other).status, "success")
        self.assertEqual(self.game.run_weekly.call_count, 2)

    def test_concurrent_same_account_is_skipped(self):
        def overlapping(*, timeout):
            result = self.run_at("2026-09-28T05:00", run_now=True)
            self.assertEqual(result.status, "skipped")
            self.assertIn("正在运行", result.decision)
            return WeeklyGameOutcome(completed=True)
        self.game.run_weekly.side_effect = overlapping
        self.assertEqual(self.run_at("2026-09-28T05:00").status, "success")
        self.game.run_weekly.assert_called_once()

    def test_update_failure_is_recorded_and_notified_on_final_day(self):
        self.prepare.side_effect = RuntimeError("update failed")
        result = self.run_at("2026-10-02T05:00")
        self.assertEqual(result.status, "failure")
        self.assertIn("update failed", result.error)
        self.game.run_weekly.assert_not_called()
        self.wx.notify.assert_called_once()

    def test_reset_boundary_and_notice_day(self):
        before = dt.datetime(2026, 10, 5, 3, 59, tzinfo=BEIJING_TZ)
        self.assertEqual(week_start(before).date().isoformat(), "2026-09-28")
        self.assertEqual(week_start(before + dt.timedelta(minutes=1)).date().isoformat(), "2026-10-05")
        self.assertEqual(week_start(before.astimezone(dt.timezone.utc)), week_start(before))
        self.assertEqual(weekly_notice_start(week_start(before), 5), dt.datetime(2026, 10, 2, tzinfo=BEIJING_TZ))
        self.assertEqual(weekly_notice_start(week_start(before), 1), week_start(before))
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.run_at("2026-09-28T05:00")
        self.run_at("2026-10-05T03:59")
        self.assertEqual(self.game.run_weekly.call_count, 1)
        self.run_at("2026-10-05T04:00", run_now=True)
        self.assertEqual(self.game.run_weekly.call_count, 2)

    def test_completion_across_reset_is_not_credited_to_either_week(self):
        current = dt.datetime(2026, 10, 5, 3, 59, tzinfo=BEIJING_TZ)
        def complete(*, timeout):
            nonlocal current
            current += dt.timedelta(minutes=2)
            return WeeklyGameOutcome(completed=True)
        self.game.run_weekly.side_effect = complete
        runner = WeeklyRunner(self.config, self.game, run_now=True, clock=lambda: current)
        self.assertEqual(runner.run().status, "failure")
        self.game.run_weekly.side_effect = None
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.assertEqual(self.run_at("2026-10-05T05:00").status, "success")


FIXED_NOW = dt.datetime(2026, 5, 16, 5, 0, tzinfo=BEIJING_TZ)


class FakeStore:
    def __init__(self, sheet_config=None, error=None, clear_exc=None, daily_append_exc=None, stamina_append_exc=None) -> None:
        self.sheet_config = sheet_config or SheetRunConfig()
        self.error = error
        self.clear_exc = clear_exc
        self.daily_append_exc = daily_append_exc
        self.stamina_append_exc = stamina_append_exc
        self.cleared = []
        self.daily_results = []
        self.stamina_results = []

    def fetch_run_config_or_default(self):
        return self.sheet_config, self.error

    def clear_skip_once(self, task_type: str) -> bool:
        if self.clear_exc is not None:
            raise self.clear_exc
        self.cleared.append(task_type)
        return True

    def append_daily_result(self, result: RunResult) -> None:
        if self.daily_append_exc is not None:
            raise self.daily_append_exc
        self.daily_results.append(result)

    def append_stamina_result(self, result: RunResult) -> None:
        if self.stamina_append_exc is not None:
            raise self.stamina_append_exc
        self.stamina_results.append(result)


class FakeGameClient:
    def __init__(self, outcome=None, exc=None) -> None:
        self.outcome = outcome or DailyGameOutcome()
        self.exc = exc
        self.configs = []

    def run_daily(self, sheet_config: SheetRunConfig) -> DailyGameOutcome:
        self.configs.append(sheet_config)
        if self.exc is not None:
            raise self.exc
        return self.outcome


class FakeStaminaGameClient:
    def __init__(
        self,
        *,
        stamina=(100, 0),
        outcome=None,
        read_exc=None,
        run_exc=None,
    ) -> None:
        self.stamina = stamina
        self.outcome = outcome or StaminaGameOutcome()
        self.read_exc = read_exc
        self.run_exc = run_exc
        self.read_configs = []
        self.run_configs = []
        self.closed_configs = []

    def read_stamina(self, sheet_config: SheetRunConfig):
        self.read_configs.append(sheet_config)
        if self.read_exc is not None:
            raise self.read_exc
        return self.stamina

    def run_stamina(self, sheet_config: SheetRunConfig):
        self.run_configs.append(sheet_config)
        if self.run_exc is not None:
            raise self.run_exc
        return self.outcome

    def close(self, sheet_config: SheetRunConfig) -> None:
        self.closed_configs.append(sheet_config)


class FakeApiClient:
    def __init__(self, *, info=None, sign_in_response=None) -> None:
        self.info = info
        self.sign_in_response = sign_in_response or {"code": 0}
        self.sign_in_count = 0
        self.read_count = 0
        self.close_count = 0

    def sign_in(self):
        self.sign_in_count += 1
        return self.sign_in_response

    def read_daily_info(self):
        self.read_count += 1
        return self.info

    def close(self) -> None:
        self.close_count += 1


class FakePowerController:
    def __init__(self) -> None:
        self.requests = []

    def request_shutdown(self, reason: str) -> None:
        self.requests.append(reason)


class FakeNoticeClient:
    def __init__(self, exc=None) -> None:
        self.exc = exc
        self.calls = []

    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        self.calls.append((result, sheet_config))
        if self.exc is not None:
            raise self.exc


class FakeHealthcheckMonitor:
    def __init__(self, *, start_exc=None, complete_exc=None) -> None:
        self.start_exc = start_exc
        self.complete_exc = complete_exc
        self.calls = []

    def start(self, result: RunResult) -> None:
        self.calls.append(("start", result.status))
        if self.start_exc is not None:
            raise self.start_exc

    def complete(self, result: RunResult) -> None:
        self.calls.append(("complete", result.status))
        if self.complete_exc is not None:
            raise self.complete_exc


class DailyRunnerTest(unittest.TestCase):
    def test_daily_failed_retry_preserves_partial_metrics_and_actual_end_time(self):
        game = Mock()
        game.run_daily.side_effect = [
            DailyGameOutcome(240, 0, 120, 0, 50, "first attempt failed"),
            RuntimeError("second attempt failed"),
        ]
        observed = FIXED_NOW + dt.timedelta(minutes=10)
        ended = FIXED_NOW + dt.timedelta(minutes=20)
        with patch("ok_ww_automator.runners.now", side_effect=[FIXED_NOW, observed, ended]):
            result = DailyRunner(store=FakeStore(), game_client=game,
                                 retry_config=RetryConfig(2, 0)).run()
        self.assertEqual(result.status, "failure")
        self.assertEqual(result.ended_at, ended)
        self.assertEqual(result.stamina_used, 120)
        self.assertIn("second attempt failed", result.error)

    def test_daily_retry_reports_stamina_consumed_across_both_attempts(self):
        game = Mock()
        game.run_daily.side_effect = [
            DailyGameOutcome(240, 0, 120, 0, 50, "first attempt failed"),
            DailyGameOutcome(120, 0, 60, 0, 100),
        ]
        result = DailyRunner(store=FakeStore(), game_client=game,
                             retry_config=RetryConfig(2, 0)).run()
        self.assertEqual(result.status, "success")
        self.assertEqual((result.stamina_start, result.stamina_left, result.stamina_used), (240, 60, 180))

    def test_api_cleanup_failure_still_persists_notifies_and_shuts_down(self):
        store = FakeStore(SheetRunConfig(shutdown_after_daily=True))
        api = FakeApiClient()
        api.close = Mock(side_effect=RuntimeError("API close failed"))
        notice = FakeNoticeClient()
        power = FakePowerController()
        monitor = FakeHealthcheckMonitor()
        result = DailyRunner(
            store=store, game_client=FakeGameClient(DailyGameOutcome(daily_points=100)),
            api_client=api, notice_client=notice, power_controller=power,
            healthcheck_monitor=monitor,
        ).run()
        self.assertEqual(result.status, "success")
        self.assertIn("API close failed", result.decision)
        self.assertEqual(store.daily_results, [result])
        self.assertEqual(notice.calls, [(result, store.sheet_config)])
        self.assertEqual(monitor.calls[-1], ("complete", "success"))
        self.assertEqual(power.requests, ["daily"])

    def test_missing_final_stamina_does_not_reuse_initial_api_reading(self):
        api = FakeApiClient(info=WavesDailyInfo(180, 30, 20))
        result = DailyRunner(
            store=FakeStore(), api_client=api,
            game_client=FakeGameClient(DailyGameOutcome(daily_points=100)),
        ).run()
        self.assertEqual(result.stamina_start, 180)
        self.assertIsNone(result.stamina_left)
        self.assertIsNone(result.backup_stamina_left)
        self.assertIsNone(result.stamina_used)

    def test_skip_daily_once_clears_flag_and_persists_skipped_result(self) -> None:
        store = FakeStore(SheetRunConfig(skip_daily_once=True, run_nightmare=True))
        game = FakeGameClient()

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game).run()

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.ended_at, result.started_at)
        self.assertFalse(result.run_nightmare)
        self.assertEqual(store.cleared, ["daily"])
        self.assertEqual(store.daily_results, [result])
        self.assertEqual(game.configs, [])

    def test_sheet_fetch_error_uses_default_config_and_records_decision(self) -> None:
        store = FakeStore(error="network down")
        game = FakeGameClient(DailyGameOutcome(daily_points=100))

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game).run()

        self.assertEqual(result.status, "success")
        self.assertIn("使用默认配置", result.decision)
        self.assertEqual(store.daily_results, [result])

    def test_daily_success_fills_stamina_and_points(self) -> None:
        outcome = DailyGameOutcome(
            stamina_start=200,
            backup_stamina_start=20,
            stamina_left=20,
            backup_stamina_left=20,
            daily_points=100,
        )
        store = FakeStore()
        game = FakeGameClient(outcome)

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game).run()

        self.assertEqual(result.status, "success")
        self.assertEqual(result.stamina_used, 180)
        self.assertEqual(result.daily_points, 100)
        self.assertEqual(result.stamina_left, 20)
        self.assertEqual(store.daily_results, [result])

    def test_daily_reports_nightmare_disabled_when_no_targets_are_selected(self) -> None:
        config = SheetRunConfig(
            run_nightmare=True,
            farm_nightmare_purification=False,
            farm_tacet_discord_nest=False,
        )
        store = FakeStore(config)
        game = FakeGameClient(DailyGameOutcome(daily_points=100))

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game).run()

        self.assertEqual(result.status, "success")
        self.assertFalse(result.run_nightmare)

    def test_daily_append_failure_does_not_turn_success_into_failure(self) -> None:
        store = FakeStore(daily_append_exc=RuntimeError("sheet unavailable"))
        game = FakeGameClient(DailyGameOutcome(daily_points=100))

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game).run()

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error)
        self.assertIn("写入表格日志失败: sheet unavailable", result.decision)
        self.assertEqual(store.daily_results, [])

    def test_daily_clear_skip_once_failure_marks_task_needs_review(self) -> None:
        store = FakeStore(SheetRunConfig(skip_daily_once=True), clear_exc=RuntimeError("sheet unavailable"))
        game = FakeGameClient()

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game).run()

        self.assertEqual(result.status, "needs review")
        self.assertIn("清除跳过一次标记失败: sheet unavailable", result.decision)
        self.assertEqual(store.cleared, [])
        self.assertEqual(store.daily_results, [result])

    def test_daily_shutdown_config_requests_shutdown_after_persist(self) -> None:
        store = FakeStore(SheetRunConfig(shutdown_after_daily=True))
        game = FakeGameClient(DailyGameOutcome(daily_points=100))
        power = FakePowerController()

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game, power_controller=power).run()

        self.assertEqual(result.status, "success")
        self.assertEqual(store.daily_results, [result])
        self.assertEqual(power.requests, ["daily"])

    def test_daily_uses_api_for_initial_metrics_and_sign_in(self) -> None:
        store = FakeStore()
        api = FakeApiClient(info=WavesDailyInfo(stamina=180, backup_stamina=30, daily_points=20))
        game = FakeGameClient(DailyGameOutcome(daily_points=100, stamina_left=0, backup_stamina_left=30))

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game, api_client=api).run()

        self.assertTrue(result.sign_in_success)
        self.assertEqual(result.stamina_start, 180)
        self.assertEqual(result.backup_stamina_start, 30)
        self.assertEqual(result.daily_points, 100)
        self.assertEqual(api.sign_in_count, 1)
        self.assertEqual(api.read_count, 1)
        self.assertEqual(api.close_count, 1)

    def test_daily_task_error_marks_needs_review(self) -> None:
        store = FakeStore()
        game = FakeGameClient(DailyGameOutcome(daily_points=100, task_error="DailyTask: bad"))

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
            ).run()

        self.assertEqual(result.status, "needs review")
        self.assertEqual(result.error, "DailyTask: bad")

    def test_daily_exception_is_persisted_as_failure(self) -> None:
        store = FakeStore()
        game = FakeGameClient(exc=RuntimeError("boom"))

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
            ).run()

        self.assertEqual(result.status, "failure")
        self.assertIn("RuntimeError: boom", result.error)
        self.assertEqual(store.daily_results, [result])

    def test_daily_retries_task_error_before_final_success(self) -> None:
        store = FakeStore()
        game = FakeGameClient()
        game.outcome = DailyGameOutcome(daily_points=0, task_error="bad")
        outcomes = [
            DailyGameOutcome(daily_points=0, task_error="bad"),
            DailyGameOutcome(daily_points=100),
        ]

        def run_daily(sheet_config):
            game.configs.append(sheet_config)
            return outcomes.pop(0)

        game.run_daily = run_daily
        sleeps = []

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=2, delay_seconds=4),
                sleep=sleeps.append,
            ).run()

        self.assertEqual(result.status, "success")
        self.assertEqual(len(game.configs), 2)
        self.assertEqual(sleeps, [4])
        self.assertIn("已触发重试", result.decision)

    def test_daily_notice_runs_once_for_final_failure(self) -> None:
        store = FakeStore()
        game = FakeGameClient(exc=RuntimeError("boom"))
        notice = FakeNoticeClient()

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
                notice_client=notice,
            ).run()

        self.assertEqual(result.status, "failure")
        self.assertEqual(notice.calls, [(result, store.sheet_config)])

    def test_daily_success_notice_can_be_skipped(self) -> None:
        store = FakeStore()
        game = FakeGameClient(DailyGameOutcome(daily_points=100))
        notice = FakeNoticeClient()

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(
                store=store,
                game_client=game,
                notice_client=notice,
                skip_success_notice=True,
            ).run()

        self.assertEqual(result.status, "success")
        self.assertEqual(notice.calls, [])

    def test_daily_healthcheck_pings_start_and_completion(self) -> None:
        store = FakeStore()
        game = FakeGameClient(DailyGameOutcome(daily_points=100))
        healthcheck = FakeHealthcheckMonitor()

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game, healthcheck_monitor=healthcheck).run()

        self.assertEqual(result.status, "success")
        self.assertEqual(healthcheck.calls, [("start", "running"), ("complete", "success")])

    def test_daily_healthcheck_failure_is_recorded_without_failing_task(self) -> None:
        store = FakeStore()
        game = FakeGameClient(DailyGameOutcome(daily_points=100))
        healthcheck = FakeHealthcheckMonitor(complete_exc=RuntimeError("hc down"))

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = DailyRunner(store=store, game_client=game, healthcheck_monitor=healthcheck).run()

        self.assertEqual(result.status, "success")
        self.assertIn("Healthchecks completion ping failed: hc down", result.decision)
        self.assertEqual(store.daily_results, [result])


class StaminaRunnerTest(unittest.TestCase):
    def test_partial_burn_then_no_burn_retains_consumption_and_failed_outcome(self):
        game = Mock()
        game.read_stamina.side_effect = [(240, 0), (60, 0)]
        game.run_stamina.return_value = StaminaGameOutcome(60, 0, "reward collection failed")
        with patch("ok_ww_automator.runners.now", return_value=dt.datetime(2026, 5, 16, 4, tzinfo=BEIJING_TZ)):
            result = StaminaRunner(store=FakeStore(), game_client=game,
                                   retry_config=RetryConfig(2, 0)).run()
        self.assertEqual(result.status, "needs review")
        self.assertEqual(result.error, "reward collection failed")
        self.assertEqual((result.stamina_start, result.stamina_left, result.stamina_used), (240, 60, 180))
        game.run_stamina.assert_called_once()

    def test_cleanup_failures_preserve_original_error_and_complete_reporting(self):
        store = FakeStore(SheetRunConfig(shutdown_after_stamina=True))
        api = FakeApiClient()
        api.close = Mock(side_effect=RuntimeError("API close failed"))
        game = FakeStaminaGameClient(read_exc=RuntimeError("original read error"))
        game.close = Mock(side_effect=RuntimeError("game close failed"))
        notice = FakeNoticeClient()
        power = FakePowerController()
        monitor = FakeHealthcheckMonitor()
        result = StaminaRunner(
            store=store, game_client=game, api_client=api, notice_client=notice,
            power_controller=power, healthcheck_monitor=monitor,
            retry_config=RetryConfig(1, 0),
        ).run()
        self.assertEqual(result.status, "failure")
        self.assertIn("original read error", result.error)
        self.assertIn("API close failed", result.decision)
        self.assertIn("game close failed", result.decision)
        self.assertEqual(store.stamina_results, [result])
        self.assertEqual(notice.calls, [(result, store.sheet_config)])
        self.assertEqual(monitor.calls[-1], ("complete", "failure"))
        self.assertEqual(power.requests, ["stamina"])

    def test_burn_prediction_uses_time_after_slow_stamina_read(self):
        started = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)
        observed = started + dt.timedelta(minutes=30)
        game = FakeStaminaGameClient(stamina=(231, 0))
        with patch("ok_ww_automator.runners.now", side_effect=[started, observed, observed]):
            result = StaminaRunner(store=FakeStore(), game_client=game).run()
        self.assertEqual(result.status, "skipped")
        self.assertEqual(game.run_configs, [])
        self.assertEqual(result.ended_at, observed)

    def test_skip_stamina_once_clears_flag_and_persists_skipped_result(self) -> None:
        store = FakeStore(SheetRunConfig(skip_stamina_once=True))
        game = FakeStaminaGameClient()

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = StaminaRunner(store=store, game_client=game).run()

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.ended_at, result.started_at)
        self.assertEqual(store.cleared, ["stamina"])
        self.assertEqual(store.stamina_results, [result])
        self.assertEqual(game.read_configs, [])
        self.assertEqual(game.run_configs, [])
        self.assertEqual(game.closed_configs, [store.sheet_config])

    def test_no_burn_needed_skips_without_running_task(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(stamina=(100, 0))
        start = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.stamina_start, 100)
        self.assertEqual(result.stamina_left, 100)
        self.assertEqual(result.stamina_used, 0)
        self.assertIn("不会溢出", result.decision)
        self.assertEqual(game.run_configs, [])

    def test_api_stamina_skips_game_read_when_available(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(stamina=(999, 999))
        api = FakeApiClient(info=WavesDailyInfo(stamina=100, backup_stamina=0, daily_points=0))
        start = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(store=store, game_client=game, api_client=api, daily_hour=5, daily_minute=0).run()

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.stamina_start, 100)
        self.assertEqual(game.read_configs, [])
        self.assertEqual(api.read_count, 1)
        self.assertEqual(api.close_count, 1)

    def test_api_stamina_falls_back_to_game_read_when_missing(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(stamina=(100, 0))
        api = FakeApiClient(info=None)
        start = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(store=store, game_client=game, api_client=api, daily_hour=5, daily_minute=0).run()

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.stamina_start, 100)
        self.assertEqual(game.read_configs, [store.sheet_config])
        self.assertEqual(api.close_count, 1)

    def test_burn_needed_runs_task_and_marks_success_for_exact_burn(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(
            stamina=(60, 0),
            outcome=StaminaGameOutcome(stamina_left=0, backup_stamina_left=0),
        )
        start = dt.datetime(2026, 5, 15, 9, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "success")
        self.assertEqual(result.stamina_used, 60)
        self.assertEqual(game.run_configs, [store.sheet_config])
        self.assertEqual(store.stamina_results, [result])

    def test_stamina_append_failure_does_not_turn_success_into_failure(self) -> None:
        store = FakeStore(stamina_append_exc=RuntimeError("sheet unavailable"))
        game = FakeStaminaGameClient(
            stamina=(60, 0),
            outcome=StaminaGameOutcome(stamina_left=0, backup_stamina_left=0),
        )
        start = dt.datetime(2026, 5, 15, 9, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error)
        self.assertIn("写入表格日志失败: sheet unavailable", result.decision)
        self.assertEqual(store.stamina_results, [])

    def test_stamina_clear_skip_once_failure_marks_task_needs_review(self) -> None:
        store = FakeStore(SheetRunConfig(skip_stamina_once=True), clear_exc=RuntimeError("sheet unavailable"))
        game = FakeStaminaGameClient()

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = StaminaRunner(store=store, game_client=game).run()

        self.assertEqual(result.status, "needs review")
        self.assertIn("清除跳过一次标记失败: sheet unavailable", result.decision)
        self.assertEqual(store.cleared, [])
        self.assertEqual(store.stamina_results, [result])

    def test_stamina_shutdown_config_requests_shutdown_after_close(self) -> None:
        store = FakeStore(SheetRunConfig(shutdown_after_stamina=True))
        game = FakeStaminaGameClient(
            stamina=(60, 0),
            outcome=StaminaGameOutcome(stamina_left=0, backup_stamina_left=0),
        )
        power = FakePowerController()
        start = dt.datetime(2026, 5, 15, 9, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                power_controller=power,
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "success")
        self.assertEqual(game.closed_configs, [store.sheet_config])
        self.assertEqual(power.requests, ["stamina"])

    def test_overburn_is_needs_review_even_when_task_runs(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(
            stamina=(180, 0),
            outcome=StaminaGameOutcome(stamina_left=0, backup_stamina_left=0),
        )
        start = dt.datetime(2026, 5, 15, 22, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "needs review")
        self.assertEqual(result.stamina_used, 180)
        self.assertIn("过量消耗", result.decision)

    def test_task_error_is_needs_review(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(
            stamina=(60, 0),
            outcome=StaminaGameOutcome(stamina_left=0, backup_stamina_left=0, task_error="TacetTask: bad"),
        )
        start = dt.datetime(2026, 5, 15, 9, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "needs review")
        self.assertEqual(result.error, "TacetTask: bad")

    def test_read_failure_is_persisted_as_failure(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(read_exc=RuntimeError("cannot read"))

        with patch("ok_ww_automator.runners.now", return_value=FIXED_NOW):
            result = StaminaRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=1, delay_seconds=0),
            ).run()

        self.assertEqual(result.status, "failure")
        self.assertIn("RuntimeError: cannot read", result.error)
        self.assertEqual(store.stamina_results, [result])

    def test_stamina_retries_read_failure_before_success(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(
            stamina=(60, 0),
            outcome=StaminaGameOutcome(stamina_left=0, backup_stamina_left=0),
            read_exc=RuntimeError("cannot read"),
        )
        sleeps = []
        start = dt.datetime(2026, 5, 15, 9, 0, tzinfo=BEIJING_TZ)

        def read_stamina(sheet_config):
            game.read_configs.append(sheet_config)
            if len(game.read_configs) == 1:
                raise RuntimeError("cannot read")
            return game.stamina

        game.read_stamina = read_stamina

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                retry_config=RetryConfig(max_attempts=2, delay_seconds=3),
                sleep=sleeps.append,
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "success")
        self.assertEqual(len(game.read_configs), 2)
        self.assertEqual(sleeps, [3])
        self.assertIn("已触发重试", result.decision)

    def test_stamina_notice_sends_expected_skip(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(stamina=(100, 0))
        notice = FakeNoticeClient()
        start = dt.datetime(2026, 5, 16, 4, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                notice_client=notice,
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "skipped")
        self.assertEqual(notice.calls, [(result, store.sheet_config)])

    def test_stamina_healthcheck_pings_failure_for_needs_review(self) -> None:
        store = FakeStore()
        game = FakeStaminaGameClient(
            stamina=(180, 0),
            outcome=StaminaGameOutcome(stamina_left=0, backup_stamina_left=0),
        )
        healthcheck = FakeHealthcheckMonitor()
        start = dt.datetime(2026, 5, 15, 22, 0, tzinfo=BEIJING_TZ)

        with patch("ok_ww_automator.runners.now", return_value=start):
            result = StaminaRunner(
                store=store,
                game_client=game,
                healthcheck_monitor=healthcheck,
                daily_hour=5,
                daily_minute=0,
            ).run()

        self.assertEqual(result.status, "needs review")
        self.assertEqual(healthcheck.calls, [("start", "running"), ("complete", "needs review")])


if __name__ == "__main__":
    unittest.main()
