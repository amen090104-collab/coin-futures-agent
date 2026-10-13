"""V4.4 autonomous SHADOW research, using only time-locked decisions and cohorts.

Hypotheses are discovered from past outcomes, frozen at registration and
evaluated ONLY on future cohorts. All candidate outcomes are paper what-if
simulations, not live executions or statistically calibrated probabilities.
"""
from __future__ import annotations

import html
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from .config import settings
from .report_sync import report_root
from .storage import _connect, get_system_state
from .v44_research import (init_research, register_hypothesis, upsert_proposal,
                           research_overview, utcnow)

MIN_HOLDOUT_COHORTS = 50
MIN_HOLDOUT_DAYS = 7
MAX_ACTIVE_RESEARCH = 5
MIN_TRAIN_SAMPLES = 16
MIN_TRIGGERED_HOLDOUT = 25


def _f(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError):
        return default


def _bootstrap_interval(values: list[float], *, alpha: float = 0.05,
                        groups: list[str] | None = None,
                        n_samples: int = 800) -> tuple[float, float] | None:
    """Fixed-seed by-DAY cluster bootstrap to reduce intraday-cohort dependence."""
    if len(values) < 2:
        return None
    buckets = defaultdict(list)
    for i, value in enumerate(values):
        day = groups[i] if groups else str(i)
        buckets[day].append(float(value))
    days = list(buckets)
    rng = random.Random(4404)
    samples = []
    for _ in range(n_samples):
        drawn = [buckets[rng.choice(days)] for _ in days]
        flat = [item for group in drawn for item in group]
        samples.append(mean(flat))
    samples.sort()
    lo = max(0, int(alpha/2 * (n_samples-1)))
    hi = min(n_samples-1, int((1-alpha/2)*(n_samples-1)))
    return round(samples[lo],5), round(samples[hi],5)


def _records() -> list[dict[str, Any]]:
    """One source-signal opportunity per cohort, including NO_TRADE decisions."""
    init_research()
    with _connect() as db:
        decisions = [dict(r) for r in db.execute("""
            SELECT cohort_id,symbol,created_at,action,method,snapshot_json
            FROM v44_decisions WHERE kind='ENTRY'
              AND event_key LIKE '%ADAPTIVE_ENTRY_DECISION'
            ORDER BY id""").fetchall()]
        positions = [dict(r) for r in db.execute("""
            SELECT cohort_id,variant,side,status,net_r,entry,stop,entered_at
            FROM v44_shadow_positions""").fetchall()]
        pending = [dict(r) for r in db.execute("""
            SELECT cohort_id,method,status FROM v44_pending""").fetchall()]
    pos_by=defaultdict(dict)
    for position in positions:
        pos_by[position["cohort_id"]][position["variant"]]=position
    pending_by=defaultdict(list)
    for p in pending:
        if p["method"]!="SOURCE_FIXED_2R":
            pending_by[p["cohort_id"]].append(p)
    results=[]
    for d in decisions:
        try:
            context=json.loads(d["snapshot_json"] or "{}")
        except ValueError:
            context={}
        variants=pos_by[d["cohort_id"]]
        baseline=variants.get("SOURCE_FIXED_2R")
        adaptive=variants.get("ENTRY_ADAPTIVE")
        control_r = (_f(baseline["net_r"]) if baseline and
                     baseline["status"]=="CLOSED" and baseline["net_r"] is not None else None)
        adaptive_r=None
        if adaptive:
            if adaptive["status"]=="CLOSED" and adaptive["net_r"] is not None:
                adaptive_r=_f(adaptive["net_r"])
        elif d["action"]=="NO_TRADE" or (pending_by[d["cohort_id"]] and all(
            p["status"] in ("EXPIRED","CANCELLED") for p in pending_by[d["cohort_id"]]
        )):
            adaptive_r=0.0
        entry=context.get("entry") or {}
        trend=context.get("trend") or {}
        market=context.get("market") or {}
        src=context.get("source_row") or {}
        results.append({
            "cohort_id":d["cohort_id"],"symbol":d["symbol"],
            "signal_at":d["created_at"],"day":d["created_at"][:10],
            "source_matched":bool(context.get("source_cohort_matched")),
            "source_side":src.get("bias"),"adaptive_side":adaptive["side"] if adaptive else None,
            "action":d["action"],"entry_method":entry.get("method"),
            "source_score":_f(src.get("long_score") if src.get("bias")=="LONG" else src.get("short_score")),
            "distance_ema_atr":_f(src.get("distance_ema20_atr")),
            "volume_ratio":_f(src.get("volume_ratio_1h")),
            "oi_change_pct":_f(src.get("oi_change_pct")),
            "trend_phase":trend.get("phase"),"trend_direction":trend.get("direction"),
            "trend_exhaustion":_f(trend.get("exhaustion")),
            "btc_regime":market.get("btc_regime"),"risk_state":market.get("risk_state"),
            "guardian_event_key":market.get("guardian_event_key"),
            "control_r":control_r,"adaptive_r":adaptive_r,
            "delta_r":adaptive_r-control_r if adaptive_r is not None and control_r is not None else None,
            "exit_a_r":_f(variants["EXIT_A_TREND"]["net_r"]) if (
                variants.get("EXIT_A_TREND") and variants["EXIT_A_TREND"]["net_r"] is not None
                and variants["EXIT_A_TREND"]["status"]=="CLOSED") else None,
            "exit_b_r":_f(variants["EXIT_B_RUNNER"]["net_r"]) if (
                variants.get("EXIT_B_RUNNER") and variants["EXIT_B_RUNNER"]["net_r"] is not None
                and variants["EXIT_B_RUNNER"]["status"]=="CLOSED") else None,
        })
    return results


