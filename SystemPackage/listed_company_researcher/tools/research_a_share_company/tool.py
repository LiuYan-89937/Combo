from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

from agent_factory.market_data.tencent import TencentMarketDataClient


CODE_RE = re.compile(r"^[0-9]{6}$")
SOURCE_NAME = "腾讯证券公开行情；同花顺财务摘要（通过 AkShare）"
ALLOWED_SECTIONS = {"basic", "quote", "history", "financial"}


def run(arguments: dict, resources: dict) -> dict:
    del resources
    code = str(arguments.get("code") or "").strip()
    if not CODE_RE.fullmatch(code):
        raise ValueError("code must be a six-digit A-share code")
    history_days = int(arguments.get("history_days", 250))
    if history_days < 30 or history_days > 1000:
        raise ValueError("history_days must be between 30 and 1000")
    raw_sections = arguments.get("sections", ["basic", "quote", "history", "financial"])
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("sections must be a non-empty array")
    sections = {str(item) for item in raw_sections}
    unknown = sorted(sections - ALLOWED_SECTIONS)
    if unknown:
        raise ValueError(f"unsupported sections: {', '.join(unknown)}")

    result: dict[str, Any] = {
        "status": "success",
        "code": code,
        "name": "",
        "observed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "source": SOURCE_NAME,
        "adjustment": "history uses qfq (前复权)",
        "basic": [],
        "quote": {},
        "history_summary": {},
        "financial": [],
        "warnings": [],
        "message": "A 股公司数据获取完成。",
    }
    with TencentMarketDataClient() as market_data:
        try:
            quote = market_data.quote(code)
            result["name"] = str(quote["name"])
        except Exception as exc:
            return {
                **result,
                "status": "error",
                "warnings": [f"A 股证券身份校验失败: {type(exc).__name__}: {exc}"],
                "message": "腾讯证券未能确认该六位代码对应 A 股证券，已停止研究。",
            }

        if "basic" in sections:
            result["basic"] = [
                {"item": "股票代码", "value": quote["code"]},
                {"item": "股票简称", "value": quote["name"]},
                {"item": "交易所", "value": quote["exchange"]},
                {"item": "腾讯行情标识", "value": quote["symbol"]},
                {"item": "行情时间", "value": quote["quote_time"]},
            ]

        if "quote" in sections:
            result["quote"] = {
                key: quote.get(key)
                for key in (
                    "price",
                    "previous_close",
                    "open",
                    "high",
                    "low",
                    "change",
                    "change_pct",
                    "volume_lots",
                    "turnover_cny",
                    "turnover_rate_pct",
                    "dynamic_pe",
                    "amplitude_pct",
                    "circulating_market_cap_cny",
                    "market_cap_cny",
                    "quote_time",
                )
            }

        if "history" in sections:
            try:
                history = market_data.history(code, count=history_days, adjustment="qfq")
                frame = pd.DataFrame(history)
                close = pd.to_numeric(frame["close"], errors="coerce").dropna()
                if close.empty:
                    raise ValueError("history contains no valid close prices")
                returns = close.pct_change().dropna()
                running_peak = close.cummax()
                drawdown = close / running_peak - 1
                result["history_summary"] = {
                    "start_date": str(frame.iloc[0]["date"]),
                    "end_date": str(frame.iloc[-1]["date"]),
                    "observations": int(len(close)),
                    "first_close": _value(close.iloc[0]),
                    "last_close": _value(close.iloc[-1]),
                    "period_return_pct": _percent(close.iloc[-1] / close.iloc[0] - 1) if len(close) > 1 else None,
                    "annualized_volatility_pct": _percent(returns.std() * math.sqrt(252)) if len(returns) > 1 else None,
                    "max_drawdown_pct": _percent(drawdown.min()),
                    "sma20": _value(close.tail(20).mean()) if len(close) >= 20 else None,
                    "sma60": _value(close.tail(60).mean()) if len(close) >= 60 else None,
                }
            except Exception as exc:
                _warn(result, "历史行情", exc)

    if "financial" in sections:
        try:
            frame = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
            if frame.empty:
                raise ValueError("financial abstract is empty")
            result["financial"] = [_record(row) for _, row in frame.head(8).iterrows()]
        except Exception as exc:
            _warn(result, "财务摘要", exc)

    if not result["name"]:
        result["name"] = code
    if result["warnings"]:
        result["status"] = "partial" if any((result["basic"], result["quote"], result["history_summary"], result["financial"])) else "error"
        result["message"] = "部分 A 股公司数据不可用，请依据 warnings 限定结论。"
    return result


def _warn(result: dict[str, Any], section: str, exc: Exception) -> None:
    result["warnings"].append(f"{section}获取失败: {type(exc).__name__}: {exc}")


def _record(row: pd.Series) -> dict[str, Any]:
    return {str(key): _value(value) for key, value in row.items()}


def _value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float):
        return round(value, 4) if math.isfinite(value) else None
    if isinstance(value, (int, str, bool)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _percent(value: Any) -> float | None:
    parsed = _value(float(value) * 100)
    return parsed if isinstance(parsed, float | int) else None
