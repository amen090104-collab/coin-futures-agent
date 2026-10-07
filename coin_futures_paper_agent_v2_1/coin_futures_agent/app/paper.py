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
    close_position_atomic,
    has_open_symbol,
    insert_position,
    open_positions,
    trades_between,
    update_position_excursion,
)
from .strategy import build_trade_plan


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso_from_ms(value: int | float) -> str:
    return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat()


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


def execution_policy() -> dict[str, Any]:
    if settings.data_collection_mode:
        return {
            "max_open_trades": max(1, min(settings.collection_max_open_trades, settings.top_n_coins)),
            "max_new_trades_per_scan": None,
            "risk_per_trade_pct": settings.collection_risk_per_trade_pct,
            "enforce_daily_loss_guard": False,
        }
    return {
        "max_open_trades": settings.max_open_trades,
        "max_new_trades_per_scan": settings.max_new_trades_per_scan,
        "risk_per_trade_pct": settings.risk_per_trade_pct,
        "enforce_daily_loss_guard": True,
    }


async def open_candidates(scan: dict[str, Any], frames_by_symbol: dict[str, Any]) -> list[dict[str, Any]]:
    now = _utcnow()
    balance = account_balance()
    current = open_positions()

    policy = execution_policy()
    max_open_trades = policy["max_open_trades"]
    max_new_trades_per_scan = policy["max_new_trades_per_scan"]
    risk_per_trade_pct = policy["risk_per_trade_pct"]

    if len(current) >= max_open_trades:
        return []
    if policy["enforce_daily_loss_guard"] and _daily_realized_loss_pct(now) >= settings.max_daily_loss_pct:
        return [{"status": "PAUSED", "reason": "daily loss guard reached"}]

    ranked = [x for x in scan.get("all", []) if x.get("bias") in {"LONG", "SHORT"}]
    ranked.sort(key=lambda x: max(float(x["long_score"]), float(x["short_score"])), reverse=True)

    opened: list[dict[str, Any]] = []
    for row in ranked:
        if len(open_positions()) >= max_open_trades:
            break
        if max_new_trades_per_scan is not None and len(opened) >= max_new_trades_per_scan:
            break
        if has_open_symbol(row["symbol"]):
            continue
        frame15 = frames_by_symbol.get(row["symbol"])
        if frame15 is None:
            continue
        plan = build_trade_plan(row, frame15, scan.get("btc_regime", "NEUTRAL"))
        if not plan:
            continue

        news_ctx = symbol_news_context(row["symbol"], hours=24)
        plan.entry_context["news_context"] = news_ctx
        if news_ctx.get("articles", 0):
            plan.reason_text += (
                f"; News 24h: {news_ctx.get('bias')} {news_ctx.get('score', 0):+.1f} "
                f"({news_ctx.get('articles')} articles, {news_ctx.get('high_impact')} high-impact)"
            )

        risk_budget = balance * risk_per_trade_pct / 100
        entry = _apply_entry_slippage(plan.entry, plan.side)
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
        take_profit = (
            entry + settings.reward_risk * risk_per_unit
            if plan.side == "LONG"
            else entry - settings.reward_risk * risk_per_unit
        )

        plan.entry_context["data_collection_mode"] = settings.data_collection_mode
        plan.entry_context["risk_per_trade_pct_used"] = risk_per_trade_pct
        plan.entry_context["strategy_version"] = "4.0.0"

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


