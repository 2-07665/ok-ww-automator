"""Pure time and stamina calculations for automation decisions."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

UTC = dt.timezone.utc
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo
BEIJING_TZ = dt.timezone(dt.timedelta(hours=8), name="UTC+08")

DEFAULT_DAILY_RUN_HOUR = 5
DEFAULT_DAILY_RUN_MINUTE = 0

STAMINA_CAP = 240
BACKUP_STAMINA_CAP = 480
STAMINA_REGEN_MINUTES = 6
BACKUP_STAMINA_REGEN_MINUTES = 12

DAILY_TASK_STAMINA = 180
TACET_FARM_STAMINA_UNIT = 60


@dataclass(frozen=True)
class BurnDecision:
    should_run: bool
    burn_amount: int
    is_expected: bool
    reason: str


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def format_timestamp(value: dt.datetime) -> str:
    """Return a Google Sheets friendly timestamp."""

    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_date(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%d")


def format_duration(total_seconds: float | int) -> str:
    """Convert durations in seconds to the form ``4d 3h 2m 30s``."""

    seconds = max(0, int(total_seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def predict_future_stamina(stamina: int, backup_stamina: int, minutes: int) -> tuple[int, int]:
    """Predict current and backup stamina after ``minutes`` of regeneration."""

    stamina = _clamp(stamina, 0, STAMINA_CAP)
    backup_stamina = _clamp(backup_stamina, 0, BACKUP_STAMINA_CAP)
    minutes = max(0, minutes)

    stamina_regen = min(STAMINA_CAP - stamina, minutes // STAMINA_REGEN_MINUTES)
    stamina_after = stamina + stamina_regen
    remaining_minutes = minutes - stamina_regen * STAMINA_REGEN_MINUTES
    backup_regen = min(BACKUP_STAMINA_CAP - backup_stamina, remaining_minutes // BACKUP_STAMINA_REGEN_MINUTES)
    backup_after = backup_stamina + backup_regen
    return stamina_after, backup_after


def minutes_until_stamina_full(stamina: int) -> int:
    stamina = _clamp(stamina, 0, STAMINA_CAP)
    return (STAMINA_CAP - stamina) * STAMINA_REGEN_MINUTES


def minutes_until_target_time(
    target_hour: int,
    target_minute: int,
    start_time: dt.datetime | None = None,
) -> int:
    """Compute minutes until the next target time in the Beijing timezone."""

    validate_time_of_day(target_hour, target_minute)
    start_time = _ensure_aware(start_time or now())
    start_time_bj = start_time.astimezone(BEIJING_TZ)
    target = start_time_bj.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if target <= start_time_bj:
        target += dt.timedelta(days=1)
    return int((target - start_time).total_seconds() // 60)


def stamina_after_consume(stamina: int, backup_stamina: int, consume: int) -> tuple[int, int]:
    """Calculate stamina and backup stamina left after consuming an amount."""

    consume = max(0, consume)
    spent = min(stamina, consume)
    stamina -= spent
    consume -= spent

    spent = min(backup_stamina, consume)
    backup_stamina -= spent
    return stamina, backup_stamina if backup_stamina >= 0 else -1


def calculate_burn(
    stamina: int | None,
    backup_stamina: int | None,
    stamina_consume_unit: int = TACET_FARM_STAMINA_UNIT,
    daily_hour: int = DEFAULT_DAILY_RUN_HOUR,
    daily_minute: int = DEFAULT_DAILY_RUN_MINUTE,
    *,
    start_time: dt.datetime | None = None,
) -> BurnDecision:
    """Return whether to burn stamina before the next assumed daily run."""

    if stamina_consume_unit <= 0:
        raise ValueError("stamina_consume_unit must be positive")
    validate_time_of_day(daily_hour, daily_minute)

    if stamina is None:
        return BurnDecision(False, 0, False, "无法读取体力，不执行任务")

    stamina = _clamp(stamina, 0, STAMINA_CAP)
    backup_stamina = _clamp(backup_stamina if backup_stamina is not None else 0, 0, BACKUP_STAMINA_CAP)

    minutes_until_daily = minutes_until_target_time(daily_hour, daily_minute, start_time=start_time)
    stamina_future, backup_future = predict_future_stamina(stamina, backup_stamina, minutes_until_daily)
    stamina_overflow = _overflow_before_target(stamina, backup_stamina, minutes_until_daily)
    stamina_future_raw = stamina_future + stamina_overflow
    if stamina_future_raw <= STAMINA_CAP:
        return BurnDecision(False, 0, True, f"下次日常时有 {stamina_future}+{backup_future} 体力，不会溢出")

    burn_needed = stamina_future_raw - STAMINA_CAP
    burn_needed = round_up_to_unit(burn_needed, stamina_consume_unit)
    available_stamina = stamina // stamina_consume_unit * stamina_consume_unit

    if available_stamina >= burn_needed + stamina_consume_unit:
        return BurnDecision(True, available_stamina, False, f"下次日常时会溢出 {stamina_overflow} 体力，过量消耗 {available_stamina}")

    if available_stamina >= burn_needed:
        return BurnDecision(True, burn_needed, True, f"下次日常时会溢出 {stamina_overflow} 体力，消耗 {burn_needed}")

    if available_stamina == 0:
        return BurnDecision(False, 0, False, f"下次日常时会溢出 {stamina_overflow} 体力，但当前可消耗不足一次任务")
    return BurnDecision(True, available_stamina, False, f"下次日常时会溢出 {stamina_overflow} 体力，但当前仅可消耗 {available_stamina}")


def round_up_to_unit(value: int, unit: int) -> int:
    if unit <= 0:
        raise ValueError("unit must be positive")
    return (value + unit - 1) // unit * unit


def _overflow_before_target(stamina: int, backup_stamina: int, minutes: int) -> int:
    minutes = max(0, minutes)
    minutes_after_current_full = max(0, minutes - minutes_until_stamina_full(stamina))

    backup_room = BACKUP_STAMINA_CAP - _clamp(backup_stamina, 0, BACKUP_STAMINA_CAP)
    backup_gain = min(backup_room, minutes_after_current_full // BACKUP_STAMINA_REGEN_MINUTES)
    minutes_spent_filling_backup = backup_gain * BACKUP_STAMINA_REGEN_MINUTES
    minutes_after_backup_full = max(0, minutes_after_current_full - minutes_spent_filling_backup)

    return backup_gain * 2 + minutes_after_backup_full // STAMINA_REGEN_MINUTES


def validate_time_of_day(hour: int, minute: int) -> None:
    if hour < 0 or hour > 23:
        raise ValueError("hour must be between 0 and 23")
    if minute < 0 or minute > 59:
        raise ValueError("minute must be between 0 and 59")


def _ensure_aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=LOCAL_TZ)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))
