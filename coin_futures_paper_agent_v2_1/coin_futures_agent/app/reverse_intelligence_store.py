"""Opt-in, additive Shadow dataset. Writes only rei_v2_* tables, never paper/REV-E."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .binance import BinanceClient
from .config import settings
from .reverse_execution import advance_reverse, TERMINAL
from .reverse_intelligence import (VERSION, CORE, ACTIONS, digest, finite, fit_policy,
                                   predict, metrics, day, valid_features, EMBARGO_MS)
from .storage import _connect
from .strategy import build_trade_plan
from .rei_plan_diagnostics import inspect_plan, eligibility, gate_counts

log = logging.getLogger(__name__)
CONTROL_VARIANTS = {"REVERSE_NOW": "REV_A_FIXED_2R", "WAIT_CONFIRMATION": "REV_B_CONFIRMED_2R",
                    "BASE_CONTROL": "REV_A_FIXED_2R", "REV_C_CONTROL": "REV_C_PARTIAL_RUNNER",
                    "REV_D_CONTROL": "REV_D_ADAPTIVE"}


def enabled():
    return bool(settings.reverse_entry_intelligence_enabled and
                (settings.runtime_profile == 'lean' or settings.v44_shadow_enabled))


def now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def clock_value(value):
    try:
        return int(value) if not isinstance(value, bool) else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def init_intelligence():
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS rei_v2_models (
            model_id TEXT PRIMARY KEY, recorded_at_ms INTEGER NOT NULL, manifest_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rei_v2_cohorts (
            cohort_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, source_side TEXT NOT NULL,
            observed_at_ms INTEGER NOT NULL, source_signal_at TEXT, legacy_cohort_id TEXT,
            payload_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS rei_v2_cohort_time ON rei_v2_cohorts(observed_at_ms);
        CREATE TABLE IF NOT EXISTS rei_v2_cases (
            cohort_id TEXT NOT NULL, control TEXT NOT NULL, symbol TEXT NOT NULL,
            status TEXT NOT NULL, cursor_ms INTEGER NOT NULL, available_at_ms INTEGER,
            payload_json TEXT NOT NULL, PRIMARY KEY(cohort_id,control));
        CREATE INDEX IF NOT EXISTS rei_v2_active ON rei_v2_cases(status,symbol,cursor_ms);
        CREATE TABLE IF NOT EXISTS rei_v2_bars (
            symbol TEXT NOT NULL, open_time_ms INTEGER NOT NULL, first_seen_at_ms INTEGER NOT NULL,
            sha256 TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(symbol,open_time_ms));
        """)


def _exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='rei_v2_cohorts'").fetchone() is not None


def dataset(db=None, *, limit=None, before_ms=2**62):
    if db is None:
        with _connect() as connection:
            return dataset(connection, limit=limit, before_ms=before_ms)
    if not _exists(db):
        return []
    selected = list(db.execute("SELECT * FROM rei_v2_cohorts WHERE observed_at_ms < ? ORDER BY observed_at_ms DESC,cohort_id DESC LIMIT ?",
                               (before_ms, -1 if limit is None else int(limit))))
    selected.reverse()
    cases = defaultdict(dict)
    query = ("SELECT * FROM rei_v2_cases WHERE cohort_id IN "
             "(SELECT cohort_id FROM rei_v2_cohorts WHERE observed_at_ms < ? ORDER BY observed_at_ms DESC,cohort_id DESC LIMIT ?) ORDER BY cohort_id,control")
    for rec in db.execute(query, (before_ms, -1 if limit is None else int(limit))):
        state = json.loads(rec["payload_json"])
        cases[rec["cohort_id"]][rec["control"]] = {**state, "available_at_ms": rec["available_at_ms"]}
    result = []
    for rec in selected:
        row = json.loads(rec["payload_json"])
        labels = cases[rec["cohort_id"]]
        row["controls"] = labels
        resolved = all(a in labels and labels[a]["status"] in {"CLOSED", "EXPIRED"}
                       and labels[a].get("closed_at_ms") and labels[a].get("available_at_ms", 0) >= labels[a]["closed_at_ms"]
                       and labels[a]["closed_at_ms"] > row["observed_at_ms"]
                       and ((labels[a]["status"] == "EXPIRED" and labels[a].get("entered_at_ms") is None)
                            or (labels[a]["status"] == "CLOSED" and finite(labels[a].get("net_r")) is not None
                                and row["observed_at_ms"] < (labels[a].get("entered_at_ms") or 0) <= labels[a]["closed_at_ms"]))
                       for a in ACTIONS)
        row["outcomes"] = {a: 0. if labels[a]["status"] == "EXPIRED" else labels[a]["net_r"]
                           for a in ACTIONS} if resolved else {}
        row["label_available_at_ms"] = max(labels[a]["available_at_ms"] for a in ACTIONS) if resolved else 0
        row["label_closed_at_ms"] = max(labels[a]["closed_at_ms"] for a in ACTIONS) if resolved else 0
        result.append(row)
    return result


