"""V3-only additive schema and provenance-preserving import. Never mutates source tables."""
from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

from .reverse_intelligence import digest, finite, valid_features
from .reverse_intelligence_research import timestamp

VERSION = "rei-v3.1"
SCHEMA = 1


def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def init(db):
    if "rei_v3_meta" in tables(db):
        versions = [r[0] for r in db.execute("SELECT schema_version FROM rei_v3_meta")]
        if versions != [SCHEMA]:
            raise ValueError("INCOMPATIBLE_V3_SCHEMA")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS rei_v3_meta(schema_version INTEGER PRIMARY KEY, version TEXT NOT NULL);
    INSERT OR IGNORE INTO rei_v3_meta VALUES(1,'rei-v3.1');
    CREATE TABLE IF NOT EXISTS rei_v3_samples(
      sample_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, origin TEXT NOT NULL,
      decision_ms INTEGER NOT NULL, label_available_ms INTEGER NOT NULL,
      status TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS rei_v3_sample_time ON rei_v3_samples(decision_ms);
    CREATE TABLE IF NOT EXISTS rei_v3_market_cache(
      cache_key TEXT PRIMARY KEY, fetched_at_ms INTEGER NOT NULL, sha256 TEXT NOT NULL,
      payload TEXT NOT NULL, provenance TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS rei_v3_models(
      model_id TEXT PRIMARY KEY, frozen_at_ms INTEGER NOT NULL, source_side TEXT NOT NULL,
      payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS rei_v3_predictions(
      sample_id TEXT PRIMARY KEY, observed_ms INTEGER NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS rei_v3_jobs(
      sample_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
      retry_after_ms INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS rei_v3_import_issues(
      sample_id TEXT PRIMARY KEY, reason TEXT NOT NULL, first_sha TEXT NOT NULL, conflicting_sha TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS rei_v3_runs(
      run_id TEXT PRIMARY KEY, created_at_ms INTEGER NOT NULL, payload TEXT NOT NULL);
    """)
    db.commit()


def obj(value):
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def opposite(side):
    return {"LONG": "SHORT", "SHORT": "LONG"}.get(side)


def normalized(record, *, origin, key, imported_ms, signal=None):
    """Allowlist only research fields. Secrets/unrelated raw JSON never enter V3 payloads."""
    context = obj(record.get("entry_context"))
    signal = signal or {}
    side = record.get("side")
    source = signal.get("source_side") or context.get("source_signal_side")
    if source not in {"LONG", "SHORT"} or side != opposite(source):
        return None
    try:
        entry = int(record.get("entered_at_ms") or timestamp(record.get("opened_at") or record.get("entered_at")))
        closed = int(record.get("closed_at_ms") or timestamp(record.get("closed_at")))
    except (ValueError, TypeError, OverflowError):
        return None
    outcome = finite(record.get("net_r", record.get("r_multiple")))
    if not (entry > 0 and closed >= entry and outcome is not None and record.get("symbol")):
        return None
    cohort = context.get("cohort_id") or signal.get("cohort_id") or ""
    signal_at = signal.get("signal_ms") or timestamp(str(cohort).split("::")[0])
    # entry time must NOT substitute for a missing original signal timestamp.
    decision = int(signal_at) if 0 < (signal_at or 0) <= entry else 0
    score = finite(signal.get("score", record.get("score")))
    codes = record.get("reason_codes") if "reason_codes" in record else obj(record.get("entry_thesis")).get("reason_codes")
    if isinstance(codes, str):
        try:
            codes = json.loads(codes)
        except ValueError:
            codes = None
    codes_known = isinstance(codes, list) and all(isinstance(c, str) for c in codes)
    row = {"version": VERSION, "sample_id": digest([origin, key, record["symbol"], side, entry]), "origin": origin,
           "symbol": str(record["symbol"]), "source_side": source, "reverse_side": side,
           "source_score": score, "decision_ms": decision, "entry_ms": entry, "closed_ms": closed,
           "label_policy": record.get("strategy_id") or record.get("variant") or record.get("control") or "UNKNOWN",
           "label_available_ms": imported_ms, "historical_label_known_ms": closed,
           "net_r": outcome, "features": {"source_score": score}, "feature_provenance": {},
           "group_id": digest([record["symbol"], source, str(cohort) or decision or entry]),
           "reason_codes": codes if codes_known else [], "reason_codes_known": codes_known,
           "source": {"table_or_export": key[0], "record_id": str(key[1]), "source_cohort": str(cohort),
                      "imported_at_ms": imported_ms, "label_basis": "stored_net_R_not_replayed_fill",
                      "label_precision": "report_export_rounded_R" if origin.endswith("EXPORT") else "database_stored_R",
                      "signal_time_source": "explicit_or_cohort_UTC" if decision else "MISSING"},
           "costs": {"basis": "source_record_net_R", "replay_equivalence": False,
                     "fees": finite(record.get("fees")), "funding_known": False},
           "status": "PENDING_RECONSTRUCTION" if decision else "SIGNAL_TIME_UNRECOVERABLE"}
    return row


def insert(db, row):
    if row is None:
        return False
    old = db.execute("SELECT payload FROM rei_v3_samples WHERE sample_id=?", (row["sample_id"],)).fetchone()
    if old:
        previous = json.loads(old[0])
        keys = ("decision_ms", "entry_ms", "closed_ms", "net_r", "source_side", "reverse_side", "source_score")
        before, after = ({k: item.get(k) for k in keys} for item in (previous, row))
        if before != after:
            db.execute("INSERT OR IGNORE INTO rei_v3_import_issues VALUES(?,?,?,?)",
                       (row["sample_id"], "CONFLICTING_SOURCE_RECORD", digest(before), digest(after)))
            previous["status"] = "IMPORT_CONFLICT"
            db.execute("UPDATE rei_v3_samples SET status='IMPORT_CONFLICT',payload=? WHERE sample_id=?",
                       (json.dumps(previous, allow_nan=False), row["sample_id"]))
        return False
    result = db.execute("INSERT OR IGNORE INTO rei_v3_samples VALUES(?,?,?,?,?,?,?)", (
        row["sample_id"], row["group_id"], row["origin"], row["decision_ms"], row["label_available_ms"],
        row["status"], json.dumps(row, allow_nan=False)))
    return bool(result.rowcount)


def import_database(source, target, *, imported_ms=None):
    """Source connection may be SQLite mode=ro. Explicit schema adapters, no paper init."""
    init(target)
    now = int(time.time()*1000) if imported_ms is None else imported_ms
    names = tables(source)
    counts = Counter()
    signals = {}
    if "reverse_lab_signals" in names:
        for raw in source.execute("SELECT * FROM reverse_lab_signals"):
            rec = dict(raw)
            signals[rec["cohort_id"]] = {**rec, "signal_ms": rec["observed_at_ms"]}
    for trade_table in ("battle_trades", "trades"):
        if trade_table not in names:
            continue
        for raw in source.execute("SELECT * FROM "+trade_table+" ORDER BY id"):
            rec = dict(raw)
            context = obj(rec.get("entry_context"))
            # Do not guess side from strategy names. Require recorded reverse provenance.
            if not (context.get("strategy_reverse") or obj(context.get("case_config")).get("direction_mode") == "REVERSE"
                    or context.get("source_signal_side") == opposite(rec.get("side"))):
                continue
            row = normalized(rec, origin="HISTORICAL_PAPER", key=(trade_table, rec["id"]), imported_ms=now)
            counts["imported" if insert(target, row) else "duplicate_or_ineligible"] += 1
    if "reverse_lab_cases" in names:
        for raw in source.execute("SELECT * FROM reverse_lab_cases WHERE status='CLOSED' ORDER BY id"):
            rec = dict(raw)
            row = normalized(rec, origin="HISTORICAL_SHADOW", key=("reverse_lab_cases", rec["id"]),
                             imported_ms=now, signal=signals.get(rec["cohort_id"]))
            counts["imported" if insert(target, row) else "duplicate_or_ineligible"] += 1
    if {"v44_shadow_positions", "v44_pending"} <= names:
        pending = [dict(r) for r in source.execute("SELECT * FROM v44_pending")]
        for raw in source.execute("SELECT * FROM v44_shadow_positions WHERE status='CLOSED' ORDER BY id"):
            rec = dict(raw)
            matches = [p for p in pending if p["cohort_id"] == rec["cohort_id"]
                       and p["symbol"] == rec["symbol"] and timestamp(p["created_at"]) <= timestamp(rec["entered_at"])
                       and ((p["method"] == "SOURCE_FIXED_2R") == (rec["variant"] == "SOURCE_FIXED_2R"))]
            snapshot = obj(matches[0].get("initial_snapshot_json")) if len(matches) == 1 else {}
            source_row = obj(snapshot.get("source_row"))
            if source_row.get("bias") != opposite(rec.get("side")):
                counts["strategy_lab_not_reverse_or_missing_provenance"] += 1
                continue
            rec["entry_context"] = {"source_signal_side": source_row["bias"], "cohort_id": rec["cohort_id"]}
            rec["score"] = source_row.get("long_score" if source_row["bias"] == "LONG" else "short_score")
            row = normalized(rec, origin="HISTORICAL_STRATEGY_LAB", key=("v44_shadow_positions", rec["id"]), imported_ms=now)
            counts["imported" if insert(target, row) else "duplicate_or_ineligible"] += 1
    if "rei_v2_cohorts" in names:
        from .reverse_intelligence_store import dataset
        for rec in dataset(source):
            cid = rec["cohort_id"]
            for control, case in rec.get("controls", {}).items():
                if control == "BASE_CONTROL" or case.get("status") != "CLOSED":
                    continue
                raw = {**case, "symbol": rec["symbol"], "score": rec["features"].get("source_score"), "control": control}
                row = normalized(raw, origin="FORWARD_SHADOW_V2", key=("rei_v2_cases", cid+":"+control),
                                 imported_ms=now, signal={"source_side": rec["source_side"], "cohort_id": cid,
                                                         "signal_ms": rec["observed_at_ms"]})
                if row:
                    row.update(features=rec["features"], feature_provenance={"status": "OBSERVED_SNAPSHOT",
                        "max_source_ms": rec.get("features_available_at_ms", 0)},
                        label_available_ms=case["available_at_ms"] or now,
                        status="READY" if rec.get("quality_ok") else "MISSING_FEATURE",
                        paired_outcomes=rec.get("outcomes", {}), control=control)
                counts["imported" if insert(target, row) else "duplicate_or_ineligible"] += 1
    target.commit()
    return dict(counts)


def import_reports(root, target, *, imported_ms=None):
    init(target)
    now, counts = int(time.time()*1000) if imported_ms is None else imported_ms, Counter()
    for path in sorted(Path(root).glob("????-??-??/daily-report.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("report_date") != path.parent.name:
            counts["invalid_report_date"] += 1
            continue
        for strategy in document.get("strategies", []):
            if strategy.get("direction_mode") != "REVERSE":
                continue
            for rec in strategy.get("trade_details", []):
                if rec.get("trade_id") is None:
                    counts["missing_trade_id"] += 1
                    continue
                # Export has no original cohort/signal clock in some versions; retain as untrainable.
                rec = {**rec, "strategy_id": strategy["strategy_id"], "entry_context": {"source_signal_side": opposite(rec.get("side")),
                                                "cohort_id": rec.get("cohort_id") or ""}}
                row = normalized(rec, origin="HISTORICAL_PAPER_EXPORT",
                                 key=("report:"+strategy["strategy_id"], rec["trade_id"]), imported_ms=now)
                if row:
                    row["source"]["export_sha256"] = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
                counts["imported" if insert(target, row) else "duplicate_or_ineligible"] += 1
    target.commit()
    return dict(counts)


def samples(db):
    if "rei_v3_samples" not in tables(db):
        return []
    return [json.loads(r[0]) for r in db.execute("SELECT payload FROM rei_v3_samples ORDER BY decision_ms,sample_id")]


async def reconstruct_pending(db, history, *, limit=10, now_ms=None):
    from .rei_v3_market import reconstruct, HistoryError
    now = int(time.time()*1000) if now_ms is None else now_ms
    counts = Counter()
    selected = db.execute("""SELECT s.sample_id,s.payload FROM rei_v3_samples s
        LEFT JOIN rei_v3_jobs j USING(sample_id)
        WHERE s.status IN ('PENDING_RECONSTRUCTION','RETRY_HISTORY')
        AND COALESCE(j.retry_after_ms,0)<=? ORDER BY s.decision_ms,s.sample_id LIMIT ?""", (now, max(0, min(50, limit)))).fetchall()
    for sid, payload in selected:
        row = json.loads(payload)
        try:
            features, proof = await reconstruct(history, row)
            row.update(features=features, feature_provenance=proof,
                       status="READY" if valid_features(features) else "MISSING_FEATURE")
        except HistoryError as exc:
            reason = str(exc)
            row.update(status="RETRY_HISTORY" if reason in {"HISTORY_NETWORK_UNAVAILABLE", "RATE_LIMIT_RETRY_LATER"}
                       else "HISTORY_UNRECOVERABLE", feature_provenance={"status": reason})
        db.execute("UPDATE rei_v3_samples SET status=?,payload=? WHERE sample_id=?", (row["status"], json.dumps(row, allow_nan=False), sid))
        db.execute("""INSERT INTO rei_v3_jobs VALUES(?,1,?,?) ON CONFLICT(sample_id) DO UPDATE SET
            attempts=attempts+1,retry_after_ms=excluded.retry_after_ms,status=excluded.status""",
                   (sid, now+3600_000 if row["status"] == "RETRY_HISTORY" else 0, row["status"]))
        db.commit()  # each completed sample is resumable, not all-or-nothing network batch.
        counts[row["status"]] += 1
    return dict(counts)
