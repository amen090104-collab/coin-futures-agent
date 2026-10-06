from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .analytics import build_dashboard_analytics
from .battle_config import STRATEGIES, STRATEGY_IDS
from .battle_storage import (
    battle_account_balance,
    battle_open_positions,
    battle_recent_trades,
)
from .config import settings


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _context(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _pf(trades: list[dict[str, Any]]) -> float:
    gp = sum(max(0.0, _f(t.get("net_pnl"))) for t in trades)
    gl = -sum(min(0.0, _f(t.get("net_pnl"))) for t in trades)
    if gl > 0:
        return round(gp / gl, 2)
    return 999.0 if gp > 0 else 0.0


def _simple_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    wins = sum(_f(t.get("net_pnl")) > 0 for t in trades)
    net = sum(_f(t.get("net_pnl")) for t in trades)
    rs = [_f(t.get("r_multiple")) for t in trades]
    return {
        "trades": n,
        "wins": wins,
        "losses": sum(_f(t.get("net_pnl")) < 0 for t in trades),
        "win_rate": round(wins / n * 100, 1) if n else 0.0,
        "net_pnl": round(net, 2),
        "avg_r": round(sum(rs) / n, 3) if n else 0.0,
        "profit_factor": _pf(trades),
    }


def _pro_metrics(
    trades: list[dict[str, Any]],
    starting_balance: float,
) -> dict[str, Any]:
    wins_r = [_f(t.get("r_multiple")) for t in trades if _f(t.get("net_pnl")) > 0]
    losses_r = [_f(t.get("r_multiple")) for t in trades if _f(t.get("net_pnl")) < 0]
    holding = [_f(t.get("holding_minutes")) for t in trades]
    exits: dict[str, int] = defaultdict(int)
    for trade in trades:
        exits[str(trade.get("exit_reason") or "UNKNOWN")] += 1

    equity = float(starting_balance)
    curve = [{"label": "START", "equity": round(equity, 2)}]
    for trade in sorted(
        trades,
        key=lambda t: (str(t.get("closed_at") or ""), int(t.get("id") or 0)),
    ):
        equity += _f(trade.get("net_pnl"))
        curve.append(
            {
                "label": str(trade.get("closed_at") or ""),
                "equity": round(equity, 2),
                "trade_id": trade.get("id"),
                "symbol": trade.get("symbol"),
            }
        )

    n = len(trades)
    return {
        "expectancy_r": round(
            sum(_f(t.get("r_multiple")) for t in trades) / n, 3
        ) if n else 0.0,
        "avg_win_r": round(sum(wins_r) / len(wins_r), 3) if wins_r else 0.0,
        "avg_loss_r": round(sum(losses_r) / len(losses_r), 3) if losses_r else 0.0,
        "avg_holding_minutes": round(sum(holding) / len(holding), 1) if holding else 0.0,
        "tp_rate": round(exits["TAKE_PROFIT"] / n * 100, 1) if n else 0.0,
        "sl_rate": round(exits["STOP_LOSS"] / n * 100, 1) if n else 0.0,
        "time_exit_rate": round(exits["TIME_EXIT"] / n * 100, 1) if n else 0.0,
        "news_exit_rate": round(exits["NEWS_RISK_EXIT"] / n * 100, 1) if n else 0.0,
        "exit_counts": dict(exits),
        "equity_curve": curve[-301:],
    }


def _score_bucket(score: float) -> str:
    if score < 80:
        return "75-79"
    if score < 85:
        return "80-84"
    if score < 90:
        return "85-89"
    return "90+"


def _score_bucket_matrix(
    trades_by_strategy: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    buckets = ["75-79", "80-84", "85-89", "90+"]
    out = []
    for bucket in buckets:
        row = {"bucket": bucket, "strategies": {}}
        for sid in STRATEGY_IDS:
            xs = [
                t
                for t in trades_by_strategy[sid]
                if _score_bucket(_f(t.get("score"))) == bucket
            ]
            row["strategies"][sid] = _simple_stats(xs)
        out.append(row)
    return out


def _regime_matrix(
    trades_by_strategy: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    regimes = ["BULLISH", "BEARISH", "NEUTRAL"]
    out = []
    for regime in regimes:
        row = {"regime": regime, "strategies": {}}
        for sid in STRATEGY_IDS:
            xs = [
                t
                for t in trades_by_strategy[sid]
                if str(_context(t.get("entry_context")).get("btc_regime") or "NEUTRAL")
                == regime
            ]
            row["strategies"][sid] = _simple_stats(xs)
        out.append(row)
    return out


def _cohorts(
    combined_trades: list[dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for trade in combined_trades:
        ctx = _context(trade.get("entry_context"))
        cohort_id = str(ctx.get("cohort_id") or "")
        if not cohort_id:
            continue
        row = grouped.setdefault(
            cohort_id,
            {
                "cohort_id": cohort_id,
                "symbol": trade.get("symbol"),
                "opened_at": trade.get("opened_at"),
                "source_signal_side": ctx.get("source_signal_side"),
                "score": _f(trade.get("score")),
                "btc_regime": ctx.get("btc_regime"),
                "results": {},
            },
        )
        sid = str(trade.get("strategy_id") or ctx.get("strategy_id") or "")
        if not sid:
            continue
        row["results"][sid] = {
            "side": trade.get("side"),
            "exit_reason": trade.get("exit_reason"),
            "net_pnl": round(_f(trade.get("net_pnl")), 2),
            "r_multiple": round(_f(trade.get("r_multiple")), 3),
            "closed_at": trade.get("closed_at"),
        }

    rows: list[dict[str, Any]] = []
    for row in grouped.values():
        results = row["results"]
        row["closed_cases"] = len(results)
        row["complete"] = len(results) == len(STRATEGY_IDS)
        row["total_net_pnl"] = round(
            sum(_f(x.get("net_pnl")) for x in results.values()),
            2,
        )
        if results:
            row["best_strategy"] = max(
                results,
                key=lambda sid: _f(results[sid].get("net_pnl")),
            )
            row["worst_strategy"] = min(
                results,
                key=lambda sid: _f(results[sid].get("net_pnl")),
            )
        else:
            row["best_strategy"] = None
            row["worst_strategy"] = None
        rows.append(row)

    rows.sort(key=lambda x: str(x.get("opened_at") or ""))
    complete = [x for x in rows if x["complete"]]
    best = sorted(complete, key=lambda x: x["total_net_pnl"], reverse=True)[:10]
    worst = sorted(complete, key=lambda x: x["total_net_pnl"])[:10]
    return {
        "recent": rows[-50:],
        "best": best,
        "worst": worst,
        "complete_count": len(complete),
        "total_count": len(rows),
    }


def _factor_summary(
    strategies: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {s["strategy_id"]: s for s in strategies}

    def metric(sid: str, key: str) -> float:
        return _f((by_id.get(sid) or {}).get("analytics", {}).get(key))

    base_pnl = metric("BASE_RR2", "realized_pnl") + metric("BASE_RR1", "realized_pnl")
    reverse_pnl = metric("REVERSE_RR2", "realized_pnl") + metric("REVERSE_RR1", "realized_pnl")
    rr2_pnl = metric("BASE_RR2", "realized_pnl") + metric("REVERSE_RR2", "realized_pnl")
    rr1_pnl = metric("BASE_RR1", "realized_pnl") + metric("REVERSE_RR1", "realized_pnl")

    return {
        "direction_effect": {
            "base_net_pnl": round(base_pnl, 2),
            "reverse_net_pnl": round(reverse_pnl, 2),
            "leader": "BASE" if base_pnl > reverse_pnl else "REVERSE" if reverse_pnl > base_pnl else "TIE",
        },
        "rr_effect": {
            "rr2_net_pnl": round(rr2_pnl, 2),
            "rr1_net_pnl": round(rr1_pnl, 2),
            "leader": "1:2" if rr2_pnl > rr1_pnl else "1:1" if rr1_pnl > rr2_pnl else "TIE",
        },
    }


def build_strategy_battle_dashboard() -> dict[str, Any]:
    strategies: list[dict[str, Any]] = []
    combined_positions: list[dict[str, Any]] = []
    combined_trades: list[dict[str, Any]] = []
    trades_by_strategy: dict[str, list[dict[str, Any]]] = {}

    for strategy_id in STRATEGY_IDS:
        trades = battle_recent_trades(5000, strategy_id)
        trades_by_strategy[strategy_id] = trades
        positions = battle_open_positions(strategy_id)
        balance = battle_account_balance(strategy_id)
        analytics = build_dashboard_analytics(
            trades,
            positions,
            balance,
            settings.timezone,
            settings.taker_fee_bps,
        )
        analytics.update(_pro_metrics(trades, settings.battle_start_balance))

        for position in analytics["open_positions"]:
            position["strategy_id"] = strategy_id
            position["strategy_name"] = STRATEGIES[strategy_id]["name"]
        for trade in trades:
            trade["strategy_name"] = STRATEGIES[strategy_id]["name"]

        combined_positions.extend(analytics["open_positions"])
        combined_trades.extend(trades)
        strategies.append(
            {
                "strategy_id": strategy_id,
                **STRATEGIES[strategy_id],
                "starting_balance": settings.battle_start_balance,
                "analytics": analytics,
            }
        )

    combined_trades.sort(
        key=lambda x: (str(x.get("closed_at") or ""), int(x.get("id") or 0))
    )

    eligible = [s for s in strategies if int(s["analytics"]["closed"]) > 0]
    leader_pnl = (
        max(eligible, key=lambda s: _f(s["analytics"]["realized_pnl"]))["strategy_id"]
        if eligible
        else None
    )
    leader_wr = (
        max(eligible, key=lambda s: _f(s["analytics"]["win_rate"]))["strategy_id"]
        if eligible
        else None
    )
    leader_expectancy = (
        max(eligible, key=lambda s: _f(s["analytics"]["expectancy_r"]))["strategy_id"]
        if eligible
        else None
    )
    leader_pf = (
        max(eligible, key=lambda s: _f(s["analytics"]["profit_factor"]))["strategy_id"]
        if eligible
        else None
    )
    leader_low_dd = (
        min(eligible, key=lambda s: _f(s["analytics"]["max_drawdown_pct"]))["strategy_id"]
        if eligible
        else None
    )
    min_closed = min(
        (int(s["analytics"]["closed"]) for s in strategies),
        default=0,
    )

    return {
        "strategies": strategies,
        "open_positions": combined_positions,
        "trades": combined_trades[-500:],
        "leader_net_pnl": leader_pnl,
        "leader_win_rate": leader_wr,
        "leader_expectancy": leader_expectancy,
        "leader_profit_factor": leader_pf,
        "leader_low_drawdown": leader_low_dd,
        "min_closed_per_case": min_closed,
        "sample_ready": min_closed >= 30,
        "recommended_comparison_sample": 30,
        "preferred_comparison_sample": 50,
        "score_buckets": _score_bucket_matrix(trades_by_strategy),
        "regimes": _regime_matrix(trades_by_strategy),
        "cohorts": _cohorts(combined_trades),
        "factors": _factor_summary(strategies),
    }
