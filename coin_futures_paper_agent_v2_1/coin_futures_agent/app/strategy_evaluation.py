from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import datetime
from typing import Any

from .battle_storage import battle_account_balance, battle_recent_trades
from .case_registry import list_strategy_cases
from .trade_journal import attribution_summary, get_trade_attribution


def _context(trade: dict[str, Any]) -> dict[str, Any]:
    raw = trade.get("entry_context")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _profit_factor(trades: list[dict[str, Any]]) -> float | None:
    gross_win = sum(max(0.0, float(t.get("net_pnl") or 0)) for t in trades)
    gross_loss = -sum(min(0.0, float(t.get("net_pnl") or 0)) for t in trades)
    if gross_loss <= 0:
        return None if gross_win <= 0 else 999.0
    return gross_win / gross_loss


def _max_drawdown(trades: list[dict[str, Any]], start_balance: float = 10_000.0) -> tuple[float, float]:
    equity = float(start_balance)
    peak = equity
    max_dd = 0.0
    for trade in trades:
        equity += float(trade.get("net_pnl") or 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    pct = max_dd / peak * 100 if peak > 0 else 0.0
    return max_dd, pct


def _longest_losing_streak(trades: list[dict[str, Any]]) -> int:
    best = cur = 0
    for trade in trades:
        if float(trade.get("net_pnl") or 0) < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _metrics(trades: list[dict[str, Any]], start_balance: float = 10_000.0) -> dict[str, Any]:
    n = len(trades)
    wins = [t for t in trades if float(t.get("net_pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("net_pnl") or 0) < 0]
    r_values = [float(t.get("r_multiple") or 0) for t in trades]
    win_r = [float(t.get("r_multiple") or 0) for t in wins]
    loss_r = [float(t.get("r_multiple") or 0) for t in losses]
    max_dd, max_dd_pct = _max_drawdown(trades, start_balance)
    pf = _profit_factor(trades)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else 0.0,
        "net_pnl": round(sum(float(t.get("net_pnl") or 0) for t in trades), 2),
        "profit_factor": round(pf, 3) if pf is not None else None,
        "expectancy_r": round(sum(r_values) / n, 3) if n else 0.0,
        "avg_win_r": round(sum(win_r) / len(win_r), 3) if win_r else 0.0,
        "avg_loss_r": round(sum(loss_r) / len(loss_r), 3) if loss_r else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "longest_losing_streak": _longest_losing_streak(trades),
        "avg_holding_minutes": round(
            sum(float(t.get("holding_minutes") or 0) for t in trades) / n, 1
        ) if n else 0.0,
    }


def _bucket(trades: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(key_fn(trade))].append(trade)
    return {key: _metrics(xs) for key, xs in sorted(groups.items())}


def _weekly_stability(trades: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        try:
            dt = datetime.fromisoformat(str(trade["closed_at"]).replace("Z", "+00:00"))
            iso = dt.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        except Exception:
            key = "UNKNOWN"
        groups[key].append(trade)
    rows = []
    for key, xs in sorted(groups.items()):
        m = _metrics(xs)
        rows.append({"week": key, **m})
    valid = [x for x in rows if x["week"] != "UNKNOWN"]
    positive = sum(1 for x in valid if x["expectancy_r"] > 0)
    ratio = positive / len(valid) * 100 if valid else 0.0
    return {
        "weeks": rows,
        "positive_weeks_pct": round(ratio, 1),
        "positive_weeks": positive,
        "total_weeks": len(valid),
    }


def _monte_carlo(trades: list[dict[str, Any]], trials: int = 1000) -> dict[str, Any] | None:
    rs = [float(t.get("r_multiple") or 0) for t in trades]
    if len(rs) < 30:
        return None
    rng = random.Random(42)
    dds: list[float] = []
    worst_streaks: list[int] = []
    for _ in range(trials):
        seq = list(rs)
        rng.shuffle(seq)
        equity = peak = 0.0
        max_dd = 0.0
        cur_loss = max_loss = 0
        for r in seq:
            equity += r
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if r < 0:
                cur_loss += 1
                max_loss = max(max_loss, cur_loss)
            else:
                cur_loss = 0
        dds.append(max_dd)
        worst_streaks.append(max_loss)
    dds.sort()
    worst_streaks.sort()
    def pct(xs: list[float] | list[int], p: float):
        i = min(len(xs) - 1, max(0, int(math.ceil(p * len(xs))) - 1))
        return xs[i]
    return {
        "trials": trials,
        "median_max_drawdown_r": round(float(pct(dds, 0.50)), 2),
        "p95_max_drawdown_r": round(float(pct(dds, 0.95)), 2),
        "p95_longest_losing_streak": int(pct(worst_streaks, 0.95)),
    }


def _single_trade_concentration(trades: list[dict[str, Any]]) -> float:
    gains = [max(0.0, float(t.get("net_pnl") or 0)) for t in trades]
    total = sum(gains)
    return max(gains, default=0.0) / total * 100 if total > 0 else 100.0


def _readiness(case: dict[str, Any], metrics: dict[str, Any], stability: dict[str, Any], attribution: dict[str, Any]) -> dict[str, Any]:
    pf = metrics.get("profit_factor")
    gates = {
        "sample_size": {
            "pass": metrics["trades"] >= 100,
            "value": metrics["trades"],
            "target": ">= 100 closed trades",
        },
        "expectancy": {
            "pass": metrics["expectancy_r"] > 0.10,
            "value": metrics["expectancy_r"],
            "target": "> +0.10R/trade",
        },
        "profit_factor": {
            "pass": pf is not None and pf > 1.25,
            "value": pf,
            "target": "> 1.25",
        },
        "drawdown": {
            "pass": metrics["max_drawdown_pct"] < 10.0,
            "value": metrics["max_drawdown_pct"],
            "target": "< 10%",
        },
        "stability": {
            "pass": stability["total_weeks"] >= 4 and stability["positive_weeks_pct"] >= 60,
            "value": stability["positive_weeks_pct"],
            "target": ">= 60% positive weeks and >=4 weeks",
        },
        "quality_adjusted_edge": {
            "pass": float(attribution.get("quality_adjusted_pnl_ex_news_assisted") or 0) > 0,
            "value": attribution.get("quality_adjusted_pnl_ex_news_assisted"),
            "target": "> 0 after excluding news-assisted wins",
        },
    }
    passed = sum(1 for x in gates.values() if x["pass"])
    score = round(passed / len(gates) * 100)
    if metrics["trades"] < 30:
        status = "EXPERIMENTAL"
    elif metrics["trades"] < 100:
        status = "PROMISING" if metrics["expectancy_r"] > 0 else "RESEARCH"
    elif passed == len(gates):
        status = "VALIDATION_CANDIDATE"
    elif passed >= 4:
        status = "PROMISING"
    else:
        status = "RESEARCH"
    return {
        "score": score,
        "status": status,
        "gates": gates,
        "note": (
            "Không dùng readiness này như lời khuyên giao dịch. Trước tiền thật vẫn cần giai đoạn validation/locked test và kiểm tra execution thực tế."
        ),
    }


def evaluate_strategy(strategy_id: str) -> dict[str, Any]:
    cases = {x["strategy_id"]: x for x in list_strategy_cases(True)}
    case = cases.get(strategy_id)
    if not case:
        raise KeyError(strategy_id)
    trades = battle_recent_trades(5000, strategy_id)
    metrics = _metrics(trades)
    stability = _weekly_stability(trades)
    attr = attribution_summary(strategy_id)
    for trade in trades:
        get_trade_attribution(int(trade["id"]))

    score_buckets = _bucket(
        trades,
        lambda t: (
            "75-79" if float(t.get("score") or 0) < 80
            else "80-84" if float(t.get("score") or 0) < 85
            else "85-89" if float(t.get("score") or 0) < 90
            else "90+"
        ),
    )
    regimes = _bucket(trades, lambda t: _context(t).get("btc_regime") or "UNKNOWN")
    sides = _bucket(trades, lambda t: t.get("side") or "UNKNOWN")
    exit_modes = _bucket(
        trades,
        lambda t: (_context(t).get("case_config") or {}).get("exit_mode", "LEGACY"),
    )

    return {
        "strategy_id": strategy_id,
        "case": case,
        "balance": round(battle_account_balance(strategy_id), 2),
        "metrics": metrics,
        "segments": {
            "score": score_buckets,
            "btc_regime": regimes,
            "side": sides,
            "exit_mode": exit_modes,
        },
        "stability": stability,
        "attribution": attribution_summary(strategy_id),
        "monte_carlo": _monte_carlo(trades),
        "largest_win_contribution_pct": round(_single_trade_concentration(trades), 1),
        "readiness": _readiness(case, metrics, stability, attr),
    }


def strategy_evaluation_overview() -> dict[str, Any]:
    rows = []
    for case in list_strategy_cases(False):
        rows.append(evaluate_strategy(case["strategy_id"]))
    rows.sort(
        key=lambda x: (
            x["readiness"]["score"],
            x["metrics"]["expectancy_r"],
            x["metrics"]["net_pnl"],
        ),
        reverse=True,
    )
    return {
        "cases": rows,
        "method": "research diagnostics: expectancy/PF/DD/stability/attribution/Monte Carlo; not an automatic live-trading approval",
    }
