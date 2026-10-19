"""Isolated Reverse Research Lab storage, matched-cohort analytics and reports.

No UPDATE/INSERT on battle_positions, battle_trades or any paper account.
Every live reverse cohort begins only after an actual Case C opening signal;
historical Case C trades are benchmarks, never backfilled as Shadow fills.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from .config import settings
from .report_sync import report_root
from .storage import _connect, get_system_state, set_system_state
from .reverse_execution import VARIANTS, TERMINAL, describe_variant
from .reverse_pattern import (
    VARIANT as PATTERN_VARIANT, VERSION as PATTERN_VERSION,
    compact_features, score_candidate, paper_signal_diagnostics,
)

SOURCE_CASE = "REVERSE_RR2"
RESEARCH_VERSION = "reverse-lab.2"
MIN_READY_PAIRS = 100
MIN_READY_DAYS = 14


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp()*1000)


def _date_ms(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms/1000, timezone.utc).isoformat() if ms is not None else None


def _json(value: Any) -> Any:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _finite(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def init_reverse_lab() -> None:
    """Additive and repeatable; no changes to historical trades or V4.4 tables."""
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS reverse_lab_signals (
            cohort_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            case_c_position_id INTEGER NOT NULL UNIQUE,
            source_side TEXT NOT NULL,
            reverse_side TEXT NOT NULL,
            score REAL NOT NULL,
            observed_at_ms INTEGER NOT NULL,
            signal_price REAL NOT NULL,
            risk_distance REAL NOT NULL,
            btc_regime TEXT NOT NULL,
            features_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reverse_lab_signals_time
            ON reverse_lab_signals(observed_at_ms);
        CREATE TABLE IF NOT EXISTS reverse_lab_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cohort_id TEXT NOT NULL REFERENCES reverse_lab_signals(cohort_id),
            symbol TEXT NOT NULL,
            variant TEXT NOT NULL,
            side TEXT NOT NULL,
            score REAL NOT NULL,
            signal_price REAL NOT NULL,
            risk_distance REAL NOT NULL,
            status TEXT NOT NULL,
            cursor_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL,
            entered_at_ms INTEGER,
            closed_at_ms INTEGER,
            entry REAL,
            stop REAL,
            effective_stop REAL,
            target REAL,
            remaining REAL NOT NULL DEFAULT 1,
            realized_r REAL NOT NULL DEFAULT 0,
            fees_r REAL NOT NULL DEFAULT 0,
            net_r REAL,
            high_water REAL NOT NULL DEFAULT 0,
            adverse_water REAL NOT NULL DEFAULT 0,
            reason TEXT,
            state_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(cohort_id,variant)
        );
        CREATE INDEX IF NOT EXISTS idx_reverse_lab_active
            ON reverse_lab_cases(status,symbol,cursor_ms);
        """)


