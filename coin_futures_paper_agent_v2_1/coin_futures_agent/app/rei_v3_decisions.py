"""Independent opt-in V3 Shadow execution. Never touches Paper accounts or orders APIs."""
import json
from collections import Counter

from .config import settings
from .rei_plan_diagnostics import eligibility
from .rei_v3_models import calibrated_score
from .reverse_intelligence import (ACTIONS, finite, day, metrics, cluster_interval,
                                   walk_forward, fit_policy, predict, digest)
from .reverse_intelligence_store import initial_case, costs_for_engine
from .reverse_execution import advance_reverse, TERMINAL

# Reuse the existing V2 research review floor, not a newly tuned score threshold.
MIN_OOS_COHORTS, MIN_OOS_DAYS = 100, 14


def init_orders(db):
    db.execute("""CREATE TABLE IF NOT EXISTS rei_v3_orders(
        sample_id TEXT PRIMARY KEY, created_at_ms INTEGER NOT NULL, status TEXT NOT NULL,
        cursor_ms INTEGER NOT NULL, payload TEXT NOT NULL)""")


def policy_evidence(rows, *, side, now_ms):
    known = [r for r in rows if r.get("source_side") == side and 0 < r.get("label_available_at_ms", 0) < now_ms]
    wf = walk_forward(known)
    tested = [p for p in wf["predictions"] if p["resolved"] and p["score"] is not None]
    values = [p["outcomes"].get(p["action"], 0.) for p in tested]
    paired = [(p["test_day"], v-p["outcomes"]["BASE_CONTROL"]) for p, v in zip(tested, values)]
    ci = cluster_interval(paired)
    stats = metrics(values)
    controls = {a: metrics([p["outcomes"][a] for p in tested]) for a in ACTIONS}
    days = len({p["test_day"] for p in tested})
    gates = {"OOS_MIN_COHORTS": len(tested) >= MIN_OOS_COHORTS, "OOS_MIN_DAYS": days >= MIN_OOS_DAYS,
        "OOS_POSITIVE_EXPECTANCY": (stats["expectancy_r"] or 0) > 0,
        "OOS_BASE_DELTA_CI_POSITIVE": bool(ci and ci[0] > 0),
        "OOS_DRAWDOWN_NOT_WORSE_THAN_NOW": bool(values) and stats["serial_drawdown_r"] <= controls["REVERSE_NOW"]["serial_drawdown_r"]}
    return {"qualified": all(gates.values()), "gates": gates, "scored_cohorts": len(tested), "days": days,
            "policy": stats, "controls": controls, "paired_base_delta_95pct": ci,
            "basis": "V2_matched_chronological_forward_shadow_fills_after_fees_slippage",
            "funding_modeled": False, "validated_for_real_money": False}


def proposal_evidence(db, rows, *, side, now_ms):
    forecasts={r[0]:json.loads(r[1]) for r in db.execute('SELECT sample_id,payload FROM rei_v3_predictions')}
    paired=[];values=[];benchmark=[];days=set()
    for row in rows:
        p=forecasts.get(row['cohort_id'],{})
        if (row.get('source_side')!=side or not p.get('score_calibrated') or not p.get('proposal_for_evaluation')
                or not 0<p.get('observed_ms',0)<row.get('label_closed_at_ms',0)<=row.get('label_available_at_ms',0)<now_ms
                or not row.get('outcomes')):continue
        action=p.get('candidate_policy_control','NO_TRADE')
        value=row['outcomes'].get(action,0.);base=row['outcomes']['BASE_CONTROL']
        d=day(p['observed_ms']);days.add(d);paired.append((d,value-base));values.append(value)
        benchmark.append(row['outcomes']['REVERSE_NOW'])
    stats=metrics(values);ci=cluster_interval(paired)
    gates={'COMPOSITE_OOS_MIN_COHORTS':len(values)>=MIN_OOS_COHORTS,'COMPOSITE_OOS_MIN_DAYS':len(days)>=MIN_OOS_DAYS,
        'COMPOSITE_OOS_POSITIVE_EXPECTANCY':(stats['expectancy_r'] or 0)>0,
        'COMPOSITE_BASE_DELTA_CI_POSITIVE':bool(ci and ci[0]>0),
        'COMPOSITE_DRAWDOWN_NOT_WORSE_THAN_NOW':bool(values) and stats['serial_drawdown_r']<=metrics(benchmark)['serial_drawdown_r']}
    return {'qualified':all(gates.values()),'gates':gates,'scored_cohorts':len(values),'days':len(days),
        'proposal_policy':stats,'paired_base_delta_95pct':ci,
        'basis':'genuinely_forward_V3_calibrated_proposals_matched_to_V2_shadow_control_fills_not_actual_V3_orders'}


