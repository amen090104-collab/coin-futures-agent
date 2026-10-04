from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from .config import settings
from .review import aggregate_recommendations, analyze_loss
from .storage import add_recommendation, account_balance, recent_trades, save_daily_report, trades_between


def _local_day_bounds(day: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    d = datetime.strptime(day, "%Y-%m-%d").date()
    start_local = datetime(d.year, d.month, d.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def build_daily_report(day: str) -> dict[str, Any]:
    start, end = _local_day_bounds(day)
    trades = trades_between(start.isoformat(), end.isoformat())
    wins = [t for t in trades if float(t["net_pnl"]) > 0]
    losses = [t for t in trades if float(t["net_pnl"]) < 0]
    pnls = [float(t["net_pnl"]) for t in trades]
    gross_profit = sum(max(0.0, x) for x in pnls)
    gross_loss = -sum(min(0.0, x) for x in pnls)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    r_values = [float(t["r_multiple"]) for t in trades]

    trade_details = []
    reason_perf: dict[str, dict[str, float]] = {}
    for t in trades:
        try:
            codes = json.loads(t["reason_codes"]) if isinstance(t["reason_codes"], str) else (t["reason_codes"] or [])
        except Exception:
            codes = []
        trade_details.append({
            "trade_id": t["id"],
            "symbol": t["symbol"],
            "side": t["side"],
            "score": round(float(t["score"]), 1),
            "entry_price": float(t["entry_price"]),
            "stop_loss": float(t["stop_loss"]),
            "take_profit": float(t["take_profit"]),
            "exit_reason": t["exit_reason"],
            "net_pnl": round(float(t["net_pnl"]), 2),
            "r_multiple": round(float(t["r_multiple"]), 2),
            "entry_reason": t["reason_text"],
            "reason_codes": codes,
        })
        for code in codes:
            x = reason_perf.setdefault(code, {"trades": 0, "wins": 0, "net_pnl": 0.0})
            x["trades"] += 1
            x["wins"] += 1 if float(t["net_pnl"]) > 0 else 0
            x["net_pnl"] += float(t["net_pnl"])

    reason_performance = []
    for code, x in reason_perf.items():
        reason_performance.append({
            "reason_code": code,
            "trades": int(x["trades"]),
            "win_rate_pct": round(x["wins"] / x["trades"] * 100, 1) if x["trades"] else 0.0,
            "net_pnl": round(x["net_pnl"], 2),
        })
    reason_performance.sort(key=lambda x: (-x["trades"], x["net_pnl"]))

    loss_details = []
    for t in losses:
        causes, fixes = analyze_loss(t)
        loss_details.append({
            "trade_id": t["id"],
            "symbol": t["symbol"],
            "side": t["side"],
            "net_pnl": round(float(t["net_pnl"]), 2),
            "r_multiple": round(float(t["r_multiple"]), 2),
            "entry_reason": t["reason_text"],
            "causes": causes,
            "fixes": fixes,
        })

    rolling = recent_trades(settings.rolling_review_trades)
    recs = aggregate_recommendations(rolling)
    now = datetime.now(timezone.utc).isoformat()
    for r in recs:
        add_recommendation(now, f"daily:{day}", r["recommendation"], r["evidence"])

    return {
        "report_date": day,
        "created_at": now,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round((len(wins) / len(trades) * 100) if trades else 0.0, 2),
        "net_pnl": round(sum(pnls), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_r": round(mean(r_values), 3) if r_values else 0.0,
        "max_drawdown_usdt": round(_max_drawdown(pnls), 2),
        "paper_balance": round(account_balance(), 2),
        "trade_details": trade_details,
        "reason_performance": reason_performance,
        "loss_details": loss_details,
        "recommendations": recs,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Daily Paper Trading Report - {report['report_date']}",
        "",
        "## Summary",
        f"- Trades: {report['trades']} | Wins: {report['wins']} | Losses: {report['losses']} | Win rate: {report['win_rate_pct']}%",
        f"- Net PnL: {report['net_pnl']} USDT | Profit factor: {report['profit_factor']} | Avg R: {report['avg_r']}",
        f"- Max intraday drawdown: {report['max_drawdown_usdt']} USDT | Paper balance: {report['paper_balance']} USDT",
        "",
        "## All trades and why the agent entered",
    ]
    if not report["trade_details"]:
        lines.append("- No trades closed today.")
    for x in report["trade_details"]:
        lines.append(
            f"- #{x['trade_id']} {x['symbol']} {x['side']} | score {x['score']} | "
            f"Entry {x['entry_price']:.8g} / SL {x['stop_loss']:.8g} / TP {x['take_profit']:.8g} | "
            f"Exit {x['exit_reason']} | {x['net_pnl']} USDT ({x['r_multiple']}R) | Why: {x['entry_reason']}"
        )

    lines += ["", "## Entry reason performance"]
    if not report["reason_performance"]:
        lines.append("- Not enough trades today.")
    for x in report["reason_performance"]:
        lines.append(
            f"- {x['reason_code']}: {x['trades']} trades | WR {x['win_rate_pct']}% | Net {x['net_pnl']} USDT"
        )

    lines += ["", "## Losing trades and postmortem"]
    if not report["loss_details"]:
        lines.append("- No losing trades closed today.")
    for x in report["loss_details"]:
        lines += [
            f"### Trade #{x['trade_id']} - {x['symbol']} {x['side']}",
            f"- Result: {x['net_pnl']} USDT ({x['r_multiple']}R)",
            f"- Entry rationale: {x['entry_reason']}",
            "- Possible causes:",
        ]
        lines += [f"  - {c}" for c in x["causes"]]
        lines.append("- Candidate fixes to backtest:")
        lines += [f"  - {f}" for f in x["fixes"]]
        lines.append("")

    lines += ["## Strategy recommendations (proposal only - not auto-applied)"]
    for r in report["recommendations"]:
        lines.append(f"- {r['recommendation']} Evidence: {r['evidence']}")
    lines += [
        "",
        "> Important: the agent never changes strategy rules automatically from a small losing sample. Recommendations must be validated with more paper data/backtesting first.",
        "",
    ]
    return "\n".join(lines)


def generate_and_save(day: str) -> dict[str, Any]:
    report = build_daily_report(day)
    out_dir = Path(settings.reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    save_daily_report(day, report["created_at"], report, str(path))
    return report
