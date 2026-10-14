"""Live prospective Reverse Lab worker; only market-data reads and isolated DB.

Runs separately from Case C paper execution. No Binance API order endpoints.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .binance import BinanceClient
from .config import settings
from .reverse_execution import advance_reverse, CandleGap, TERMINAL
from .reverse_research import (
    active_reverse_cases, mark_censored, persist_reverse_case,
    register_reverse_signals, reverse_lab_snapshot,
)
from .storage import set_system_state

log=logging.getLogger(__name__)
MAX_RECOVERY_MINUTES=48*60


async def reverse_scan_job(scan: dict, opened: list[dict]) -> dict:
    if not (settings.reverse_lab_enabled and settings.v44_shadow_enabled
            and settings.strategy_battle_enabled):
        return {"status":"DISABLED","reason":"Reverse Lab needs V4.4 Shadow + Strategy Battle"}
    try:
        return register_reverse_signals(opened,scan)
    except Exception as exc:
        log.exception("Reverse Lab register failed; Paper Case C is unaffected")
        return {"status":"ERROR","reason":str(exc)[:250]}


async def monitor_reverse_lab(*, client: Any | None = None,
                              now_ms: int | None = None) -> dict:
    """One forward scan, with market-data client injection for acceptance tests."""
    if not (settings.reverse_lab_enabled and settings.v44_shadow_enabled
            and settings.strategy_battle_enabled):
        return {"status":"DISABLED"}
    owns_client=client is None
    if owns_client:
        client=BinanceClient()
    observed_ms=now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp()*1000)
    counters=defaultdict(int)
    grouped=defaultdict(list)
    try:
        for rec in active_reverse_cases():
            grouped[rec["symbol"]].append(rec)
        for symbol,cases in grouped.items():
            try:
                active=[]
                for p in cases:
                    if observed_ms-int(p["cursor_ms"])>MAX_RECOVERY_MINUTES*60000:
                        if mark_censored(p,"DATA_RECOVERY_WINDOW_EXCEEDED",observed_ms):
                            counters["censored"]+=1
                    else:
                        active.append(p)
                if not active:
                    continue
                oldest=min(int(p["cursor_ms"]) for p in active)
                bars=await client.klines_1m_between(symbol,oldest,observed_ms-1)
                if bars.empty:
                    counters["awaiting_market_bars"]+=len(active)
                    continue
                bars=bars.loc[
                    (bars["open_time"]>=oldest)&(bars["close_time"]<observed_ms)
                ].sort_values("open_time").drop_duplicates(subset=["open_time"])
                if bars.empty:
                    counters["awaiting_market_bars"]+=len(active)
                    continue
                candles=bars.to_dict("records")
                for original in active:
                    current=dict(original)
                    changed=False
                    cursor=int(current["cursor_ms"])
                    for candle in candles:
                        b_ms=int(candle["open_time"])
                        if b_ms<cursor:
                            continue
                        if b_ms>cursor:
                            if mark_censored(original,"MISSING_CLOSED_1M_BAR",observed_ms):
                                counters["censored"]+=1
                            changed=False
                            break
                        # This bar must have fully closed by observed_ms.
                        assert int(candle["close_time"])<observed_ms
                        try:
                            current=advance_reverse(current,candle,
                                  fee_bps=settings.taker_fee_bps,
                                  slippage_bps=settings.slippage_bps,
                                  max_hold_hours=settings.max_hold_hours)
                        except (ValueError,TypeError,CandleGap) as exc:
                            if mark_censored(original,"INVALID_FORWARD_BAR",observed_ms):
                                counters["censored"]+=1
                            log.warning("Reverse Lab invalid data %s %s: %s",
                                        symbol,original["variant"],exc)
                            changed=False
                            break
                        changed=True
                        cursor=int(current["cursor_ms"])
                        if current["status"] in TERMINAL:
                            break
                    if changed:
                        if persist_reverse_case(original,current):
                            counters["updated"]+=1
                            if original["status"]!="OPEN" and current["entered_at_ms"]:
                                counters["entries"]+=1
                            if current["status"]=="CLOSED":
                                counters["closed"]+=1
                            elif current["status"]=="EXPIRED":
                                counters["expired"]+=1
                        else:
                            counters["conflict"]+=1
            except Exception:
                log.exception("Reverse Lab cannot read %s; keep cases unresolved",symbol)
                counters["market_errors"]+=1
        result={
            "status":"SHADOW_ONLY","at":datetime.now(timezone.utc).isoformat(),
            "symbols":len(grouped),"open_cases":len(active_reverse_cases()),
            **dict(counters),
        }
        set_system_state("reverse_lab_monitor",result)
        # Analytics errors must never impact Paper or corrupt open state.
        try:
            snapshot=reverse_lab_snapshot(limit=20)
            set_system_state("reverse_lab_summary",{
                "cohorts":snapshot["cohorts"],"variants":snapshot["variants"],
                "paired_vs_control":snapshot["paired_vs_control"],
                "paired_case_c":snapshot["paired_case_c"],
                "generated_at":result["at"],
            })
        except Exception:
            log.exception("Reverse Lab snapshot refresh failed")
        return result
    finally:
        if owns_client:
            await client.close()