def _paired_summary(rows: list[dict], value_key: str = "delta_r",
                    *, alpha: float = 0.05) -> dict:
    valid=[r for r in rows if r.get(value_key) is not None]
    deltas=[_f(r[value_key]) for r in valid]
    days=[r["day"] for r in valid]
    ci=_bootstrap_interval(deltas,alpha=alpha,groups=days)
    return {
        "cohorts_all":len(rows),"cohorts_resolved":len(valid),
        "censored_or_unmatched":len(rows)-len(valid),
        "independent_days":len(set(days)),
        "mean_delta_r":round(mean(deltas),5) if deltas else None,
        "total_delta_r":round(sum(deltas),5),
        "bootstrap_clustered_95pct_interval":ci,
        "status": "INSUFFICIENT_DATA" if len(valid)<MIN_HOLDOUT_COHORTS or len(set(days))<MIN_HOLDOUT_DAYS else (
            "PROMISING_EXPLORATORY" if ci and ci[0]>0 else
            "WEAKENED_EXPLORATORY" if ci and ci[1]<0 else "INCONCLUSIVE"),
    }


def compare_exit_variants(cohorts: list[dict] | None = None) -> dict:
    rows=cohorts if cohorts is not None else _records()
    paired=[]
    for r in rows:
        if r["exit_a_r"] is not None and r["exit_b_r"] is not None:
            paired.append({**r,"exit_delta_r":r["exit_b_r"]-r["exit_a_r"]})
    result=_paired_summary(paired,"exit_delta_r")
    result["comparison"]="EXIT_B_RUNNER_MINUS_EXIT_A_TREND"
    result["cohorts_original"]=len(rows)
    result["cohorts_unresolved"]=len(rows)-len(paired)
    result["out_of_sample_validated"]=False
    result["paper_promotion"]="REQUIRES_EXPLICIT_USER_APPROVAL"
    return result


def pending_outcomes() -> dict:
    with _connect() as db:
        counts={r["status"]:r["n"] for r in db.execute(
            "SELECT status,COUNT(*) AS n FROM v44_pending WHERE method!='SOURCE_FIXED_2R' GROUP BY status"
        ).fetchall()}
    cohorts=_records()
    skipped=[r for r in cohorts if r["adaptive_r"]==0 and r["control_r"] is not None]
    return {
        "states":counts,"measured_skipped":len(skipped),
        "avoided_losses":sum(1 for r in skipped if r["control_r"]<0),
        "missed_winners":sum(1 for r in skipped if r["control_r"]>0),
        "skipped_control_total_r":round(sum(r["control_r"] for r in skipped),5),
        "unresolved_skips":sum(1 for r in cohorts if r["action"]=="NO_TRADE" and r["control_r"] is None),
        "assumption":"Matched fixed-2R counterfactual fills only; no guarantee of real execution",
    }