def register_reverse_signals(opened: list[dict], scan: dict,
                             *, observed_ms: int | None = None) -> dict:
    """Register only actually OPENED Case C positions, exact IDs and same side.

    Existing paper trades remain unchanged; no entries are retroactively
    simulated before this function observes the signal.
    """
    init_reverse_lab()
    now = int(observed_ms) if observed_ms is not None else _now_ms()
    first_future_open = (now//60_000+1)*60_000
    scanned = {str(r.get("symbol")): r for r in scan.get("all", [])}
    inserted = 0
    ignored = 0
    samples = []
    with _connect() as db:
        # Train exclusively on REV-A Shadow outcomes already CLOSED before
        # this observation. Historical Paper is never training data for REV-E.
        previous = [dict(p) for p in db.execute("""
            SELECT s.cohort_id,s.source_side,s.score,s.observed_at_ms,
                   s.btc_regime,s.features_json,c.closed_at_ms,c.net_r
            FROM reverse_lab_signals s JOIN reverse_lab_cases c
                 ON c.cohort_id=s.cohort_id
            WHERE c.variant='REV_A_FIXED_2R' AND c.status='CLOSED'
              AND c.net_r IS NOT NULL AND s.observed_at_ms < ?
              AND c.closed_at_ms < ?
            ORDER BY s.observed_at_ms DESC LIMIT 600
        """, (now,now)).fetchall()]
        training = []
        for p in previous:
            old = _json(p["features_json"])
            snapshot = old.get("pattern_features")
            if not isinstance(snapshot, dict):
                snapshot = compact_features(
                    old, base_score=p["score"],
                    source_side=p["source_side"], btc_regime=p["btc_regime"],
                )
            training.append({
                "cohort_id":p["cohort_id"],
                "source_side":p["source_side"],
                "observed_at_ms":p["observed_at_ms"],
                "closed_at_ms":p["closed_at_ms"],
                "net_r":p["net_r"],
                "features":snapshot,
            })
        for rec in opened:
            if str(rec.get("strategy_id")) != SOURCE_CASE:
                continue
            ctx = rec.get("entry_context") or {}
            if isinstance(ctx, str):
                ctx = _json(ctx)
            cohort = str(ctx.get("cohort_id") or "") if isinstance(ctx, dict) else ""
            sym = str(rec.get("symbol") or "")
            side = str(rec.get("side") or "")
            source = str(ctx.get("source_signal_side") or "") if isinstance(ctx, dict) else ""
            risk = abs(float(rec["entry_price"])-float(rec["stop_loss"]))
            source_price = _finite(rec.get("signal_price"))
            score = _finite(rec.get("score"))
            case_id = rec.get("position_id")
            if (not cohort or sym not in scanned or source not in ("LONG","SHORT")
                    or side not in ("LONG","SHORT") or side == source or risk <= 0
                    or source_price is None or source_price <= 0 or score is None
                    or case_id is None or int(case_id) <= 0):
                ignored += 1
                continue
            r = scanned[sym]
            btc=str(scan.get("btc_regime") or "UNKNOWN")
            pattern_features=compact_features(
                r,base_score=score,source_side=source,btc_regime=btc,
            )
            try:
                pattern=score_candidate(
                    pattern_features,training,source_side=source,
                    observed_at_ms=now,
                )
            except Exception as exc:
                # Fail closed for REV-E without affecting legacy variants.
                pattern={"model_version":PATTERN_VERSION,"status":"SCORING_ERROR",
                         "eligible":False,"score":None,"expected_r":None,
                         "error":type(exc).__name__}
            features = {
                "source_score":score,"source_side":source,"reverse_side":side,
                "pattern_features":pattern_features,"reverse_pattern":pattern,
                "rsi_1h":r.get("rsi_1h"),"distance_ema20_atr":r.get("distance_ema20_atr"),
                "volume_ratio_1h":r.get("volume_ratio_1h"),
                "atr_pct_1h":r.get("atr_pct_1h"),
                "funding_rate":r.get("funding_rate"),
                "oi_change_pct":r.get("oi_change_pct"),
                "relative_strength_1h_pct":r.get("relative_strength_1h_pct"),
                "trend_4h_long":r.get("trend_4h_long"),
                "trend_4h_short":r.get("trend_4h_short"),
                "trend_1h_long":r.get("trend_1h_long"),
                "trend_1h_short":r.get("trend_1h_short"),
                "signal_at":scan.get("created_at"),
                "source_case_id":SOURCE_CASE,
                "reference_case_c_entry":rec.get("entry_price"),
                "reference_case_c_stop":rec.get("stop_loss"),
                "research_policy_version":RESEARCH_VERSION,
                "time_scope":"PROSPECTIVE_ONLY",
            }
            cur=db.execute("""INSERT OR IGNORE INTO reverse_lab_signals(
                cohort_id,symbol,case_c_position_id,source_side,reverse_side,
                score,observed_at_ms,signal_price,risk_distance,btc_regime,
                features_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(
                cohort,sym,int(case_id),source,side,score,now,
                source_price,risk,btc,json.dumps(features,ensure_ascii=False,default=str),
                _date_ms(now)
            ))
            if not cur.rowcount:
                continue
            inserted += 1
            samples.append({"cohort_id":cohort,"symbol":sym,"side":side,"score":score,
                            "pattern_score":pattern.get("score"),
                            "pattern_status":pattern.get("status")})
            for variant in VARIANTS:
                # D keeps its unchanged Base-score entry/exit policy.
                waits = (variant == "REV_B_CONFIRMED_2R"
                         or (variant == "REV_D_ADAPTIVE" and score < 85))
                skipped = variant == PATTERN_VARIANT and not pattern.get("eligible",False)
                status = "EXPIRED" if skipped else "WAIT_CONFIRM" if waits else "WAIT_ENTRY"
                state = {
                    "decision_at_ms":now,
                    "entry_policy":"NO_ENTRY_PATTERN_GATE" if skipped else
                                   "WAIT_CONFIRM" if waits else "NEXT_FUTURE_MINUTE_OPEN",
                    "signal_score":score,
                    "confirmation_streak":0,
                    "fills":[],
                }
                if variant == PATTERN_VARIANT:
                    # Freeze once; never re-score after seeing future outcomes.
                    state["pattern_decision"]=pattern
                db.execute("""INSERT OR IGNORE INTO reverse_lab_cases(
                    cohort_id,symbol,variant,side,score,signal_price,risk_distance,
                    status,cursor_ms,expires_at_ms,closed_at_ms,reason,state_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    cohort,sym,variant,side,score,source_price,risk,
                    status,first_future_open,now+90*60_000,
                    now if skipped else None,
                    "PATTERN_"+str(pattern.get("status")) if skipped else None,
                    json.dumps(state,separators=(",",":")),
                ))
    result = {
        "status":"RESEARCH_ONLY","enabled":True,"at_ms":now,
        "registered":inserted,"ignored":ignored,"sample":samples[:10],
        "baseline":SOURCE_CASE,"variants":list(VARIANTS),
    }
    set_system_state("reverse_lab_scan",result)
    return result


def active_reverse_cases() -> list[dict]:
    init_reverse_lab()
    with _connect() as db:
        return [dict(r) for r in db.execute("""
            SELECT * FROM reverse_lab_cases
            WHERE status IN ('WAIT_ENTRY','WAIT_CONFIRM','OPEN')
            ORDER BY cursor_ms,id""").fetchall()]


def persist_reverse_case(old: dict, result: dict) -> bool:
    """Optimistic cursor+status guard prevents stale monitor writes."""
    with _connect() as db:
        cur=db.execute("""UPDATE reverse_lab_cases SET
            status=?,cursor_ms=?,entered_at_ms=?,closed_at_ms=?,
            entry=?,stop=?,effective_stop=?,target=?,remaining=?,
            realized_r=?,fees_r=?,net_r=?,high_water=?,adverse_water=?,
            reason=?,state_json=?
            WHERE id=? AND cursor_ms=? AND status=?""",(
            result["status"],result["cursor_ms"],result.get("entered_at_ms"),
            result.get("closed_at_ms"),result.get("entry"),result.get("stop"),
            result.get("effective_stop"),result.get("target"),
            result["remaining"],result["realized_r"],result["fees_r"],
            result.get("net_r"),result["high_water"],result["adverse_water"],
            result.get("reason"),result["state_json"],old["id"],
            old["cursor_ms"],old["status"],
        ))
        return bool(cur.rowcount)


def mark_censored(old: dict, reason: str, at_ms: int,
                  progressed: dict | None = None) -> bool:
    # Preserve realized partial-fills and next cursor before a later gap;
    # never represent an uncertain position as profit or loss.
    new=dict(progressed or old)
    new.update(status="CENSORED",closed_at_ms=at_ms,reason=reason,net_r=None)
    return persist_reverse_case(old,new)


def _bucket(score: float) -> str:
    if score < 80: return "75-79"
    if score < 85: return "80-84"
    if score < 90: return "85-89"
    return "90+"


def _cluster_ci(pairs: list[dict], key: str = "delta_r") -> list[float] | None:
    groups: dict[str,list[float]] = defaultdict(list)
    for row in pairs:
        groups[row["day"]].append(float(row[key]))
    days=list(groups)
    if len(days)<2:
        return None  # one independent trading day cannot give an honest CI
    rng=random.Random(44052)
    arr=[]
    for _ in range(500):
        draw=[groups[rng.choice(days)] for _ in days]
        values=[v for cluster in draw for v in cluster]
        arr.append(mean(values))
    arr.sort()
    return [round(arr[12],5),round(arr[487],5)]


def _summary(rows: list[dict], *, key: str = "net_r") -> dict:
    values=[float(r[key]) for r in rows if r.get(key) is not None]
    if not values:
        return {"closed":0,"expectancy_r":None,"win_rate_pct":None,
                "profit_factor":None,"total_net_r":0}
    wins=sum(1 for r in rows if r.get(key) is not None and float(r[key])>0)
    gains=sum(x for x in values if x>0)
    losses=-sum(x for x in values if x<0)
    return {"closed":len(values),"wins":wins,
            "win_rate_pct":round(100*wins/len(values),2),
            "expectancy_r":round(mean(values),5),
            "profit_factor":round(gains/losses,4) if losses>0 else None,
            "total_net_r":round(sum(values),5)}



def historic_case_c_diagnostics(*, limit: int = 10000) -> dict:
    """READ-ONLY existing Case C history; never pretend historical Shadow fills.

    Paper trades may be correlated and overlapping. These group summaries
    describe the past dataset only, not prospective statistical evidence.
    """
    with _connect() as db:
        exists=db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='battle_trades'"
        ).fetchone()
        history=([dict(r) for r in db.execute("""
            SELECT symbol,side,score,opened_at,closed_at,net_pnl,r_multiple,
                   mfe_r,mae_r,holding_minutes,exit_reason,entry_context
            FROM battle_trades WHERE strategy_id=? ORDER BY closed_at DESC
            LIMIT ?""",(SOURCE_CASE,max(1,min(20000,int(limit))))).fetchall()]
            if exists else [])
    # Oldest -> newest for serial trade sequence, which is NOT a
    # capital-equity/drawdown series because positions overlap in reality.
    history.reverse()
    by_score=defaultdict(list)
    by_regime=defaultdict(list)
    by_side=defaultdict(list)
    by_coin=defaultdict(list)
    exits=defaultdict(int)
    ignored=0
    stopped_with_mfe_05=stopped_with_mfe_1=stop_count=0
    records=[]
    for r in history:
        value=_finite(r.get("r_multiple"))
        score=_finite(r.get("score"))
        if value is None or score is None:
            ignored+=1
            continue
        ctx=_json(r["entry_context"])
        regime=str(ctx.get("btc_regime") or "UNKNOWN")
        item={"net_r":value}
        by_score[_bucket(score)].append(item)
        by_regime[regime].append(item)
        by_side[r["side"]].append(item)
        by_coin[r["symbol"]].append(item)
        exits[str(r["exit_reason"])]+=1
        if str(r["exit_reason"]).upper().startswith("STOP"):
            stop_count+=1
            mfe=_finite(r.get("mfe_r")) or 0
            stopped_with_mfe_05+=int(mfe>=.5)
            stopped_with_mfe_1+=int(mfe>=1)
        records.append(item)
    cum=peak=max_dd=0.0
    for r in records:
        cum+=r["net_r"]
        peak=max(peak,cum)
        max_dd=max(max_dd,peak-cum)
    return {
        "status":"HISTORICAL_PAPER_ONLY_NOT_OUT_OF_SAMPLE",
        "source_case":SOURCE_CASE,
        "closed_trades":len(records),"ignored_invalid":ignored,
        "overall":_summary(records),
        "score":{k:_summary(v) for k,v in by_score.items()},
        "btc_regime":{k:_summary(v) for k,v in by_regime.items()},
        "side":{k:_summary(v) for k,v in by_side.items()},
        "coin":{k:_summary(v) for k,v in by_coin.items() if len(v)>=5},
        "exit_reasons":dict(exits),
        "stops_after_mfe":{
            "stop_trades":stop_count,
            "had_reached_plus_0_5R":stopped_with_mfe_05,
            "had_reached_plus_1R":stopped_with_mfe_1,
            "warning":"MFE from candle ranges is approximate; cannot infer intrabar ordering",
        },
        "serial_trade_drawdown_r":round(max_dd,4),
        "drawdown_warning":"Serial R drawdown is NOT true portfolio-equity drawdown with overlapping positions",
        "cohort_warning":"Historic Case C data is for discovery; new Reverse Lab cohorts are prospective",
        "funding_and_orderbook_costs_verified":False,
        "signal_patterns":paper_signal_diagnostics(history),
    }


