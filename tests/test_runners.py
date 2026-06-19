import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import RetryConfig
from ok_ww_automator.models import RunResult, SheetRunConfig
from ok_ww_automator.runners import (
    DailyRunner,
    StaminaRunner,
)
from ok_ww_automator.game_clients import (
    DailyGameOutcome,
    StaminaGameOutcome,
)
from ok_ww_automator.time_utils import BEIJING_TZ
from ok_ww_automator.waves_api import WavesDailyInfo


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
