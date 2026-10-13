"""V4.4 forward-only SHADOW research runner. Existing paper paths unaffected."""
from __future__ import annotations
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from .binance import BinanceClient
from .config import settings
from .storage import get_system_state, set_system_state
from .v44_trend import assess_trend, market_context, select_entry, closed_frame, trend_exit_state
from .v44_research import (active_pending,create_pending,update_pending,log_decision,
                           open_shadow,open_shadows,update_shadow,register_hypothesis,
                           research_overview,utcnow)

log=logging.getLogger(__name__)
MAX_SHADOW_OPEN=75


def _iso_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()*1000)


def _next_step(pos: dict, bar: dict, trend: dict) -> dict:
    """Conservative OHLC; previous confirmed state determines current stop.
    No new stop may protect the same candle that generated it.
    """
    result=dict(pos)
    state=json.loads(result.get("state_json") or "{}") if "state_json" in result else dict(result.get("state") or {})
    side=pos["side"]
    sign=1 if side=="LONG" else -1
    entry=float(pos["entry"])
    risk=float(pos["risk"])
    high,low,close,opened=(float(bar[k]) for k in ("high","low","close","open"))
    original=float(pos["stop"])
    stop=float(pos["effective_stop"])
    target=float(pos["target"])
    result["last_candle_ms"]=int(bar["close_time"])
    prior_mfe=float(pos.get("high_water") or 0)
    result["high_water"]=max(prior_mfe,(high-entry)/risk if sign==1 else (entry-low)/risk)
    remaining=float(pos["remaining"])
    realized=float(pos["realized_r"])
    fee_unit=(float(settings.taker_fee_bps)+float(settings.slippage_bps))*2/10000*entry/risk
    hit_stop=low<=stop if sign==1 else high>=stop
    hit_tp=high>=target if sign==1 else low<=target
    if hit_stop:
        fill=min(opened,stop) if sign==1 else max(opened,stop)
        realized += remaining*sign*(fill-entry)/risk
        remaining=0
        result["reason"]="STOP_FIRST" if hit_tp else "STOP"
    elif pos["variant"]=="EXIT_B_RUNNER" and remaining>0.99 and (high>=entry+risk if sign==1 else low<=entry-risk):
        # never collect runner TP on same OHLC candle as the first partial.
        realized+=0.5
        remaining=0.5
        result["reason"]="PARTIAL_TP_1R"
    elif hit_tp and pos["variant"]!="EXIT_B_RUNNER":
        realized+=remaining*sign*(target-entry)/risk
        remaining=0
        result["reason"]="FIXED_TP_2R"
    elif pos["variant"]=="EXIT_B_RUNNER" and hit_tp and remaining<0.99:
        # 2R is a runner activation, not a forced upper bound.
        state["runner_active"]=True
    if remaining:
        last_exit=trend_exit_state(trend)
        state["last_exit_state"]=last_exit
        if last_exit=="WEAKENING" and result["high_water"]>=0.75:
            candidate=entry+sign*max(0.1,result["high_water"]-0.8)*risk
            result["effective_stop"]=max(stop,candidate) if sign==1 else min(stop,candidate)
        elif pos["variant"]=="EXIT_B_RUNNER" and state.get("runner_active"):
            candidate=entry+sign*max(0.3,result["high_water"]-1.0)*risk
            result["effective_stop"]=max(stop,candidate) if sign==1 else min(stop,candidate)
        elif last_exit=="REVERSAL_CONFIRMED":
            realized+=remaining*sign*(close-entry)/risk
            remaining=0
            result["reason"]="TREND_EXIT"
    result["remaining"]=remaining
    result["realized_r"]=realized
    result["state"]=state
    if remaining<=0:
        result["status"]="CLOSED"
        result["closed_at"]=datetime.fromtimestamp(int(bar["close_time"])/1000,timezone.utc).isoformat()
        result["net_r"]=round(realized-fee_unit,6)
    return result


def _collect_cohorts(scan: dict, frames: dict) -> list[tuple[str,dict,dict]]:
    asof=scan.get("created_at") or utcnow()
    cohort_key=asof[:16].replace(":","") # scanner session key, no future trade source
    out=[]
    for row in scan.get("all",[]):
        if row.get("bias") not in ("LONG","SHORT"):
            continue
        if max(float(row.get("long_score") or 0),float(row.get("short_score") or 0)) < settings.score_threshold:
            continue
        if row["symbol"] not in frames:
            continue
        cohort=f"V44::{cohort_key}::{row['symbol']}"
        out.append((cohort,row,frames[row["symbol"]]))
    return out


