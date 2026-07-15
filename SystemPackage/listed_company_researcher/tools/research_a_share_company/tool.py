from __future__ import annotations

from datetime import datetime, timedelta
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd


CODE_RE = re.compile(r"^[0-9]{6}$")
SOURCE_NAME = "东方财富与同花顺公开数据（通过 AkShare）"
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
    try:
        result["name"] = _a_share_name(code)
    except Exception as exc:
        return {
            **result,
            "status": "error",
            "warnings": [f"A 股证券身份校验失败: {type(exc).__name__}: {exc}"],
            "message": "无法确认该代码属于当前 A 股证券列表，已停止研究以避免混入其他市场或证券类型。",
        }

    if "basic" in sections:
        try:
            frame = ak.stock_individual_info_em(symbol=code)
            _require_columns(frame, {"item", "value"}, dataset="company basic information")
            result["basic"] = [_record(row) for _, row in frame.iterrows()]
            names = frame.loc[frame["item"] == "股票简称", "value"]
            if not names.empty:
                result["name"] = str(names.iloc[0]).strip()
        except Exception as exc:
            _warn(result, "基本资料", exc)

    if "quote" in sections:
        try:
            frame = ak.stock_zh_a_spot_em()
            _require_columns(frame, {"代码", "名称", "最新价", "涨跌幅", "成交额", "换手率", "市盈率-动态", "总市值"}, dataset="A-share quote")
            matched = frame.loc[frame["代码"].map(_code_text) == code]
            if matched.empty:
                raise ValueError("quote not found")
            row = matched.iloc[0]
            result["name"] = result["name"] or str(row.get("名称") or "").strip()
            result["quote"] = {
                "price": _value(row.get("最新价")),
                "change_pct": _value(row.get("涨跌幅")),
                "turnover_cny": _value(row.get("成交额")),
                "turnover_rate_pct": _value(row.get("换手率")),
                "dynamic_pe": _value(row.get("市盈率-动态")),
                "market_cap_cny": _value(row.get("总市值")),
            }
        except Exception as exc:
            _warn(result, "实时行情", exc)

    if "history" in sections:
        try:
            end_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            start_date = end_date - timedelta(days=history_days * 2)
            frame = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq",
            )
            _require_columns(frame, {"日期", "收盘"}, dataset="A-share history")
            frame = frame.tail(history_days).copy()
            close = pd.to_numeric(frame["收盘"], errors="coerce").dropna()
            if close.empty:
                raise ValueError("history contains no valid close prices")
            returns = close.pct_change().dropna()
            running_peak = close.cummax()
            drawdown = close / running_peak - 1
            result["history_summary"] = {
                "start_date": _date_text(frame.iloc[0]["日期"]),
                "end_date": _date_text(frame.iloc[-1]["日期"]),
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


def _a_share_name(code: str) -> str:
    frame = ak.stock_info_a_code_name()
    _require_columns(frame, {"code", "name"}, dataset="A-share security list")
    matched = frame.loc[frame["code"].map(_code_text) == code]
    if matched.empty:
        raise ValueError(f"code is not present in the current A-share security list: {code}")
    return str(matched.iloc[0]["name"]).strip() or code


def _require_columns(frame: pd.DataFrame, required: set[str], *, dataset: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{dataset} missing columns: {', '.join(missing)}")


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


def _date_text(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _code_text(value: Any) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.zfill(6)
