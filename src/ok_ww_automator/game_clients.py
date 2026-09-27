"""Game clients for executing ok-script tasks."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol

from .config import AppConfig
from .models import SheetRunConfig
from .ok_launcher import OkLauncher, kill_game_processes, run_onetime_task, ww_runtime_context
from .processes import run_with_timeout

WINDOWS_ACCESS_VIOLATION_EXIT_CODE = 0xC0000005
WINDOWS_ACCESS_VIOLATION_SIGNED_EXIT_CODE = -1073741819
WINDOWS_NATIVE_TEARDOWN_EXIT_CODES = {
    WINDOWS_ACCESS_VIOLATION_EXIT_CODE,
    WINDOWS_ACCESS_VIOLATION_SIGNED_EXIT_CODE,
}
DAILY_ADDITIONAL_TASKS = "Additional Tasks to Run After Daily Task"
AUTO_FARM_NIGHTMARE_NEST = "Auto Farm all Nightmare Nest"
NIGHTMARE_FARM_SELECTION = "Which to Farm"
NIGHTMARE_PURIFICATION = "Nightmare Purification"
TACET_DISCORD_NEST = "Tacet Discord Nest"
BENIGN_DAILY_TASK_ERRORS = frozenset(
    {
        "can not battle pass, maybe ended",
    }
)
GARDEN_COMPLETED_LOG = "乐园任务完成, 已达到上限"


def normalize_daily_task_error(task_error: str | None) -> str | None:
    """Discard upstream DailyTask errors that describe optional work being unavailable."""
    if not task_error:
        return None
    task_error = task_error.strip()
    error_message = task_error.split(": ", 1)[-1]
    if error_message in BENIGN_DAILY_TASK_ERRORS:
        return None
    return task_error or None


@dataclass(frozen=True)
class DailyGameOutcome:
    stamina_start: int | None = None
    backup_stamina_start: int | None = None
    stamina_left: int | None = None
    backup_stamina_left: int | None = None
    daily_points: int | None = None
    task_error: str | None = None


@dataclass(frozen=True)
class StaminaGameOutcome:
    stamina_left: int | None = None
    backup_stamina_left: int | None = None
    task_error: str | None = None


class DailyGameClient(Protocol):
    def run_daily(self, sheet_config: SheetRunConfig) -> DailyGameOutcome: ...


@dataclass(frozen=True)
class WeeklyGameOutcome:
    completed: bool = False
    task_error: str | None = None


class WeeklyGameClient(Protocol):
    def run_weekly(self, *, timeout: float) -> WeeklyGameOutcome: ...


class OkWeeklyGameClient:
    def __init__(self, launcher: OkLauncher) -> None:
        self.launcher = launcher

    def run_weekly(self) -> WeeklyGameOutcome:
        ok = None
        try:
            with ww_runtime_context(self.launcher.options.ww_root):
                ok = self.launcher.start_ok_and_game()
                from src.task.GardenTask import GardenTask

                task = ok.task_executor.get_task_by_class(GardenTask)
                if task is None:
                    raise RuntimeError("GardenTask is not registered")
                try:
                    task_error = run_onetime_task(ok.task_executor, task, timeout_seconds=1800)
                except Exception as exc:
                    if task.info_get("Log") != GARDEN_COMPLETED_LOG:
                        raise
                    task_error = str(exc)
                # This task instance belongs to this attempt's fresh process. Its
                # completion log takes precedence over non-fatal upstream errors.
                completed = task.info_get("Log") == GARDEN_COMPLETED_LOG or not task_error
                return WeeklyGameOutcome(completed=completed, task_error=task_error or None)
        finally:
            if ok is not None:
                close_ok_runtime(ok)
            kill_game_processes()


class SubprocessWeeklyGameClient:
    def __init__(self, app_config: AppConfig, *, ww_root: Path) -> None:
        self.app_config = app_config
        self.ww_root = ww_root

    def run_weekly(self, *, timeout: float = 40 * 60) -> WeeklyGameOutcome:
        payload = run_game_attempt_subprocess(
            self.app_config, self.ww_root, "weekly", "run", SheetRunConfig(), timeout=timeout
        )
        return WeeklyGameOutcome(**payload)


class StaminaGameClient(Protocol):
    def read_stamina(self, sheet_config: SheetRunConfig) -> tuple[int | None, int | None]: ...

    def run_stamina(self, sheet_config: SheetRunConfig) -> StaminaGameOutcome: ...

    def close(self, sheet_config: SheetRunConfig) -> None: ...


class OkDailyGameClient:
    def __init__(self, launcher: OkLauncher) -> None:
        self.launcher = launcher

    def run_daily(self, sheet_config: SheetRunConfig) -> DailyGameOutcome:
        ok = None
        try:
            with ww_runtime_context(self.launcher.options.ww_root):
                ok = self.launcher.start_ok_and_game()
                from src.task.DailyTask import DailyTask
                from src.task.NightmareNestTask import NightmareNestTask

                daily_task = ok.task_executor.get_task_by_class(DailyTask)
                nightmare_task = ok.task_executor.get_task_by_class(NightmareNestTask)
                if daily_task is None or nightmare_task is None:
                    raise RuntimeError("DailyTask or NightmareNestTask is not registered")
                apply_daily_task_config(sheet_config, daily_task, nightmare_task)
                stamina_start, backup_start = read_live_stamina(daily_task)
                task_error = normalize_daily_task_error(
                    run_onetime_task(ok.task_executor, daily_task, timeout_seconds=1800)
                )
                daily_points = read_live_daily_points(daily_task)
                stamina_left, backup_left = read_live_stamina(daily_task)
                return DailyGameOutcome(
                    stamina_start=stamina_start,
                    backup_stamina_start=backup_start,
                    stamina_left=stamina_left,
                    backup_stamina_left=backup_left,
                    daily_points=daily_points,
                    task_error=task_error or None,
                )
        finally:
            if ok is not None:
                close_ok_runtime(ok)
            kill_game_processes()


class SubprocessDailyGameClient:
    def __init__(self, app_config: AppConfig, *, ww_root: Path) -> None:
        self.app_config = app_config
        self.ww_root = ww_root

    def run_daily(self, sheet_config: SheetRunConfig) -> DailyGameOutcome:
        payload = run_game_attempt_subprocess(self.app_config, self.ww_root, "daily", "run", sheet_config)
        return DailyGameOutcome(**payload)


class OkStaminaGameClient:
    def __init__(self, launcher: OkLauncher) -> None:
        self.launcher = launcher
        self.ok = None
        self.stamina_task = None
        self.launch_attempted = False

    def read_stamina(self, sheet_config: SheetRunConfig) -> tuple[int | None, int | None]:
        with ww_runtime_context(self.launcher.options.ww_root):
            task = self._get_stamina_task()
            return read_live_stamina(task)

    def run_stamina(self, sheet_config: SheetRunConfig) -> StaminaGameOutcome:
        with ww_runtime_context(self.launcher.options.ww_root):
            task = self._get_stamina_run_task(sheet_config)
            task_error = run_onetime_task(self.ok.task_executor, task, timeout_seconds=600)
            stamina_left, backup_left = read_live_stamina(task)
            return StaminaGameOutcome(
                stamina_left=stamina_left,
                backup_stamina_left=backup_left,
                task_error=task_error or None,
            )

    def close(self, sheet_config: SheetRunConfig) -> None:
        if self.ok is not None:
            close_ok_runtime(self.ok)
            self.ok = None
            self.stamina_task = None
        if self.launch_attempted:
            kill_game_processes()
            self.launch_attempted = False

    def _get_stamina_task(self):
        if self.ok is None:
            self.ok = self._start_ok_and_game()
        if self.stamina_task is None:
            from src.task.DailyTask import DailyTask

            self.stamina_task = self.ok.task_executor.get_task_by_class(DailyTask)
        return self.stamina_task

    def _get_stamina_run_task(self, sheet_config: SheetRunConfig):
        if self.ok is None:
            self.ok = self._start_ok_and_game()
        farm_index = farm_type_index(sheet_config.which_to_farm)
        if farm_index == 0:
            from src.task.TacetTask import TacetTask

            task = self.ok.task_executor.get_task_by_class(TacetTask)
            task.config["Which Tacet Suppression to Farm"] = sheet_config.tacet_serial
        elif farm_index == 1:
            from src.task.ForgeryTask import ForgeryTask

            task = self.ok.task_executor.get_task_by_class(ForgeryTask)
            task.config["Which Forgery Challenge to Farm"] = sheet_config.forgery_serial
        else:
            from src.task.SimulationTask import SimulationTask

            task = self.ok.task_executor.get_task_by_class(SimulationTask)
            task.config["Material Selection"] = simulation_material_value(sheet_config.simulation_material)
        return task

    def _start_ok_and_game(self):
        self.launch_attempted = True
        return self.launcher.start_ok_and_game()


class SubprocessStaminaGameClient:
    def __init__(self, app_config: AppConfig, *, ww_root: Path) -> None:
        self.app_config = app_config
        self.ww_root = ww_root

    def read_stamina(self, sheet_config: SheetRunConfig) -> tuple[int | None, int | None]:
        payload = run_game_attempt_subprocess(self.app_config, self.ww_root, "stamina", "read", sheet_config)
        return payload["stamina"], payload["backup_stamina"]

    def run_stamina(self, sheet_config: SheetRunConfig) -> StaminaGameOutcome:
        payload = run_game_attempt_subprocess(self.app_config, self.ww_root, "stamina", "run", sheet_config)
        return StaminaGameOutcome(**payload)

    def close(self, sheet_config: SheetRunConfig) -> None:
        return None


def run_game_attempt_subprocess(
    app_config: AppConfig,
    ww_root: Path,
    mode: str,
    operation: str,
    sheet_config: SheetRunConfig,
    *,
    timeout: float | None = None,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="ok-ww-attempt-") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "input.json"
        output_path = temp_path / "output.json"
        input_path.write_text(
            json.dumps({"sheet_config": asdict(sheet_config)}, ensure_ascii=False),
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-m",
            "ok_ww_automator.game_attempt",
            "--project-root",
            str(app_config.project_root),
            "--env-file",
            str(app_config.env_path),
            "--ww-root",
            str(ww_root),
            "--mode",
            mode,
            "--operation",
            operation,
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
        env = dict(os.environ)
        env["ENV_FILE"] = str(app_config.env_path)

        if timeout is None:
            completed = subprocess.run(command, env=env, check=False)
        else:
            try:
                completed = run_with_timeout(command, env=env, timeout=timeout)
            except BaseException:
                # A game started through a platform launcher may not remain a
                # descendant of the Python process; use the existing game cleanup too.
                kill_game_processes()
                raise
        payload = read_attempt_payload(output_path)
        if completed.returncode != 0:
            if is_native_teardown_crash(completed.returncode) and is_attempt_result_payload(payload, mode, operation):
                return payload
            message = payload.get("error") if isinstance(payload, dict) else None
            raise RuntimeError(message or f"Game attempt subprocess exited {completed.returncode}")
        if not isinstance(payload, dict):
            raise RuntimeError("Game attempt subprocess did not return a JSON object")
        return payload


def read_attempt_payload(output_path: Path) -> dict:
    if not output_path.exists():
        return {}
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Game attempt subprocess wrote invalid JSON: {exc}") from exc


def is_native_teardown_crash(returncode: int) -> bool:
    return returncode in WINDOWS_NATIVE_TEARDOWN_EXIT_CODES


def is_attempt_result_payload(payload: object, mode: str, operation: str) -> bool:
    if not isinstance(payload, dict) or "error" in payload:
        return False
    if mode == "weekly" and operation == "run":
        return isinstance(payload.get("completed"), bool)
    if mode == "daily" and operation == "run":
        return any(key in payload for key in DailyGameOutcome.__dataclass_fields__)
    if mode == "stamina" and operation == "read":
        return "stamina" in payload and "backup_stamina" in payload
    if mode == "stamina" and operation == "run":
        return any(key in payload for key in StaminaGameOutcome.__dataclass_fields__)
    return False


def close_ok_runtime(ok) -> None:
    try:
        ok.device_manager.stop_hwnd()
    except Exception:
        pass
    try:
        ok.quit()
    except Exception:
        pass


def apply_daily_task_config(sheet_config: SheetRunConfig, daily_task, nightmare_task) -> None:
    nightmare_targets = selected_nightmare_targets(sheet_config)

    selected_idx = farm_type_index(sheet_config.which_to_farm)
    daily_task.config["Which to Farm"] = daily_task.support_tasks[selected_idx]
    daily_task.config["Which Tacet Suppression to Farm"] = sheet_config.tacet_serial
    daily_task.config["Which Forgery Challenge to Farm"] = sheet_config.forgery_serial
    daily_task.config["Material Selection"] = simulation_material_value(sheet_config.simulation_material)
    daily_task.config["Farm Nightmare Nest for Daily Echo"] = bool(nightmare_targets)
    daily_task.config[DAILY_ADDITIONAL_TASKS] = (
        [AUTO_FARM_NIGHTMARE_NEST] if sheet_config.should_run_nightmare else []
    )
    nightmare_task.config[NIGHTMARE_FARM_SELECTION] = nightmare_targets


def selected_nightmare_targets(sheet_config: SheetRunConfig) -> list[str]:
    targets = []
    if sheet_config.farm_nightmare_purification:
        targets.append(NIGHTMARE_PURIFICATION)
    if sheet_config.farm_tacet_discord_nest:
        targets.append(TACET_DISCORD_NEST)
    return targets


def farm_type_index(which_to_farm: str) -> int:
    return {
        "无音区": 0,
        "凝素领域": 1,
        "模拟领域": 2,
    }.get(which_to_farm.strip(), 0)


def stamina_burn_unit(sheet_config: SheetRunConfig) -> int:
    return 60 if farm_type_index(sheet_config.which_to_farm) == 0 else 40


def simulation_material_value(simulation_material: str) -> str:
    return {
        "共鸣者经验": "Resonator EXP",
        "武器经验": "Weapon EXP",
        "贝币": "Shell Credit",
    }.get(simulation_material.strip(), "Shell Credit")


def read_live_stamina(task, *, retries: int = 3, retry_sleep: float = 10.0) -> tuple[int | None, int | None]:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            task.ensure_main(esc=True, time_out=20)
            book_box = task.openF2Book("gray_book_boss")
            task.click_box(book_box, after_sleep=1)
            stamina, backup_stamina, _ = task.get_stamina()
            task.send_key("esc", after_sleep=1)
            if stamina >= 0:
                return stamina, backup_stamina
        except Exception as exc:
            last_exc = exc
        finally:
            task.ensure_main(esc=True, time_out=20)

        if attempt < retries:
            import time

            time.sleep(retry_sleep)

    if last_exc is not None:
        return None, None
    return None, None


def read_live_daily_points(task, *, retries: int = 3, retry_sleep: float = 10.0) -> int | None:
    for attempt in range(1, retries + 1):
        try:
            task.ensure_main(esc=True, time_out=20)
            task.open_daily()
            points = coerce_int(task.info_get("total daily points", 0))
            if points is not None:
                return points
        except Exception:
            pass
        finally:
            task.ensure_main(esc=True, time_out=20)

        if attempt < retries:
            import time

            time.sleep(retry_sleep)

    return None


def coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