async def scan_shadow(scan: dict, frames_15m: dict, *, enabled: bool = True) -> dict:
    """Best effort shadow scan: failures must never interrupt the paper scanner."""
    if not enabled:
        return {"status":"DISABLED"}
    context=market_context(scan,{"state":get_system_state("news_guardian",{}) or {}})
    active=open_shadows()
    opened=0
    pending_created=0
    evaluated=0
    client=BinanceClient()
    try:
        for cohort,row,frame15 in _collect_cohorts(scan,frames_15m)[:max(1,int(settings.v44_shadow_scan_max))]:
            symbol=row["symbol"]
            try:
                from .indicators import enrich
                h=await client.klines(symbol,"1h",220)
                d=await client.klines(symbol,"4h",220)
                trend=assess_trend({"15m":frame15,"1h":enrich(h),"4h":enrich(d)})
                decision=select_entry(row,frame15,trend,context)
                snapshot={"trend":trend,"entry":decision,"market":context,"source":row}
                log_decision(cohort,symbol,"ENTRY",decision["action"],snapshot,decision["reason"],decision.get("method"),
                             event_key=f"{cohort}|ENTRY")
                evaluated+=1
                if decision["action"]=="WAIT" and not active_pending(symbol):
                    expiry=datetime.now(timezone.utc)+timedelta(minutes=120)
                    create_pending(cohort,symbol,decision["side"],decision["method"],decision,expiry.isoformat())
                    pending_created+=1
                elif decision["action"]=="ENTER" and len(active)+opened<MAX_SHADOW_OPEN:
                    if any(x["symbol"]==symbol and x["variant"]=="ENTRY_ADAPTIVE" for x in active):
                        continue
                    candle_ms=int(decision["decision_candle_ms"])
                    # paper counterfactual enters at the NEXT observed candle open, not a past close.
                    expiry=datetime.now(timezone.utc)+timedelta(minutes=30)
                    if not active_pending(symbol):
                        create_pending(cohort,symbol,decision["side"],decision["method"],{**decision,"ready_for_next_open":True},expiry.isoformat())
                        pending_created+=1
            except Exception as exc:
                log.warning("V4.4 shadow skipped %s: %s",symbol,exc)
    finally:
        await client.close()
    state={"at":utcnow(),"status":"SHADOW","evaluated":evaluated,"pending_created":pending_created,
           "market":context,"opened_on_scan":opened}
    set_system_state("v44_scan",state)
    return state