def reverse_lab_snapshot(*, limit: int = 35) -> dict:
    """Calculate exact same-cohort comparisons, including skipped-entry cost."""
    init_reverse_lab()
    with _connect() as db:
        signals=[dict(x) for x in db.execute(
            "SELECT * FROM reverse_lab_signals ORDER BY observed_at_ms,cohort_id").fetchall()]
        rows=[dict(x) for x in db.execute(
            "SELECT * FROM reverse_lab_cases ORDER BY cohort_id,variant").fetchall()]
        # The research API must work even if Strategy Battle has never been
        # initialized on this machine (and paper accounts remain untouched).
        table_present=db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='battle_trades'"
        ).fetchone()
        paper=([dict(x) for x in db.execute("""
            SELECT s.cohort_id,t.side,t.r_multiple,t.net_pnl,t.exit_reason,
                   t.closed_at,t.opened_at
            FROM reverse_lab_signals s
            JOIN battle_trades t ON t.position_id=s.case_c_position_id
            WHERE t.strategy_id=? AND t.side=s.reverse_side""",(SOURCE_CASE,)).fetchall()]
            if table_present else [])
    by_cohort: dict[str,dict[str,dict]] = defaultdict(dict)
    for row in rows:
        by_cohort[row["cohort_id"]][row["variant"]]=row
    paper_by={p["cohort_id"]:p for p in paper}
    position_summaries={v:[] for v in VARIANTS}
    pending_by_variant={}
    for variant in VARIANTS:
        relevant=[r for r in rows if r["variant"]==variant]
        complete=[r for r in relevant if r["status"]=="CLOSED" and r["net_r"] is not None]
        position_summaries[variant]=complete
        pending_by_variant[variant]={
            status:sum(r["status"]==status for r in relevant)
            for status in ("WAIT_ENTRY","WAIT_CONFIRM","OPEN","CLOSED","EXPIRED","CENSORED")
        }

    paired: dict[str, list[dict]] = {v:[] for v in VARIANTS if v!="REV_A_FIXED_2R"}
    paired_paper: list[dict] = []
    no_trade_cost={v:{"avoided_losses":0,"missed_winners":0,"unresolved":0,
                      "measured_skips":0,"skipped_control_total_r":0.0}
                   for v in ("REV_B_CONFIRMED_2R","REV_D_ADAPTIVE",PATTERN_VARIANT)}
    segment: dict[str,dict[str,list[dict]]] = defaultdict(lambda:defaultdict(list))
    details=[]
    pattern_status_counts=defaultdict(int)
    pattern_score_segments=defaultdict(list)
    pattern_eligible=0
    recent_ids={x["cohort_id"] for x in signals[-max(1,min(int(limit),120)):]}
    for signal in signals:
        cid=signal["cohort_id"]
        feature=_json(signal["features_json"])
        pattern=feature.get("reverse_pattern") or {}
        if pattern:
            pattern_status_counts[str(pattern.get("status") or "UNKNOWN")]+=1
            pattern_eligible+=int(bool(pattern.get("eligible")))
        day=(_date_ms(signal["observed_at_ms"]) or "")[:10]
        control=by_cohort[cid].get("REV_A_FIXED_2R")
        a_net=(float(control["net_r"]) if control and control["status"]=="CLOSED"
               and control["net_r"] is not None else None)
        caseC=paper_by.get(cid)
        if caseC and a_net is not None:
            paired_paper.append({"cohort_id":cid,"day":day,
                                 "delta_r":a_net-float(caseC["r_multiple"])})
        for v in paired:
            candidate=by_cohort[cid].get(v)
            if not candidate:
                continue
            if a_net is None:
                # Cannot claim an avoided loss/missed win while the fixed
                # counterfactual is still open, censored or unavailable.
                if v in no_trade_cost and candidate["status"]=="EXPIRED":
                    no_trade_cost[v]["unresolved"]+=1
                continue
            delta=None
            if candidate["status"]=="CLOSED" and candidate["net_r"] is not None:
                delta=float(candidate["net_r"])-a_net
            elif candidate["status"]=="EXPIRED":
                delta=-a_net
                cost=no_trade_cost[v] if v in no_trade_cost else None
                if cost is not None:
                    cost["measured_skips"]+=1
                    cost["avoided_losses"]+=int(a_net<0)
                    cost["missed_winners"]+=int(a_net>0)
                    cost["skipped_control_total_r"]+=a_net
            elif v in no_trade_cost and candidate["status"] not in TERMINAL:
                no_trade_cost[v]["unresolved"]+=1
            if delta is not None:
                paired[v].append({"cohort_id":cid,"day":day,
                                  "delta_r":delta,
                                  "candidate_status":candidate["status"]})
        if a_net is not None:
            if pattern and _finite(pattern.get("score")) is not None:
                q=float(pattern["score"])
                pattern_score_segments["<55" if q<55 else "55-69" if q<70
                                       else "70+"].append({"net_r":a_net})
            grouped=_bucket(float(signal["score"]))
            segment["score"][grouped].append({"net_r":a_net})
            segment["btc_regime"][signal["btc_regime"]].append({"net_r":a_net})
            feature=_json(signal["features_json"])
            direction=feature.get("source_side","UNKNOWN")
            segment["source_side"][str(direction)].append({"net_r":a_net})
            ema=_finite(feature.get("distance_ema20_atr"))
            rsi=_finite(feature.get("rsi_1h"))
            oi=_finite(feature.get("oi_change_pct"))
            funding=_finite(feature.get("funding_rate"))
            segments={
                "ema_distance": ("UNKNOWN" if ema is None else
                    ">=2 ATR" if abs(ema)>=2 else "1-2 ATR" if abs(ema)>=1 else "<1 ATR"),
                "rsi_1h": ("UNKNOWN" if rsi is None else
                    ">=70" if rsi>=70 else "<=30" if rsi<=30 else "30-70"),
                "oi_change": ("UNKNOWN" if oi is None else
                    "rising >=1%" if oi>=1 else "falling <=-1%" if oi<=-1 else "flat"),
                "funding": ("UNKNOWN" if funding is None else
                    "high positive" if funding>=.0005 else
                    "high negative" if funding<=-.0005 else "normal"),
            }
            for factor,segment_name in segments.items():
                segment[factor][segment_name].append({"net_r":a_net})
        if cid in recent_ids:
            details.append({
                "cohort_id":cid,"symbol":signal["symbol"],
                "observed_at":_date_ms(signal["observed_at_ms"]),
                "score":signal["score"],"source_side":signal["source_side"],
                "reverse_side":signal["reverse_side"],
                "btc_regime":signal["btc_regime"],
                "reverse_pattern":{k:pattern.get(k) for k in (
                    "status","score","expected_r","training_n",
                    "training_days","effective_n","eligible")},
                "variants":{v:{"status":x["status"],"entry":x["entry"],
                                "stop":x["stop"],"target":x["target"],
                                "net_r":x["net_r"],"reason":x["reason"],
                                "mfe_r":round(x["high_water"],3),
                                "mae_r":round(x["adverse_water"],3),
                                "entry_time":_date_ms(x["entered_at_ms"]),
                                "closed_at":_date_ms(x["closed_at_ms"]),
                                "fills":_json(x["state_json"]).get("fills",[])}
                            for v,x in by_cohort[cid].items()},
                "case_c":({"net_r":caseC["r_multiple"],
                           "exit_reason":caseC["exit_reason"],
                           "net_pnl":caseC["net_pnl"]} if caseC else None),
            })
    result_pairs={}
    for variant, pairs in paired.items():
        deltas=[x["delta_r"] for x in pairs]
        independent_days=len(set(x["day"] for x in pairs))
        interval=_cluster_ci(pairs)
        result_pairs[variant]={
            "control":"REV_A_FIXED_2R","measured_cohorts":len(pairs),
            "all_cohorts":len(signals),"independent_days":independent_days,
            "delta_r_mean":round(mean(deltas),5) if deltas else None,
            "cluster_95pct_interval":interval,
            "status":"INSUFFICIENT_DATA" if len(pairs)<MIN_READY_PAIRS or independent_days<MIN_READY_DAYS else (
                "PROMISING_RESEARCH" if interval and interval[0]>0 else
                "WEAKER_RESEARCH" if interval and interval[1]<0 else "INCONCLUSIVE"
            ),
            "out_of_sample_validated":False,
        }
    paper_ci=_cluster_ci(paired_paper)
    paper_vals=[x["delta_r"] for x in paired_paper]
    for cost in no_trade_cost.values():
        cost["skipped_control_total_r"]=round(cost["skipped_control_total_r"],5)
    payload={
        "version":RESEARCH_VERSION,"mode":"SHADOW_ONLY",
        "paper_trading_enabled_by_lab":False,
        "real_trading_enabled":False,
        "source_case":SOURCE_CASE,
        "cohorts":len(signals),
        "open_cases":sum(r["status"] not in TERMINAL for r in rows),
        "variants":{v:{**_summary(position_summaries[v]),
                       "pending":pending_by_variant[v],
                       "description":describe_variant(v)} for v in VARIANTS},
        "paired_vs_control":result_pairs,
        "paired_case_c":{
            "pairs":len(paired_paper),"delta_mean_r":round(mean(paper_vals),5) if paper_vals else None,
            "cluster_95pct_interval":paper_ci,
            "note":"Same cohort and side, but paper Case C enters earlier than Shadow; not a causal execution comparison",
        },
        "missed_opportunities":no_trade_cost,
        "pattern_learning":{
            "model_version":PATTERN_VERSION,
            "variant":PATTERN_VARIANT,
            "training_source":"past CLOSED REV-A Shadow, same source side",
            "score_is_win_probability":False,
            "eligible_at_signal":pattern_eligible,
            "status_counts":dict(pattern_status_counts),
            "matched_control_by_score":{
                k:_summary(v) for k,v in pattern_score_segments.items()},
            "note":"Scores are frozen at entry; skips count avoided losses AND missed winners.",
            "out_of_sample_validated":False,
        },
        "score_groups":{factor:{k:_summary(v) for k,v in groups.items()}
                        for factor,groups in segment.items()},
        "historical_case_c":historic_case_c_diagnostics(),
        "recent_cohorts":list(reversed(details)),
        "sample_gate":{"min_matched":MIN_READY_PAIRS,"min_days":MIN_READY_DAYS,
                       "paper_approval":"REQUIRES_USER_APPROVAL"},
        "limitations":["Funding and liquidation not modeled",
                       "Shadow fills are OHLC hypothetical, not exchange executions",
                       "Paired test not OOS-validated; correlated signals across coins",
                       "No paper or real-money orders"],
    }
    return payload


