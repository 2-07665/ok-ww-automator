"""Game clients for executing ok-script tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import SheetRunConfig
from .ok_launcher import OkLauncher, run_onetime_task, ww_runtime_context


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

                daily_task = ok.task_executor.get_task_by_class(DailyTask)
                apply_daily_task_config(sheet_config, daily_task)
                stamina_start, backup_start = read_live_stamina(daily_task)
                task_error = run_onetime_task(ok.task_executor, daily_task, timeout_seconds=1800)
                daily_points = daily_task.info_get("total daily points", 0)
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
                ok.device_manager.stop_hwnd()
                ok.quit()


class OkStaminaGameClient:
    def __init__(self, launcher: OkLauncher) -> None:
        self.launcher = launcher
        self.ok = None
        self.stamina_task = None

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
        if self.ok is None:
            return
        self.ok.device_manager.stop_hwnd()
        self.ok.quit()
        self.ok = None
        self.stamina_task = None

    def _get_stamina_task(self):
        if self.ok is None:
            self.ok = self.launcher.start_ok_and_game()
        if self.stamina_task is None:
            from src.task.DailyTask import DailyTask

            self.stamina_task = self.ok.task_executor.get_task_by_class(DailyTask)
        return self.stamina_task

    def _get_stamina_run_task(self, sheet_config: SheetRunConfig):
        if self.ok is None:
            self.ok = self.launcher.start_ok_and_game()
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


def apply_daily_task_config(sheet_config: SheetRunConfig, daily_task) -> None:
    selected_idx = farm_type_index(sheet_config.which_to_farm)
    daily_task.config["Which to Farm"] = daily_task.support_tasks[selected_idx]
    daily_task.config["Which Tacet Suppression to Farm"] = sheet_config.tacet_serial
    daily_task.config["Which Forgery Challenge to Farm"] = sheet_config.forgery_serial
    daily_task.config["Material Selection"] = simulation_material_value(sheet_config.simulation_material)
    daily_task.config["Auto Farm all Nightmare Nest"] = sheet_config.run_nightmare
    daily_task.config["Farm Nightmare Nest for Daily Echo"] = True


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
