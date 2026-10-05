from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if out.tzinfo is None:
            out = out.replace(tzinfo=timezone.utc)
        return out
    except Exception:
        return None


def _reason_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except Exception:
        return []


def enrich_open_position(position: dict[str, Any], fee_bps: float = 0.0) -> dict[str, Any]:
    entry = _f(position.get("entry_price"))
    last = _f(position.get("last_price"), entry)
    qty = _f(position.get("quantity"))
    side = str(position.get("side") or "")
    gross = (last - entry) * qty if side == "LONG" else (entry - last) * qty
    fees = (entry * qty + last * qty) * fee_bps / 10_000
    net = gross - fees
    risk_usdt = max(_f(position.get("risk_usdt")), 0.0)
    notional = abs(last * qty)
    opened = _dt(position.get("opened_at"))
    now = datetime.now(timezone.utc)
    holding_minutes = (now - opened).total_seconds() / 60 if opened else 0.0
    stop = _f(position.get("stop_loss"))
    tp = _f(position.get("take_profit"))
    return {
        **position,
        "market_price": last,
        "unrealized_gross_pnl": round(gross, 6),
        "estimated_fees": round(fees, 6),
        "unrealized_pnl": round(net, 6),
        "unrealized_r": round(net / risk_usdt, 3) if risk_usdt > 0 else 0.0,
        "pnl_pct_notional": round(net / notional * 100, 3) if notional > 0 else 0.0,
        "notional_usdt": round(notional, 2),
        "holding_minutes": round(max(0.0, holding_minutes), 1),
        "distance_to_sl_pct": round(abs(last - stop) / last * 100, 3) if last > 0 and stop > 0 else 0.0,
        "distance_to_tp_pct": round(abs(tp - last) / last * 100, 3) if last > 0 and tp > 0 else 0.0,
    }


def _drawdown(trades: list[dict[str, Any]], balance: float) -> tuple[float, float]:
    realized = sum(_f(t.get("net_pnl")) for t in trades)
    equity = balance - realized
    peak = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    for trade in trades:
        equity += _f(trade.get("net_pnl"))
        peak = max(peak, equity)
        dd = max(0.0, peak - equity)
        dd_pct = dd / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        max_dd_pct = max(max_dd_pct, dd_pct)
    return round(max_dd, 2), round(max_dd_pct, 2)


def _daily_stats(trades: list[dict[str, Any]], timezone_name: str, limit: int = 14) -> list[dict[str, Any]]:
    tz = ZoneInfo(timezone_name)
    grouped: dict[str, dict[str, Any]] = {}
    for trade in trades:
        closed = _dt(trade.get("closed_at"))
        if not closed:
            continue
        day = closed.astimezone(tz).strftime("%Y-%m-%d")
        row = grouped.setdefault(day, {"date": day, "trades": 0, "wins": 0, "net_pnl": 0.0, "r": 0.0})
        row["trades"] += 1
        row["wins"] += _f(trade.get("net_pnl")) > 0
        row["net_pnl"] += _f(trade.get("net_pnl"))
        row["r"] += _f(trade.get("r_multiple"))
    out = []
    for day in sorted(grouped)[-limit:]:
        row = grouped[day]
        count = max(int(row["trades"]), 1)
        out.append({
            "date": day,
            "trades": row["trades"],
            "wins": row["wins"],
            "win_rate": round(row["wins"] / count * 100, 1),
            "net_pnl": round(row["net_pnl"], 2),
            "avg_r": round(row["r"] / count, 2),
        })
    return out


def _setup_stats(trades: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0.0, "wins": 0.0, "net_pnl": 0.0, "r": 0.0})
    for trade in trades:
        codes = set(_reason_codes(trade.get("reason_codes")))
        for code in codes:
            row = stats[code]
            row["trades"] += 1
            row["wins"] += _f(trade.get("net_pnl")) > 0
            row["net_pnl"] += _f(trade.get("net_pnl"))
            row["r"] += _f(trade.get("r_multiple"))
    out = []
    for code, row in stats.items():
        n = int(row["trades"])
        if not n:
            continue
        out.append({
            "setup": code,
            "trades": n,
            "wins": int(row["wins"]),
            "win_rate": round(row["wins"] / n * 100, 1),
            "net_pnl": round(row["net_pnl"], 2),
            "avg_r": round(row["r"] / n, 2),
        })
    out.sort(key=lambda x: (x["trades"], x["net_pnl"]), reverse=True)
    return out[:limit]


def _side_stats(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for side in ("LONG", "SHORT"):
        xs = [t for t in trades if t.get("side") == side]
        wins = sum(_f(t.get("net_pnl")) > 0 for t in xs)
        out.append({
            "side": side,
            "trades": len(xs),
            "wins": wins,
            "win_rate": round(wins / len(xs) * 100, 1) if xs else 0.0,
            "net_pnl": round(sum(_f(t.get("net_pnl")) for t in xs), 2),
            "avg_r": round(sum(_f(t.get("r_multiple")) for t in xs) / len(xs), 2) if xs else 0.0,
        })
    return out


def build_dashboard_analytics(
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    balance: float,
    timezone_name: str,
    fee_bps: float = 0.0,
) -> dict[str, Any]:
    enriched_positions = [enrich_open_position(p, fee_bps) for p in positions]
    unrealized = sum(_f(p.get("unrealized_pnl")) for p in enriched_positions)
    equity = balance + unrealized
    realized = sum(_f(t.get("net_pnl")) for t in trades)
    wins = sum(_f(t.get("net_pnl")) > 0 for t in trades)
    losses = sum(_f(t.get("net_pnl")) < 0 for t in trades)
    gross_profit = sum(max(0.0, _f(t.get("net_pnl"))) for t in trades)
    gross_loss = -sum(min(0.0, _f(t.get("net_pnl"))) for t in trades)
    max_dd, max_dd_pct = _drawdown(trades, balance)
    avg_r = sum(_f(t.get("r_multiple")) for t in trades) / len(trades) if trades else 0.0

    return {
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "open_notional": round(sum(_f(p.get("notional_usdt")) for p in enriched_positions), 2),
        "open_risk_usdt": round(sum(_f(p.get("risk_usdt")) for p in enriched_positions), 2),
        "closed": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "avg_r": round(avg_r, 2),
        "max_drawdown_usdt": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "open_positions": enriched_positions,
        "daily": _daily_stats(trades, timezone_name),
        "setups": _setup_stats(trades),
        "sides": _side_stats(trades),
    }