def paper_case_comparison(cohorts: list[dict]) -> dict:
    """Match exact paper cohort IDs; NEVER compare opposite-direction outcomes."""
    init_research()
    with _connect() as db:
        try:
            cases={r["strategy_id"]:str(r["short_name"]).upper() for r in
                   db.execute("SELECT strategy_id,short_name FROM strategy_cases").fetchall()}
            trades=[dict(r) for r in db.execute(
                "SELECT strategy_id,side,r_multiple,entry_context FROM battle_trades").fetchall()]
        except Exception:
            return {"status":"PAPER_CASE_TABLES_UNAVAILABLE","matches":{}}
    paper=defaultdict(dict)
    for trade in trades:
        try:
            ctx=json.loads(trade.get("entry_context") or "{}")
        except ValueError:
            continue
        cohort_id=ctx.get("cohort_id")
        if cohort_id and cases.get(trade["strategy_id"]) in ("C","F"):
            paper[cohort_id][cases[trade["strategy_id"])]=trade
    pairs=defaultdict(list)
    incompatible=0
    for row in cohorts:
        if not row["source_matched"] or row["adaptive_r"] is None:
            continue
        for case in ("C","F"):
            tr=paper[row["cohort_id"]].get(case)
            if not tr:
                continue
            if row["adaptive_side"] != tr["side"]:
                incompatible+=1
                continue
            pairs[case].append({**row,"case_delta_r":row["adaptive_r"]-_f(tr["r_multiple"])})
    return {
        "same_direction_only":True,"opposite_direction_excluded":incompatible,
        "cases":{k:_paired_summary(v,"case_delta_r") for k,v in pairs.items()},
        "status":"RESEARCH_COMPARISON_NOT_CAUSAL",
    }


def _feature_matches(row: dict, spec: dict) -> bool:
    field=spec.get("feature")
    if field == "distance_ema_atr":
        return _f(row.get(field)) >= _f(spec.get("threshold"),float("inf"))
    if field == "trend_exhaustion":
        return _f(row.get(field)) >= _f(spec.get("threshold"),float("inf"))
    if field in ("btc_regime","trend_phase","risk_state"):
        return str(row.get(field))==str(spec.get("equals"))
    return False


def _evaluate_frozen_hypothesis(spec: dict, registered: str,
                                cohorts: list[dict], n_tests: int) -> dict:
    holdout=[r for r in cohorts if r["signal_at"]>registered and r["control_r"] is not None]
    triggered=[r for r in holdout if _feature_matches(r,spec)]
    # The prospective candidate policy is SKIP entry on matching signals.
    # For all other cohorts candidate follows the baseline (0 difference).
    effects=[{**r,"effect_r":-_f(r["control_r"])} for r in triggered]
    alpha=0.05/max(1,n_tests)  # conservative multiplicity adjustment
    outcome=_paired_summary(effects,"effect_r",alpha=alpha)
    positive=sum(1 for r in triggered if r["control_r"]>0)
    negative=sum(1 for r in triggered if r["control_r"]<0)
    enough=(len(triggered)>=MIN_TRIGGERED_HOLDOUT
            and len(holdout)>=MIN_HOLDOUT_COHORTS
            and len({r["day"] for r in triggered})>=MIN_HOLDOUT_DAYS)
    ci=_bootstrap_interval([-r["control_r"] for r in triggered],alpha=alpha,
                           groups=[r["day"] for r in triggered])
    if not enough:
        verdict="INSUFFICIENT_OUT_OF_SAMPLE"
    elif ci and ci[0]>0:
        verdict="PROMISING_OUT_OF_SAMPLE"
    elif ci and ci[1]<0:
        verdict="WEAKENED_OUT_OF_SAMPLE"
    else:
        verdict="INCONCLUSIVE"
    return {
        "verdict":verdict,"rule":"SKIP_IF_MATCHED","cohorts_oos":len(holdout),
        "cohorts_triggered":len(triggered),"triggered_days":len({r["day"] for r in triggered}),
        "avoided_losses":negative,"missed_winners":positive,
        "mean_effect_r":outcome["mean_delta_r"],
        "total_effect_r":outcome["total_delta_r"],
        "interval_adjusted_for_hypotheses":ci,
        "holdout_started_at":registered,
        "out_of_sample_validated":verdict=="PROMISING_OUT_OF_SAMPLE",
    }


