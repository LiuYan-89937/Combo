from __future__ import annotations

from datetime import datetime, timedelta
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import numpy as np
import pandas as pd


CODE_RE = re.compile(r"^[0-9]{6}$")
SOURCE_NAME = "东方财富 A 股历史行情（通过 AkShare）"


def run(arguments: dict, resources: dict) -> dict:
    del resources
    holdings = _holdings(arguments.get("holdings"))
    history_days = int(arguments.get("history_days", 250))
    if history_days < 60 or history_days > 500:
        raise ValueError("history_days must be between 60 and 500")
    stress_scenarios = _stress_scenarios(arguments.get("stress_scenarios", []))
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    end_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start_date = end_date - timedelta(days=history_days * 2)
    warnings: list[str] = []
    close_by_code: dict[str, pd.Series] = {}
    weight_basis = "provided_weights" if "weight" in holdings[0] else "latest_market_value"
    try:
        names = _a_share_names([holding["code"] for holding in holdings])
    except Exception as exc:
        return {
            "status": "error",
            "observed_at": observed_at,
            "source": SOURCE_NAME,
            "adjustment": "qfq (前复权)",
            "weight_basis": weight_basis,
            "portfolio": {},
            "holdings": [],
            "highest_correlation": None,
            "stress_results": [],
            "warnings": [f"A 股证券身份校验失败: {type(exc).__name__}: {exc}"],
            "message": "无法确认全部代码属于当前 A 股证券列表，已停止分析以避免混入其他市场或证券类型。",
        }

    for holding in holdings:
        code = holding["code"]
        try:
            frame = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq",
            )
            required = {"日期", "收盘"}
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ValueError(f"history missing columns: {', '.join(missing)}")
            dates = pd.to_datetime(frame["日期"], errors="coerce")
            close = pd.to_numeric(frame["收盘"], errors="coerce")
            series = pd.Series(close.to_numpy(), index=dates, name=code).dropna().tail(history_days)
            series = series.loc[~series.index.isna()]
            if len(series) < 2:
                raise ValueError("not enough valid history")
            close_by_code[code] = series
        except Exception as exc:
            warnings.append(f"{code} 历史行情获取失败: {type(exc).__name__}: {exc}")

    if len(close_by_code) != len(holdings):
        return {
            "status": "error",
            "observed_at": observed_at,
            "source": SOURCE_NAME,
            "adjustment": "qfq (前复权)",
            "weight_basis": weight_basis,
            "portfolio": {},
            "holdings": [],
            "highest_correlation": None,
            "stress_results": [],
            "warnings": warnings,
            "message": "部分持仓缺少有效历史数据，未计算可能误导的残缺组合。",
        }

    prices = pd.concat(close_by_code.values(), axis=1, join="inner").dropna()
    if len(prices) < 2:
        raise ValueError("holdings have fewer than two overlapping trading days")
    weights, weight_basis = _weights(holdings, close_by_code)
    returns = prices.pct_change().dropna()
    portfolio_returns = returns.mul(weights, axis="columns").sum(axis=1)
    equity = (1 + portfolio_returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    portfolio = {
        "start_date": prices.index[0].date().isoformat(),
        "end_date": prices.index[-1].date().isoformat(),
        "observations": int(len(prices)),
        "period_return_pct": _percent(equity.iloc[-1] - 1),
        "annualized_volatility_pct": _percent(portfolio_returns.std() * math.sqrt(252)),
        "max_drawdown_pct": _percent(drawdown.min()),
        "concentration_hhi": _number(float(np.square(weights.to_numpy()).sum())),
        "largest_weight_pct": _percent(weights.max()),
    }

    holding_results: list[dict[str, Any]] = []
    for holding in holdings:
        code = holding["code"]
        close = close_by_code[code]
        item_returns = close.pct_change().dropna()
        item_drawdown = close / close.cummax() - 1
        latest_close = float(close.iloc[-1])
        item = {
            "code": code,
            "name": names[code],
            "weight_pct": _percent(weights[code]),
            "latest_close": _number(latest_close),
            "latest_date": close.index[-1].date().isoformat(),
            "period_return_pct": _percent(close.iloc[-1] / close.iloc[0] - 1),
            "annualized_volatility_pct": _percent(item_returns.std() * math.sqrt(252)),
            "max_drawdown_pct": _percent(item_drawdown.min()),
            "cost_return_pct": None,
        }
        if "cost_price" in holding:
            item["cost_return_pct"] = _percent(latest_close / holding["cost_price"] - 1)
        holding_results.append(item)

    correlation = returns.corr()
    highest_correlation = _highest_correlation(correlation)
    stress_results = [
        {
            "uniform_price_shock_pct": shock,
            "estimated_portfolio_change_pct": _number(shock),
        }
        for shock in stress_scenarios
    ]
    return {
        "status": "partial" if warnings else "success",
        "observed_at": observed_at,
        "source": SOURCE_NAME,
        "adjustment": "qfq (前复权)",
        "weight_basis": weight_basis,
        "portfolio": portfolio,
        "holdings": holding_results,
        "highest_correlation": highest_correlation,
        "stress_results": stress_results,
        "warnings": warnings,
        "message": "A 股持仓风险指标计算完成；结果描述历史统计，不代表未来表现。",
    }


def _holdings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("holdings must contain 1 to 20 items")
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("each holding must be an object")
        code = str(raw.get("code") or "").strip()
        if not CODE_RE.fullmatch(code):
            raise ValueError(f"invalid six-digit A-share code: {code or '<empty>'}")
        has_weight = raw.get("weight") is not None
        has_shares = raw.get("shares") is not None
        if has_weight == has_shares:
            raise ValueError(f"holding {code} must provide exactly one of weight or shares")
        item: dict[str, Any] = {"code": code}
        key = "weight" if has_weight else "shares"
        item[key] = _positive(raw[key], field=f"{code}.{key}")
        if raw.get("cost_price") is not None:
            item["cost_price"] = _positive(raw["cost_price"], field=f"{code}.cost_price")
        normalized.append(item)
    codes = [item["code"] for item in normalized]
    if len(codes) != len(set(codes)):
        raise ValueError("holding codes must be unique")
    basis_keys = {"weight" if "weight" in item else "shares" for item in normalized}
    if len(basis_keys) != 1:
        raise ValueError("all holdings must use the same weight or shares basis")
    return normalized


def _a_share_names(codes: list[str]) -> dict[str, str]:
    frame = ak.stock_info_a_code_name()
    required = {"code", "name"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"A-share security list missing columns: {', '.join(missing)}")
    indexed = {
        _code_text(row["code"]): str(row["name"]).strip()
        for _, row in frame.iterrows()
    }
    unknown = sorted(code for code in codes if code not in indexed)
    if unknown:
        raise ValueError("codes are not present in the current A-share security list: " + ", ".join(unknown))
    return {code: indexed[code] or code for code in codes}


def _weights(holdings: list[dict[str, Any]], close_by_code: dict[str, pd.Series]) -> tuple[pd.Series, str]:
    if "weight" in holdings[0]:
        raw = pd.Series({item["code"]: item["weight"] for item in holdings}, dtype=float)
        basis = "provided_weights"
    else:
        raw = pd.Series(
            {item["code"]: item["shares"] * float(close_by_code[item["code"]].iloc[-1]) for item in holdings},
            dtype=float,
        )
        basis = "latest_market_value"
    total = float(raw.sum())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("holding basis must have a positive finite total")
    return raw / total, basis


def _stress_scenarios(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError("stress_scenarios must contain at most 5 numbers")
    scenarios: list[float] = []
    for item in value:
        shock = float(item)
        if not math.isfinite(shock) or shock < -50 or shock > 50:
            raise ValueError("stress scenarios must be between -50 and 50 percent")
        scenarios.append(shock)
    return scenarios


def _highest_correlation(correlation: pd.DataFrame) -> dict[str, Any] | None:
    if len(correlation.columns) < 2:
        return None
    best: tuple[str, str, float] | None = None
    columns = list(correlation.columns)
    for index, left in enumerate(columns):
        for right in columns[index + 1 :]:
            value = float(correlation.loc[left, right])
            if math.isfinite(value) and (best is None or value > best[2]):
                best = (left, right, value)
    if best is None:
        return None
    return {"left_code": best[0], "right_code": best[1], "correlation": _number(best[2])}


def _positive(value: Any, *, field: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return parsed


def _number(value: Any) -> float | None:
    parsed = float(value)
    return round(parsed, 4) if math.isfinite(parsed) else None


def _percent(value: Any) -> float | None:
    return _number(float(value) * 100)


def _code_text(value: Any) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.zfill(6)