def policies(db, rows, *, now_ms):
    result = {}
    for side in ("LONG", "SHORT"):
        key = f"v34-policy::{now_ms//86400000}::{side}"
        old = db.execute("SELECT payload FROM rei_v3_runs WHERE run_id=?", (key,)).fetchone()
        if old:
            result[side] = json.loads(old[0]); continue
        policy = fit_policy(rows, asof_ms=now_ms, source_side=side)
        proof = policy_evidence(rows, side=side, now_ms=now_ms)
        proof['composite_forward']=proposal_evidence(db,rows,side=side,now_ms=now_ms)
        payload = {"policy": policy, "evidence": proof, "frozen_at_ms": now_ms}
        db.execute("INSERT OR IGNORE INTO rei_v3_runs VALUES(?,?,?)", (key, now_ms, json.dumps(payload, allow_nan=False)))
        result[side] = json.loads(db.execute("SELECT payload FROM rei_v3_runs WHERE run_id=?", (key,)).fetchone()[0])
    db.commit()
    return result


def make_decision(row, model, policy, *, now_ms, active_count=0):
    base = row["source_side"]; reverse = "SHORT" if base == "LONG" else "LONG"
    quality = eligibility(row)
    fresh = 0 <= now_ms-row["observed_at_ms"] <= 60000 and not row.get("outcomes")
    p = finite(row.get("signal_price")); risk = finite(row.get("risk_distance"))
    geometry = bool(p and p > 0 and risk and risk > 0 and (p-risk > 0 if reverse=='LONG' else p-2*risk > 0))
    plan = None
    if geometry:
        d = 1 if reverse == "LONG" else -1
        plan = {"side": reverse, "entry": p, "stop_loss": p-d*risk, "take_profit": p+d*2*risk,
            "risk_distance": risk, "reward_risk": 2., "entry_is_reference_not_fill": True,
            "entry_rule": "NEXT_FUTURE_1M_OPEN_WITH_ADVERSE_SLIPPAGE", "wait_rule": "TWO_CLOSED_1M_CONFIRMATIONS_THEN_NEXT_OPEN"}
    score = calibrated_score(model, row.get("features", {})) if quality["observation_eligible"] and fresh and model.get('source_side')==base else None
    paired = predict(row.get("features", {}), policy.get("policy", {}), source_side=base)
    news = row.get("risk_snapshot", {})
    news_time = news.get("observed_at_ms", 0)
    news_ok = news.get("news_allowed") is True and 0 < news_time <= row["observed_at_ms"]
    if 'news_known_at_ms' in news:
        known=news['news_known_at_ms']
        news_ok=news_ok and 0<known<=row['observed_at_ms'] and row['observed_at_ms']-known<=news.get('news_max_age_ms',0)
    costs = row.get("costs", {})
    costs_ok = all(finite(costs.get(k)) is not None and 0 <= costs[k] < 1000 for k in ("fee_bps", "slippage_bps"))
    costs_ok = costs_ok and (finite(costs.get('max_hold_hours')) or 0)>0
    first_open = (row["observed_at_ms"]//60000+1)*60000
    gates = {"TIMELY_SIGNAL": fresh, "TRADE_PLAN_ELIGIBLE": quality["paired_policy_eligible"] and geometry,
        "CALIBRATED_MODEL": score is not None,
        "MODEL_SOURCE_SIDE_MATCH": model.get('source_side')==base,
        "RESEARCHED_SCORE_THRESHOLD_MET": score is not None and model.get('entry_score_threshold') is not None and score>=model['entry_score_threshold'],
        "MODEL_FROZEN_BEFORE_DECISION": model.get("model_kind") == "FORWARD_FROZEN_MODEL" and model.get("frozen_at_ms", now_ms+1) <= now_ms,
        "FUTURE_ENTRY_WINDOW": now_ms < first_open,
        "SOURCE_SCORE_FILTER": quality["plan_gate_reason"] == "PLAN_OK",
        "NEWS_SNAPSHOT_ALLOWS_ENTRY": news_ok,
        "KNOWN_REGIME": row.get("btc_regime") in {"BULLISH", "BEARISH", "NEUTRAL"},
        "EXECUTION_COSTS_KNOWN": costs_ok,
        "MAX_CONCURRENT_V3": active_count < max(1, settings.reverse_entry_v3_max_open),
        "MATCHED_POLICY_OOS_QUALIFIED": policy.get("evidence", {}).get("qualified") is True,
        "COMPOSITE_FORWARD_OOS_QUALIFIED": policy.get('evidence',{}).get('composite_forward',{}).get('qualified') is True,
        "PAIRED_POLICY_SELECTS_REVERSE": paired.get("action") in {"REVERSE_NOW", "WAIT_CONFIRMATION"},
        "SHADOW_EXECUTION_OPT_IN": settings.reverse_entry_v3_shadow_execution_enabled}
    allowed = all(gates.values())
    proposal_ok=all(passed for name,passed in gates.items() if name not in {
        'MATCHED_POLICY_OOS_QUALIFIED','COMPOSITE_FORWARD_OOS_QUALIFIED','SHADOW_EXECUTION_OPT_IN','MAX_CONCURRENT_V3',
        'RESEARCHED_SCORE_THRESHOLD_MET','PAIRED_POLICY_SELECTS_REVERSE'})
    proposed_control=paired.get('action','NO_TRADE') if proposal_ok and gates['RESEARCHED_SCORE_THRESHOLD_MET'] and gates['PAIRED_POLICY_SELECTS_REVERSE'] else 'NO_TRADE'
    control = paired.get("action", "NO_TRADE") if allowed else "NO_TRADE"
    action = "WAIT_CONFIRMATION" if control == "WAIT_CONFIRMATION" else "REVERSE_"+reverse if control == "REVERSE_NOW" else "NO_TRADE"
    reasons = [name for name, passed in gates.items() if not passed]
    if not fresh: reasons.insert(0, "HISTORICAL_OBSERVED_LATE")
    elif not quality["paired_policy_eligible"]: reasons.insert(0, quality["status"])
    if score is None: reasons.extend(model.get("reason_codes", ["NO_MODEL"]))
    factors = []
    if score is not None:
        from .reverse_intelligence import FEATURES
        for key, median in zip(FEATURES, model["model"]["scaler"]["median"]):
            if finite(row["features"].get(key)) is not None:
                factors.append({"feature": key, "value": row["features"][key],
                    "delta_score": round(score-calibrated_score(model, {**row["features"], key: median}), 4)})
        factors.sort(key=lambda f: abs(f["delta_score"]), reverse=True)
    return {"action": action, "policy_control": control, "score": round(score, 2) if score is not None else None,
        "score_calibrated": score is not None, "score_is_win_probability": False,
        "source_score": row.get("features", {}).get("source_score"), "base_side": base,
        "source_side": base, "reverse_side": reverse, "symbol": row["symbol"],
        "recommendation": reverse if action.startswith("REVERSE_") else "WAIT" if action == "WAIT_CONFIRMATION" else "NO TRADE",
        "candidate_plan": plan, "qualified": allowed, "gates": gates,
        'gate_details':{'source_score':row.get('features',{}).get('source_score'),'model_status':model.get('status'),
            'calibration_n':model.get('calibration_n'),'entry_score_threshold':model.get('entry_score_threshold'),
            'news_snapshot':news,'regime':row.get('btc_regime'),'active_v3':active_count,
            'max_open_v3':settings.reverse_entry_v3_max_open,'future_open_ms':first_open,
            'oos_requirements':{'cohorts':MIN_OOS_COHORTS,'independent_days':MIN_OOS_DAYS},
            'costs':costs,'paired_estimated_net_r':paired.get('expected_net_r')},
        'candidate_policy_control':proposed_control,
        'proposal_for_evaluation':proposal_ok,
        "policy_evidence": policy.get("evidence", {}), "model_kind": model.get("model_kind"),
        "model_id": model.get("model_id"), "model_frozen_at_ms": model.get("frozen_at_ms"),
        "status": "SHADOW_QUALIFIED" if allowed else "HISTORICAL_OBSERVED_LATE" if not fresh else
                  quality["status"] if not quality["paired_policy_eligible"] else "NO_MODEL" if score is None else "NOT_QUALIFIED",
        "reason_codes": reasons or ["ALL_SHADOW_GATES_PASSED"],
        "reasons": ["Các gate false chặn thực thi; score đã calibration trên lịch sử, chưa phải lợi nhuận hay xác suất thắng đã xác minh forward."],
        "research_eligibility": quality, "factors": factors, "observed_ms": now_ms, "signal_ms": row["observed_at_ms"],
        "observation_kind": "TIMELY_PROSPECTIVE" if fresh else "HISTORICAL_OBSERVED_LATE",
        "forward_eligible": fresh and quality["paired_policy_eligible"], "money_mode": "SHADOW_ONLY"}


def create_order(db, row, prediction):
    if not prediction["qualified"]: return False
    state = initial_case(prediction["policy_control"], source_side=row["source_side"],
        score=row["features"]["source_score"], signal_price=row["signal_price"], risk=row["risk_distance"], observed=row["observed_at_ms"])
    payload = {"state": state, "costs": row["costs"], "decision_ms": prediction["observed_ms"],
               "model_id": prediction["model_id"], "policy_control": prediction["policy_control"],
               "symbol": row["symbol"], "source_side": row["source_side"], "fills_are_shadow_only": True}
    cur = db.execute("INSERT OR IGNORE INTO rei_v3_orders VALUES(?,?,?,?,?)", (row["cohort_id"],
        prediction["observed_ms"], state["status"], state["cursor_ms"], json.dumps(payload, allow_nan=False)))
    return bool(cur.rowcount)


def advance_orders(db, *, now_ms):
    """Reuse immutable public bars already collected by V2; no extra network client."""
    init_orders(db)
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "rei_v2_bars" not in names: return {"status": "WAITING_FOR_V2_BARS"}
    counts = Counter()
    for sid, raw in db.execute("SELECT sample_id,payload FROM rei_v3_orders WHERE status NOT IN ('CLOSED','CENSORED','EXPIRED')").fetchall():
        payload = json.loads(raw); state = payload["state"]
        bars = db.execute("SELECT payload_json,sha256,first_seen_at_ms FROM rei_v2_bars WHERE symbol=? AND open_time_ms>=? ORDER BY open_time_ms",
                          (payload["symbol"], state["cursor_ms"])).fetchall()
        changed = False
        if now_ms-state["cursor_ms"] > 48*3600000:
            state.update(status="CENSORED", reason="RECOVERY_OVER_48H", net_r=None, closed_at_ms=now_ms); changed = True
        for raw_bar, checksum, first_seen in bars:
            if state["status"] in TERMINAL: break
            bar = json.loads(raw_bar)
            if bar["close_time"] >= now_ms or first_seen > now_ms: break
            if digest(bar) != checksum or bar["open_time"] != state["cursor_ms"] or bar["open_time"] <= payload["decision_ms"]:
                state.update(status="CENSORED", reason="GAP_OR_INVALID_FUTURE_BAR", net_r=None, closed_at_ms=now_ms)
            else:
                state = advance_reverse(state, bar, **costs_for_engine(payload["costs"]))
            changed = True
        if changed:
            payload["state"] = state
            db.execute("UPDATE rei_v3_orders SET status=?,cursor_ms=?,payload=? WHERE sample_id=?",
                       (state["status"], state["cursor_ms"], json.dumps(payload, allow_nan=False), sid))
            counts[state["status"]] += 1
    db.commit()
    return {"status": "SHADOW_ONLY", **dict(counts)}


def order_summary(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='rei_v3_orders'").fetchone():
        return {"enabled": settings.reverse_entry_v3_shadow_execution_enabled, "orders": 0, "closed": 0}
    rows = [json.loads(r[0]) for r in db.execute("SELECT payload FROM rei_v3_orders ORDER BY created_at_ms,sample_id")]
    closed = [r for r in rows if r["state"]["status"] == "CLOSED"]
    return {"enabled": settings.reverse_entry_v3_shadow_execution_enabled, "orders": len(rows), "closed": len(closed),
            "statuses": dict(Counter(r["state"]["status"] for r in rows)),
            "performance": metrics([r["state"]["net_r"] for r in closed]),
            "recent": rows[-10:][::-1], "real_orders": 0, "funding_modeled": False}
