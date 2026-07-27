from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import math
from typing import Any
from zoneinfo import ZoneInfo

from agent_factory.market_data.tencent import (
    TENCENT_SOURCE_NAME,
    TencentMarketDataClient,
    TencentMarketDataError,
)


def run(arguments: dict, resources: dict) -> dict:
    del resources
    top_n = int(arguments.get("top_n", 10))
    if top_n < 1 or top_n > 20:
        raise ValueError("top_n must be between 1 and 20")
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    stock_provider = TencentMarketDataClient()

    try:
        try:
            spot = stock_provider.stock_rows()
        except TencentMarketDataError as exc:
            return {
                "status": "error",
                "observed_at": observed_at,
                "source": TENCENT_SOURCE_NAME,
                "market": {},
                "top_gainers": [],
                "top_turnover": [],
                "provider_diagnostics": stock_provider.diagnostics(),
                "message": f"A 股行情获取失败: {exc}",
            }

        valid_changes = [
            value for row in spot if (value := _number(row.get("change_pct"))) is not None
        ]
        turnover_values = [_number(row.get("turnover_cny")) for row in spot]
        market = {
            "listed_count": len(spot),
            "priced_count": len(valid_changes),
            "advancers": sum(value > 0 for value in valid_changes),
            "decliners": sum(value < 0 for value in valid_changes),
            "unchanged": sum(value == 0 for value in valid_changes),
            "turnover_cny": _sum_numbers(turnover_values),
        }
        top_gainers = _top_rows(spot, field="change_pct", limit=top_n)
        top_turnover = _top_rows(spot, field="turnover_cny", limit=top_n)

        return {
            "status": "success",
            "observed_at": observed_at,
            "source": TENCENT_SOURCE_NAME,
            "market": market,
            "top_gainers": top_gainers,
            "top_turnover": top_turnover,
            "provider_diagnostics": stock_provider.diagnostics(),
            "message": "A 股市场快照获取完成。",
        }
    finally:
        stock_provider.close()


def _top_rows(rows: Iterable[dict[str, Any]], *, field: str, limit: int) -> list[dict[str, Any]]:
    valued_rows = [(value, row) for row in rows if (value := _number(row.get(field))) is not None]
    valued_rows.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in valued_rows[:limit]]


def _sum_numbers(values: Iterable[float | int | None]) -> float | int | None:
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return _number(sum(numbers))


def _number(value: Any) -> float | int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 4)
