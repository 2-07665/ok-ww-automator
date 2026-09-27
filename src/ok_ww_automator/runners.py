"""Runner orchestration for scheduled automation jobs."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
import subprocess
import time
import traceback
from pathlib import Path
from typing import Callable, Protocol

from .config import AppConfig, RetryConfig
from .game_clients import (
    DailyGameClient,
    DailyGameOutcome,
    StaminaGameClient,
    StaminaGameOutcome,
    SubprocessDailyGameClient,
    SubprocessStaminaGameClient,
    SubprocessWeeklyGameClient,
    stamina_burn_unit,
)
from .healthchecks import HealthcheckMonitor, NullHealthcheckMonitor, healthcheck_monitor_from_config
from .models import RunResult, SheetRunConfig
from .notices import NoticeClient, NullNoticeClient, notice_client_from_config, should_notify
from .sheets import GoogleSheetsStore
from .time_utils import calculate_burn, now
from .waves_api import WavesApiClient, WavesDailyInfo, is_api_success

RUN_STATUS_FAILURE = "failure"
RUN_STATUS_NEEDS_REVIEW = "needs review"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SKIPPED = "skipped"
RUN_STATUS_SUCCESS = "success"


class RunnerError(RuntimeError):
    """Raised when a scheduled runner cannot be executed."""


@dataclass(frozen=True)
class RunnerContext:
    app_config: AppConfig
    ww_root: Path
    run_now: bool = False
    prepare: Callable[[float], None] | None = None
    shutdown_request_file: Path | None = None


class DailyApiClient(Protocol):
    def sign_in(self) -> dict: ...

    def read_daily_info(self) -> WavesDailyInfo | None: ...

    def close(self) -> None: ...


class PowerController(Protocol):
    def request_shutdown(self, reason: str) -> None: ...


class SystemPowerController:
    def request_shutdown(self, reason: str) -> None:
        command = ["shutdown", "/s", "/t", "0"] if os.name == "nt" else ["shutdown", "-h", "now"]
        subprocess.run(command, check=False)


class DeferredPowerController:
    """Record the existing runner's shutdown request for the outer scheduler."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def request_shutdown(self, reason: str) -> None:
        self.path.write_text(reason, encoding="utf-8")


class SheetsRunStore(Protocol):
    def fetch_run_config_or_default(self) -> tuple[SheetRunConfig, str | None]: ...

    def clear_skip_once(self, task_type: str) -> bool: ...

    def append_daily_result(self, result: RunResult) -> None: ...

    def append_stamina_result(self, result: RunResult) -> None: ...


def run_mode(mode: str, context: RunnerContext) -> RunResult:
    if mode == "weekly":
        from .weekly import WeeklyRunner

        return WeeklyRunner(
            context.app_config,
            SubprocessWeeklyGameClient(context.app_config, ww_root=context.ww_root),
            run_now=context.run_now,
            prepare=context.prepare,
        ).run()
    if mode == "daily":
        store = GoogleSheetsStore.from_config(context.app_config.google_sheets)
        game_client = SubprocessDailyGameClient(context.app_config, ww_root=context.ww_root)
        api_client = api_client_from_config(context.app_config)
        notice_client = notice_client_from_config(context.app_config.notice)
        healthcheck_monitor = healthcheck_monitor_from_config(context.app_config.healthchecks, "daily")
        return DailyRunner(
            store=store,
            game_client=game_client,
            power_controller=(DeferredPowerController(context.shutdown_request_file)
                              if context.shutdown_request_file is not None else None),
            api_client=api_client,
            retry_config=context.app_config.retry,
            notice_client=notice_client,
            skip_success_notice=context.app_config.notice.skip_success,
            healthcheck_monitor=healthcheck_monitor,
        ).run()
    if mode == "stamina":
        store = GoogleSheetsStore.from_config(context.app_config.google_sheets)
        game_client = SubprocessStaminaGameClient(context.app_config, ww_root=context.ww_root)
        api_client = api_client_from_config(context.app_config)
        notice_client = notice_client_from_config(context.app_config.notice)
        healthcheck_monitor = healthcheck_monitor_from_config(context.app_config.healthchecks, "stamina")
        return StaminaRunner(
            store=store,
            game_client=game_client,
            power_controller=(DeferredPowerController(context.shutdown_request_file)
                              if context.shutdown_request_file is not None else None),
            api_client=api_client,
            retry_config=context.app_config.retry,
            notice_client=notice_client,
            skip_success_notice=context.app_config.notice.skip_success,
            healthcheck_monitor=healthcheck_monitor,
            daily_hour=context.app_config.daily_run_time.hour,
            daily_minute=context.app_config.daily_run_time.minute,
        ).run()
    raise RunnerError(f"Unsupported runner mode: {mode}")


