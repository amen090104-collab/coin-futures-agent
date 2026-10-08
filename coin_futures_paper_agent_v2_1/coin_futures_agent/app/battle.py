from __future__ import annotations
from .decision_journal import record_open, record_exit, record_stop_change, record_milestones

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .battle_config import STRATEGIES, STRATEGY_IDS
from .strategy_cases import active_strategy_cases, get_strategy_case, case_accepts_signal
from .battle_storage import (
    battle_account_balance,
    battle_has_open_symbol,
    battle_open_positions,
    battle_recent_trades,
    battle_trades_between,
    close_battle_position_atomic,
    insert_battle_positions_atomic,
    update_battle_position_excursion,
)
from .binance import BinanceClient
from .config import settings
from .news import symbol_news_context
from .news_guardian import news_entry_guard
from .paper import (
    _apply_entry_slippage,
    _as_utc,
    _build_closed_trade,
    _utcnow,
    evaluate_position_candle,
)
from .strategy import build_trade_plan


def battle_execution_policy() -> dict[str, Any]:
    if settings.data_collection_mode:
        return {
            "max_open_trades_per_strategy": max(
                1, min(settings.collection_max_open_trades, settings.top_n_coins)
            ),
            "max_new_trades_per_scan_per_strategy": None,
            "risk_per_trade_pct": settings.collection_risk_per_trade_pct,
            "enforce_daily_loss_guard": False,
        }
    return {
        "max_open_trades_per_strategy": settings.max_open_trades,
        "max_new_trades_per_scan_per_strategy": settings.max_new_trades_per_scan,
        "risk_per_trade_pct": settings.risk_per_trade_pct,
        "enforce_daily_loss_guard": True,
    }


def _today_bounds(now: datetime) -> tuple[str, str]:
    tz = ZoneInfo(settings.timezone)
    local = now.astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).isoformat(),
        end.astimezone(timezone.utc).isoformat(),
    )


def _daily_loss_pct(strategy_id: str, now: datetime) -> float:
    start, end = _today_bounds(now)
    trades = battle_trades_between(start, end, strategy_id)
    loss = -sum(min(0.0, float(t["net_pnl"])) for t in trades)
    balance = max(battle_account_balance(strategy_id), 1.0)
    return loss / balance * 100


def _case_name(strategy_id: str) -> str:
    case = get_strategy_case(strategy_id)
    if case:
        return str(case["name"])
    return str(STRATEGIES.get(strategy_id, {}).get("name") or strategy_id)


def _variant_geometry(plan: Any, case: dict[str, Any] | str) -> tuple[str, float, float, float]:
    if isinstance(case, str):
        legacy = STRATEGIES[case]
        spec = {
            "direction_mode": "REVERSE" if legacy["reverse"] else "BASE",
            "rr": legacy["rr"],
        }
    else:
        spec = case
    source_side = plan.side
    source_entry = float(plan.entry)
    source_stop = float(plan.stop_loss)
    source_risk = abs(source_entry - source_stop)
    reverse = str(spec.get("direction_mode") or "BASE").upper() == "REVERSE"

    if not reverse:
        side = source_side
        entry = _apply_entry_slippage(source_entry, side)
        stop = source_stop
    else:
        side = "SHORT" if source_side == "LONG" else "LONG"
        entry = _apply_entry_slippage(source_entry, side)
        stop = source_entry + source_risk if side == "SHORT" else source_entry - source_risk

    risk_per_unit = abs(entry - stop)
    rr = float(spec.get("rr") or 1.0)
    take_profit = (
        entry + rr * risk_per_unit
        if side == "LONG"
        else entry - rr * risk_per_unit
    )
    return side, entry, stop, take_profit


