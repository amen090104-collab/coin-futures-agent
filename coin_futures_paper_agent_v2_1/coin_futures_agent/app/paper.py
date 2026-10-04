from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from .binance import BinanceClient
from .config import settings
from .review import analyze_loss
from .news import symbol_news_context
from .storage import (
    account_balance,
    add_account_event,
    close_position,
    has_open_symbol,
    insert_position,
    open_positions,
    trades_between,
    update_position_excursion,
)
from .strategy import build_trade_plan


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _apply_entry_slippage(price: float, side: str) -> float:
    s = settings.slippage_bps / 10_000
    return price * (1 + s if side == "LONG" else 1 - s)


def _apply_exit_slippage(price: float, side: str) -> float:
    s = settings.slippage_bps / 10_000
    return price * (1 - s if side == "LONG" else 1 + s)


def _today_utc_bounds(now: datetime) -> tuple[str, str]:
    tz = ZoneInfo(settings.timezone)
    local = now.astimezone(tz)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc).isoformat(), end_local.astimezone(timezone.utc).isoformat()


def _daily_realized_loss_pct(now: datetime) -> float:
    start, end = _today_utc_bounds(now)
    xs = trades_between(start, end)
    loss = -sum(min(0.0, float(t["net_pnl"])) for t in xs)
    bal = max(account_balance(), 1.0)
    return loss / bal * 100


async def open_candidates(scan: dict[str, Any], frames_by_symbol: dict[str, Any]) -> list[dict[str, Any]]:
    now = _utcnow()
    balance = account_balance()
    current = open_positions()
    if len(current) >= settings.max_open_trades:
        return []
    if _daily_realized_loss_pct(now) >= settings.max_daily_loss_pct:
        return [{"status": "PAUSED", "reason": "daily loss guard reached"}]

    ranked = [x for x in scan.get("all", []) if x.get("bias") in {"LONG", "SHORT"}]
    ranked.sort(key=lambda x: max(float(x["long_score"]), float(x["short_score"])), reverse=True)

    opened: list[dict[str, Any]] = []
    for row in ranked:
        if len(open_positions()) >= settings.max_open_trades:
            break
        if len(opened) >= settings.max_new_trades_per_scan:
            break
        if has_open_symbol(row["symbol"]):
            continue
        frame15 = frames_by_symbol.get(row["symbol"])
        if frame15 is None:
            continue
        plan = build_trade_plan(row, frame15, scan.get("btc_regime", "NEUTRAL"))
        if not plan:
            continue

        # Attach news research context to the entry rationale. News is informational in v2.1
        # and does not change the quantitative score or auto-block trades yet.
        news_ctx = symbol_news_context(row["symbol"], hours=24)
        plan.entry_context["news_context"] = news_ctx
        if news_ctx.get("articles", 0):
            plan.reason_text += (
                f"; News 24h: {news_ctx.get('bias')} {news_ctx.get('score', 0):+.1f} "
                f"({news_ctx.get('articles')} articles, {news_ctx.get('high_impact')} high-impact)"
            )

        risk_budget = balance * settings.risk_per_trade_pct / 100
        entry = _apply_entry_slippage(plan.entry, plan.side)
        # Recalculate risk after slippage.
        risk_per_unit = abs(entry - plan.stop_loss)
        if risk_per_unit <= 0:
            continue
        qty_by_risk = risk_budget / risk_per_unit
        max_notional = balance * settings.max_notional_pct_balance / 100 * settings.paper_leverage
        qty_by_notional = max_notional / entry
        qty = min(qty_by_risk, qty_by_notional)
        if qty <= 0:
            continue
        actual_risk = qty * risk_per_unit
        take_profit = entry + settings.reward_risk * risk_per_unit if plan.side == "LONG" else entry - settings.reward_risk * risk_per_unit

        rec = {
            **plan.as_dict(),
            "opened_at": now.isoformat(),
            "entry_price": entry,
            "take_profit": take_profit,
            "quantity": qty,
            "risk_usdt": actual_risk,
            "initial_risk_per_unit": risk_per_unit,
        }
        pid = insert_position(rec)
        opened.append({"position_id": pid, **rec})

    return opened