async def monitor_shadow() -> dict:
    """Close only confirmed 1m bars, forward since last processed timestamp."""
    client=BinanceClient()
    updated=0
    expired=0
    opened=0
    try:
        for p in active_pending():
            try:
                if _iso_ms(p["expires_at"])<=int(datetime.now(timezone.utc).timestamp()*1000):
                    if update_pending(p["signal_id"],"EXPIRED","PENDING_TIMEOUT"):
                        expired+=1
                    continue
                # A pending entry is checked on a future completed 15m bar.
                symbol=p["symbol"]
                from .indicators import enrich
                f=enrich(await client.klines(symbol,"15m",60))
                bars=closed_frame(f)
                if bars.empty or int(bars.iloc[-1]["close_time"])<=_iso_ms(p["created_at"]):
                    continue
                orig=json.loads(p["initial_snapshot_json"])
                last=bars.iloc[-1]
                side=p["side"]
                direction=1 if side=="LONG" else -1
                price=float(last["close"]);ema=float(last["ema20"]);atr=float(last["atr14"])
                if atr<=0 or not math.isfinite(atr):
                    continue
                dist=direction*(price-ema)/atr
                rebound=bool(last["close"]>last["open"] if direction==1 else last["close"]<last["open"])
                if dist< -1.0:
                    update_pending(p["signal_id"],"CANCELLED","STRUCTURE_OR_TREND_INVALID")
                    continue
                zone=json.loads(p["entry_zone_json"])
                trigger=float(zone.get("trigger") or 0)
                method=p["method"]
                confirmed=(method=="PULLBACK" and 0<=dist<=0.8 and rebound) or (
                    method=="RETEST" and direction*(price-trigger)>=0 and abs(price-trigger)<=0.8*atr and rebound
                ) or (method=="BREAKOUT" and rebound and 0<=dist<=1.4)
                if not confirmed:
                    continue
                if any(x["symbol"]==symbol and x["variant"]=="ENTRY_ADAPTIVE" for x in open_shadows(symbol)):
                    update_pending(p["signal_id"],"CANCELLED","EXISTING_SHADOW_POSITION")
                    continue
                # Defer the fill to the NEXT 1m candle, strictly after confirmation.
                # Monitor returns to this row on the next poll if no future bar yet.
                next_minute=int(last["close_time"])+1
                one=await client.klines(symbol,"1m",3,start_time=next_minute)
                future=one.loc[one["open_time"]>int(last["close_time"])]
                future=future.loc[future["close_time"]<int(datetime.now(timezone.utc).timestamp()*1000)]
                if future.empty:
                    continue
                first=future.iloc[0]
                entry=float(first["open"])
                atr=float(last["atr14"])
                sign=1 if side=="LONG" else -1
                stop=(min(float(bars.tail(10)["low"].min())-0.15*atr,entry-1.35*atr)
                      if sign==1 else
                      max(float(bars.tail(10)["high"].max())+0.15*atr,entry+1.35*atr))
                risk=abs(entry-stop)
                if risk<=0 or 100*risk/entry>3.5 or 100*risk/entry<0.35:
                    update_pending(p["signal_id"],"CANCELLED","FUTURE_FILL_RISK_INVALID")
                    continue
                created=open_shadow(p["cohort_id"],symbol,"ENTRY_ADAPTIVE",side,
                                    int(first["open_time"]),entry,stop,entry+sign*2*risk,
                                    state={"entry_method":method,"trend":{}})
                if created:
                    for variant in ("EXIT_A_TREND","EXIT_B_RUNNER"):
                        open_shadow(p["cohort_id"],symbol,variant,side,
                                    int(first["open_time"]),entry,stop,entry+sign*2*risk,
                                    state={"entry_method":method,"trend":{}})
                if not created:
                    update_pending(p["signal_id"],"CANCELLED","DUPLICATE_SHADOW")
                    continue
                opened+=1
                update_pending(p["signal_id"],"CONFIRMED","FUTURE_ENTRY_CONFIRMED")
                log_decision(p["cohort_id"],symbol,"PENDING","CONFIRMED",
                             {"confirm_price":price,"candle_ms":int(last["close_time"])},
                             "FUTURE_15M_CONFIRMATION",method,event_key=f"{p['signal_id']}|CONFIRMED")
            except Exception as exc:
                log.warning("V4.4 pending monitor %s: %s",p["symbol"],exc)
        trend_cache={}
        for position in open_shadows():
            try:
                symbol=position["symbol"]
                start=int(position["last_candle_ms"])+1
                now=int(datetime.now(timezone.utc).timestamp()*1000)
                if now-start>65*60_000:
                    # Do not extrapolate across outage without complete bars.
                    position["status"]="CENSORED"
                    position["reason"]="DATA_GAP"
                    # persisted as closed with no PnL to avoid false wins
                    position["remaining"]=position["remaining"]
                    position["closed_at"]=utcnow()
                    position["net_r"]=None
                    update_shadow(position)
                    continue
                bars=await client.klines_1m_between(symbol,start,now-60_000)
                if bars.empty:
                    continue
                recent=list(bars.to_dict("records"))
                # Calculate trend using only candles completed by NOW; apply it
                # to the latest bar only, never retroactively during gap replay.
                if symbol not in trend_cache:
                    try:
                        from .indicators import enrich
                        ff=await client.klines(symbol,"15m",220)
                        fh=await client.klines(symbol,"1h",220)
                        fd=await client.klines(symbol,"4h",220)
                        trend_cache[symbol]=assess_trend({"15m":enrich(ff),"1h":enrich(fh),"4h":enrich(fd)})
                    except Exception:
                        trend_cache[symbol]={"data_quality":"INSUFFICIENT"}
                prior=position["last_candle_ms"]
                for bar in recent:
                    if int(bar["open_time"])>prior+60_001 and prior>0:
                        position["status"]="CENSORED"
                        position["reason"]="MISSING_1M_CANDLE"
                        position["closed_at"]=utcnow()
                        position["net_r"]=None
                        break
                    # Replayed earlier bars do not see a trend state computed later.
                    trend=trend_cache[symbol] if bar is recent[-1] else {"data_quality":"INSUFFICIENT"}
                    position=_next_step(position,bar,trend)
                    prior=int(bar["close_time"])
                    if position["status"]!="OPEN":
                        break
                update_shadow(position)
                updated+=1
            except Exception as exc:
                log.warning("V4.4 monitor %s: %s",position.get("symbol"),exc)
    finally:
        await client.close()
    state={"status":"SHADOW","at":utcnow(),"positions_updated":updated,
           "pending_expired":expired,"pending_confirmed":opened}
    set_system_state("v44_monitor",state)
    return state


def daily_shadow_summary() -> dict:
    report=research_overview()
    report["research_status"]="EXPLORATORY"
    report["paper_promotion"]="REQUIRES_MANUAL_APPROVAL"
    return report
