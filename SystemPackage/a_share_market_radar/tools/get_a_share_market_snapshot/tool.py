from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import math
import time
from typing import Any
from zoneinfo import ZoneInfo

import requests


SOURCE_NAME = "东方财富公开行情（多节点直连）"


class MarketDataUnavailable(RuntimeError):
    """Raised when a complete market dataset cannot be obtained."""


class EastMoneyMarketDataProvider:
    _API_PATH = "/api/qt/clist/get"
    _HOSTS = (
        "https://push2.eastmoney.com",
        "https://82.push2.eastmoney.com",
        "https://7.push2.eastmoney.com",
        "https://88.push2.eastmoney.com",
    )
    _PAGE_SIZE = 100
    _REQUEST_TIMEOUT = (5, 15)
    _BASE_PARAMS = {
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
    }
    _HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://quote.eastmoney.com/",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }

    def __init__(self) -> None:
        self._sessions: dict[str, requests.Session] = {}
        self._hosts_used: list[str] = []
        self._fallback_count = 0
        self._page_count = 0

    def close(self) -> None:
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()

    def stock_rows(self) -> list[dict[str, Any]]:
        return self._fetch_collection(
            {
                "fid": "f12",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f2,f3,f6,f12,f14",
            },
            dataset="A 股全市场行情",
            identity_field="f12",
        )

    def industry_rows(self) -> list[dict[str, Any]]:
        return self._fetch_collection(
            {
                "fid": "f3",
                "fs": "m:90 t:2 f:!50",
                "fields": "f3,f8,f14,f20",
            },
            dataset="A 股行业板块",
            identity_field="f14",
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": "eastmoney",
            "hosts_used": list(self._hosts_used),
            "fallback_count": self._fallback_count,
            "pages_fetched": self._page_count,
        }

    def _fetch_collection(
        self,
        query: dict[str, str],
        *,
        dataset: str,
        identity_field: str,
    ) -> list[dict[str, Any]]:
        params = {
            **self._BASE_PARAMS,
            **query,
            "pn": "1",
            "pz": str(self._PAGE_SIZE),
        }
        first_rows, total = self._fetch_page(params, page=1, dataset=dataset)
        if total < 1 or not first_rows:
            raise MarketDataUnavailable(f"{dataset}返回空数据")

        rows = list(first_rows)
        page_count = math.ceil(total / self._PAGE_SIZE)
        for page in range(2, page_count + 1):
            page_rows, _ = self._fetch_page(params, page=page, dataset=dataset)
            if not page_rows:
                raise MarketDataUnavailable(f"{dataset}第 {page} 页返回空数据")
            rows.extend(page_rows)

        unique_rows = _unique_by_field(rows, identity_field)
        if len(unique_rows) != total:
            raise MarketDataUnavailable(
                f"{dataset}分页不完整：接口声明 {total} 条，实际获得 {len(unique_rows)} 条"
            )
        return unique_rows

    def _fetch_page(
        self,
        base_params: dict[str, str],
        *,
        page: int,
        dataset: str,
    ) -> tuple[list[dict[str, Any]], int]:
        params = {**base_params, "pn": str(page)}
        start_index = (page - 1) % len(self._HOSTS)
        failures: list[str] = []

        for attempt in range(len(self._HOSTS)):
            host = self._HOSTS[(start_index + attempt) % len(self._HOSTS)]
            try:
                response = self._session(host).get(
                    f"{host}{self._API_PATH}",
                    params=params,
                    timeout=self._REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
                rows, total = _parse_page_payload(payload, dataset=dataset, page=page)
                if host not in self._hosts_used:
                    self._hosts_used.append(host)
                self._fallback_count += attempt
                self._page_count += 1
                return rows, total
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                failures.append(f"{host}: {type(exc).__name__}")
                self._reset_session(host)
                if attempt + 1 < len(self._HOSTS):
                    time.sleep(0.25 * (2**attempt))

        evidence = "; ".join(failures)
        raise MarketDataUnavailable(f"{dataset}第 {page} 页全部节点失败（{evidence}）")

    def _session(self, host: str) -> requests.Session:
        session = self._sessions.get(host)
        if session is None:
            session = requests.Session()
            session.headers.update(self._HEADERS)
            self._sessions[host] = session
        return session

    def _reset_session(self, host: str) -> None:
        session = self._sessions.pop(host, None)
        if session is not None:
            session.close()


def run(arguments: dict, resources: dict) -> dict:
    del resources
    top_n = int(arguments.get("top_n", 10))
    if top_n < 1 or top_n > 20:
        raise ValueError("top_n must be between 1 and 20")
    include_industries = bool(arguments.get("include_industries", True))
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    provider = EastMoneyMarketDataProvider()
    warnings: list[str] = []

    try:
        try:
            spot = provider.stock_rows()
            change_values = [_number(row.get("f3")) for row in spot]
            turnover_values = [_number(row.get("f6")) for row in spot]
            valid_changes = [value for value in change_values if value is not None]
            market = {
                "listed_count": len(spot),
                "priced_count": len(valid_changes),
                "advancers": sum(value > 0 for value in valid_changes),
                "decliners": sum(value < 0 for value in valid_changes),
                "unchanged": sum(value == 0 for value in valid_changes),
                "turnover_cny": _sum_numbers(turnover_values),
            }
            top_gainers = _stock_rows(_top_rows(spot, field="f3", limit=top_n))
            top_turnover = _stock_rows(_top_rows(spot, field="f6", limit=top_n))
        except MarketDataUnavailable as exc:
            return {
                "status": "error",
                "observed_at": observed_at,
                "source": SOURCE_NAME,
                "market": {},
                "top_gainers": [],
                "top_turnover": [],
                "industries": [],
                "warnings": [],
                "provider_diagnostics": provider.diagnostics(),
                "message": f"A 股行情获取失败: {exc}",
            }

        industries: list[dict[str, Any]] = []
        if include_industries:
            try:
                industries = [
                    {
                        "name": _text(row.get("f14")),
                        "change_pct": _number(row.get("f3")),
                        "market_cap_cny": _number(row.get("f20")),
                        "turnover_rate_pct": _number(row.get("f8")),
                    }
                    for row in _top_rows(provider.industry_rows(), field="f3", limit=top_n)
                ]
            except MarketDataUnavailable as exc:
                warnings.append(f"行业数据获取失败: {exc}")

        return {
            "status": "partial" if warnings else "success",
            "observed_at": observed_at,
            "source": SOURCE_NAME,
            "market": market,
            "top_gainers": top_gainers,
            "top_turnover": top_turnover,
            "industries": industries,
            "warnings": warnings,
            "provider_diagnostics": provider.diagnostics(),
            "message": "A 股市场快照获取完成。",
        }
    finally:
        provider.close()


def _parse_page_payload(payload: Any, *, dataset: str, page: int) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or payload.get("rc") != 0:
        raise ValueError(f"{dataset}第 {page} 页响应状态异常")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{dataset}第 {page} 页缺少 data")
    total = int(data.get("total") or 0)
    diff = data.get("diff")
    if isinstance(diff, dict):
        values: Iterable[Any] = diff.values()
    elif isinstance(diff, list):
        values = diff
    else:
        raise ValueError(f"{dataset}第 {page} 页 diff 格式异常")
    rows = [item for item in values if isinstance(item, dict)]
    return rows, total


def _unique_by_field(rows: Iterable[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _text(row.get(field))
        if not key:
            raise MarketDataUnavailable(f"行情数据缺少唯一字段 {field}")
        unique[key] = row
    return list(unique.values())


def _top_rows(rows: Iterable[dict[str, Any]], *, field: str, limit: int) -> list[dict[str, Any]]:
    valued_rows = [(value, row) for row in rows if (value := _number(row.get(field))) is not None]
    valued_rows.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in valued_rows[:limit]]


def _stock_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "code": _text(row.get("f12")),
            "name": _text(row.get("f14")),
            "price": _number(row.get("f2")),
            "change_pct": _number(row.get("f3")),
            "turnover_cny": _number(row.get("f6")),
        }
        for row in rows
    ]


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