async def open_battle_candidates(
    scan: dict[str, Any],
    frames_by_symbol: dict[str, Any],
) -> list[dict[str, Any]]:
    now = _utcnow()
    policy = battle_execution_policy()
    cases = active_strategy_cases()
    if not cases:
        return []

    case_by_id = {str(x["strategy_id"]): x for x in cases}
    open_counts = {
        sid: len(battle_open_positions(sid))
        for sid in case_by_id
    }
    opened_counts = {sid: 0 for sid in case_by_id}
    paused = {
        sid: (
            bool(policy["enforce_daily_loss_guard"])
            and _daily_loss_pct(sid, now) >= settings.max_daily_loss_pct
        )
        for sid in case_by_id
    }

    ranked = [
        row for row in scan.get("all", [])
        if row.get("bias") in {"LONG", "SHORT"}
    ]
    ranked.sort(
        key=lambda row: max(
            float(row.get("long_score") or 0),
            float(row.get("short_score") or 0),
        ),
        reverse=True,
    )

    opened: list[dict[str, Any]] = []
    for row in ranked:
        symbol = str(row["symbol"])
        source_side = str(row.get("bias"))
        guard = news_entry_guard(symbol)
        if not guard.get("allowed", True):
            continue
        frame15 = frames_by_symbol.get(symbol)
        if frame15 is None:
            continue
        plan = build_trade_plan(row, frame15, scan.get("btc_regime", "NEUTRAL"))
        if not plan:
            continue

        eligible: list[dict[str, Any]] = []
        for case in cases:
            sid = str(case["strategy_id"])
            if paused.get(sid):
                continue
            max_open = int(case.get("max_open") or policy["max_open_trades_per_strategy"])
            if open_counts[sid] >= max_open:
                continue
            max_new = policy["max_new_trades_per_scan_per_strategy"]
            if max_new is not None and opened_counts[sid] >= int(max_new):
                continue
            if battle_has_open_symbol(sid, symbol):
                continue
            accepted, _ = case_accepts_signal(
                case,
                row,
                source_side,
                str(scan.get("btc_regime", "NEUTRAL")),
            )
            if accepted:
                eligible.append(case)

        if not eligible:
            continue

        news_ctx = symbol_news_context(symbol, hours=24)
        base_reason = plan.reason_text
        if news_ctx.get("articles", 0):
            base_reason += (
                f"; News 24h: {news_ctx.get('bias')} "
                f"{news_ctx.get('score', 0):+.1f} "
                f"({news_ctx.get('articles')} articles, "
                f"{news_ctx.get('high_impact')} high-impact)"
            )

        cohort_id = f"{now.isoformat()}::{symbol}"
        eligible_ids = [str(x["strategy_id"]) for x in eligible]
        cohort_records: list[dict[str, Any]] = []
        for case in eligible:
            strategy_id = str(case["strategy_id"])
            side, entry, stop, take_profit = _variant_geometry(plan, case)
            risk_per_unit = abs(entry - stop)
            balance = battle_account_balance(strategy_id)
            if risk_per_unit <= 0 or balance <= 0 or entry <= 0:
                continue

            risk_pct = float(
                case.get("risk_pct")
                if case.get("risk_pct") is not None
                else policy["risk_per_trade_pct"]
            )
            risk_budget = balance * risk_pct / 100
            qty_by_risk = risk_budget / risk_per_unit
            max_notional = (
                balance
                * settings.max_notional_pct_balance
                / 100
                * settings.paper_leverage
            )
            qty_by_notional = max_notional / entry
            qty = min(qty_by_risk, qty_by_notional)
            if qty <= 0:
                continue

            actual_risk = qty * risk_per_unit
            reverse = str(case.get("direction_mode") or "BASE") == "REVERSE"
            context = dict(plan.entry_context)
            context.update(
                {
                    "strategy_version": f"{strategy_id}-v{int(case.get('version') or 1)}",
                    "case_version": int(case.get("version") or 1),
                    "case_config": {
                        k: case.get(k)
                        for k in (
                            "direction_mode", "rr", "score_min", "score_max",
                            "allowed_regimes", "side_filter", "min_volume_ratio",
                            "min_oi_change_pct", "min_atr_pct", "max_atr_pct",
                            "risk_pct", "max_open", "news_policy", "entry_mode",
                            "exit_mode", "management_mode",
                        )
                    },
                    "cohort_id": cohort_id,
                    "eligible_case_ids": eligible_ids,
                    "strategy_id": strategy_id,
                    "strategy_name": case["name"],
                    "strategy_rr": case["rr"],
                    "strategy_reverse": reverse,
                    "source_signal_side": plan.side,
                    "source_signal_entry": float(plan.entry),
                    "source_signal_stop": float(plan.stop_loss),
                    "source_signal_take_profit": float(plan.take_profit),
                    "entry_thesis": {
                        "primary_reason": plan.reason_text,
                        "reason_codes": list(plan.reason_codes),
                        "expected_scenario": f"{plan.side} continuation after signal confirmation",
                        "known_risks": [
                            f"BTC regime {scan.get('btc_regime', 'NEUTRAL')}",
                            f"News bias {news_ctx.get('bias', 'NO_DATA')}",
                        ],
                    },
                    "news_context": news_ctx,
                    "data_collection_mode": settings.data_collection_mode,
                    "risk_per_trade_pct_used": risk_pct,
                }
            )

            reason_text = (
                f"{case['name']}; REVERSE TEST of source {plan.side}; source rationale: {base_reason}"
                if reverse
                else f"{case['name']}; {base_reason}"
            )

            cohort_records.append(
                {
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "side": side,
                    "opened_at": now.isoformat(),
                    "signal_price": float(plan.entry),
                    "entry_price": entry,
                    "stop_loss": stop,
                    "take_profit": take_profit,
                    "quantity": qty,
                    "risk_usdt": actual_risk,
                    "initial_risk_per_unit": risk_per_unit,
                    "score": float(plan.score),
                    "reason_text": reason_text,
                    "reason_codes": list(plan.reason_codes) + [strategy_id],
                    "entry_context": context,
                }
            )

        if not cohort_records:
            continue

        position_ids = insert_battle_positions_atomic(cohort_records)
        for rec, position_id in zip(cohort_records, position_ids):
            record_open(position_id, rec)
            strategy_id = rec["strategy_id"]
            opened.append(
                {
                    "position_id": position_id,
                    **rec,
                    "strategy_name": _case_name(strategy_id),
                }
            )
            open_counts[strategy_id] += 1
            opened_counts[strategy_id] += 1

    for strategy_id, is_paused in paused.items():
        if is_paused:
            opened.append(
                {
                    "status": "PAUSED",
                    "strategy_id": strategy_id,
                    "strategy_name": _case_name(strategy_id),
                    "reason": "daily loss guard reached",
                }
            )

    return opened


