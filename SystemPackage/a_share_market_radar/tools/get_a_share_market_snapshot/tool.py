from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import math
import time
from typing import Any
from zoneinfo import ZoneInfo

import requests


STOCK_SOURCE_NAME = "腾讯证券公开行情"


class MarketDataUnavailable(RuntimeError):
    """Raised when a complete market dataset cannot be obtained."""


class TencentMarketDataProvider:
    _URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
    _PAGE_SIZE = 200
    _MAX_COLLECTION_PASSES = 2
    _MAX_PAGE_ATTEMPTS = 3
    _REQUEST_TIMEOUT = (5, 15)
    _TURNOVER_UNIT_CNY = 10_000
    _HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://stockapp.finance.qq.com/",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }

    def __init__(self) -> None:
        self._session = self._new_session()
        self._retry_count = 0
        self._page_count = 0

    def close(self) -> None:
        self._session.close()

    def stock_rows(self) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        expected_total = 0

        for collection_pass in range(1, self._MAX_COLLECTION_PASSES + 1):
            first_rows, current_total = self._fetch_page(offset=0)
            if current_total < 1 or not first_rows:
                raise MarketDataUnavailable("腾讯证券 A 股行情返回空数据")
            expected_total = max(expected_total, current_total)
            self._merge_rows(unique, first_rows)

            page_count = math.ceil(current_total / self._PAGE_SIZE)
            for page in range(2, page_count + 1):
                offset = (page - 1) * self._PAGE_SIZE
                page_rows, page_total = self._fetch_page(offset=offset)
                expected_total = max(expected_total, page_total)
                if not page_rows:
                    raise MarketDataUnavailable(f"腾讯证券 A 股行情 offset={offset} 返回空数据")
                self._merge_rows(unique, page_rows)

            if len(unique) == expected_total:
                return list(unique.values())
            if collection_pass < self._MAX_COLLECTION_PASSES:
                time.sleep(0.5)

        raise MarketDataUnavailable(
            f"腾讯证券行情分页不完整：接口声明 {expected_total} 条，实际获得 {len(unique)} 条"
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": "tencent_finance",
            "hosts_used": ["proxy.finance.qq.com"],
            "retry_count": self._retry_count,
            "pages_fetched": self._page_count,
        }

    def _fetch_page(self, *, offset: int) -> tuple[list[dict[str, Any]], int]:
        params = {
            "_appver": "11.17.0",
            "board_code": "aStock",
            "sort_type": "price",
            "direct": "down",
            "offset": str(offset),
            "count": str(self._PAGE_SIZE),
        }
        failures: list[str] = []
        for attempt in range(self._MAX_PAGE_ATTEMPTS):
            try:
                response = self._session.get(self._URL, params=params, timeout=self._REQUEST_TIMEOUT)
                response.raise_for_status()
                rows, total = _parse_tencent_page(response.json(), offset=offset)
                self._retry_count += attempt
                self._page_count += 1
                return rows, total
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                failures.append(type(exc).__name__)
                self._reset_session()
                if attempt + 1 < self._MAX_PAGE_ATTEMPTS:
                    time.sleep(0.25 * (2**attempt))
        raise MarketDataUnavailable(
            f"腾讯证券 A 股行情 offset={offset} 请求失败（{', '.join(failures)}）"
        )

    def _merge_rows(self, target: dict[str, dict[str, Any]], rows: Iterable[dict[str, Any]]) -> None:
        for raw in rows:
            code_with_market = _text(raw.get("code"))
            code = code_with_market[2:] if code_with_market[:2] in {"sh", "sz", "bj"} else code_with_market
            if not code:
                raise MarketDataUnavailable("腾讯证券行情数据缺少股票代码")
            turnover = _number(raw.get("turnover"))
            target[code] = {
                "code": code,
                "name": _text(raw.get("name")),
                "price": _number(raw.get("zxj")),
                "change_pct": _number(raw.get("zdf")),
                "turnover_cny": (
                    _number(turnover * self._TURNOVER_UNIT_CNY) if turnover is not None else None
                ),
            }

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(self._HEADERS)
        return session

    def _reset_session(self) -> None:
        self._session.close()
        self._session = self._new_session()


def run(arguments: dict, resources: dict) -> dict:
    del resources
    top_n = int(arguments.get("top_n", 10))
    if top_n < 1 or top_n > 20:
        raise ValueError("top_n must be between 1 and 20")
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    stock_provider = TencentMarketDataProvider()

    try:
        try:
            spot = stock_provider.stock_rows()
        except MarketDataUnavailable as exc:
            return {
                "status": "error",
                "observed_at": observed_at,
                "source": STOCK_SOURCE_NAME,
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
            "source": STOCK_SOURCE_NAME,
            "market": market,
            "top_gainers": top_gainers,
            "top_turnover": top_turnover,
            "provider_diagnostics": stock_provider.diagnostics(),
            "message": "A 股市场快照获取完成。",
        }
    finally:
        stock_provider.close()


def _parse_tencent_page(payload: Any, *, offset: int) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise ValueError(f"腾讯证券 offset={offset} 响应状态异常")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"腾讯证券 offset={offset} 缺少 data")
    rows = data.get("rank_list")
    if not isinstance(rows, list):
        raise ValueError(f"腾讯证券 offset={offset} rank_list 格式异常")
    total = int(data.get("total") or 0)
    return [row for row in rows if isinstance(row, dict)], total


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


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