def api_client_from_config(app_config: AppConfig) -> WavesApiClient | None:
    if not app_config.waves_api.enabled:
        return None
    return WavesApiClient(app_config.waves_api)


class DailyRunner:
    def __init__(
        self,
        *,
        store: SheetsRunStore,
        game_client: DailyGameClient,
        api_client: DailyApiClient | None = None,
        power_controller: PowerController | None = None,
        retry_config: RetryConfig | None = None,
        notice_client: NoticeClient | None = None,
        skip_success_notice: bool = False,
        healthcheck_monitor: HealthcheckMonitor | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.game_client = game_client
        self.api_client = api_client
        self.power_controller = power_controller or SystemPowerController()
        self.retry_config = retry_config or RetryConfig()
        self.notice_client = notice_client or NullNoticeClient()
        self.skip_success_notice = skip_success_notice
        self.healthcheck_monitor = healthcheck_monitor or NullHealthcheckMonitor()
        self.sleep = sleep

    def run(self) -> RunResult:
        sheet_config, config_error = self.store.fetch_run_config_or_default()
        result = RunResult(
            task_type="daily",
            started_at=now(),
            ended_at=None,
            status=RUN_STATUS_RUNNING,
            run_nightmare=sheet_config.should_run_nightmare,
        )
        self.start_healthcheck(result)
        if config_error:
            result.decision = f"读取表格配置失败，使用默认配置: {config_error}"

        try:
            self.fill_from_api(result)
            if should_skip_daily(sheet_config):
                apply_daily_skip(result, sheet_config)
                if sheet_config.skip_daily_once:
                    self.clear_skip_once(result, "daily")
            else:
                outcome = self.run_daily_with_retries(sheet_config, result)
                apply_daily_outcome(result, outcome)
        except Exception as exc:
            result.status = RUN_STATUS_FAILURE
            result.ended_at = now()
            result.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        finally:
            if self.api_client is not None:
                cleanup(result, "Waves API", self.api_client.close)
        self.complete_and_persist(result)
        self.notify(result, sheet_config)
        if sheet_config.shutdown_after_daily:
            self.power_controller.request_shutdown("daily")
        return result

    def persist(self, result: RunResult) -> RunResult:
        result.ensure_ended_at()
        try:
            self.store.append_daily_result(result)
        except Exception as exc:
            append_decision(result, f"写入表格日志失败: {exc}")
        return result

    def complete_and_persist(self, result: RunResult) -> RunResult:
        result.ensure_ended_at()
        self.complete_healthcheck(result)
        return self.persist(result)

    def start_healthcheck(self, result: RunResult) -> None:
        try:
            self.healthcheck_monitor.start(result)
        except Exception as exc:
            append_decision(result, f"Healthchecks start ping failed: {exc}")

    def complete_healthcheck(self, result: RunResult) -> None:
        try:
            self.healthcheck_monitor.complete(result)
        except Exception as exc:
            append_decision(result, f"Healthchecks completion ping failed: {exc}")

    def clear_skip_once(self, result: RunResult, task_type: str) -> None:
        try:
            self.store.clear_skip_once(task_type)
        except Exception as exc:
            result.status = RUN_STATUS_NEEDS_REVIEW
            append_decision(result, f"清除跳过一次标记失败: {exc}")

    def fill_from_api(self, result: RunResult) -> None:
        if self.api_client is None:
            return
        sign_in_response = self.api_client.sign_in()
        result.sign_in_success = is_api_success(sign_in_response)
        if info := self.api_client.read_daily_info():
            result.fill_stamina_start(info.stamina, info.backup_stamina)
            result.fill_stamina_left_from_start()
            result.daily_points = info.daily_points

    def run_daily_with_retries(self, sheet_config: SheetRunConfig, result: RunResult) -> DailyGameOutcome:
        last_outcome = DailyGameOutcome(task_error="Daily task did not run")
        first_stamina: tuple[int | None, int | None] | None = None
        for attempt in range(1, self.retry_config.max_attempts + 1):
            try:
                outcome = self.game_client.run_daily(sheet_config)
            except Exception as exc:
                if attempt >= self.retry_config.max_attempts:
                    raise
                append_retry_decision(result, attempt, exc)
                self.sleep(self.retry_config.delay_seconds)
                continue

            if first_stamina is None and outcome.stamina_start is not None:
                first_stamina = (outcome.stamina_start, outcome.backup_stamina_start)
            if first_stamina is not None:
                outcome = replace(outcome, stamina_start=first_stamina[0], backup_stamina_start=first_stamina[1])
            # Retain observations from a partially completed attempt even if a
            # later retry raises before returning any metrics.
            apply_daily_outcome(result, outcome)
            last_outcome = outcome
            if not outcome.task_error or attempt >= self.retry_config.max_attempts:
                return outcome
            append_retry_decision(result, attempt, outcome.task_error)
            self.sleep(self.retry_config.delay_seconds)
        return last_outcome

    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        if not should_notify(result, skip_success=self.skip_success_notice):
            return
        try:
            self.notice_client.notify(result, sheet_config)
        except Exception as exc:
            append_decision(result, f"通知发送失败: {exc}")


class StaminaRunner:
    def __init__(
        self,
        *,
        store: SheetsRunStore,
        game_client: StaminaGameClient,
        api_client: DailyApiClient | None = None,
        power_controller: PowerController | None = None,
        retry_config: RetryConfig | None = None,
        notice_client: NoticeClient | None = None,
        skip_success_notice: bool = False,
        healthcheck_monitor: HealthcheckMonitor | None = None,
        sleep: Callable[[float], None] = time.sleep,
        daily_hour: int = 5,
        daily_minute: int = 0,
    ) -> None:
        self.store = store
        self.game_client = game_client
        self.api_client = api_client
        self.power_controller = power_controller or SystemPowerController()
        self.retry_config = retry_config or RetryConfig()
        self.notice_client = notice_client or NullNoticeClient()
        self.skip_success_notice = skip_success_notice
        self.healthcheck_monitor = healthcheck_monitor or NullHealthcheckMonitor()
        self.sleep = sleep
        self.daily_hour = daily_hour
        self.daily_minute = daily_minute

    def run(self) -> RunResult:
        sheet_config, config_error = self.store.fetch_run_config_or_default()
        result = RunResult(
            task_type="stamina",
            started_at=now(),
            ended_at=None,
            status=RUN_STATUS_RUNNING,
        )
        self.start_healthcheck(result)
        if config_error:
            result.decision = f"读取表格配置失败，使用默认配置: {config_error}"

        try:
            if should_skip_stamina(sheet_config):
                apply_stamina_skip(result)
                if sheet_config.skip_stamina_once:
                    self.clear_skip_once(result, "stamina")
            else:
                outcome, expected_burn, exact_expected = self.run_stamina_with_retries(sheet_config, result)
                if outcome is not None:
                    apply_stamina_outcome(result, outcome, expected_burn=expected_burn, exact_expected=exact_expected)
        except Exception as exc:
            result.status = RUN_STATUS_FAILURE
            result.ended_at = now()
            result.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        finally:
            if self.api_client is not None:
                cleanup(result, "Waves API", self.api_client.close)
            cleanup(result, "游戏", lambda: self.game_client.close(sheet_config))
        self.complete_and_persist(result)
        self.notify(result, sheet_config)
        if sheet_config.shutdown_after_stamina:
            self.power_controller.request_shutdown("stamina")
        return result

    def persist(self, result: RunResult) -> RunResult:
        result.ensure_ended_at()
        try:
            self.store.append_stamina_result(result)
        except Exception as exc:
            append_decision(result, f"写入表格日志失败: {exc}")
        return result

    def complete_and_persist(self, result: RunResult) -> RunResult:
        result.ensure_ended_at()
        self.complete_healthcheck(result)
        return self.persist(result)

    def start_healthcheck(self, result: RunResult) -> None:
        try:
            self.healthcheck_monitor.start(result)
        except Exception as exc:
            append_decision(result, f"Healthchecks start ping failed: {exc}")

    def complete_healthcheck(self, result: RunResult) -> None:
        try:
            self.healthcheck_monitor.complete(result)
        except Exception as exc:
            append_decision(result, f"Healthchecks completion ping failed: {exc}")

    def clear_skip_once(self, result: RunResult, task_type: str) -> None:
        try:
            self.store.clear_skip_once(task_type)
        except Exception as exc:
            result.status = RUN_STATUS_NEEDS_REVIEW
            append_decision(result, f"清除跳过一次标记失败: {exc}")

    def read_stamina(self, sheet_config: SheetRunConfig) -> tuple[int | None, int | None]:
        if self.api_client is not None:
            if info := self.api_client.read_daily_info():
                return info.stamina, info.backup_stamina
        return self.game_client.read_stamina(sheet_config)

    def run_stamina_with_retries(
        self,
        sheet_config: SheetRunConfig,
        result: RunResult,
    ) -> tuple[StaminaGameOutcome | None, int, bool]:
        expected_burn = 0
        exact_expected = True
        has_initial_stamina = False
        previous_error: str | None = None
        last_outcome = StaminaGameOutcome(task_error="Stamina task did not run")
        for attempt in range(1, self.retry_config.max_attempts + 1):
            try:
                stamina, backup_stamina = self.read_stamina(sheet_config)
                if not has_initial_stamina and stamina is not None:
                    result.fill_stamina_start(stamina, backup_stamina)
                    has_initial_stamina = True
                result.fill_stamina_left(stamina, backup_stamina)
                result.fill_stamina_used()
                decision = calculate_burn(
                    stamina,
                    backup_stamina,
                    stamina_consume_unit=stamina_burn_unit(sheet_config),
                    daily_hour=self.daily_hour,
                    daily_minute=self.daily_minute,
                    start_time=now(),
                )
                append_decision(result, decision.reason)

                if not decision.should_run:
                    apply_stamina_no_run(result, decision.is_expected)
                    if previous_error is not None:
                        result.status = RUN_STATUS_NEEDS_REVIEW
                        result.error = previous_error
                    return None, decision.burn_amount, decision.is_expected

                expected_burn = (result.stamina_used or 0) + decision.burn_amount
                exact_expected = exact_expected and decision.is_expected
                outcome = self.game_client.run_stamina(sheet_config)
            except Exception as exc:
                previous_error = str(exc)
                cleanup(result, "游戏", lambda: self.game_client.close(sheet_config))
                if attempt >= self.retry_config.max_attempts:
                    raise
                append_retry_decision(result, attempt, exc)
                self.sleep(self.retry_config.delay_seconds)
                continue

            result.fill_stamina_left(outcome.stamina_left, outcome.backup_stamina_left)
            result.fill_stamina_used()
            last_outcome = outcome
            if not outcome.task_error or attempt >= self.retry_config.max_attempts:
                return outcome, expected_burn, exact_expected
            previous_error = outcome.task_error
            cleanup(result, "游戏", lambda: self.game_client.close(sheet_config))
            append_retry_decision(result, attempt, outcome.task_error)
            self.sleep(self.retry_config.delay_seconds)
        return last_outcome, expected_burn, exact_expected

    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        if not should_notify(result, skip_success=self.skip_success_notice):
            return
        try:
            self.notice_client.notify(result, sheet_config)
        except Exception as exc:
            append_decision(result, f"通知发送失败: {exc}")


def should_skip_daily(sheet_config: SheetRunConfig) -> bool:
    return sheet_config.skip_daily_once or not sheet_config.run_daily


def should_skip_stamina(sheet_config: SheetRunConfig) -> bool:
    return sheet_config.skip_stamina_once or not sheet_config.run_stamina


def apply_daily_skip(result: RunResult, sheet_config: SheetRunConfig) -> None:
    result.ended_at = result.started_at
    result.status = RUN_STATUS_SKIPPED
    append_decision(result, "日常任务设置为不执行")
    result.run_nightmare = False
    result.fill_stamina_left_from_start()
    if result.stamina_start is not None:
        result.stamina_used = 0


def apply_stamina_skip(result: RunResult) -> None:
    result.ended_at = result.started_at
    result.status = RUN_STATUS_SKIPPED
    append_decision(result, "体力任务设置为不执行")
    result.fill_stamina_left_from_start()
    if result.stamina_start is not None:
        result.stamina_used = 0


def apply_stamina_no_run(result: RunResult, is_expected: bool) -> None:
    result.ended_at = now()
    result.fill_stamina_used()
    result.status = RUN_STATUS_SKIPPED if is_expected else RUN_STATUS_NEEDS_REVIEW


def apply_daily_outcome(result: RunResult, outcome: DailyGameOutcome) -> None:
    fill_if_available(result.fill_stamina_start, outcome.stamina_start, outcome.backup_stamina_start)
    result.fill_stamina_left(outcome.stamina_left, outcome.backup_stamina_left)
    result.fill_stamina_used()
    result.daily_points = outcome.daily_points
    result.error = outcome.task_error
    result.ended_at = now()
    if outcome.daily_points is not None and outcome.daily_points >= 100 and not outcome.task_error:
        result.status = RUN_STATUS_SUCCESS
    else:
        result.status = RUN_STATUS_NEEDS_REVIEW


def apply_stamina_outcome(
    result: RunResult,
    outcome: StaminaGameOutcome,
    *,
    expected_burn: int,
    exact_expected: bool,
) -> None:
    result.fill_stamina_left(outcome.stamina_left, outcome.backup_stamina_left)
    result.fill_stamina_used()
    result.error = outcome.task_error
    result.ended_at = now()
    if exact_expected and result.stamina_used == expected_burn and not outcome.task_error:
        result.status = RUN_STATUS_SUCCESS
    else:
        result.status = RUN_STATUS_NEEDS_REVIEW


def append_decision(result: RunResult, decision: str) -> None:
    if result.decision:
        result.decision = f"{result.decision}; {decision}"
    else:
        result.decision = decision


def cleanup(result: RunResult, name: str, close: Callable[[], None]) -> None:
    """Report cleanup errors without losing the task result or other cleanup."""
    try:
        close()
    except Exception as exc:
        append_decision(result, f"{name} 清理失败: {exc}")


def append_retry_decision(result: RunResult, attempt: int, reason: object) -> None:
    append_decision(result, f"[第 {attempt} 次尝试失败(已触发重试): {reason}]")


def fill_if_available(fill, stamina: int | None, backup_stamina: int | None) -> None:
    if stamina is not None or backup_stamina is not None:
        fill(stamina, backup_stamina)