def _discover_candidates(cohorts: list[dict]) -> list[tuple[str,str,dict,dict]]:
    completed=[r for r in cohorts if r["control_r"] is not None]
    if len(completed)<MIN_TRAIN_SAMPLES:
        return []
    distance=sorted(r["distance_ema_atr"] for r in completed)
    if not distance:
        return []
    median=distance[len(distance)//2]
    specs=[
        {"feature":"distance_ema_atr","threshold":round(max(0.5,median),2)},
        {"feature":"trend_exhaustion","threshold":60},
        {"feature":"btc_regime","equals":"NEUTRAL"},
        {"feature":"trend_phase","equals":"EXHAUSTED"},
        {"feature":"risk_state","equals":"CAUTION"},
        {"feature":"risk_state","equals":"EVENT_LOCK"},
    ]
    results=[]
    for spec in specs:
        group=[r for r in completed if _feature_matches(r,spec)]
        outside=[r for r in completed if not _feature_matches(r,spec)]
        if len(group)<MIN_TRAIN_SAMPLES or len(outside)<MIN_TRAIN_SAMPLES:
            continue
        group_mean=mean(r["control_r"] for r in group)
        other_mean=mean(r["control_r"] for r in outside)
        # Candidate arises from actual observed negative control expectancy.
        # This is discovery-only, never report the in-sample gain as validated.
        if group_mean>=-0.10 or group_mean>=other_mean-0.10:
            continue
        frozen={"type":"SKIP_IF","version":"V4.4.2",
                "policy_action":"SKIP","feature":spec["feature"],
                "threshold":spec.get("threshold"),"equals":spec.get("equals"),
                "direction":"SOURCE_SIDE","timeframe":"15m"}
        spec_label=(f">={spec['threshold']}" if spec.get("threshold") is not None
                    else f"={spec.get('equals')}")
        title=f"Skip weak {spec['feature']} {spec_label}"
        rationale=(f"Training: {len(group)} matching cohorts had source expectancy "
                   f"{group_mean:+.3f}R vs {other_mean:+.3f}R outside. "
                   "Candidate is not validated until prospectively evaluated.")
        results.append((title,rationale,frozen,
                        {"matching":len(group),"matching_mean_r":round(group_mean,4),
                         "outside_mean_r":round(other_mean,4)}))
    results.sort(key=lambda x:x[3]["matching_mean_r"]-x[3]["outside_mean_r"])
    return results


def _register_and_evaluate(cohorts: list[dict]) -> list[dict]:
    init_research()
    with _connect() as db:
        existing=[dict(r) for r in db.execute("SELECT * FROM v44_hypotheses ORDER BY created_at").fetchall()]
    active=sum(1 for r in existing if r["status"] in ("TESTING","INSUFFICIENT_OUT_OF_SAMPLE"))
    candidates=_discover_candidates(cohorts)
    for title,rationale,spec,evidence in candidates:
        if active>=MAX_ACTIVE_RESEARCH:
            break
        from hashlib import sha256
        identity=sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:20]
        if any(r["hypothesis_id"]==identity for r in existing):
            continue
        ident=register_hypothesis(title,rationale,spec)
        # register_hypothesis hashes the entire spec; keep it immutable forever.
        with _connect() as db:
            row=db.execute("SELECT * FROM v44_hypotheses WHERE hypothesis_id=?",(ident,)).fetchone()
            if row:
                existing.append(dict(row))
                active+=1
    n_tests=len(existing)
    outcomes=[]
    for hyp in existing:
        spec=json.loads(hyp["spec_json"] or "{}")
        if spec.get("type")!="SKIP_IF":
            continue
        evaluation=_evaluate_frozen_hypothesis(spec,hyp["created_at"],cohorts,n_tests)
        status=evaluation["verdict"]
        with _connect() as db:
            db.execute("UPDATE v44_hypotheses SET status=?,evaluation_json=? WHERE hypothesis_id=?",
                       (status,json.dumps(evaluation,ensure_ascii=False),hyp["hypothesis_id"]))
        if status=="PROMISING_OUT_OF_SAMPLE":
            upsert_proposal(hyp["hypothesis_id"],spec,evaluation)
        outcomes.append({"hypothesis_id":hyp["hypothesis_id"],"title":hyp["title"],**evaluation})
    return outcomes


def market_diagnostics(cohorts: list[dict]) -> dict:
    results={}
    for field in ("trend_phase","btc_regime","risk_state","entry_method"):
        groups=defaultdict(list)
        for r in cohorts:
            if r["control_r"] is not None:
                groups[str(r.get(field) or "UNKNOWN")].append(r["control_r"])
        results[field]={
            key:{"resolved_cohorts":len(v),"source_fixed_2r_mean":round(mean(v),4)}
            for key,v in groups.items()}
    return results