def evaluate_position_candle(
    position: dict[str, Any],
    candle: Any,
    favorable: float | None = None,
    adverse: float | None = None,
) -> dict[str, Any]:
    """Pure candle evaluation used by live monitoring and startup recovery."""
    entry = float(position["entry_price"])
    stop = float(position["stop_loss"])
    tp = float(position["take_profit"])
    side = position["side"]

    # V4.3 optional adaptive management. Legacy/default cases remain FIXED.
    try:
        entry_ctx = (
            position.get("entry_context")
            if isinstance(position.get("entry_context"), dict)
            else json.loads(position.get("entry_context") or "{}")
        )
    except Exception:
        entry_ctx = {}
    case_cfg = entry_ctx.get("case_config") or {}
    management_mode = str(case_cfg.get("management_mode") or "FIXED").upper()
    high = float(candle["high"])
    low = float(candle["low"])
    last = float(candle["close"])
    favorable = float(position["max_favorable_price"] if favorable is None else favorable)
    adverse = float(position["max_adverse_price"] if adverse is None else adverse)

    initial_risk = abs(entry - float(position["stop_loss"]))
    dynamic_stop = stop
    adaptive_reason = None

    if side == "LONG":
        favorable = max(favorable, high)
        adverse = min(adverse, low)
        mfe_r_now = (favorable - entry) / initial_risk if initial_risk > 0 else 0.0
        if management_mode == "BREAKEVEN_0_8R" and mfe_r_now >= 0.8:
            dynamic_stop = max(stop, entry)
            adaptive_reason = "BREAKEVEN_EXIT"
        elif management_mode == "TRAIL_AFTER_1R" and mfe_r_now >= 1.0:
            locked_r = max(0.25, mfe_r_now - 0.75)
            dynamic_stop = max(stop, entry + locked_r * initial_risk)
            adaptive_reason = "TRAILING_STOP"
        hit_sl = low <= dynamic_stop
        hit_tp = high >= tp
    else:
        favorable = min(favorable, low)
        adverse = max(adverse, high)
        mfe_r_now = (entry - favorable) / initial_risk if initial_risk > 0 else 0.0
        if management_mode == "BREAKEVEN_0_8R" and mfe_r_now >= 0.8:
            dynamic_stop = min(stop, entry)
            adaptive_reason = "BREAKEVEN_EXIT"
        elif management_mode == "TRAIL_AFTER_1R" and mfe_r_now >= 1.0:
            locked_r = max(0.25, mfe_r_now - 0.75)
            dynamic_stop = min(stop, entry - locked_r * initial_risk)
            adaptive_reason = "TRAILING_STOP"
        hit_sl = high >= dynamic_stop
        hit_tp = low <= tp

    exit_reason = None
    raw_exit = None
    if hit_sl and hit_tp:
        if settings.conservative_same_candle:
            exit_reason, raw_exit = adaptive_reason or "STOP_LOSS", dynamic_stop
        else:
            candle_open = float(candle["open"])
            if abs(candle_open - dynamic_stop) <= abs(candle_open - tp):
                exit_reason, raw_exit = adaptive_reason or "STOP_LOSS", dynamic_stop
            else:
                exit_reason, raw_exit = "TAKE_PROFIT", tp
    elif hit_sl:
        exit_reason, raw_exit = adaptive_reason or "STOP_LOSS", dynamic_stop
    elif hit_tp:
        exit_reason, raw_exit = "TAKE_PROFIT", tp

    closed_at = _iso_from_ms(candle["close_time"])
    if exit_reason is None:
        opened_at = _as_utc(position["opened_at"])
        age_hours = (_as_utc(closed_at) - opened_at).total_seconds() / 3600
        if age_hours >= settings.max_hold_hours:
            exit_reason, raw_exit = "TIME_EXIT", last

    return {
        "favorable": favorable,
        "adverse": adverse,
        "last": last,
        "closed_at": closed_at,
        "exit_reason": exit_reason,
        "raw_exit": raw_exit,
        "effective_stop": dynamic_stop,
        "management_mode": management_mode,
    }


def _build_closed_trade(
    position: dict[str, Any],
    closed_at: str,
    exit_reason: str,
    raw_exit: float,
    favorable: float,
    adverse: float,
) -> dict[str, Any]:
    side = position["side"]
    entry = float(position["entry_price"])
    qty = float(position["quantity"])
    exit_price = _apply_exit_slippage(float(raw_exit), side)
    gross = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty
    fees = (entry * qty + exit_price * qty) * settings.taker_fee_bps / 10_000
    net = gross - fees
    initial_risk_per_unit = float(position["initial_risk_per_unit"])
    initial_risk = initial_risk_per_unit * qty
    r_mult = net / initial_risk if initial_risk > 0 else 0.0
    if side == "LONG":
        mfe_r = (favorable - entry) / initial_risk_per_unit
        mae_r = (entry - adverse) / initial_risk_per_unit
    else:
        mfe_r = (entry - favorable) / initial_risk_per_unit
        mae_r = (adverse - entry) / initial_risk_per_unit

    opened_at = _as_utc(position["opened_at"])
    close_dt = _as_utc(closed_at)
    trade = {
        "symbol": position["symbol"],
        "side": side,
        "opened_at": position["opened_at"],
        "closed_at": closed_at,
        "entry_price": entry,
        "exit_price": exit_price,
        "stop_loss": float(position["stop_loss"]),
        "take_profit": float(position["take_profit"]),
        "quantity": qty,
        "score": float(position["score"]),
        "gross_pnl": round(gross, 6),
        "fees": round(fees, 6),
        "net_pnl": round(net, 6),
        "r_multiple": round(r_mult, 4),
        "exit_reason": exit_reason,
        "holding_minutes": round(max(0.0, (close_dt - opened_at).total_seconds() / 60), 1),
        "mfe_r": round(max(0.0, mfe_r), 3),
        "mae_r": round(max(0.0, mae_r), 3),
        "reason_text": position["reason_text"],
        "reason_codes": json.loads(position["reason_codes"]),
        "entry_context": json.loads(position["entry_context"]),
    }
    causes, fixes = analyze_loss(trade)
    trade["loss_analysis"] = causes
    trade["fix_suggestions"] = fixes
    return trade