def freeze_features(row, source_side, regime, observed):
    reverse = "SHORT" if source_side == "LONG" else "LONG"
    features = {key: finite(row.get(key)) for key in (
        "rsi_1h", "distance_ema20_atr", "atr_pct_1h", "volume_ratio_1h",
        "oi_change_pct", "funding_rate", "relative_strength_1h_pct")}
    provenance = row.get("research_provenance") or {}
    for name in ("oi", "funding"):
        if not provenance.get(name + "_observed"):
            features["oi_change_pct" if name == "oi" else "funding_rate"] = None
    features["source_score"] = finite(row.get("long_score" if source_side == "LONG" else "short_score"))
    atr, price, ema = (finite(row.get(k)) for k in ("atr_15m", "price", "ema20_15m"))
    features["signed_ema_distance_atr"] = (price - ema) / atr if atr and atr > 0 and price and ema else None
    for interval in ("1h", "4h"):
        value = row.get(f"trend_{interval}_{reverse.lower()}")
        features[f"trend_{interval}_reverse"] = float(value) if isinstance(value, bool) else None
    features.update(btc_bullish=float(regime == "BULLISH"), btc_bearish=float(regime == "BEARISH"),
                    btc_neutral=float(regime == "NEUTRAL"), btc_unknown=float(regime not in {"BULLISH", "BEARISH", "NEUTRAL"}))
    angle = (observed % 86_400_000) / 86_400_000 * 2 * 3.141592653589793
    import math
    features.update(hour_sin=math.sin(angle), hour_cos=math.cos(angle))
    available = clock_value(provenance.get("available_at_ms"))
    max_source = clock_value(provenance.get("max_source_time_ms"))
    missing = [k for k in CORE if features[k] is None]
    quality = {"missing_core": missing, "missing_optional": [k for k, v in features.items() if v is None],
               "timestamps_valid": 0 < max_source <= available <= observed,
               "provenance": provenance}
    return features, quality, available


