from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from .battle_config import STRATEGIES, STRATEGY_IDS
from .battle_storage import (
    battle_account_balance,
    battle_trades_between,
)
from .config import settings
from .storage import save_daily_report


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
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _strategy_summary(strategy_id: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(t["net_pnl"]) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_profit = sum(max(0.0, x) for x in pnls)
    gross_loss = -sum(min(0.0, x) for x in pnls)
    r_values = [float(t["r_multiple"]) for t in trades]
    return {
        "strategy_id": strategy_id,
        **STRATEGIES[strategy_id],
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "net_pnl": round(sum(pnls), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "avg_r": round(mean(r_values), 3) if r_values else 0.0,
        "max_drawdown_usdt": round(_max_drawdown(pnls), 2),
        "paper_balance": round(battle_account_balance(strategy_id), 2),
        "trade_details": [
            {
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
            }
            for t in trades
        ],
    }


def build_battle_daily_report(day: str) -> dict[str, Any]:
    start, end = _local_day_bounds(day)
    summaries = []
    for strategy_id in STRATEGY_IDS:
        trades = battle_trades_between(start.isoformat(), end.isoformat(), strategy_id)
        summaries.append(_strategy_summary(strategy_id, trades))

    with_trades = [x for x in summaries if x["trades"] > 0]
    winner_pnl = max(with_trades, key=lambda x: x["net_pnl"])["strategy_id"] if with_trades else None
    winner_wr = max(with_trades, key=lambda x: x["win_rate_pct"])["strategy_id"] if with_trades else None
    min_sample = min((x["trades"] for x in summaries), default=0)

    return {
        "report_type": "STRATEGY_BATTLE",
        "report_date": day,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategies": summaries,
        "winner_by_net_pnl": winner_pnl,
        "winner_by_win_rate": winner_wr,
        "sample_ready": min_sample >= 30,
        "min_closed_per_case_today": min_sample,
        "recommended_min_sample": 30,
    }


def render_battle_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Daily Strategy Battle Report - {report['report_date']}",
        "",
        "## A/B/C comparison",
        "",
        "| Case | Trades | W/L | Win rate | Net PnL | PF | Avg R | Max DD | Balance |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in report["strategies"]:
        lines.append(
            f"| {s['name']} | {s['trades']} | {s['wins']}/{s['losses']} | "
            f"{s['win_rate_pct']}% | {s['net_pnl']} USDT | {s['profit_factor']} | "
            f"{s['avg_r']} | {s['max_drawdown_usdt']} | {s['paper_balance']} |"
        )

    lines += [
        "",
        f"- Highest daily Net PnL: {report['winner_by_net_pnl'] or 'N/A'}",
        f"- Highest daily Win rate: {report['winner_by_win_rate'] or 'N/A'}",
        "",
    ]
    if report["sample_ready"]:
        lines.append("Sample status: đủ tối thiểu 30 lệnh đóng/case trong ngày để bắt đầu xem xét so sánh.")
    else:
        lines.append(
            "Sample status: CHƯA ĐỦ MẪU. Không chọn winner chỉ từ vài lệnh; "
            "mục tiêu tối thiểu 30 lệnh đóng/case, tốt hơn là 50-100."
        )

    for s in report["strategies"]:
        lines += ["", f"## {s['name']}", s["description"]]
        if not s["trade_details"]:
            lines.append("- Không có lệnh đóng trong ngày.")
            continue
        for t in s["trade_details"]:
            lines.append(
                f"- #{t['trade_id']} {t['symbol']} {t['side']} | score {t['score']} | "
                f"Entry {t['entry_price']:.8g} / SL {t['stop_loss']:.8g} / TP {t['take_profit']:.8g} | "
                f"{t['exit_reason']} | {t['net_pnl']} USDT ({t['r_multiple']}R)"
            )

    lines += [
        "",
        "> Đây là paper experiment. Case thắng theo win rate chưa chắc thắng theo lợi nhuận; "
        "ưu tiên Net PnL, Profit Factor, Avg R và Drawdown khi chọn chiến lược.",
        "",
    ]
    return "\n".join(lines)


def generate_battle_and_save(day: str) -> dict[str, Any]:
    report = build_battle_daily_report(day)
    out_dir = Path(settings.reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}-strategy-battle.md"
    path.write_text(render_battle_markdown(report), encoding="utf-8")
    save_daily_report(day, report["created_at"], report, str(path))
    return report
