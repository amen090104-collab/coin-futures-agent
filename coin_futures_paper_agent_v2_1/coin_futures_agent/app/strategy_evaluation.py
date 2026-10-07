from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from .battle_storage import battle_recent_trades
from .strategy_cases import list_strategy_cases
from .trade_intelligence import attribution_summary


def _f(value: Any) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else 0.0
    except Exception:
        return 0.0


def _ctx(trade: dict[str, Any]) -> dict[str, Any]:
    value = trade.get("entry_context")
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


def _longest_losing_streak(trades: list[dict[str, Any]]) -> int:
    longest = current = 0
    for t in sorted(trades, key=lambda x: str(x.get("closed_at") or "")):
        if _f(t.get("net_pnl")) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _weekly_consistency(trades: list[dict[str, Any]]) -> dict[str, Any]:
    weeks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        try:
            d = datetime.fromisoformat(str(t.get("closed_at")).replace("Z", "+00:00"))
            key = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
        except Exception:
            key = "UNKNOWN"
        weeks[key].append(t)
    rows = []
    for week, xs in sorted(weeks.items()):
        avg_r = sum(_f(x.get("r_multiple")) for x in xs) / len(xs)
        rows.append({
            "week": week,
            "trades": len(xs),
            "net_pnl": round(sum(_f(x.get("net_pnl")) for x in xs), 2),
            "avg_r": round(avg_r, 3),
        })
    positive = sum(x["avg_r"] > 0 for x in rows)
    consistency = positive / len(rows) * 100 if rows else 0.0
    return {"weeks": rows[-16:], "positive_week_pct": round(consistency, 1)}


def _exit_research(trades: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [t for t in trades if _f(t.get("net_pnl")) > 0]
    losses = [t for t in trades if _f(t.get("net_pnl")) < 0]
    win_mae = [abs(_f(t.get("mae_r"))) for t in wins]
    win_mfe = [_f(t.get("mfe_r")) for t in wins]
    loss_mfe = [_f(t.get("mfe_r")) for t in losses]
    return {
        "winning_trade_mae_median_r": round(_percentile(win_mae, 0.50), 3),
        "winning_trade_mae_p90_r": round(_percentile(win_mae, 0.90), 3),
        "winning_trade_mfe_median_r": round(_percentile(win_mfe, 0.50), 3),
        "winning_trade_mfe_p75_r": round(_percentile(win_mfe, 0.75), 3),
        "losing_trade_mfe_median_r": round(_percentile(loss_mfe, 0.50), 3),
        "losing_trade_mfe_p75_r": round(_percentile(loss_mfe, 0.75), 3),
        "research_note": (
            "Use these distributions to design future dynamic stop, breakeven, partial-profit "
            "and trailing experiments. They are descriptive statistics, not automatic live rules."
        ),
    }


def evaluate_strategy(strategy_id: str, case: dict[str, Any]) -> dict[str, Any]:
    trades = battle_recent_trades(5000, strategy_id)
    n = len(trades)
    wins = [t for t in trades if _f(t.get("net_pnl")) > 0]
    losses = [t for t in trades if _f(t.get("net_pnl")) < 0]
    win_r = [_f(t.get("r_multiple")) for t in wins]
    loss_r = [_f(t.get("r_multiple")) for t in losses]
    avg_win = sum(win_r) / len(win_r) if win_r else 0.0
    avg_loss = abs(sum(loss_r) / len(loss_r)) if loss_r else 0.0
    expectancy = sum(_f(t.get("r_multiple")) for t in trades) / n if n else 0.0
    gp = sum(max(0.0, _f(t.get("net_pnl"))) for t in trades)
    gl = -sum(min(0.0, _f(t.get("net_pnl"))) for t in trades)
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
    break_even_wr = (
        avg_loss / (avg_win + avg_loss) * 100
        if avg_win > 0 and avg_loss > 0 else 0.0
    )
    actual_wr = len(wins) / n * 100 if n else 0.0

    version = int(case.get("version") or 1)
    current_version = [
        t for t in trades
        if int(_ctx(t).get("case_version") or 1) == version
    ]
    weekly = _weekly_consistency(trades)
    attribution = attribution_summary(trades) if trades else {
        "counts": {}, "thesis_confirmed_pnl": 0, "external_event_pnl": 0, "other_pnl": 0
    }

    score = 0
    score += min(25, n / 100 * 25)
    score += 25 if expectancy >= 0.10 else 15 if expectancy > 0 else 0
    score += 20 if pf >= 1.25 else 10 if pf >= 1.0 else 0
    score += min(15, weekly["positive_week_pct"] / 100 * 15)
    score += 15 if actual_wr >= break_even_wr and n >= 30 else 0
    score = round(min(score, 100), 1)

    if n < 30:
        status = "EXPERIMENTAL"
    elif expectancy <= 0 or pf < 1.0:
        status = "RESEARCH_ONLY"
    elif n < 100:
        status = "PROMISING"
    else:
        status = "VALIDATION_CANDIDATE"

    gates = {
        "sample_100": n >= 100,
        "expectancy_gt_0_10r": expectancy >= 0.10,
        "profit_factor_gt_1_25": pf >= 1.25,
        "win_rate_above_break_even": actual_wr >= break_even_wr if break_even_wr else False,
        "current_version_sample_30": len(current_version) >= 30,
        "out_of_sample_validation": False,
        "live_execution_validation": False,
    }
    return {
        "strategy_id": strategy_id,
        "name": case.get("name"),
        "version": version,
        "status": status,
        "readiness_score": score,
        "closed_trades": n,
        "current_version_trades": len(current_version),
        "win_rate": round(actual_wr, 1),
        "break_even_win_rate": round(break_even_wr, 1),
        "expectancy_r": round(expectancy, 3),
        "profit_factor": round(pf, 2),
        "avg_win_r": round(avg_win, 3),
        "avg_loss_r": round(-avg_loss, 3),
        "longest_losing_streak": _longest_losing_streak(trades),
        "weekly_consistency": weekly,
        "outcome_attribution": attribution,
        "exit_research": _exit_research(trades),
        "gates": gates,
        "live_note": (
            "Never auto-promoted to live. Out-of-sample and real execution validation remain "
            "manual mandatory gates before considering real-money deployment."
        ),
    }


def strategy_evaluation_overview() -> dict[str, Any]:
    cases = list_strategy_cases(include_archived=False)
    rows = [evaluate_strategy(str(c["strategy_id"]), c) for c in cases]
    rows.sort(key=lambda x: x["readiness_score"], reverse=True)
    return {
        "strategies": rows,
        "top_research_candidate": rows[0]["strategy_id"] if rows else None,
        "method": (
            "Research readiness prioritizes sample size, expectancy, profit factor, break-even "
            "win rate and consistency. It intentionally cannot mark a strategy LIVE READY."
        ),
    }