def reverse_lab_overview(limit: int = 35) -> dict:
    # Cached/full analytics refreshed by the monitor. API remains current on
    # startup by calling the pure query; no market/network operations.
    return reverse_lab_snapshot(limit=limit)


def write_reverse_lab_report(day: str, root: Path | None = None) -> dict:
    today=datetime.now(ZoneInfo(settings.timezone)).date()
    if day not in {today.isoformat(),(today-timedelta(days=1)).isoformat()}:
        raise ValueError("Cannot backfill historical research with future aggregates")
    result=reverse_lab_snapshot(limit=25)
    result["report_day"]=day
    result["generated_at"]=datetime.now(timezone.utc).isoformat()
    folder=(root or report_root())/day
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"reverse-lab.json").write_text(json.dumps(result,ensure_ascii=False,
                                             default=str,indent=2),encoding="utf-8")
    md=[
        f"# Reverse Research Lab — {day}",
        f"Generated at: {result['generated_at']}",
        "**Research-only / no real orders / no auto paper promotion**",
        f"Matched prospective Case C cohorts: **{result['cohorts']}**",
        "## A/B/C/D research outcomes",
        "| Variant | Closed | Mean net R | Win rate | Paired vs A | Verdict |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for name,v in result["variants"].items():
        paired=result["paired_vs_control"].get(name,{})
        md.append(f"| {name} | {v['closed']} | {v['expectancy_r']} | "
                  f"{v['win_rate_pct']}% | {paired.get('delta_r_mean','—')} | "
                  f"{paired.get('status','CONTROL')} |")
    md += [
        "## Source Case C (exact cohort + direction)",
        f"Matched closed comparisons: {result['paired_case_c']['pairs']}; "
        f"REV-A minus Case C: {result['paired_case_c']['delta_mean_r']}R",
        result["paired_case_c"]["note"],
        "## Entry opportunity costs",
    ]
    for key,cost in result["missed_opportunities"].items():
        md.append(f"- {key}: avoided losses {cost['avoided_losses']}; "
                  f"missed winners {cost['missed_winners']}; "
                  f"measurable skips {cost['measured_skips']}; "
                  f"control PnL of skipped {cost['skipped_control_total_r']}R")
    historic=result["historical_case_c"]
    md += ["## Historical Case C — discovery only (not Shadow backfill)",
           f"Historical Case C trades: {historic['closed_trades']}; mean "
           f"{historic['overall']['expectancy_r']}R; win rate "
           f"{historic['overall']['win_rate_pct']}%",
           f"Stopped trades with prior 0.5R MFE: "
           f"{historic['stops_after_mfe']['had_reached_plus_0_5R']} / "
           f"{historic['stops_after_mfe']['stop_trades']}",
           "Historical results are not independent prospective evidence."]
    md += ["## Score / BTC / EMA / RSI / OI / funding factors (REV-A only)"]
    for factor,groups in result["score_groups"].items():
        md.append(f"### {factor}")
        for key,stats in groups.items():
            md.append(f"- {key}: {stats['closed']} resolved; "
                      f"{stats['expectancy_r']}R average, {stats['win_rate_pct']}% wins")
    md += ["## Risk/validation limitations"]
    md.extend(f"- {t}" for t in result["limitations"])
    markdown="\n\n".join(md)+"\n"
    (folder/"reverse-lab.md").write_text(markdown,encoding="utf-8")
    from html import escape
    (folder/"reverse-lab.html").write_text(
        "<!DOCTYPE html><html lang='vi'><meta charset='utf-8'>"
        "<title>Reverse Research Lab</title><style>body{font:15px system-ui;"
        "margin:32px auto;max-width:980px;background:#101828;color:#eaf2ff;"
        "line-height:1.7;padding:0 18px}pre{white-space:pre-wrap}"
        "</style><h1>Reverse Research Lab</h1><pre>"+escape(markdown)+"</pre></html>",
        encoding="utf-8",
    )
    set_system_state("reverse_lab_summary",{
        "report_day":day,"generated_at":result["generated_at"],
        "cohorts":result["cohorts"],
        "variants":result["variants"],
        "paired_vs_control":result["paired_vs_control"],
        "paired_case_c":result["paired_case_c"],
    })
    return result