def _calc_pnl(side: str, entry: float, exit_price: float, qty: float) -> float:
    return (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty


async def monitor_positions() -> list[dict[str, Any]]:
    positions = open_positions()
    if not positions:
        return []

    client = BinanceClient()
    closed_events: list[dict[str, Any]] = []
    try:
        for p in positions:
            now = _utcnow()
            df = await client.klines(p["symbol"], "1m", 3)
            # Use last closed 1m candle for trigger checks.
            candle = df.iloc[-2]
            high = float(candle["high"])
            low = float(candle["low"])
            last = float(candle["close"])
            entry = float(p["entry_price"])
            stop = float(p["stop_loss"])
            tp = float(p["take_profit"])
            side = p["side"]

            favorable = float(p["max_favorable_price"])
            adverse = float(p["max_adverse_price"])
            if side == "LONG":
                favorable = max(favorable, high)
                adverse = min(adverse, low)
                hit_sl = low <= stop
                hit_tp = high >= tp
            else:
                favorable = min(favorable, low)
                adverse = max(adverse, high)
                hit_sl = high >= stop
                hit_tp = low <= tp

            update_position_excursion(p["id"], favorable, adverse, last, now.isoformat())

            opened_at = datetime.fromisoformat(p["opened_at"])
            age_hours = (now - opened_at).total_seconds() / 3600
            exit_reason = None
            raw_exit = None
            if hit_sl and hit_tp:
                # With 1m OHLC the intra-candle path is unknown. Conservative mode assumes SL first.
                if settings.conservative_same_candle:
                    exit_reason, raw_exit = "STOP_LOSS", stop
                else:
                    # Choose the level closer to the candle open as a rough path proxy.
                    o = float(candle["open"])
                    if abs(o - stop) <= abs(o - tp):
                        exit_reason, raw_exit = "STOP_LOSS", stop
                    else:
                        exit_reason, raw_exit = "TAKE_PROFIT", tp
            elif hit_sl:
                exit_reason, raw_exit = "STOP_LOSS", stop
            elif hit_tp:
                exit_reason, raw_exit = "TAKE_PROFIT", tp
            elif age_hours >= settings.max_hold_hours:
                exit_reason, raw_exit = "TIME_EXIT", last

            if exit_reason is None:
                continue

            exit_price = _apply_exit_slippage(float(raw_exit), side)
            qty = float(p["quantity"])
            gross = _calc_pnl(side, entry, exit_price, qty)
            fees = (entry * qty + exit_price * qty) * settings.taker_fee_bps / 10_000
            net = gross - fees
            initial_risk = float(p["initial_risk_per_unit"]) * qty
            r_mult = net / initial_risk if initial_risk > 0 else 0.0
            if side == "LONG":
                mfe_r = (favorable - entry) / float(p["initial_risk_per_unit"])
                mae_r = (entry - adverse) / float(p["initial_risk_per_unit"])
            else:
                mfe_r = (entry - favorable) / float(p["initial_risk_per_unit"])
                mae_r = (adverse - entry) / float(p["initial_risk_per_unit"])

            trade = {
                "symbol": p["symbol"],
                "side": side,
                "opened_at": p["opened_at"],
                "closed_at": now.isoformat(),
                "entry_price": entry,
                "exit_price": exit_price,
                "stop_loss": stop,
                "take_profit": tp,
                "quantity": qty,
                "score": float(p["score"]),
                "gross_pnl": round(gross, 6),
                "fees": round(fees, 6),
                "net_pnl": round(net, 6),
                "r_multiple": round(r_mult, 4),
                "exit_reason": exit_reason,
                "holding_minutes": round((now - opened_at).total_seconds() / 60, 1),
                "mfe_r": round(max(0.0, mfe_r), 3),
                "mae_r": round(max(0.0, mae_r), 3),
                "reason_text": p["reason_text"],
                "reason_codes": json.loads(p["reason_codes"]),
                "entry_context": json.loads(p["entry_context"]),
            }
            causes, fixes = analyze_loss(trade)
            trade["loss_analysis"] = causes
            trade["fix_suggestions"] = fixes
            tid = close_position(p["id"], now.isoformat(), trade)
            add_account_event(now.isoformat(), "TRADE_PNL", net, f"trade {tid} {p['symbol']} {side} {exit_reason}")
            closed_events.append({"trade_id": tid, **trade})
    finally:
        await client.close()
    return closed_events
