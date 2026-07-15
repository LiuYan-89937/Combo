from __future__ import annotations

from datetime import datetime
import math
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd


SOURCE_NAME = "东方财富公开行情（通过 AkShare）"


def run(arguments: dict, resources: dict) -> dict:
    del resources
    top_n = int(arguments.get("top_n", 10))
    if top_n < 1 or top_n > 20:
        raise ValueError("top_n must be between 1 and 20")
    include_industries = bool(arguments.get("include_industries", True))
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    warnings: list[str] = []
    try:
        spot = ak.stock_zh_a_spot_em()
        _require_columns(spot, {"代码", "名称", "最新价", "涨跌幅", "成交额"}, dataset="A-share spot")
        change = pd.to_numeric(spot["涨跌幅"], errors="coerce")
        amount = pd.to_numeric(spot["成交额"], errors="coerce")
        valid_change = change.dropna()
        market = {
            "listed_count": int(len(spot)),
            "priced_count": int(valid_change.count()),
            "advancers": int((valid_change > 0).sum()),
            "decliners": int((valid_change < 0).sum()),
            "unchanged": int((valid_change == 0).sum()),
            "turnover_cny": _number(amount.sum(min_count=1)),
        }
        top_gainers = _stock_rows(spot.assign(_sort=change).nlargest(top_n, "_sort"))
        top_turnover = _stock_rows(spot.assign(_sort=amount).nlargest(top_n, "_sort"))
    except Exception as exc:
        return {
            "status": "error",
            "observed_at": observed_at,
            "source": SOURCE_NAME,
            "market": {},
            "top_gainers": [],
            "top_turnover": [],
            "industries": [],
            "warnings": [],
            "message": f"A 股行情获取失败: {type(exc).__name__}: {exc}",
        }

    industries: list[dict[str, Any]] = []
    if include_industries:
        try:
            board = ak.stock_board_industry_name_em()
            _require_columns(board, {"板块名称", "涨跌幅", "总市值", "换手率"}, dataset="industry board")
            board_change = pd.to_numeric(board["涨跌幅"], errors="coerce")
            selected = board.assign(_sort=board_change).nlargest(top_n, "_sort")
            industries = [
                {
                    "name": _text(row.get("板块名称")),
                    "change_pct": _number(row.get("涨跌幅")),
                    "market_cap_cny": _number(row.get("总市值")),
                    "turnover_rate_pct": _number(row.get("换手率")),
                }
                for _, row in selected.iterrows()
            ]
        except Exception as exc:
            warnings.append(f"行业数据获取失败: {type(exc).__name__}: {exc}")

    return {
        "status": "partial" if warnings else "success",
        "observed_at": observed_at,
        "source": SOURCE_NAME,
        "market": market,
        "top_gainers": top_gainers,
        "top_turnover": top_turnover,
        "industries": industries,
        "warnings": warnings,
        "message": "A 股市场快照获取完成。",
    }


def _stock_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "code": _text(row.get("代码")),
            "name": _text(row.get("名称")),
            "price": _number(row.get("最新价")),
            "change_pct": _number(row.get("涨跌幅")),
            "turnover_cny": _number(row.get("成交额")),
        }
        for _, row in frame.iterrows()
    ]


def _require_columns(frame: pd.DataFrame, required: set[str], *, dataset: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{dataset} missing columns: {', '.join(missing)}")


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
