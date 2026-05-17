"""Pure data models shared by runners, Sheets, and notices."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable

from .time_utils import (
    DEFAULT_DAILY_RUN_HOUR,
    DEFAULT_DAILY_RUN_MINUTE,
    format_duration,
    format_timestamp,
    minutes_until_target_time,
    now,
    predict_future_stamina,
)

STAMINA_CONSUME_UNIT = 20


@dataclass
class SheetRunConfig:
    run_daily: bool = True
    skip_daily_once: bool = False
    shutdown_after_daily: bool = False
    run_nightmare: bool = False

    run_stamina: bool = True
    skip_stamina_once: bool = False
    shutdown_after_stamina: bool = False

    which_to_farm: str = "无音区"

    tacet_serial: int = 1
    tacet_name: str = ""
    tacet_set1: str = ""
    tacet_set2: str = ""

    forgery_serial: int = 1
    forgery_name: str = ""
    forgery_weapon_type: str = ""
    forgery_version: str = ""

    simulation_material: str = "贝币"


@dataclass(frozen=True)
class DerivedRunFields:
    end_time: dt.datetime
    started_at_text: str
    ended_at_text: str
    duration_seconds: int
    duration_text: str
    next_daily_stamina: str
    next_daily_backup_stamina: str
    decision: str
    error: str

    @property
    def notes_visible(self) -> bool:
        return bool(self.decision or self.error)


@dataclass
class RunResult:
    task_type: str
    started_at: dt.datetime
    ended_at: dt.datetime | None
    status: str

    stamina_start: int | None = None
    backup_stamina_start: int | None = None
    stamina_used: int | None = None
    stamina_left: int | None = None
    backup_stamina_left: int | None = None

    run_nightmare: bool = False

    daily_points: int | None = None
    sign_in_success: bool | None = None

    decision: str | None = None
    error: str | None = None

    def ensure_ended_at(self) -> dt.datetime:
        if self.ended_at is None:
            self.ended_at = now()
        return self.ended_at

    def derive(
        self,
        *,
        end_time: dt.datetime | None = None,
        daily_hour: int = DEFAULT_DAILY_RUN_HOUR,
        daily_minute: int = DEFAULT_DAILY_RUN_MINUTE,
    ) -> DerivedRunFields:
        resolved_end = end_time if end_time is not None else (self.ended_at or now())
        duration_seconds = max(0, int(round((resolved_end - self.started_at).total_seconds())))

        if self.stamina_left is not None and self.backup_stamina_left is not None:
            next_daily_stamina, next_daily_backup = predict_future_stamina(
                self.stamina_left,
                self.backup_stamina_left,
                minutes_until_target_time(daily_hour, daily_minute, resolved_end),
            )
        else:
            next_daily_stamina, next_daily_backup = "", ""

        return DerivedRunFields(
            end_time=resolved_end,
            started_at_text=format_timestamp(self.started_at),
            ended_at_text=format_timestamp(resolved_end),
            duration_seconds=duration_seconds,
            duration_text=format_duration(duration_seconds),
            next_daily_stamina=safe_str(next_daily_stamina),
            next_daily_backup_stamina=safe_str(next_daily_backup),
            decision=safe_str(self.decision),
            error=safe_str(self.error),
        )

    def as_daily_row(self, *, derived: DerivedRunFields | None = None) -> list[str]:
        resolved = derived or self.derive()
        return (
            self._basic_row(resolved)
            + self._stamina_row()
            + [safe_str(self.daily_points), resolved.next_daily_stamina, resolved.next_daily_backup_stamina]
            + [success_label(self.sign_in_success), bool_label(self.run_nightmare)]
            + self._info_row(resolved)
        )

    def as_stamina_row(self, *, derived: DerivedRunFields | None = None) -> list[str]:
        resolved = derived or self.derive()
        return (
            self._basic_row(resolved)
            + self._stamina_row()
            + [resolved.next_daily_stamina, resolved.next_daily_backup_stamina]
            + self._info_row(resolved)
        )

    def fill_stamina_start(self, stamina: int | None, backup_stamina: int | None) -> None:
        self.stamina_start = stamina
        self.backup_stamina_start = backup_stamina

    def fill_stamina_left(self, stamina: int | None, backup_stamina: int | None) -> None:
        self.stamina_left = stamina
        self.backup_stamina_left = backup_stamina

    def fill_stamina_left_from_start(self) -> None:
        self.stamina_left = self.stamina_start
        self.backup_stamina_left = self.backup_stamina_start

    def fill_stamina_used(self) -> None:
        if None in (self.stamina_start, self.backup_stamina_start, self.stamina_left, self.backup_stamina_left):
            return
        start_total = (self.stamina_start or 0) + (self.backup_stamina_start or 0)
        end_total = (self.stamina_left or 0) + (self.backup_stamina_left or 0)
        consumed = max(0, start_total - end_total)
        self.stamina_used = int(round(consumed / STAMINA_CONSUME_UNIT)) * STAMINA_CONSUME_UNIT

    def _basic_row(self, derived: DerivedRunFields) -> list[str]:
        return [derived.started_at_text, derived.ended_at_text, derived.duration_text, self.status]

    def _stamina_row(self) -> list[str]:
        return safe_str_list(
            [
                self.stamina_start,
                self.backup_stamina_start,
                self.stamina_used,
                self.stamina_left,
                self.backup_stamina_left,
            ]
        )

    def _info_row(self, derived: DerivedRunFields) -> list[str]:
        return [derived.decision, derived.error]


@dataclass
class FastFarmResult:
    started_at: dt.datetime
    ended_at: dt.datetime | None
    status: str

    fight_count: int | None = None
    fight_speed: int | None = None

    echo_number_start: int | None = None
    echo_number_end: int | None = None
    echo_number_gained: int | None = None
    merge_count: int | None = None

    info: str | None = ""

    def as_row(self, *, end_time: dt.datetime | None = None) -> list[str]:
        end = end_time if end_time is not None else (self.ended_at or now())
        total_seconds = max(0, int(round((end - self.started_at).total_seconds())))

        if self.fight_count is not None and total_seconds != 0:
            self.fight_speed = max(0, round(self.fight_count * 3600 / total_seconds))
        self.fill_echo_number_gained()

        basic_entry = [format_timestamp(self.started_at), format_timestamp(end), format_duration(total_seconds), self.status]
        fight_entry = safe_str_list([self.fight_count, self.fight_speed])
        echo_entry = safe_str_list([self.echo_number_start, self.echo_number_end, self.echo_number_gained, self.merge_count])
        return basic_entry + fight_entry + echo_entry + [safe_str(self.info)]

    def fill_echo_number_gained(self) -> None:
        if self.echo_number_start is None or self.echo_number_end is None:
            return
        self.echo_number_gained = max(0, self.echo_number_end - self.echo_number_start)


def safe_str(value: Any) -> str:
    return "" if value is None else str(value)


def safe_str_list(values: Iterable[Any]) -> list[str]:
    return [safe_str(value) for value in values]


def bool_label(value: bool) -> str:
    return "是" if value else "否"


def success_label(value: bool | None) -> str:
    if value is None:
        return ""
    return "成功" if value else "失败"