def _persist_battle_closed(
    position: dict[str, Any],
    evaluated: dict[str, Any],
    recovery: bool = False,
) -> dict[str, Any]:
    trade = _build_closed_trade(
        position,
        evaluated["closed_at"],
        str(evaluated["exit_reason"]),
        float(evaluated["raw_exit"]),
        float(evaluated["favorable"]),
        float(evaluated["adverse"]),
    )
    strategy_id = str(position["strategy_id"])
    trade["strategy_id"] = strategy_id
    trade["strategy_name"] = _case_name(strategy_id)
    if recovery:
        trade["entry_context"]["recovered_after_offline"] = True
    trade_id = close_battle_position_atomic(
        int(position["id"]),
        trade["closed_at"],
        trade,
    )
    record_exit(position, trade_id, trade)
    return {"trade_id": trade_id, **trade}


async def monitor_battle_positions() -> list[dict[str, Any]]:
    positions = battle_open_positions()
    if not positions:
        return []

    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position in positions:
        by_symbol[str(position["symbol"])].append(position)

    client = BinanceClient()
    closed_events: list[dict[str, Any]] = []
    try:
        for symbol, group in by_symbol.items():
            df = await client.klines(symbol, "1m", 3)
            if len(df) < 2:
                continue
            candle = df.iloc[-2]
            for position in group:
                evaluated = evaluate_position_candle(position, candle)
                record_stop_change(position, evaluated)
                record_milestones(position, evaluated)
                update_battle_position_excursion(
                    int(position["id"]),
                    float(evaluated["favorable"]),
                    float(evaluated["adverse"]),
                    float(evaluated["last"]),
                    str(evaluated["closed_at"]),
                )
                if evaluated["exit_reason"] is not None:
                    closed_events.append(
                        _persist_battle_closed(position, evaluated)
                    )
    finally:
        await client.close()

    return closed_events