def initial_case(control, *, source_side, score, signal_price, risk, observed):
    variant = CONTROL_VARIANTS[control]
    waits = control == "WAIT_CONFIRMATION" or (control == "REV_D_CONTROL" and score < 85)
    return {"variant": variant, "side": source_side if control == "BASE_CONTROL" else "SHORT" if source_side == "LONG" else "LONG",
            "score": score, "signal_price": signal_price, "risk_distance": risk,
            "status": "WAIT_CONFIRM" if waits else "WAIT_ENTRY", "cursor_ms": (observed // 60_000 + 1) * 60_000,
            "expires_at_ms": observed + 90 * 60_000, "entered_at_ms": None, "closed_at_ms": None,
            "net_r": None, "state_json": json.dumps({"confirmation_streak": 0, "fills": []})}


def register(scan, frames, opened, *, observed_ms=None):
    if not enabled():
        return {"status": "DISABLED"}
    observed = observed_ms if observed_ms is not None else now_ms()
    init_intelligence()
    model_asof = observed // 86_400_000 * 86_400_000
    history = dataset(limit=4000, before_ms=model_asof - EMBARGO_MS)
    policies = {side: fit_policy(history, asof_ms=model_asof, source_side=side) for side in ("LONG", "SHORT")}
    legacy = {}
    for position in opened:
        if position.get("strategy_id") != "REVERSE_RR2":
            continue
        context = position.get("entry_context") or {}
        if isinstance(context, str):
            context = json.loads(context)
        legacy[position["symbol"]] = context.get("cohort_id")
    inserted = 0
    diagnostics = []
    with _connect() as db:
        for model in policies.values():
            if model.get("model_id"):
                db.execute("INSERT OR IGNORE INTO rei_v2_models VALUES(?,?,?)",
                           (model["model_id"], observed, json.dumps(model, allow_nan=False)))
        for row in scan.get("all", []):
            side, symbol = row.get("bias"), row.get("symbol")
            if side not in {"LONG", "SHORT"} or not symbol:
                continue
            cid = f"REI2::{scan.get('created_at')}::{symbol}::{side}"
            features, quality, available = freeze_features(row, side, scan.get("btc_regime"), observed)
            try:
                source_date = datetime.fromisoformat(str(scan.get("created_at")).replace("Z", "+00:00"))
                source_time = int(source_date.timestamp()*1000) if source_date.tzinfo is not None else 0
            except (ValueError, TypeError, OverflowError):
                source_time = 0
            quality["source_signal_time_valid"] = 0 < source_time <= observed
            plan, plan_diagnostics = inspect_plan(row, frames.get(symbol), scan.get("btc_regime", "NEUTRAL"), build_trade_plan)
            quality.update(plan_diagnostics)
            quality_ok = bool(plan and quality["plan_gate_reason"] == "PLAN_OK" and valid_features(features)
                              and quality["timestamps_valid"] and quality["source_signal_time_valid"])
            decision = predict(features, policies[side] if quality_ok else {"status": "INVALID_DATA_OR_PLAN"}, source_side=side)
            decision["model_asof_ms"] = model_asof
            payload = {"dataset": VERSION, "cohort_id": cid, "symbol": symbol, "source_side": side,
                       "btc_regime": scan.get("btc_regime", "UNKNOWN"), "observed_at_ms": observed,
                       "features_available_at_ms": available, "features": features, "quality": quality,
                       "quality_ok": quality_ok, "prediction": decision,
                       "signal_price": finite(plan.signal_price) if plan else None,
                       "risk_distance": finite(abs(plan.entry - plan.stop_loss)) if plan else None,
                       "costs": {"fee_bps": settings.taker_fee_bps, "slippage_bps": settings.slippage_bps,
                                 "max_hold_hours": settings.max_hold_hours, "funding_modeled": False},
                       "source_signal_at": scan.get("created_at"), "legacy_cohort_id": legacy.get(symbol)}
            payload["scan_id"] = str(scan.get("created_at"))
            try:
                from .news_guardian import news_entry_guard
                from .storage import get_system_state
                guard = news_entry_guard(symbol)
                state = get_system_state('news_guardian',{}) or {}
                stamp = datetime.fromisoformat(str(state.get('updated_at','')).replace('Z','+00:00')) if state.get('updated_at') else None
                known_at = int(stamp.timestamp()*1000) if stamp and stamp.tzinfo else 0
                if not settings.news_guardian_enabled: known_at=observed
                payload["risk_snapshot"] = {"observed_at_ms": observed, "news_allowed": guard.get("allowed") is True if known_at else None,
                    "news_known_at_ms": known_at, "news_max_age_ms": settings.news_guardian_fresh_minutes*60000,
                    "news_mode": guard.get("mode", "NORMAL")}
            except Exception:
                payload["risk_snapshot"] = {"observed_at_ms": observed, "news_allowed": None, "news_mode": "UNKNOWN"}
            payload["research_eligibility"] = eligibility(payload)
            cur = db.execute("INSERT OR IGNORE INTO rei_v2_cohorts VALUES(?,?,?,?,?,?,?)",
                             (cid, symbol, side, observed, scan.get("created_at"), legacy.get(symbol), json.dumps(payload, allow_nan=False)))
            if not cur.rowcount:
                continue
            inserted += 1
            diagnostics.append(payload)
            # Invalid opportunities remain in the dataset, with no invented fill.
            if not quality_ok:
                continue
            for control in CONTROL_VARIANTS:
                state = initial_case(control, source_side=side, score=plan.score, signal_price=plan.signal_price,
                                     risk=abs(plan.entry - plan.stop_loss), observed=observed)
                db.execute("INSERT INTO rei_v2_cases VALUES(?,?,?,?,?,?,?)",
                           (cid, control, symbol, state["status"], state["cursor_ms"], None, json.dumps(state)))
    summary = gate_counts(diagnostics)
    log.info("REI_PLAN_GATES %s", json.dumps({"scan_id": str(scan.get("created_at")),
             "observed_at_ms": observed, "counts": summary}, ensure_ascii=True))
    return {"status": "SHADOW_ONLY", "registered": inserted, "diagnostics": summary}


async def collect(scan, frames, opened):
    try:
        return await asyncio.to_thread(register, scan, frames, opened)
    except Exception:
        log.exception("Reverse Entry V2 collection failed; paper/REV-E unchanged")
        return {"status": "ERROR"}


def _persist(rec, state, available):
    with _connect() as db:
        result = db.execute("""UPDATE rei_v2_cases SET status=?,cursor_ms=?,available_at_ms=?,payload_json=?
            WHERE cohort_id=? AND control=? AND cursor_ms=? AND status=?""",
                   (state["status"], state["cursor_ms"], available if state["status"] in TERMINAL else None,
                    json.dumps(state, allow_nan=False), rec["cohort_id"], rec["control"], rec["cursor_ms"], rec["status"]))
        return bool(result.rowcount)


async def monitor(*, client=None, observed_ms=None):
    if not enabled():
        return {"status": "DISABLED"}
    init_intelligence()
    observed = observed_ms if observed_ms is not None else now_ms()
    owned = client is None
    if owned:
        client = BinanceClient()
    groups = defaultdict(list)
    with _connect() as db:
        for rec in db.execute("""SELECT c.*,s.payload_json AS cohort_json FROM rei_v2_cases c
            JOIN rei_v2_cohorts s USING(cohort_id) WHERE c.status NOT IN ('CLOSED','CENSORED','EXPIRED')"""):
            groups[rec["symbol"]].append(dict(rec))
    counts = Counter()
    try:
        for symbol, records in groups.items():
            active = []
            for rec in records:
                if observed - rec["cursor_ms"] > 48 * 3600_000:
                    state = json.loads(rec["payload_json"])
                    state.update(status="CENSORED", reason="RECOVERY_OVER_48H", closed_at_ms=observed, net_r=None)
                    _persist(rec, state, observed)
                    counts["censored"] += 1
                else:
                    active.append(rec)
            if not active:
                continue
            try:
                bars = await client.klines_1m_between(symbol, min(r["cursor_ms"] for r in active), observed - 1)
                bars = bars.loc[bars["close_time"] < observed].sort_values("open_time").drop_duplicates("open_time")
                candles = []
                for raw in bars.to_dict("records"):
                    try:
                        candle = {k: int(raw[k]) if k.endswith("time") else float(raw[k])
                                  for k in ("open_time", "close_time", "open", "high", "low", "close")}
                        checksum = digest(candle)
                    except (ValueError, TypeError, KeyError, OverflowError):
                        candles.append((None, False))
                        continue
                    with _connect() as db:
                        db.execute("INSERT OR IGNORE INTO rei_v2_bars VALUES(?,?,?,?,?)",
                                   (symbol, candle["open_time"], observed, checksum, json.dumps(candle)))
                        old = db.execute("SELECT sha256 FROM rei_v2_bars WHERE symbol=? AND open_time_ms=?",
                                         (symbol, candle["open_time"])).fetchone()
                    candles.append((candle, old["sha256"] == checksum))
                for rec in active:
                    state = json.loads(rec["payload_json"])
                    costs = json.loads(rec["cohort_json"])["costs"]
                    changed = False
                    for candle, immutable in candles:
                        if candle is None:
                            state.update(status="CENSORED", reason="INVALID_BAR", net_r=None, closed_at_ms=observed)
                            changed = True
                            break
                        if candle["open_time"] < state["cursor_ms"]:
                            continue
                        if not immutable or candle["open_time"] != state["cursor_ms"]:
                            state.update(status="CENSORED", reason="GAP_OR_REVISED_BAR", net_r=None, closed_at_ms=observed)
                        else:
                            try:
                                state = advance_reverse(state, candle, **costs_for_engine(costs))
                            except (ValueError, TypeError, KeyError):
                                state.update(status="CENSORED", reason="INVALID_BAR", net_r=None, closed_at_ms=observed)
                        changed = True
                        if state["status"] in TERMINAL:
                            break
                    if changed:
                        if _persist(rec, state, observed):
                            counts[state["status"]] += 1
                        else:
                            counts["conflicts"] += 1
            except Exception:
                log.exception("Reverse Entry V2 cannot read market data for %s", symbol)
                counts["market_errors"] += 1
        return {"status": "SHADOW_ONLY", **dict(counts)}
    finally:
        if owned:
            await client.close()


def costs_for_engine(costs):
    return {"fee_bps": costs["fee_bps"], "slippage_bps": costs["slippage_bps"], "max_hold_hours": costs["max_hold_hours"]}


def overview(limit=30):
    rows = dataset(limit=2000)
    resolved = sorted((r for r in rows if r.get("outcomes")), key=lambda r: (r["label_closed_at_ms"], r["cohort_id"]))
    result = {"version": VERSION, "enabled": enabled(), "mode": "SHADOW_ONLY", "cohorts": len(rows),
              "quality_ok": sum(r["quality_ok"] for r in rows), "resolved": len(resolved),
              "status": "EXPLORATORY" if any(r["prediction"].get("score") is not None for r in rows) else "INSUFFICIENT_DATA",
              "score_is_win_probability": False, "out_of_sample_validated": False,
              "analysis_window_limit": 2000,
              "recent": [{k: r[k] for k in ("cohort_id", "symbol", "source_side", "btc_regime", "observed_at_ms", "prediction", "quality")}
                         for r in rows[-limit:][::-1]],
              "decisions": dict(Counter(r["prediction"]["action"] for r in rows)),
              "controls": {a: metrics([r["outcomes"][a] for r in resolved]) for a in ACTIONS},
              "timeline": []}
    result["policy"] = metrics([r["outcomes"].get(r["prediction"]["action"], 0.) for r in resolved])
    result["scored_resolved"] = sum(r["prediction"].get("score") is not None for r in resolved)
    result["additional_control_results"] = {a: metrics([r["controls"][a]["net_r"] for r in rows
        if a in r.get("controls", {}) and r["controls"][a]["status"] == "CLOSED" and finite(r["controls"][a].get("net_r")) is not None])
        for a in ("REV_C_CONTROL", "REV_D_CONTROL")}
    for signal_day in sorted({day(r["observed_at_ms"]) for r in resolved}):
        selected = [r for r in resolved if day(r["observed_at_ms"]) == signal_day]
        result["timeline"].append({"day": signal_day, **metrics([r["outcomes"].get(r["prediction"]["action"], 0.) for r in selected])})
    skipped = [r for r in resolved if r["prediction"]["action"] == "NO_TRADE" or (
        r["prediction"]["action"] in r["controls"] and r["controls"][r["prediction"]["action"]].get("entered_at_ms") is None)]
    result.update(avoided_losses=sum(r["outcomes"]["REVERSE_NOW"] < 0 for r in skipped),
                  missed_winners=sum(r["outcomes"]["REVERSE_NOW"] > 0 for r in skipped))
    result["legacy_matched"] = legacy_comparison(resolved)
    return result


def legacy_comparison(rows):
    """Read exact cohort links only; different observation/fill times remain contextual."""
    matched = defaultdict(list)
    if not rows:
        return {"status": "NO_MATCHED_LEGACY_DATA", "variants": {}}
    with _connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='reverse_lab_cases'").fetchone():
            return {"status": "NO_MATCHED_LEGACY_DATA", "variants": {}}
        reverse = defaultdict(dict)
        for rec in db.execute("SELECT cohort_id,variant,status,net_r FROM reverse_lab_cases"):
            if rec["status"] == "CLOSED" and rec["net_r"] is not None:
                reverse[rec["cohort_id"]][rec["variant"]] = rec["net_r"]
        paper = {}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_trades'").fetchone():
            for rec in db.execute("""SELECT s.cohort_id,t.r_multiple FROM reverse_lab_signals s
                JOIN battle_trades t ON t.position_id=s.case_c_position_id
                WHERE t.strategy_id='REVERSE_RR2' AND t.side=s.reverse_side"""):
                paper[rec["cohort_id"]] = rec["r_multiple"]
        for row in rows:
            legacy = row.get("legacy_cohort_id")
            actual = row["outcomes"].get(row["prediction"]["action"], 0.)
            for name, value in {**reverse.get(legacy, {}), **({"CASE_C": paper[legacy]} if legacy in paper else {})}.items():
                matched[name].append(actual - value)
    return {"status": "CONTEXTUAL_DIFFERENT_FILL_TIMES", "variants": {k: metrics(v) for k, v in matched.items()},
            "note": "Cùng cohort nguồn; thời điểm quan sát/fill khác nhau, không kết luận nhân quả."}


def report_lines(summary):
    if not summary:
        return []
    lines = ["## Reverse Entry Intelligence V2 — nghiên cứu Shadow độc lập",
            f"Trạng thái: {summary['status']}; cohort: {summary['cohorts']}; đủ outcome: {summary['resolved']}.",
            f"Quyết định đóng băng: {summary['decisions']}; bỏ qua lệnh thắng: {summary['missed_winners']}; tránh lệnh thua: {summary['avoided_losses']}.",
            f"Policy V2 theo cohort: {summary.get('policy')}; đối chứng cùng cohort: {summary['controls']}.",
            f"Controls C/D độc lập (chỉ trạng thái CLOSED, tập mẫu có thể khác): {summary.get('additional_control_results')}.",
            f"So sánh với Case C/REV-A/B/C/D/E cũ (nếu có cohort khớp): {summary.get('legacy_matched')}.",
            "Chỉ số 0–100 chưa phải xác suất thắng; chưa đủ bằng chứng lợi nhuận ngoài mẫu. Không đổi Case A/B/C/D hoặc REV-E."]
    for row in summary.get("recent", [])[:5]:
        prediction = row["prediction"]
        lines.append(f"- {row['symbol']}, Base {row['source_side']}: {prediction['action']}, "
                     f"điểm {prediction['score']}; lý do: {' '.join(prediction['reasons'])}")
    return lines
