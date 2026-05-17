"""Runner orchestration for scheduled automation jobs."""

from __future__ import annotations

from dataclasses import dataclass
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
    OkDailyGameClient,
    OkStaminaGameClient,
    StaminaGameClient,
    StaminaGameOutcome,
    stamina_burn_unit,
)
from .models import RunResult, SheetRunConfig
from .notices import NoticeClient, NullNoticeClient, notice_client_from_config, should_notify
from .ok_launcher import OkLauncher
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


class SheetsRunStore(Protocol):
    def fetch_run_config_or_default(self) -> tuple[SheetRunConfig, str | None]: ...

    def clear_skip_once(self, task_type: str) -> bool: ...

    def append_daily_result(self, result: RunResult) -> None: ...

    def append_stamina_result(self, result: RunResult) -> None: ...


def run_mode(mode: str, context: RunnerContext) -> RunResult:
    if mode == "daily":
        store = GoogleSheetsStore.from_config(context.app_config.google_sheets)
        launcher = OkLauncher.from_app_config(context.app_config, ww_root=context.ww_root)
        game_client = OkDailyGameClient(launcher)
        api_client = api_client_from_config(context.app_config)
        notice_client = notice_client_from_config(context.app_config.notice)
        return DailyRunner(
            store=store,
            game_client=game_client,
            api_client=api_client,
            retry_config=context.app_config.retry,
            notice_client=notice_client,
        ).run()
    if mode == "stamina":
        store = GoogleSheetsStore.from_config(context.app_config.google_sheets)
        launcher = OkLauncher.from_app_config(context.app_config, ww_root=context.ww_root)
        game_client = OkStaminaGameClient(launcher)
        api_client = api_client_from_config(context.app_config)
        notice_client = notice_client_from_config(context.app_config.notice)
        return StaminaRunner(
            store=store,
            game_client=game_client,
            api_client=api_client,
            retry_config=context.app_config.retry,
            notice_client=notice_client,
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
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.game_client = game_client
        self.api_client = api_client
        self.power_controller = power_controller or SystemPowerController()
        self.retry_config = retry_config or RetryConfig()
        self.notice_client = notice_client or NullNoticeClient()
        self.sleep = sleep

    def run(self) -> RunResult:
        sheet_config, config_error = self.store.fetch_run_config_or_default()
        result = RunResult(
            task_type="daily",
            started_at=now(),
            ended_at=None,
            status=RUN_STATUS_RUNNING,
            run_nightmare=sheet_config.run_nightmare,
        )
        if config_error:
            result.decision = f"读取表格配置失败，使用默认配置: {config_error}"

        try:
            self.fill_from_api(result)
            if should_skip_daily(sheet_config):
                apply_daily_skip(result, sheet_config)
                if sheet_config.skip_daily_once:
                    self.store.clear_skip_once("daily")
                return self.persist(result)

            outcome = self.run_daily_with_retries(sheet_config, result)
            apply_daily_outcome(result, outcome)
            return self.persist(result)
        except Exception as exc:
            result.status = RUN_STATUS_FAILURE
            result.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            return self.persist(result)
        finally:
            if self.api_client is not None:
                self.api_client.close()
            self.notify(result, sheet_config)
            if sheet_config.shutdown_after_daily:
                self.power_controller.request_shutdown("daily")

    def persist(self, result: RunResult) -> RunResult:
        result.ensure_ended_at()
        self.store.append_daily_result(result)
        return result

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
        for attempt in range(1, self.retry_config.max_attempts + 1):
            try:
                outcome = self.game_client.run_daily(sheet_config)
            except Exception as exc:
                if attempt >= self.retry_config.max_attempts:
                    raise
                append_retry_decision(result, attempt, exc)
                self.sleep(self.retry_config.delay_seconds)
                continue

            last_outcome = outcome
            if not outcome.task_error or attempt >= self.retry_config.max_attempts:
                return outcome
            append_retry_decision(result, attempt, outcome.task_error)
            self.sleep(self.retry_config.delay_seconds)
        return last_outcome

    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        if not should_notify(result):
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
        if config_error:
            result.decision = f"读取表格配置失败，使用默认配置: {config_error}"

        try:
            if should_skip_stamina(sheet_config):
                apply_stamina_skip(result)
                if sheet_config.skip_stamina_once:
                    self.store.clear_skip_once("stamina")
                return self.persist(result)

            outcome, expected_burn, exact_expected = self.run_stamina_with_retries(sheet_config, result)
            if outcome is None:
                return self.persist(result)
            apply_stamina_outcome(result, outcome, expected_burn=expected_burn, exact_expected=exact_expected)
            return self.persist(result)
        except Exception as exc:
            result.status = RUN_STATUS_FAILURE
            result.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            return self.persist(result)
        finally:
            if self.api_client is not None:
                self.api_client.close()
            self.game_client.close(sheet_config)
            self.notify(result, sheet_config)
            if sheet_config.shutdown_after_stamina:
                self.power_controller.request_shutdown("stamina")

    def persist(self, result: RunResult) -> RunResult:
        result.ensure_ended_at()
        self.store.append_stamina_result(result)
        return result

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
        last_outcome = StaminaGameOutcome(task_error="Stamina task did not run")
        for attempt in range(1, self.retry_config.max_attempts + 1):
            try:
                stamina, backup_stamina = self.read_stamina(sheet_config)
                result.fill_stamina_start(stamina, backup_stamina)
                decision = calculate_burn(
                    stamina,
                    backup_stamina,
                    stamina_consume_unit=stamina_burn_unit(sheet_config),
                    daily_hour=self.daily_hour,
                    daily_minute=self.daily_minute,
                    start_time=result.started_at,
                )
                append_decision(result, decision.reason)

                if not decision.should_run:
                    apply_stamina_no_run(result, decision.is_expected)
                    return None, decision.burn_amount, decision.is_expected

                expected_burn = decision.burn_amount
                exact_expected = decision.is_expected
                outcome = self.game_client.run_stamina(sheet_config)
            except Exception as exc:
                self.game_client.close(sheet_config)
                if attempt >= self.retry_config.max_attempts:
                    raise
                append_retry_decision(result, attempt, exc)
                self.sleep(self.retry_config.delay_seconds)
                continue

            last_outcome = outcome
            if not outcome.task_error or attempt >= self.retry_config.max_attempts:
                return outcome, expected_burn, exact_expected
            self.game_client.close(sheet_config)
            append_retry_decision(result, attempt, outcome.task_error)
            self.sleep(self.retry_config.delay_seconds)
        return last_outcome, expected_burn, exact_expected

    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        if not should_notify(result):
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
    result.decision = "日常任务设置为不执行"
    result.run_nightmare = False
    result.fill_stamina_left_from_start()
    if result.stamina_start is not None:
        result.stamina_used = 0


def apply_stamina_skip(result: RunResult) -> None:
    result.ended_at = result.started_at
    result.status = RUN_STATUS_SKIPPED
    result.decision = "体力任务设置为不执行"
    result.fill_stamina_left_from_start()
    if result.stamina_start is not None:
        result.stamina_used = 0


def apply_stamina_no_run(result: RunResult, is_expected: bool) -> None:
    result.ended_at = result.started_at
    result.fill_stamina_left_from_start()
    if result.stamina_start is not None:
        result.stamina_used = 0
    result.status = RUN_STATUS_SKIPPED if is_expected else RUN_STATUS_NEEDS_REVIEW


def apply_daily_outcome(result: RunResult, outcome: DailyGameOutcome) -> None:
    fill_if_available(result.fill_stamina_start, outcome.stamina_start, outcome.backup_stamina_start)
    fill_if_available(result.fill_stamina_left, outcome.stamina_left, outcome.backup_stamina_left)
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


def append_retry_decision(result: RunResult, attempt: int, reason: object) -> None:
    append_decision(result, f"第 {attempt} 次运行失败，准备重试: {reason}")


def fill_if_available(fill, stamina: int | None, backup_stamina: int | None) -> None:
    if stamina is not None or backup_stamina is not None:
        fill(stamina, backup_stamina)