def _persist_closed(position: dict[str, Any], evaluated: dict[str, Any], recovery: bool = False) -> dict[str, Any]:
    trade = _build_closed_trade(
        position,
        evaluated["closed_at"],
        str(evaluated["exit_reason"]),
        float(evaluated["raw_exit"]),
        float(evaluated["favorable"]),
        float(evaluated["adverse"]),
    )
    if recovery:
        trade["entry_context"]["recovered_after_offline"] = True
    trade_id = close_position_atomic(position["id"], trade["closed_at"], trade)
    return {"trade_id": trade_id, **trade}


async def monitor_positions() -> list[dict[str, Any]]:
    positions = open_positions()
    if not positions:
        return []

    client = BinanceClient()
    closed_events: list[dict[str, Any]] = []
    try:
        for position in positions:
            df = await client.klines(position["symbol"], "1m", 3)
            if len(df) < 2:
                continue
            candle = df.iloc[-2]
            evaluated = evaluate_position_candle(position, candle)
            update_position_excursion(
                position["id"],
                evaluated["favorable"],
                evaluated["adverse"],
                evaluated["last"],
                evaluated["closed_at"],
            )
            if evaluated["exit_reason"] is not None:
                closed_events.append(_persist_closed(position, evaluated))
    finally:
        await client.close()
    return closed_events


async def recover_open_positions() -> dict[str, Any]:
    """Replay missed 1m candles after an outage/restart and repair SL/TP/time exits."""
    positions = open_positions()
    summary: dict[str, Any] = {
        "positions_checked": len(positions),
        "positions_closed": 0,
        "candles_replayed": 0,
        "closed": [],
        "errors": [],
    }
    if not positions:
        return summary

    now = _utcnow()
    client = BinanceClient()
    try:
        for position in positions:
            try:
                opened = _as_utc(position["opened_at"])
                updated = _as_utc(position["updated_at"])
                start = max(opened, updated - timedelta(minutes=1))
                # There is no need to replay forever: after MAX_HOLD_HOURS the position
                # should have been closed by TIME_EXIT. Replay only through that deadline.
                deadline = opened + timedelta(hours=max(0.1, settings.max_hold_hours), minutes=2)
                replay_end = min(now, deadline)
                max_span_end = start + timedelta(hours=max(1, settings.recovery_max_hours))
                replay_end = min(replay_end, max_span_end)
                if replay_end < start:
                    replay_end = start
                end_ms = int(replay_end.timestamp() * 1000)
                df = await client.klines_1m_between(
                    position["symbol"],
                    int(start.timestamp() * 1000),
                    end_ms,
                )
                if df.empty:
                    continue

                favorable = float(position["max_favorable_price"])
                adverse = float(position["max_adverse_price"])
                last = float(position["last_price"])
                last_ts = position["updated_at"]

                for _, candle in df.iterrows():
                    if int(candle["close_time"]) > end_ms:
                        continue
                    evaluated = evaluate_position_candle(position, candle, favorable, adverse)
                    favorable = float(evaluated["favorable"])
                    adverse = float(evaluated["adverse"])
                    last = float(evaluated["last"])
                    last_ts = str(evaluated["closed_at"])
                    summary["candles_replayed"] += 1
                    if evaluated["exit_reason"] is not None:
                        event = _persist_closed(position, evaluated, recovery=True)
                        summary["closed"].append(event)
                        summary["positions_closed"] += 1
                        break
                else:
                    update_position_excursion(
                        position["id"], favorable, adverse, last, last_ts
                    )
            except Exception as exc:
                summary["errors"].append(
                    {"symbol": position.get("symbol"), "error": str(exc)[:500]}
                )
    finally:
        await client.close()
    return summary