def news_attribution_audit(cohorts: list[dict]) -> dict:
    with _connect() as db:
        try:
            events=[dict(r) for r in db.execute(
                "SELECT event_key,created_at,headline,impact_score FROM news_guardian_events"
            ).fetchall()]
        except Exception:
            events=[]
    known={str(r["event_key"]) for r in events}
    exposed=[r for r in cohorts if r.get("guardian_event_key")]
    linked=sum(1 for r in exposed if str(r["guardian_event_key"]) in known)
    unlinked=len(exposed)-linked
    return {
        "news_guardian_events":len(events),
        "cohort_snapshots_claiming_event":len(exposed),
        "linked_to_saved_event":linked,"unlinked_event_keys":unlinked,
        "causal_attribution":"NOT_SUPPORTED_BY_TEMPORAL_OVERLAP_ALONE",
        "data_quality":"VERIFY" if unlinked else "NO_UNLINKED_KEYS_FOUND",
    }


def research_snapshot() -> dict:
    cohorts=_records()
    exits=compare_exit_variants(cohorts)
    hypotheses=_register_and_evaluate(cohorts)
    entry_delta=_paired_summary(cohorts)
    result={
        "version":"4.4.2","generated_at":utcnow(),"mode":"SHADOW",
        "status":"EXPLORATORY_UNTIL_HOLDOUT_PASSES",
        "cohort_count":len(cohorts),"entry_vs_fixed_2r":entry_delta,
        "exit_comparison":exits,"pending_outcomes":pending_outcomes(),
        "paper_cases":paper_case_comparison(cohorts),
        "market_diagnostics":market_diagnostics(cohorts),
        "news_attribution":news_attribution_audit(cohorts),
        "hypothesis_evaluations":hypotheses,
        "overview":research_overview(limit=50),
        "out_of_sample_validated":any(x.get("out_of_sample_validated") for x in hypotheses),
        "promotion_requires_user_approval":True,
    }
    return result


def write_research_report(day: str, root: Path | None = None) -> dict:
    local=datetime.now(ZoneInfo(settings.timezone)).date()
    if day not in {local.isoformat(),(local-timedelta(days=1)).isoformat()}:
        raise ValueError("Historical V4.4 state must not be reconstructed from future aggregates")
    payload=research_snapshot()
    payload["report_day"]=day
    folder=(root or report_root())/day
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"v44-research.json").write_text(
        json.dumps(payload,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    entry=payload["entry_vs_fixed_2r"]
    ex=payload["exit_comparison"]
    pending=payload["pending_outcomes"]
    md=[
        f"# V4.4 Shadow Strategy Lab — {day}",
        f"Generated: {payload['generated_at']}",
        "Status: EXPLORATORY / NO PAPER CASE AUTO-ACTIVATION",
        "## Adaptive Entry vs source Fixed 2R",
        f"Evaluated cohorts: {entry['cohorts_all']}; complete paired: {entry['cohorts_resolved']}; "
        f"censored: {entry['censored_or_unmatched']}",
        f"Paired mean: {entry['mean_delta_r']}R; clustered CI: "
        f"{entry['bootstrap_clustered_95pct_interval']}; verdict: {entry['status']}",
        "## Smart Exit A vs B",
        f"Matched: {ex['cohorts_resolved']}; EX-B minus EX-A: {ex['mean_delta_r']}R; "
        f"verdict: {ex['status']}",
        "## Pending outcomes",
        f"Avoided losses: {pending['avoided_losses']}; missed winners: "
        f"{pending['missed_winners']} (only measurable controls)",
        "## Autonomous hypotheses",
    ]
    for h in payload["hypothesis_evaluations"]:
        md.append(f"- {h['title']}: {h['verdict']} | future cohorts "
                  f"{h['cohorts_oos']} | triggered {h['cohorts_triggered']} "
                  f"| mean effect {h['mean_effect_r']}R")
    md.extend([
        "## News provenance",
        f"Unlinked event keys: {payload['news_attribution']['unlinked_event_keys']}; "
        "temporal overlap is not proof of causation.",
        "## Paper promotion",
        "A proposal is only created after prospective held-out evidence; USER approval required.",
        "## Safety",
        "No A/B/C/D/E/F rule changes. No live-money trading.",
    ])
    markdown="\n\n".join(md)+"\n"
    (folder/"v44-research.md").write_text(markdown,encoding="utf-8")
    body="<h1>V4.4 Shadow Strategy Lab</h1>"+"".join(
        "<p>"+html.escape(line)+"</p>" for line in md[1:])
    (folder/"v44-research.html").write_text(
        "<!doctype html><html lang='vi'><meta charset='utf-8'><title>V4.4 Research</title>"
        "<style>body{font:15px system-ui;background:#0b1321;color:#eaf1ff;padding:2rem;"
        "max-width:1100px;margin:auto}p{padding:.45rem;border-bottom:1px solid #26334d}</style>"
        "<body>"+body+"</body></html>",encoding="utf-8")
    return payload
