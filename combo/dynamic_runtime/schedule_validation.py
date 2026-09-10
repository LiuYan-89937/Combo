from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger


ScheduleType = Literal["cron", "interval", "date"]


@dataclass(frozen=True, slots=True)
class ValidatedSchedule:
    schedule_type: ScheduleType
    expression: str
    timezone: str
    interval_seconds: float | None = None
    date: datetime | None = None


def validate_schedule(
    schedule_type: Any,
    schedule_expr: Any,
    timezone: Any,
) -> ValidatedSchedule:
    kind = _text(schedule_type, "schedule_type")
    expression = _text(schedule_expr, "schedule_expr")
    timezone_name = _text(timezone, "timezone")
    zone = _timezone(timezone_name)

    if kind == "cron":
        fields = expression.split()
        if len(fields) != 5:
            raise ValueError("cron expression must contain exactly five fields")
        try:
            CronTrigger.from_crontab(expression, timezone=zone)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid cron expression: {exc}") from exc
        return ValidatedSchedule(kind, expression, timezone_name)

    if kind == "interval":
        try:
            seconds = Decimal(expression)
        except InvalidOperation as exc:
            raise ValueError("interval expression must be a positive number of seconds") from exc
        if not seconds.is_finite() or seconds <= 0:
            raise ValueError("interval expression must be a positive finite number of seconds")
        value = float(seconds)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("interval expression is outside the supported numeric range")
        return ValidatedSchedule(kind, expression, timezone_name, interval_seconds=value)

    if kind == "date":
        try:
            run_date = datetime.fromisoformat(expression)
        except ValueError as exc:
            raise ValueError("date expression must be a valid ISO-8601 datetime") from exc
        if run_date.tzinfo is None or run_date.utcoffset() is None:
            raise ValueError("date expression must include a timezone offset")
        return ValidatedSchedule(kind, expression, timezone_name, date=run_date)

    raise ValueError("schedule_type must be one of: cron, interval, date")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value.strip()


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"timezone must be a valid IANA timezone: {value}") from exc
