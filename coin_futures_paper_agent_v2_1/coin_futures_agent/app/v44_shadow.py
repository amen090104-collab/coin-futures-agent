"""V4.4 prospective Shadow runner: never mutates existing paper accounts.

Scanner snapshots are captured at a completed candle. Entry only uses the
first FUTURE 1m open after confirmation; exits are processed forward across
contiguous completed 1m candles. Per-candle trend state is as-of only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .binance import BinanceClient
from .config import settings
from .indicators import enrich
from .storage import get_system_state, latest_scan, recent_news, set_system_state
from .strategy import build_trade_plan
from .v44_learning import evaluate_live_hypotheses
from .v44_execution import advance_shadow, adverse_fill, valid_trade
from .v44_trend import (assess_trend, closed_frame, entry_risk_block,
                        market_context, select_entry)
from .v44_research import (active_pending, create_pending, log_decision,
                           open_shadow, open_shadows, record_event,
                           research_overview, update_pending, update_shadow, utcnow)

log = logging.getLogger(__name__)
MAX_SHADOW_OPEN = 80
MAX_REPLAY_MINUTES = 1440


def _iso_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def _known_news_at(asof: str) -> list[dict]:
    """Use news actually INGESTED by the Agent before the decision timestamp."""
    try:
        cutoff = _iso_ms(asof)
    except (ValueError, TypeError):
        return []
    items = []
    for article in recent_news(limit=250, hours=48):
        try:
            fetched = _iso_ms(str(article.get("fetched_at") or ""))
            published = _iso_ms(str(article.get("published_at") or ""))
        except (TypeError, ValueError):
            continue
        if fetched <= cutoff and published <= cutoff:
            items.append(article)
    return items


def _pending_for_symbol(symbol: str, method: str | None = None) -> bool:
    return any(p["method"] == method for p in active_pending(symbol)) if method else bool(active_pending(symbol))


def _collect_cohorts(scan: dict, frames: dict, opened: list[dict] | None = None):
    """Join real case cohorts by exact source entry_context from THIS scan.
    Unmatched opportunities receive a synthetic cohort and are labeled later.
    """
    source = {}
    for record in opened or []:
        ctx = record.get("entry_context") or {}
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except ValueError:
                continue
        if isinstance(ctx, dict) and ctx.get("cohort_id"):
            source[str(record.get("symbol"))] = str(ctx["cohort_id"])
    stamp = scan.get("created_at") or utcnow()
    results = []
    for row in scan.get("all") or []:
        symbol = str(row.get("symbol") or "")
        if row.get("bias") not in ("LONG", "SHORT") or symbol not in frames:
            continue
        score = float(row.get("long_score") if row["bias"] == "LONG" else row.get("short_score") or 0)
        if score < settings.score_threshold:
            continue
        cohort = source.get(symbol) or f"SHADOW::{stamp}::{symbol}"
        results.append((cohort, row, frames[symbol], bool(source.get(symbol))))
    return results[:max(1, int(settings.v44_shadow_scan_max))]


async def scan_shadow(scan: dict, frames_15m: dict, opened: list[dict] | None = None) -> dict:
    """No extra API calls. Runs AFTER paper processing, off the hot path."""
    if not settings.v44_shadow_enabled:
        return {"status": "DISABLED"}
    guardian_state=get_system_state("news_guardian",{}) or {}
    stamp=str(scan.get("created_at") or utcnow())
    if guardian_state.get("updated_at"):
        try:
            changed_after_scan=_iso_ms(str(guardian_state["updated_at"])) > _iso_ms(stamp)
        except (TypeError, ValueError):
            changed_after_scan=True
    else:
        changed_after_scan=False
    context = market_context(scan, {"state": {} if changed_after_scan else guardian_state},
                             articles=_known_news_at(stamp))
    if changed_after_scan:
        context["risk_state"]="RESTRICTED"
        context["reason_codes"].append("STATE_NEWER_THAN_SIGNAL")
    created = evaluated = blocked = hypothesis_checks = 0
    now = datetime.now(timezone.utc)
    for cohort, row, frame15, matched in _collect_cohorts(scan, frames_15m, opened):
        symbol = row["symbol"]
        try:
            trend = row.get("trend_v44") or {"data_quality": "INSUFFICIENT"}
            decision = select_entry(row, frame15, trend, context)
            snapshot = {"entry": decision, "trend": trend, "market": context,
                        "source_row": row, "source_cohort_matched": matched}
            log_decision(cohort, symbol, "ENTRY", decision["action"], snapshot,
                         decision["reason"], decision.get("method"),
                         event_key=f"{cohort}|ADAPTIVE_ENTRY_DECISION")
            evaluated += 1
            hypothesis_checks += evaluate_live_hypotheses(
                cohort, symbol, str(scan.get('created_at') or utcnow()), row, trend, context)
            # Every source opportunity is accounted for, even when Adaptive
            # declines. The fixed-2R control requires an individually valid plan.
            try:
                plan = build_trade_plan(row, frame15, str(scan.get("btc_regime") or "NEUTRAL"))
            except (TypeError, ValueError, IndexError):
                plan = None
            if plan and not _pending_for_symbol(symbol, "SOURCE_FIXED_2R") and not any(
                x["symbol"] == symbol and x["variant"] == "SOURCE_FIXED_2R" for x in open_shadows(symbol)
            ):
                baseline = {"ready_for_next_open": True,
                            "decision_candle_ms": int(closed_frame(frame15).iloc[-1]["close_time"]),
                            "entry": {"side": plan.side, "stop": plan.stop_loss,
                                      "target": plan.take_profit, "price": plan.entry},
                            "source_row": row, "market": context,
                            "source_cohort_matched": matched}
                expiry = now + timedelta(minutes=20)
                create_pending(cohort, symbol, plan.side, "SOURCE_FIXED_2R", baseline, expiry.isoformat())
                created += 1
            if decision["action"] not in ("ENTER", "WAIT"):
                blocked += 1
                continue
            # One adaptive position OR pending per coin; keep source cohort.
            if any(x["variant"] == "ENTRY_ADAPTIVE" for x in open_shadows(symbol)):
                log_decision(cohort, symbol, "ENTRY", "SKIP",
                             snapshot, "EXISTING_ADAPTIVE_SHADOW", decision.get("method"),
                             event_key=f"{cohort}|ADAPTIVE_ALREADY_OPEN")
                continue
            if any(x["method"] != "SOURCE_FIXED_2R" for x in active_pending(symbol)):
                log_decision(cohort, symbol, "ENTRY", "SKIP",
                             snapshot, "EXISTING_PENDING_SIGNAL", decision.get("method"),
                             event_key=f"{cohort}|ADAPTIVE_PENDING_ALREADY_EXISTS")
                continue
            pending_snapshot = {**snapshot, "ready_for_next_open": decision["action"] == "ENTER",
                                "decision_candle_ms": decision.get("decision_candle_ms"),
                                "method_switch_count": 0}
            time_limit = {"BREAKOUT": 30, "PULLBACK": 180, "RETEST": 120}
            expires = now + timedelta(minutes=time_limit.get(decision.get("method"), 60))
            create_pending(cohort, symbol, decision["side"], decision["method"],
                           pending_snapshot, expires.isoformat())
            created += 1
        except Exception:
            log.exception("V4.4 scan shadow %s failed", symbol)
    state = {"status": "SHADOW", "at": utcnow(), "market": context,
             "evaluated": evaluated, "pending_created": created,
             "blocked_no_trade": blocked, "hypotheses_evaluated":hypothesis_checks}
    set_system_state("v44_scan", state)
    return state


async def _fetch_three(client: BinanceClient, symbol: str) -> dict[str, pd.DataFrame]:
    f15, f1h, f4h = await asyncio.gather(
        client.klines(symbol, "15m", 220),
        client.klines(symbol, "1h", 220),
        client.klines(symbol, "4h", 220))
    return {"15m": enrich(f15), "1h": enrich(f1h), "4h": enrich(f4h)}


def _context_now() -> dict[str, Any]:
    scan = latest_scan() or {}
    if not scan.get("created_at"):
        return {"risk_state": "RESTRICTED", "reason_codes": ["NO_SCAN"]}
    try:
        age = (datetime.now(timezone.utc) -
               datetime.fromisoformat(scan["created_at"].replace("Z", "+00:00"))).total_seconds()
    except (TypeError, ValueError):
        return {"risk_state": "RESTRICTED", "reason_codes": ["BAD_SCAN_TIME"]}
    if age > max(40*60, 2*int(settings.scan_interval_min)*60):
        return {"risk_state": "RESTRICTED", "reason_codes": ["STALE_SCAN"]}
    return market_context(scan, {"state": get_system_state("news_guardian", {}) or {}},
                          articles=_known_news_at(utcnow()))


async def _first_future_bar(client: BinanceClient, symbol: str,
                            confirmation_ms: int, created_ms: int):
    """First CLOSED 1m bar at or after BOTH observation and confirmation."""
    earliest = max(int(confirmation_ms), int(created_ms))
    open_ms = ((earliest + 59999) // 60000) * 60000
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if now_ms - open_ms > 12 * 60000:
        return None, "STALE_CONFIRMATION"
    if now_ms < open_ms + 60000:
        return None, "WAIT_FOR_NEXT_CLOSED_MINUTE"
    data = await client.klines(symbol, "1m", 5,
                              start_time=open_ms, end_time=min(now_ms-1, open_ms+5*60000))
    rows = data.loc[(data["open_time"] == open_ms) & (data["close_time"] < now_ms)]
    if rows.empty:
        return None, "MISSING_EXECUTION_BAR"
    return rows.iloc[0], None


def _stop_from_confirmation(confirmed: dict, frames: dict, side: str) -> float | None:
    stop = (confirmed.get("entry") or {}).get("stop")
    if stop is not None:
        return float(stop)
    close15 = closed_frame(frames["15m"])
    if len(close15) < 15:
        return None
    atr = float(close15.iloc[-1]["atr14"])
    close = float(close15.iloc[-1]["close"])
    if side == "LONG":
        return min(float(close15.tail(10)["low"].min())-.15*atr, close-1.35*atr)
    return max(float(close15.tail(10)["high"].max())+.15*atr, close+1.35*atr)


async def _monitor_pending(client: BinanceClient, p: dict, frames_cache: dict,
                           context: dict, existing: list[dict]) -> str:
    symbol = p["symbol"]
    signal_id = p["signal_id"]
    snapshot = json.loads(p["initial_snapshot_json"] or "{}")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if _iso_ms(p["expires_at"]) < now_ms:
        if update_pending(signal_id, "EXPIRED", "PENDING_TIMEOUT"):
            record_event(p["cohort_id"], symbol, "PENDING_TIMEOUT", snapshot,
                         f"{signal_id}|EXPIRED")
        return "EXPIRED"
    if p["method"] != "SOURCE_FIXED_2R" and entry_risk_block(context, symbol):
        return "NEWS_OR_MARKET_RESTRICTED"  # do not fill during lock
    if (p["method"] != "SOURCE_FIXED_2R" and context.get("risk_state") == "CAUTION"
            and bool(snapshot.get("ready_for_next_open"))):
        initial = snapshot.get("entry") or {}
        best = max((initial.get("scores") or {}).values(), default=0)
        if best < 72 or float((snapshot.get("trend") or {}).get("volume_ratio_15m") or 0) < 1.1:
            return "CAUTION_REQUIRE_STRONG_CONFIRMATION"

    confirmation_ms = int(snapshot.get("decision_candle_ms") or _iso_ms(p["created_at"]))
    ready = bool(snapshot.get("ready_for_next_open"))
    confirmed = snapshot
    frames = None
    if not ready:
        if symbol not in frames_cache:
            frames_cache[symbol] = await _fetch_three(client, symbol)
        frames = frames_cache[symbol]
        last15 = closed_frame(frames["15m"])
        if last15.empty or int(last15.iloc[-1]["close_time"]) <= confirmation_ms:
            return "WAIT_CANDLE"
        candle_ms = int(last15.iloc[-1]["close_time"])
        trend = assess_trend(frames, asof_ms=candle_ms)
        row = snapshot.get("source_row") or {}
        decision = select_entry(row, frames["15m"], trend, context)
        log_decision(p["cohort_id"], symbol, "PENDING_EVAL", decision["action"],
                     {"trend": trend, "entry": decision, "market": context},
                     decision.get("reason", "UNKNOWN"), decision.get("method"),
                     event_key=f"{signal_id}|CHECK|{candle_ms}")
        if decision["action"] == "NO_TRADE":
            reason = decision.get("reason") or "NO_TRADE"
            if reason in ("MARKET_RESTRICTED", "EVENT_LOCK", "INVALID_TREND_DATA"):
                return "RISK_WAIT"
            update_pending(signal_id, "CANCELLED", reason)
            return "CANCELLED"
        if decision.get("side") != p["side"]:
            update_pending(signal_id, "CANCELLED", "DIRECTION_CHANGED")
            return "CANCELLED"
        if decision.get("method") != p["method"]:
            initial = snapshot.get("entry") or {}
            current_scores = decision.get("scores") or {}
            gain = float(current_scores.get(decision["method"], 0)) - float(current_scores.get(p["method"], 0))
            if gain >= 12 and int(snapshot.get("method_switch_count") or 0) < 1:
                update_pending(signal_id, "CANCELLED", "METHOD_SWITCHED")
                transfer = {**snapshot, "entry": decision,
                            "decision_candle_ms": candle_ms,
                            "ready_for_next_open": decision["action"] == "ENTER",
                            "method_switch_count": 1}
                # preserve the original absolute expiry; never perpetually reset TTL.
                create_pending(p["cohort_id"],symbol,p["side"],decision["method"],
                               transfer,p["expires_at"])
                record_event(p["cohort_id"],symbol,"METHOD_SWITCH",{
                    "from":p["method"],"to":decision["method"],"gain":gain
                },f"{signal_id}|SWITCH|{candle_ms}")
                return "SWITCHED"
            return "WAIT_METHOD"
        if decision["action"] != "ENTER":
            return "WAIT_CONFIRMATION"
        confirmed = {**snapshot, "entry": decision, "trend": trend}
        confirmation_ms = candle_ms

    if p["method"] != "SOURCE_FIXED_2R" and any(
        x["variant"] == "ENTRY_ADAPTIVE" and x["symbol"] == symbol for x in existing
    ):
        update_pending(signal_id,"CANCELLED","OTHER_ADAPTIVE_POSITION")
        return "CANCELLED"

    bar, reason = await _first_future_bar(
        client,symbol,confirmation_ms,_iso_ms(p["created_at"]))
    if bar is None:
        if reason in ("STALE_CONFIRMATION","MISSING_EXECUTION_BAR"):
            update_pending(signal_id, "CANCELLED", reason)
            record_event(p["cohort_id"],symbol,"CANCELLED",{"reason":reason},
                         f"{signal_id}|{reason}")
        return reason or "WAIT"
    raw_entry = float(bar["open"])
    side = p["side"]
    direction = 1 if side == "LONG" else -1
    entry = raw_entry*(1+direction*float(settings.slippage_bps)/10000)
    if frames is None:
        stop = (confirmed.get("entry") or {}).get("stop")
    else:
        stop = _stop_from_confirmation(confirmed, frames, side)
    if stop is None or not math.isfinite(float(stop)):
        update_pending(signal_id,"CANCELLED","INVALID_STOP")
        return "CANCELLED"
    stop = float(stop)
    risk = abs(entry-stop)
    target = entry+direction*2*risk
    stop_pct=100*risk/entry
    if not valid_trade(side,entry,stop,target) or not(settings.min_stop_pct<=stop_pct<=settings.max_stop_pct):
        update_pending(signal_id,"CANCELLED","RISK_REWARD_INVALID_AT_FILL")
        return "CANCELLED"
    variants = ("SOURCE_FIXED_2R",) if p["method"]=="SOURCE_FIXED_2R" else (
        "ENTRY_ADAPTIVE","EXIT_A_TREND","EXIT_B_RUNNER")
    if len(existing) + len(variants) > MAX_SHADOW_OPEN:
        return "CAPACITY_WAIT"
    inserted = 0
    for variant in variants:
        # Recorded post-confirmation minute open; no historical price optimization.
        state={"entry_method":p["method"],"entry_raw":raw_entry,
               "confirmation_ms":confirmation_ms,"market":context,
               "source_cohort_matched":snapshot.get("source_cohort_matched",False)}
        if open_shadow(p["cohort_id"],symbol,variant,side,int(bar["open_time"]),
                       entry,stop,target,state=state):
            inserted+=1
    if not inserted:
        update_pending(signal_id,"CANCELLED","DUPLICATE_SHADOW_COHORT")
        return "CANCELLED"
    update_pending(signal_id,"CONFIRMED","FIRST_FUTURE_MINUTE_OPEN")
    log_decision(p["cohort_id"],symbol,"PENDING","FILLED_SHADOW",
                 {"raw_entry":raw_entry,"effective_entry":entry,"stop":stop,"target":target,
                  "confirmation_ms":confirmation_ms,"first_open_ms":int(bar["open_time"]),
                  "variants":variants},
                 "FIRST_FUTURE_MINUTE_OPEN",p["method"],
                 event_key=f"{signal_id}|SHADOW_FILLED")
    record_event(p["cohort_id"],symbol,"SHADOW_ENTRY",
                 {"variants":variants,"entry":entry,"stop":stop,"confirmation_ms":confirmation_ms},
                 f"{signal_id}|FILL")
    return "FILLED"


async def monitor_shadow() -> dict:
    if not settings.v44_shadow_enabled:
        return {"status":"DISABLED"}
    client=BinanceClient()
    frames_cache={}
    context=_context_now()
    counters=defaultdict(int)
    try:
        existing=open_shadows()
        for p in active_pending():
            try:
                result=await _monitor_pending(client,p,frames_cache,context,existing)
                counters["pending_"+result]+=1
                if result=="FILLED":
                    existing=open_shadows()
            except Exception as exc:
                log.warning("V4.4 pending %s failed: %s",p["signal_id"],exc)
                counters["pending_errors"]+=1

        positions=open_shadows()
        grouped=defaultdict(list)
        for pos in positions:
            grouped[pos["symbol"]].append(pos)
        now_ms=int(datetime.now(timezone.utc).timestamp()*1000)
        for symbol, group in grouped.items():
            try:
                oldest=min(int(p["last_candle_ms"])+1 for p in group)
                if now_ms-oldest > MAX_REPLAY_MINUTES*60000:
                    for pos in group:
                        x={**pos,"status":"CENSORED","closed_at":utcnow(),
                           "reason":"RECOVERY_WINDOW_EXCEEDED","net_r":None,
                           "state":json.loads(pos.get("state_json") or "{}")}
                        update_shadow(x)
                        counters["censored"]+=1
                    continue
                bars = await client.klines_1m_between(symbol,oldest,now_ms-1)
                bars=bars.loc[(bars["close_time"]<now_ms) & (bars["open_time"]>=oldest)].copy()
                if bars.empty:
                    continue
                if symbol not in frames_cache:
                    frames_cache[symbol]=await _fetch_three(client,symbol)
                frames=frames_cache[symbol]
                cache={}
                for original in group:
                    pos=dict(original)
                    expected=int(pos["last_candle_ms"])+1
                    if expected < oldest:
                        expected=int(pos["last_candle_ms"])+1
                    portion=bars.loc[bars["open_time"]>=expected]
                    for _, candle in portion.iterrows():
                        row=candle.to_dict()
                        if int(row["open_time"])!=expected:
                            pos.update(status="CENSORED",closed_at=utcnow(),reason="MISSING_1M_CANDLE",net_r=None)
                            break
                        # Cached trend uses ONLY higher-TF candles closed by this 1m close.
                        bucket=(int(row["close_time"])+1)//900000
                        asof=int(row["close_time"])
                        if bucket not in cache:
                            cache[bucket]=assess_trend(frames,asof_ms=asof)
                        previous=json.loads(pos.get("state_json") or "{}") if "state_json" in pos else pos.get("state",{})
                        oldfills=len(previous.get("fills") or [])
                        pos=advance_shadow(pos,row,cache[bucket])
                        for idx, fill in enumerate((pos.get("state") or {}).get("fills",[])[oldfills:]):
                            record_event(pos["cohort_id"],symbol,"SHADOW_EXIT_FILL",
                                         {"variant":pos["variant"],**fill},
                                         f"POS{pos['id']}|{fill['at_ms']}|{oldfills+idx}")
                        expected=int(row["close_time"])+1
                        if pos["status"]!="OPEN":
                            break
                    if pos.get("status")=="CENSORED":
                        pos["state"]=pos.get("state") or json.loads(pos.get("state_json") or "{}")
                        record_event(pos["cohort_id"],symbol,"DATA_CENSORED",{
                            "variant":pos["variant"],"reason":pos["reason"]
                        },f"POS{pos['id']}|CENSORED")
                    if pos["last_candle_ms"]!=original["last_candle_ms"] or pos.get("status")!="OPEN":
                        update_shadow(pos)
                        counters["positions_updated"]+=1
            except Exception as exc:
                log.exception("V4.4 shadow monitor failed for %s: %s",symbol,exc)
                counters["monitor_errors"]+=1
    finally:
        await client.close()
    state={"status":"SHADOW","at":utcnow(),"market":context,**dict(counters)}
    set_system_state("v44_monitor",state)
    return state


# Backward-compatible name used by early V4.4 unit tests; new tests also
# import the pure execution module directly.
def _next_step(pos: dict, bar: dict, trend: dict) -> dict:
    return advance_shadow(pos,bar,trend)


def daily_shadow_summary() -> dict:
    report=research_overview()
    report["research_status"]="EXPLORATORY"
    report["paper_promotion"]="REQUIRES_MANUAL_APPROVAL"
    return report