async def close_battle_for_news(decision: dict[str, Any]) -> list[dict[str, Any]]:
    """Close all open cases affected by an EVENT_LOCK at current market prices."""
    if decision.get("mode") != "EVENT_LOCK":
        return []

    positions = battle_open_positions()
    if not positions:
        return []

    scope = str(decision.get("scope") or "MARKET")
    affected = {str(x).upper() for x in decision.get("symbols", [])}

    targets: list[dict[str, Any]] = []
    for position in positions:
        base = str(position["symbol"]).replace("USDT", "").upper()
        if scope == "MARKET" or base in affected:
            targets.append(position)
    if not targets:
        return []

    client = BinanceClient()
    closed: list[dict[str, Any]] = []
    try:
        marks = await client.mark_prices()
        closed_at = _utcnow().isoformat()
        for position in targets:
            symbol = str(position["symbol"])
            price = float(marks.get(symbol) or 0)
            if price <= 0:
                try:
                    price = await client.mark_price(symbol)
                except Exception:
                    price = float(position.get("last_price") or position["entry_price"])

            favorable = float(position["max_favorable_price"])
            adverse = float(position["max_adverse_price"])
            if position["side"] == "LONG":
                favorable = max(favorable, price)
                adverse = min(adverse, price)
            else:
                favorable = min(favorable, price)
                adverse = max(adverse, price)

            evaluated = {
                "favorable": favorable,
                "adverse": adverse,
                "last": price,
                "closed_at": closed_at,
                "exit_reason": "NEWS_RISK_EXIT",
                "raw_exit": price,
            }
            trade = _build_closed_trade(
                position,
                closed_at,
                "NEWS_RISK_EXIT",
                price,
                favorable,
                adverse,
            )
            strategy_id = str(position["strategy_id"])
            trade["strategy_id"] = strategy_id
            trade["strategy_name"] = _case_name(strategy_id)
            trade["entry_context"]["news_risk_exit"] = {
                "event_id": decision.get("event_id"),
                "event_key": decision.get("event_key"),
                "headline": decision.get("headline"),
                "scope": scope,
                "impact_score": decision.get("impact_score"),
                "direction": decision.get("direction"),
                "confidence": decision.get("confidence"),
                "cooldown_until": decision.get("cooldown_until"),
            }
            trade_id = close_battle_position_atomic(
                int(position["id"]),
                closed_at,
                trade,
            )
            record_exit(position, trade_id, trade)
            closed.append({"trade_id": trade_id, **trade})
    finally:
        await client.close()

    return closed


async def recover_battle_open_positions() -> dict[str, Any]:
    positions = battle_open_positions()
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
                deadline = opened + timedelta(
                    hours=max(0.1, settings.max_hold_hours),
                    minutes=2,
                )
                replay_end = min(now, deadline)
                replay_end = min(
                    replay_end,
                    start + timedelta(hours=max(1, settings.recovery_max_hours)),
                )
                if replay_end < start:
                    replay_end = start
                end_ms = int(replay_end.timestamp() * 1000)

                df = await client.klines_1m_between(
                    str(position["symbol"]),
                    int(start.timestamp() * 1000),
                    end_ms,
                )
                if df.empty:
                    continue

                favorable = float(position["max_favorable_price"])
                adverse = float(position["max_adverse_price"])
                last = float(position["last_price"])
                last_ts = str(position["updated_at"])

                for _, candle in df.iterrows():
                    if int(candle["close_time"]) > end_ms:
                        continue
                    evaluated = evaluate_position_candle(
                        position,
                        candle,
                        favorable,
                        adverse,
                    )
                    record_stop_change(position, evaluated)
                    record_milestones({**position, "max_favorable_price": favorable}, evaluated)
                    favorable = float(evaluated["favorable"])
                    adverse = float(evaluated["adverse"])
                    last = float(evaluated["last"])
                    last_ts = str(evaluated["closed_at"])
                    summary["candles_replayed"] += 1
                    if evaluated["exit_reason"] is not None:
                        event = _persist_battle_closed(
                            position,
                            evaluated,
                            recovery=True,
                        )
                        summary["closed"].append(event)
                        summary["positions_closed"] += 1
                        break
                else:
                    update_battle_position_excursion(
                        int(position["id"]),
                        favorable,
                        adverse,
                        last,
                        last_ts,
                    )
            except Exception as exc:
                summary["errors"].append(
                    {
                        "strategy_id": position.get("strategy_id"),
                        "symbol": position.get("symbol"),
                        "error": str(exc)[:500],
                    }
                )
    finally:
        await client.close()

    return summary


def battle_closed_count() -> dict[str, int]:
    return {
        str(case["strategy_id"]): len(battle_recent_trades(5000, str(case["strategy_id"])))
        for case in active_strategy_cases()
    }
