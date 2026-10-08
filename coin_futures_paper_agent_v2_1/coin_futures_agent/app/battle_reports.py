from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from .battle_analytics import build_strategy_battle_dashboard
from .battle_config import STRATEGIES, STRATEGY_IDS
from .strategy_cases import list_strategy_cases, get_strategy_case
from .strategy_evaluation import strategy_evaluation_overview
from .coin_intelligence import coin_performance_summary, daily_trade_attribution
from .battle_storage import (
    battle_account_balance,
    battle_recent_trades,
    battle_trades_between,
)
from .config import settings
from .storage import (
    get_system_state,
    latest_scan,
    recent_news_guardian_events,
    save_daily_report,
)


def _local_day_bounds(day: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    d = datetime.strptime(day, "%Y-%m-%d").date()
    start_local = datetime(d.year, d.month, d.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return out if out.tzinfo else out.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _context(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _strategy_summary(strategy_id: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_f(t.get("net_pnl")) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_profit = sum(max(0.0, x) for x in pnls)
    gross_loss = -sum(min(0.0, x) for x in pnls)
    r_values = [_f(t.get("r_multiple")) for t in trades]
    win_r = [_f(t.get("r_multiple")) for t in trades if _f(t.get("net_pnl")) > 0]
    loss_r = [_f(t.get("r_multiple")) for t in trades if _f(t.get("net_pnl")) < 0]
    exits: dict[str, int] = defaultdict(int)
    for trade in trades:
        exits[str(trade.get("exit_reason") or "UNKNOWN")] += 1

    case = get_strategy_case(strategy_id) or {"name": strategy_id, "short_name": strategy_id, "rr": 0, "direction_mode": "BASE"}
    return {
        "strategy_id": strategy_id,
        **case,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "net_pnl": round(sum(pnls), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "avg_r": round(mean(r_values), 3) if r_values else 0.0,
        "expectancy_r": round(mean(r_values), 3) if r_values else 0.0,
        "avg_win_r": round(mean(win_r), 3) if win_r else 0.0,
        "avg_loss_r": round(mean(loss_r), 3) if loss_r else 0.0,
        "avg_holding_minutes": round(mean([_f(t.get("holding_minutes")) for t in trades]), 1) if trades else 0.0,
        "max_drawdown_usdt": round(_max_drawdown(pnls), 2),
        "paper_balance": round(battle_account_balance(strategy_id), 2),
        "tp_rate": round(exits["TAKE_PROFIT"] / len(trades) * 100, 1) if trades else 0.0,
        "sl_rate": round(exits["STOP_LOSS"] / len(trades) * 100, 1) if trades else 0.0,
        "time_exit_rate": round(exits["TIME_EXIT"] / len(trades) * 100, 1) if trades else 0.0,
        "news_exit_rate": round(exits["NEWS_RISK_EXIT"] / len(trades) * 100, 1) if trades else 0.0,
        "trade_details": [
            {
                "trade_id": t["id"],
                "symbol": t["symbol"],
                "side": t["side"],
                "score": round(_f(t.get("score")), 1),
                "opened_at": t.get("opened_at"),
                "closed_at": t.get("closed_at"),
                "entry_price": _f(t.get("entry_price")),
                "exit_price": _f(t.get("exit_price")),
                "stop_loss": _f(t.get("stop_loss")),
                "take_profit": _f(t.get("take_profit")),
                "exit_reason": t.get("exit_reason"),
                "net_pnl": round(_f(t.get("net_pnl")), 2),
                "r_multiple": round(_f(t.get("r_multiple")), 2),
                "mfe_r": round(_f(t.get("mfe_r")), 3),
                "mae_r": round(_f(t.get("mae_r")), 3),
                "holding_minutes": round(_f(t.get("holding_minutes")), 1),
                "cohort_id": _context(t.get("entry_context")).get("cohort_id"),
                "btc_regime": _context(t.get("entry_context")).get("btc_regime"),
                "strategy_version": _context(t.get("entry_context")).get("strategy_version"),
                "management_mode": (
                    _context(t.get("entry_context")).get("case_config") or {}
                ).get("management_mode"),
                "entry_thesis": _context(t.get("entry_context")).get("entry_thesis") or {},
                "reason_text": t.get("reason_text"),
                "loss_analysis": _list_value(t.get("loss_analysis")),
                "fix_suggestions": _list_value(t.get("fix_suggestions")),
            }
            for t in trades
        ],
    }


def _daily_cohorts(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for trade in trades:
        ctx = _context(trade.get("entry_context"))
        cohort_id = str(ctx.get("cohort_id") or "")
        if not cohort_id:
            continue
        row = grouped.setdefault(
            cohort_id,
            {
                "cohort_id": cohort_id,
                "symbol": trade.get("symbol"),
                "score": _f(trade.get("score")),
                "source_side": ctx.get("source_signal_side"),
                "btc_regime": ctx.get("btc_regime"),
                "results": {},
            },
        )
        sid = str(trade.get("strategy_id") or ctx.get("strategy_id") or "")
        row["results"][sid] = {
            "net_pnl": round(_f(trade.get("net_pnl")), 2),
            "r_multiple": round(_f(trade.get("r_multiple")), 2),
            "exit_reason": trade.get("exit_reason"),
        }

    rows = []
    for row in grouped.values():
        eligible = []
        for trade in trades:
            ctx2 = _context(trade.get("entry_context"))
            if str(ctx2.get("cohort_id") or "") == str(row["cohort_id"]):
                eligible = list(ctx2.get("eligible_case_ids") or [])
                if eligible:
                    break
        row["eligible_case_ids"] = eligible
        row["complete"] = bool(eligible) and all(sid in row["results"] for sid in eligible)
        row["total_net_pnl"] = round(
            sum(_f(x.get("net_pnl")) for x in row["results"].values()),
            2,
        )
        if row["results"]:
            row["best_strategy"] = max(
                row["results"],
                key=lambda sid: _f(row["results"][sid].get("net_pnl")),
            )
            row["worst_strategy"] = min(
                row["results"],
                key=lambda sid: _f(row["results"][sid].get("net_pnl")),
            )
        rows.append(row)
    return rows


def _news_events_for_day(start: datetime, end: datetime) -> list[dict[str, Any]]:
    events = recent_news_guardian_events(200)
    return [
        x
        for x in events
        if (_dt(x.get("created_at")) or start) >= start
        and (_dt(x.get("created_at")) or end) < end
    ]


def _commentary(
    daily: list[dict[str, Any]],
    cumulative: dict[str, Any],
    news_events: list[dict[str, Any]],
) -> list[str]:
    comments: list[str] = []
    active = [x for x in daily if x["trades"] > 0]
    if active:
        pnl_leader = max(active, key=lambda x: x["net_pnl"])
        wr_leader = max(active, key=lambda x: x["win_rate_pct"])
        exp_leader = max(active, key=lambda x: x["expectancy_r"])
        comments.append(
            f"Hôm nay {pnl_leader['name']} dẫn Net PnL với {pnl_leader['net_pnl']:+.2f} USDT."
        )
        comments.append(
            f"{wr_leader['name']} có Win Rate cao nhất ({wr_leader['win_rate_pct']:.1f}%), "
            f"trong khi {exp_leader['name']} có expectancy tốt nhất ({exp_leader['expectancy_r']:+.3f}R/trade)."
        )

    factors = cumulative.get("factors") or {}
    direction = factors.get("direction_effect") or {}
    rr = factors.get("rr_effect") or {}
    comments.append(
        f"Dữ liệu tích lũy hiện nghiêng về hướng {direction.get('leader', 'TIE')} "
        f"(Base {direction.get('base_net_pnl', 0):+.2f} vs Reverse {direction.get('reverse_net_pnl', 0):+.2f} USDT)."
    )
    comments.append(
        f"So sánh R:R tích lũy hiện nghiêng về {rr.get('leader', 'TIE')} "
        f"(1:2 {rr.get('rr2_net_pnl', 0):+.2f} vs 1:1 {rr.get('rr1_net_pnl', 0):+.2f} USDT)."
    )

    if not cumulative.get("sample_ready"):
        comments.append(
            f"Chưa đủ mẫu tối thiểu: case ít nhất mới có {cumulative.get('min_closed_per_case', 0)} "
            "lệnh đóng. Chưa nên chọn chiến lược thắng cuối cùng."
        )
    else:
        comments.append(
            "Mỗi case đã đạt ngưỡng mẫu tối thiểu 30 lệnh; vẫn nên ưu tiên 50-100 lệnh/case trước khi promote chiến lược."
        )

    if news_events:
        locks = sum(x.get("status") == "EVENT_LOCK" for x in news_events)
        correct = sum(x.get("prediction_result") == "CORRECT" for x in news_events)
        wrong = sum(x.get("prediction_result") == "WRONG" for x in news_events)
        comments.append(
            f"News Guardian ghi nhận {len(news_events)} event hôm nay, gồm {locks} EVENT_LOCK; "
            f"prediction đã chấm: {correct} đúng / {wrong} sai."
        )
    return comments


def _research_findings(
    daily_coins: list[dict[str, Any]],
    attribution: dict[str, Any],
    cumulative: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    if daily_coins:
        best = max(daily_coins, key=lambda x: _f(x.get("net_pnl")))
        worst = min(daily_coins, key=lambda x: _f(x.get("net_pnl")))
        findings.append(
            f"Coin tốt nhất hôm nay: {best['symbol']} {best['net_pnl']:+.2f} USDT "
            f"({best['expectancy_r']:+.3f}R/trade, {best['trades']} trades)."
        )
        findings.append(
            f"Coin gây lỗ lớn nhất hôm nay: {worst['symbol']} {worst['net_pnl']:+.2f} USDT "
            f"({worst['expectancy_r']:+.3f}R/trade, {worst['trades']} trades)."
        )

    counts = attribution.get("counts") or {}
    if counts:
        key = max(counts, key=counts.get)
        findings.append(
            f"Outcome attribution phổ biến nhất hôm nay: {key} ({counts[key]} trades)."
        )
        assisted = int(counts.get("NEWS_ASSISTED_WIN") or 0)
        shocks = int(counts.get("NEWS_SHOCK_LOSS") or 0)
        if assisted or shocks:
            findings.append(
                f"External-news attribution: {assisted} news-assisted win / {shocks} news-shock loss; "
                "không nên quy toàn bộ kết quả này cho entry thesis."
            )

    score_rows = cumulative.get("score_buckets") or []
    best_cell: tuple[float, str, str] | None = None
    worst_cell: tuple[float, str, str] | None = None
    for row in score_rows:
        for sid, stats in (row.get("strategies") or {}).items():
            if int(stats.get("trades") or 0) < 3:
                continue
            pnl = _f(stats.get("net_pnl"))
            item = (pnl, str(row.get("bucket")), str(sid))
            if best_cell is None or pnl > best_cell[0]:
                best_cell = item
            if worst_cell is None or pnl < worst_cell[0]:
                worst_cell = item
    if best_cell:
        findings.append(
            f"Score segment mạnh nhất hiện tại theo PnL: {best_cell[1]} / "
            f"{_strategy_label(best_cell[2])} ({best_cell[0]:+.2f} USDT)."
        )
    if worst_cell:
        findings.append(
            f"Score segment yếu nhất hiện tại theo PnL: {worst_cell[1]} / "
            f"{_strategy_label(worst_cell[2])} ({worst_cell[0]:+.2f} USDT)."
        )

    regime_rows = cumulative.get("regimes") or []
    regime_best: tuple[float, str, str] | None = None
    for row in regime_rows:
        for sid, stats in (row.get("strategies") or {}).items():
            if int(stats.get("trades") or 0) < 3:
                continue
            pnl = _f(stats.get("net_pnl"))
            item = (pnl, str(row.get("regime")), str(sid))
            if regime_best is None or pnl > regime_best[0]:
                regime_best = item
    if regime_best:
        findings.append(
            f"Regime/case mạnh nhất hiện tại: BTC {regime_best[1]} / "
            f"{_strategy_label(regime_best[2])} ({regime_best[0]:+.2f} USDT)."
        )
    return findings


def build_battle_daily_report(day: str) -> dict[str, Any]:
    start, end = _local_day_bounds(day)
    summaries: list[dict[str, Any]] = []
    all_daily_trades: list[dict[str, Any]] = []

    cases = list_strategy_cases(include_archived=False)
    strategy_ids = [str(x["strategy_id"]) for x in cases]
    for strategy_id in strategy_ids:
        trades = battle_trades_between(
            start.isoformat(),
            end.isoformat(),
            strategy_id,
        )
        all_daily_trades.extend(trades)
        summary = _strategy_summary(strategy_id, trades)
        summary["cumulative_closed"] = len(battle_recent_trades(5000, strategy_id))
        summaries.append(summary)

    active = [x for x in summaries if x["trades"] > 0]
    cumulative = build_strategy_battle_dashboard()
    cohorts = _daily_cohorts(all_daily_trades)
    complete = [x for x in cohorts if x["complete"]]
    best_cohorts = sorted(complete, key=lambda x: x["total_net_pnl"], reverse=True)[:5]
    worst_cohorts = sorted(complete, key=lambda x: x["total_net_pnl"])[:5]
    news_events = _news_events_for_day(start, end)
    scan = latest_scan() or {}
    guardian = get_system_state("news_guardian", {}) or {}

    daily_coins = coin_performance_summary(all_daily_trades)
    cumulative_trades = battle_recent_trades(5000)
    cumulative_coins = coin_performance_summary(cumulative_trades)
    trade_attribution = daily_trade_attribution(all_daily_trades)

    news_accuracy = {
        "events": len(news_events),
        "event_locks": sum(x.get("status") == "EVENT_LOCK" for x in news_events),
        "directional_warnings": sum(x.get("status") == "DIRECTIONAL_WARNING" for x in news_events),
        "cautions": sum(x.get("status") == "CAUTION" for x in news_events),
        "correct": sum(x.get("prediction_result") == "CORRECT" for x in news_events),
        "wrong": sum(x.get("prediction_result") == "WRONG" for x in news_events),
        "mixed": sum(x.get("prediction_result") == "MIXED" for x in news_events),
    }

    report = {
        "report_type": "DAILY_INTELLIGENCE_V432",
        "report_date": day,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "market": {
            "btc_regime": scan.get("btc_regime", "UNKNOWN"),
            "symbols_scanned": scan.get("symbols_scanned", 0),
            "news_guardian": guardian,
        },
        "strategies": summaries,
        "winner_by_net_pnl": max(active, key=lambda x: x["net_pnl"])["strategy_id"] if active else None,
        "winner_by_win_rate": max(active, key=lambda x: x["win_rate_pct"])["strategy_id"] if active else None,
        "winner_by_expectancy": max(active, key=lambda x: x["expectancy_r"])["strategy_id"] if active else None,
        "cumulative": {
            "leader_net_pnl": cumulative.get("leader_net_pnl"),
            "leader_win_rate": cumulative.get("leader_win_rate"),
            "leader_expectancy": cumulative.get("leader_expectancy"),
            "leader_profit_factor": cumulative.get("leader_profit_factor"),
            "leader_low_drawdown": cumulative.get("leader_low_drawdown"),
            "min_closed_per_case": cumulative.get("min_closed_per_case"),
            "sample_ready": cumulative.get("sample_ready"),
            "factors": cumulative.get("factors"),
            "score_buckets": cumulative.get("score_buckets"),
            "regimes": cumulative.get("regimes"),
        },
        "sample_ready": cumulative.get("sample_ready", False),
        "min_closed_per_case": cumulative.get("min_closed_per_case", 0),
        "recommended_min_sample": cumulative.get("recommended_comparison_sample", 30),
        "preferred_sample": cumulative.get("preferred_comparison_sample", 50),
        "cohorts": {
            "count": len(cohorts),
            "complete": len(complete),
            "best": best_cohorts,
            "worst": worst_cohorts,
        },
        "news_guardian": {
            "summary": news_accuracy,
            "events": news_events,
        },
        "strategy_evaluation": strategy_evaluation_overview(),
        "coin_analysis": {
            "daily": daily_coins,
            "cumulative_best": cumulative_coins[:10],
            "cumulative_worst": list(reversed(cumulative_coins[-10:])) if cumulative_coins else [],
        },
        "trade_attribution": trade_attribution,
    }
    report["research_findings"] = _research_findings(
        daily_coins,
        trade_attribution,
        cumulative,
    )
    report["ai_commentary"] = _commentary(
        summaries,
        cumulative,
        news_events,
    )
    return report


def _strategy_label(strategy_id: str | None) -> str:
    if not strategy_id:
        return "N/A"
    case = get_strategy_case(strategy_id)
    return str(case.get("name") if case else STRATEGIES.get(strategy_id, {}).get("name", strategy_id))


def render_battle_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Daily Strategy Intelligence Report - {report['report_date']}",
        "",
        "## Executive Summary",
        "",
        f"- BTC regime: **{report.get('market', {}).get('btc_regime', 'UNKNOWN')}**",
        f"- News Guardian: **{report.get('market', {}).get('news_guardian', {}).get('mode', 'NORMAL')}**",
        f"- Daily Net PnL leader: **{_strategy_label(report.get('winner_by_net_pnl'))}**",
        f"- Daily Win Rate leader: **{_strategy_label(report.get('winner_by_win_rate'))}**",
        f"- Daily Expectancy leader: **{_strategy_label(report.get('winner_by_expectancy'))}**",
        f"- Minimum cumulative closed trades/case: **{report.get('min_closed_per_case', 0)}**",
        "",
        "## Dynamic Strategy Case Daily Comparison",
        "",
        "| Case | Trades | W/L | WR | Net PnL | PF | Expectancy | Avg Win R | Avg Loss R | Max DD | Balance |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in report["strategies"]:
        lines.append(
            f"| {s['name']} | {s['trades']} | {s['wins']}/{s['losses']} | "
            f"{s['win_rate_pct']:.1f}% | {s['net_pnl']:+.2f} | {s['profit_factor']} | "
            f"{s['expectancy_r']:+.3f}R | {s['avg_win_r']:+.3f}R | {s['avg_loss_r']:+.3f}R | "
            f"{s['max_drawdown_usdt']:.2f} | {s['paper_balance']:.2f} |"
        )

    factors = report.get("cumulative", {}).get("factors") or {}
    de = factors.get("direction_effect") or {}
    re = factors.get("rr_effect") or {}
    case_ids = [str(s["strategy_id"]) for s in report.get("strategies", [])]
    case_labels = [_strategy_label(sid) for sid in case_ids]
    matrix_header = "| Segment | " + " | ".join(case_labels) + " |"
    matrix_sep = "|---|" + "|".join("---" for _ in case_ids) + "|"

    lines += [
        "",
        "## Factor Analysis - Cumulative",
        "",
        f"- Direction: **{de.get('leader', 'TIE')}** | Base {de.get('base_net_pnl', 0):+.2f} USDT vs Reverse {de.get('reverse_net_pnl', 0):+.2f} USDT",
        f"- R:R: **{re.get('leader', 'TIE')}** | 1:2 {re.get('rr2_net_pnl', 0):+.2f} USDT vs 1:1 {re.get('rr1_net_pnl', 0):+.2f} USDT",
        "",
        "## Score Bucket Performance - Cumulative",
        "",
        matrix_header,
        matrix_sep,
    ]
    for row in report.get("cumulative", {}).get("score_buckets", []) or []:
        cells = []
        for sid in case_ids:
            s = (row.get("strategies") or {}).get(sid, {})
            cells.append(
                f"{s.get('trades', 0)} trades / WR {_f(s.get('win_rate')):.1f}% / "
                f"PnL {_f(s.get('net_pnl')):+.2f}"
            )
        lines.append(f"| {row.get('bucket')} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## BTC Regime Performance - Cumulative",
        "",
        matrix_header,
        matrix_sep,
    ]
    for row in report.get("cumulative", {}).get("regimes", []) or []:
        cells = []
        for sid in case_ids:
            s = (row.get("strategies") or {}).get(sid, {})
            cells.append(
                f"{s.get('trades', 0)} trades / WR {_f(s.get('win_rate')):.1f}% / "
                f"PnL {_f(s.get('net_pnl')):+.2f}"
            )
        lines.append(f"| {row.get('regime')} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Coin Performance - Today",
        "",
        "| Coin | Trades | W/L | WR | Net PnL | Expectancy | PF | Best Case |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for coin in report.get("coin_analysis", {}).get("daily", []) or []:
        lines.append(
            f"| {coin['symbol']} | {coin['trades']} | {coin['wins']}/{coin['losses']} | "
            f"{coin['win_rate']:.1f}% | {coin['net_pnl']:+.2f} | {coin['expectancy_r']:+.3f}R | "
            f"{coin['profit_factor']} | {_strategy_label(coin.get('best_case'))} |"
        )

    lines += ["", "## Trade Outcome Attribution", ""]
    ta = report.get("trade_attribution", {})
    for key, count in sorted((ta.get("counts") or {}).items(), key=lambda x: (-x[1], x[0])):
        pnl = _f((ta.get("pnl_by_class") or {}).get(key))
        lines.append(f"- **{key}**: {count} trades | PnL {pnl:+.2f} USDT")

    lines += ["", "## Research Findings", ""]
    lines += [f"- {x}" for x in report.get("research_findings", [])]

    evaluation = report.get("strategy_evaluation", {}).get("strategies", []) or []
    lines += [
        "",
        "## Strategy Research Readiness",
        "",
        "| Case | Status | Score | N | EV | PF | WR / BE WR | Max DD | Win MAE P90 | Loser MFE Median |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ev in evaluation:
        ex = ev.get("exit_research") or {}
        lines.append(
            f"| {ev.get('name')} v{ev.get('version')} | {ev.get('status')} | "
            f"{_f(ev.get('readiness_score')):.0f}/100 | {int(ev.get('closed_trades') or 0)} | "
            f"{_f(ev.get('expectancy_r')):+.3f}R | {_f(ev.get('profit_factor')):.2f} | "
            f"{_f(ev.get('win_rate')):.1f}% / {_f(ev.get('break_even_win_rate')):.1f}% | "
            f"{_f(ev.get('max_drawdown_pct')):.2f}% | "
            f"{_f(ex.get('winning_trade_mae_p90_r')):.2f}R | "
            f"{_f(ex.get('losing_trade_mfe_median_r')):.2f}R |"
        )

    lines += [
        "",
        "## AI Commentary",
        "",
    ]
    lines += [f"- {x}" for x in report.get("ai_commentary", [])]

    lines += ["", "## News Guardian", ""]
    ns = report.get("news_guardian", {}).get("summary", {})
    lines.append(
        f"- Events: {ns.get('events', 0)} | EVENT_LOCK: {ns.get('event_locks', 0)} | "
        f"Directional: {ns.get('directional_warnings', 0)} | Correct/Wrong: "
        f"{ns.get('correct', 0)}/{ns.get('wrong', 0)}"
    )
    for ev in report.get("news_guardian", {}).get("events", [])[:12]:
        r1 = (ev.get("reactions") or {}).get("1h") or {}
        lines.append(
            f"- [{ev.get('status')}] {ev.get('headline')} | Impact {ev.get('impact_score')} | "
            f"{ev.get('direction')} {ev.get('confidence')}% | 1h {r1.get('change_pct', 'N/A')}% | "
            f"{ev.get('prediction_result')}"
        )

    lines += ["", "## Best Cohorts", ""]
    for row in report.get("cohorts", {}).get("best", []):
        lines.append(
            f"- {row['symbol']} score {row['score']:.1f} {row.get('source_side')} | "
            f"Best {_strategy_label(row.get('best_strategy'))} | combined diagnostic PnL {row['total_net_pnl']:+.2f}"
        )
    lines += ["", "## Worst Cohorts", ""]
    for row in report.get("cohorts", {}).get("worst", []):
        lines.append(
            f"- {row['symbol']} score {row['score']:.1f} {row.get('source_side')} | "
            f"Worst {_strategy_label(row.get('worst_strategy'))} | combined diagnostic PnL {row['total_net_pnl']:+.2f}"
        )

    attribution_by_trade = {
        int(x.get("trade_id")): x
        for x in report.get("trade_attribution", {}).get("details", []) or []
        if x.get("trade_id") is not None
    }
    lines += ["", "## Trade Details", ""]
    for s in report["strategies"]:
        lines += ["", f"### {s['name']}"]
        if not s["trade_details"]:
            lines.append("- No closed trades.")
            continue
        for t in s["trade_details"]:
            attr = attribution_by_trade.get(int(t["trade_id"]), {})
            lines.append(
                f"- #{t['trade_id']} {t['symbol']} {t['side']} | score {t['score']} | "
                f"{t['exit_reason']} | {t['net_pnl']:+.2f} USDT ({t['r_multiple']:+.2f}R) | "
                f"Entry {t['entry_price']:.8g} | SL {t['stop_loss']:.8g} | TP {t['take_profit']:.8g} | "
                f"Exit {t['exit_price']:.8g} | MFE {t.get('mfe_r',0):+.2f}R / MAE {t.get('mae_r',0):.2f}R | "
                f"hold {t['holding_minutes']:.0f}m | BTC {t.get('btc_regime') or 'N/A'} | "
                f"Attribution {attr.get('classification', 'N/A')} | "
                f"Thesis {(t.get('entry_thesis') or {}).get('primary_reason') or t.get('reason_text') or 'N/A'}"
            )

    lines += [
        "",
        "> Paper experiment only. Win rate is not sufficient to choose a winner; prioritize Net PnL, Profit Factor, Expectancy and Drawdown with an adequate sample.",
        "",
    ]
    return "\n".join(lines)


def render_battle_html(report: dict[str, Any]) -> str:
    def e(x: Any) -> str:
        return html.escape(str(x if x is not None else ""))

    rows = "".join(
        f"""<tr>
        <td><b>{e(s['name'])}</b></td><td>{s['trades']}</td><td>{s['wins']}/{s['losses']}</td>
        <td>{s['win_rate_pct']:.1f}%</td><td class="{'pos' if s['net_pnl'] >= 0 else 'neg'}">{s['net_pnl']:+.2f}</td>
        <td>{s['profit_factor']}</td><td>{s['expectancy_r']:+.3f}R</td>
        <td>{s['avg_win_r']:+.3f}R</td><td>{s['avg_loss_r']:+.3f}R</td>
        <td>{s['max_drawdown_usdt']:.2f}</td><td>{s['paper_balance']:.2f}</td>
        </tr>"""
        for s in report["strategies"]
    )
    comments = "".join(f"<li>{e(x)}</li>" for x in report.get("ai_commentary", []))
    news_rows = "".join(
        f"""<tr><td>{e(ev.get('status'))}</td><td>{e(ev.get('headline'))}</td>
        <td>{e(ev.get('impact_score'))}</td><td>{e(ev.get('direction'))}</td>
        <td>{e(ev.get('confidence'))}%</td><td>{e(((ev.get('reactions') or {}).get('1h') or {}).get('change_pct','N/A'))}</td>
        <td>{e(ev.get('prediction_result'))}</td></tr>"""
        for ev in report.get("news_guardian", {}).get("events", [])[:20]
    )
    best = "".join(
        f"<li><b>{e(x['symbol'])}</b> score {x['score']:.1f} - best {e(_strategy_label(x.get('best_strategy')))} - {x['total_net_pnl']:+.2f}</li>"
        for x in report.get("cohorts", {}).get("best", [])
    )
    worst = "".join(
        f"<li><b>{e(x['symbol'])}</b> score {x['score']:.1f} - worst {e(_strategy_label(x.get('worst_strategy')))} - {x['total_net_pnl']:+.2f}</li>"
        for x in report.get("cohorts", {}).get("worst", [])
    )
    ns = report.get("news_guardian", {}).get("summary", {})

    coin_rows = "".join(
        f"""<tr><td><b>{e(x.get('symbol'))}</b></td><td>{int(x.get('trades') or 0)}</td>
        <td>{_f(x.get('win_rate')):.1f}%</td>
        <td class="{'pos' if _f(x.get('net_pnl')) >= 0 else 'neg'}">{_f(x.get('net_pnl')):+.2f}</td>
        <td>{_f(x.get('expectancy_r')):+.3f}R</td><td>{_f(x.get('profit_factor')):.2f}</td>
        <td>{e(_strategy_label(x.get('best_case')))}</td></tr>"""
        for x in report.get("coin_analysis", {}).get("daily", []) or []
    )
    attr_rows = "".join(
        f"""<tr><td><b>{e(key)}</b></td><td>{int(count)}</td>
        <td class="{'pos' if _f((report.get('trade_attribution',{}).get('pnl_by_class') or {}).get(key)) >= 0 else 'neg'}">
        {_f((report.get('trade_attribution',{}).get('pnl_by_class') or {}).get(key)):+.2f}</td></tr>"""
        for key, count in sorted(
            (report.get("trade_attribution", {}).get("counts") or {}).items(),
            key=lambda x: (-x[1], x[0]),
        )
    )
    findings_html = "".join(
        f"<li>{e(x)}</li>" for x in report.get("research_findings", []) or []
    )
    readiness_rows = "".join(
        f"""<tr><td><b>{e(ev.get('name'))} v{e(ev.get('version'))}</b></td>
        <td>{e(ev.get('status'))}</td><td>{_f(ev.get('readiness_score')):.0f}/100</td>
        <td>{int(ev.get('closed_trades') or 0)}</td><td>{_f(ev.get('expectancy_r')):+.3f}R</td>
        <td>{_f(ev.get('profit_factor')):.2f}</td>
        <td>{_f(ev.get('win_rate')):.1f}% / {_f(ev.get('break_even_win_rate')):.1f}%</td>
        <td>{_f(ev.get('max_drawdown_pct')):.2f}%</td>
        <td>{_f((ev.get('exit_research') or {}).get('winning_trade_mae_p90_r')):.2f}R</td>
        <td>{_f((ev.get('exit_research') or {}).get('losing_trade_mfe_median_r')):.2f}R</td></tr>"""
        for ev in report.get("strategy_evaluation", {}).get("strategies", []) or []
    )
    attribution_by_trade = {
        int(x.get("trade_id")): x
        for x in report.get("trade_attribution", {}).get("details", []) or []
        if x.get("trade_id") is not None
    }
    trade_rows_html_parts: list[str] = []
    for strategy in report.get("strategies", []):
        for t in strategy.get("trade_details", []) or []:
            attr = attribution_by_trade.get(int(t.get("trade_id") or 0), {})
            thesis = (t.get("entry_thesis") or {}).get("primary_reason") or t.get("reason_text") or ""
            trade_rows_html_parts.append(
                f"""<tr><td>#{int(t.get('trade_id') or 0)}</td><td>{e(strategy.get('name'))}</td>
                <td><b>{e(t.get('symbol'))}</b></td><td>{e(t.get('side'))}</td>
                <td>{e(t.get('opened_at'))}<br>{e(t.get('closed_at'))}</td>
                <td>{_f(t.get('entry_price')):.8g}</td><td>{_f(t.get('stop_loss')):.8g}</td>
                <td>{_f(t.get('take_profit')):.8g}</td><td>{_f(t.get('exit_price')):.8g}</td>
                <td>{e(t.get('exit_reason'))}</td>
                <td class="{'pos' if _f(t.get('net_pnl')) >= 0 else 'neg'}">{_f(t.get('net_pnl')):+.2f}</td>
                <td>{_f(t.get('r_multiple')):+.2f}R</td><td>{_f(t.get('mfe_r')):.2f} / {_f(t.get('mae_r')):.2f}R</td>
                <td>{e(attr.get('classification','N/A'))}</td><td>{e(thesis)}</td></tr>"""
            )
    trade_rows_html = "".join(trade_rows_html_parts)


    report_case_ids = [str(s["strategy_id"]) for s in report.get("strategies", [])]
    report_case_headers = "".join(
        f"<th>{e(_strategy_label(sid))}</th>" for sid in report_case_ids
    )

    def matrix_rows(items: list[dict[str, Any]], label_key: str) -> str:
        out: list[str] = []
        for row in items or []:
            cells: list[str] = []
            for sid in report_case_ids:
                s = (row.get("strategies") or {}).get(sid, {})
                pnl = _f(s.get("net_pnl"))
                cells.append(
                    f"<td>{int(s.get('trades', 0))} trades<br>"
                    f"WR {_f(s.get('win_rate')):.1f}%<br>"
                    f"<span class=\"{'pos' if pnl >= 0 else 'neg'}\">{pnl:+.2f}</span></td>"
                )
            out.append(
                f"<tr><td><b>{e(row.get(label_key))}</b></td>{''.join(cells)}</tr>"
            )
        return "".join(out)

    score_rows = matrix_rows(
        report.get("cumulative", {}).get("score_buckets", []) or [],
        "bucket",
    )
    regime_rows = matrix_rows(
        report.get("cumulative", {}).get("regimes", []) or [],
        "regime",
    )

    return f"""<!doctype html><html><head><meta charset="utf-8">
    <title>Daily Strategy Intelligence Report {e(report['report_date'])}</title>
    <style>
    body{{font-family:Segoe UI,Arial,sans-serif;background:#f4f7fb;color:#142033;margin:0}}
    .wrap{{max-width:1250px;margin:auto;padding:28px}}h1{{margin:0 0 4px}}h2{{margin-top:28px}}
    .muted{{color:#65758b}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}}
    .card{{background:white;border:1px solid #dce4ef;border-radius:12px;padding:14px}}.k{{font-size:11px;color:#728198;text-transform:uppercase}}.v{{font-size:21px;font-weight:800;margin-top:5px}}
    table{{width:100%;border-collapse:collapse;background:white;border:1px solid #dce4ef}}th,td{{padding:9px;border-bottom:1px solid #e4eaf2;text-align:left;font-size:12px}}th{{background:#eef3f9}}
    .pos{{color:#087a45;font-weight:700}}.neg{{color:#b42318;font-weight:700}}.box{{background:white;border:1px solid #dce4ef;border-radius:12px;padding:16px}}
    @media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}}}
    </style></head><body><div class="wrap">
    <h1>Daily Strategy Intelligence Report</h1><div class="muted">{e(report['report_date'])} • V4.3.2 Coin Intelligence Platform</div>
    <div class="cards">
      <div class="card"><div class="k">BTC Regime</div><div class="v">{e(report.get('market',{}).get('btc_regime','UNKNOWN'))}</div></div>
      <div class="card"><div class="k">PnL Leader</div><div class="v">{e(_strategy_label(report.get('winner_by_net_pnl')))}</div></div>
      <div class="card"><div class="k">Expectancy Leader</div><div class="v">{e(_strategy_label(report.get('winner_by_expectancy')))}</div></div>
      <div class="card"><div class="k">Min Sample / Case</div><div class="v">{e(report.get('min_closed_per_case',0))}</div></div>
    </div>
    <h2>Dynamic Strategy Case Daily Comparison</h2>
    <table><tr><th>Case</th><th>Trades</th><th>W/L</th><th>WR</th><th>Net PnL</th><th>PF</th><th>Expectancy</th><th>Avg Win</th><th>Avg Loss</th><th>Max DD</th><th>Balance</th></tr>{rows}</table>
    <h2>Score Bucket Performance - Cumulative</h2>
    <table><tr><th>Score</th>{report_case_headers}</tr>{score_rows or f'<tr><td colspan="{max(2, len(report_case_ids)+1)}">No score data.</td></tr>'}</table>
    <h2>BTC Regime Performance - Cumulative</h2>
    <table><tr><th>Regime</th>{report_case_headers}</tr>{regime_rows or f'<tr><td colspan="{max(2, len(report_case_ids)+1)}">No regime data.</td></tr>'}</table>
    <h2>Coin Performance - Today</h2>
    <table><tr><th>Coin</th><th>Trades</th><th>WR</th><th>Net PnL</th><th>Expectancy</th><th>PF</th><th>Best Case</th></tr>{coin_rows or '<tr><td colspan="7">No closed coin trades today.</td></tr>'}</table>
    <h2>Trade Outcome Attribution</h2>
    <table><tr><th>Classification</th><th>Trades</th><th>PnL</th></tr>{attr_rows or '<tr><td colspan="3">No attribution data.</td></tr>'}</table>
    <h2>Research Findings</h2><div class="box"><ul>{findings_html or '<li>No strong finding yet.</li>'}</ul></div>
    <h2>Strategy Research Readiness</h2>
    <table><tr><th>Case</th><th>Status</th><th>Score</th><th>N</th><th>EV</th><th>PF</th><th>WR / BE</th><th>Max DD</th><th>Win MAE P90</th><th>Loser MFE Median</th></tr>{readiness_rows or '<tr><td colspan="10">No readiness data.</td></tr>'}</table>
    <h2>AI Commentary</h2><div class="box"><ul>{comments}</ul></div>
    <h2>News Guardian</h2><div class="muted">Events {ns.get('events',0)} • EVENT_LOCK {ns.get('event_locks',0)} • Correct/Wrong {ns.get('correct',0)}/{ns.get('wrong',0)}</div>
    <table><tr><th>Status</th><th>Event</th><th>Impact</th><th>Direction</th><th>Confidence</th><th>1h %</th><th>Result</th></tr>{news_rows or '<tr><td colspan="7">No News Guardian events today.</td></tr>'}</table>
    <h2>Best Cohorts</h2><div class="box"><ul>{best or '<li>No complete cohorts.</li>'}</ul></div>
    <h2>Worst Cohorts</h2><div class="box"><ul>{worst or '<li>No complete cohorts.</li>'}</ul></div>
    <h2>Detailed Closed Trades</h2>
    <table><tr><th>ID</th><th>Case</th><th>Coin</th><th>Side</th><th>Open / Close</th><th>Entry</th><th>SL</th><th>TP</th><th>Exit</th><th>Reason</th><th>PnL</th><th>R</th><th>MFE/MAE</th><th>Attribution</th><th>Entry Thesis</th></tr>{trade_rows_html or '<tr><td colspan="15">No closed trades today.</td></tr>'}</table>
    <p class="muted">Paper experiment only. Do not select a winner from win rate alone.</p>
    </div></body></html>"""


def generate_battle_and_save(day: str) -> dict[str, Any]:
    report = build_battle_daily_report(day)
    out_dir = Path(settings.reports_dir) / day
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "daily-report.md"
    html_path = out_dir / "daily-report.html"
    json_path = out_dir / "daily-report.json"
    md_path.write_text(render_battle_markdown(report), encoding="utf-8")
    html_path.write_text(render_battle_html(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["markdown_path"] = str(md_path)
    report["html_path"] = str(html_path)
    report["json_path"] = str(json_path)
    save_daily_report(day, report["created_at"], report, str(md_path))
    return report
