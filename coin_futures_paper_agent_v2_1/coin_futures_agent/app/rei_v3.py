"""Opt-in V3 orchestrator and read-only overview. All output remains research/Shadow."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import time
from collections import Counter
from pathlib import Path
from contextlib import closing, contextmanager

from . import storage
from .config import settings
from .rei_v3_store import (init, import_database, import_reports, samples, reconstruct_pending, tables,
                           reconstruct_entry_proxies, coverage, VERSION)
from .rei_v3_market import FuturesHistory
from .rei_v3_learning import DAY, fit, decision, differentiators, source_discovery, evaluate, holdout
from .reverse_intelligence import digest, fit_policy, walk_forward
from .reverse_intelligence_store import dataset as v2_dataset

log = logging.getLogger(__name__)


def enabled():
    return bool(settings.reverse_entry_v3_enabled and settings.reverse_entry_intelligence_enabled and settings.v44_shadow_enabled)


@contextmanager
def source_connection(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        yield db


def frozen_models(db, rows, now):
    cutoff = now//DAY*DAY
    hold = db.execute("SELECT payload FROM rei_v3_runs WHERE run_id='holdout-v1'").fetchone()
    excluded = json.loads(hold[0])["groups"] if hold else holdout(rows)
    models = {}
    for side in ("LONG", "SHORT"):
        key = f"daily::{cutoff}::{side}"
        old = db.execute("SELECT payload FROM rei_v3_models WHERE model_id=?", (key,)).fetchone()
        if old:
            models[side] = json.loads(old[0])
        else:
            classifier = fit(rows, asof_ms=cutoff, side=side, excluded_groups=excluded)
            if classifier["status"] != "RESEARCH_CLASSIFIER":
                forward = fit(rows, asof_ms=cutoff, side=side, lane="FORWARD_SHADOW")
                if forward["status"] == "RESEARCH_CLASSIFIER":
                    classifier = forward
            models[side] = classifier
            db.execute("INSERT INTO rei_v3_models VALUES(?,?,?,?)", (key, cutoff, side, json.dumps(classifier, allow_nan=False)))
    db.commit()
    return models


def observe(db, source, *, now_ms):
    """Freeze V3 predictions when seen; late historical V2 rows can never become forward OOS."""
    rows = samples(db)
    models = frozen_models(db, rows, now_ms)
    cohorts = v2_dataset(source, limit=4000)
    cutoff = now_ms//DAY*DAY
    policies = {s: fit_policy(cohorts, asof_ms=cutoff, source_side=s) for s in ("LONG", "SHORT")}
    inserted = 0
    for row in cohorts:
        sid = row["cohort_id"]
        if db.execute("SELECT 1 FROM rei_v3_predictions WHERE sample_id=?", (sid,)).fetchone():
            continue
        out = decision(row["features"], models[row["source_side"]], side=row["source_side"], paired_policy=policies[row["source_side"]])
        fresh = 0 <= now_ms-row["observed_at_ms"] <= 60_000 and not row.get("outcomes")
        if not fresh or not row.get("quality_ok"):
            out.update(score=None, action="NO_TRADE", recommendation="NO TRADE",
                       status="MISSED_DECISION_WINDOW" if not fresh else "MISSING_FEATURE",
                       reason_codes=["MISSED_DECISION_WINDOW" if not fresh else "MISSING_FEATURE"],
                       reasons=["Quan sát muộn hoặc dữ liệu không đạt chuẩn; không ghi nhận như dự đoán OOS."], factors=[])
        out.update(symbol=row["symbol"], source_side=row["source_side"], observed_ms=now_ms,
                   signal_ms=row["observed_at_ms"], model_asof_ms=cutoff, forward_eligible=fresh and row.get("quality_ok", False),
                   model_training_n=models[row["source_side"]].get("training_n", 0))
        db.execute("INSERT OR IGNORE INTO rei_v3_predictions VALUES(?,?,?)", (sid, now_ms, json.dumps(out, allow_nan=False)))
        inserted += 1
    db.commit()
    return inserted


def run_analysis(db, *, now_ms):
    rows = samples(db)
    old = db.execute("SELECT payload FROM rei_v3_runs WHERE run_id='holdout-v1'").fetchone()
    held = json.loads(old[0])["groups"] if old else holdout(rows)
    # Freeze only once usable features span enough days. No silent holdout rollover on next import.
    if not old and held:
        db.execute("INSERT INTO rei_v3_runs VALUES(?,?,?)", ("holdout-v1", now_ms, json.dumps({"groups": held})))
    result = {"retrospective": evaluate(rows, holdout_groups=held),
              "differentiators": differentiators([r for r in rows if r["group_id"] not in held]),
              "source_discovery": source_discovery([r for r in rows if r["group_id"] not in held]),
              "holdout_groups": len(held), "heldout_is_retrospective": True}
    db.execute("INSERT OR REPLACE INTO rei_v3_runs VALUES(?,?,?)", ("latest-analysis", now_ms, json.dumps(result, allow_nan=False)))
    db.commit()
    return result


async def cycle(*, reconstruct_limit=2):
    if not enabled():
        return {"status": "DISABLED"}
    try:
        with closing(storage._connect()) as db:
            init(db)
            with source_connection(storage.DB_PATH) as source:
                imported = import_database(source, db)
            # Public market only; no credentials/current premium/OI endpoints.
            history = FuturesHistory(db)
            try:
                recovered = await reconstruct_pending(db, history, limit=reconstruct_limit)
                proxies = await reconstruct_entry_proxies(db, history, limit=reconstruct_limit)
            finally:
                await history.close()
            now = int(time.time()*1000)
            with source_connection(storage.DB_PATH) as source:
                observe(db, source, now_ms=now)
            # Research can be expensive: only one persisted evaluation per UTC day.
            last = db.execute("SELECT created_at_ms FROM rei_v3_runs WHERE run_id='latest-analysis'").fetchone()
            if not last or last[0]//DAY != now//DAY:
                await asyncio.to_thread(_analysis_connection, now)
            return {"status": "SHADOW_ONLY", "import": imported, "reconstruction": recovered, "entry_context": proxies}
    except Exception:
        log.exception("V3 research failed; existing strategies unchanged")
        return {"status": "RESEARCH_ERROR"}


def _analysis_connection(now):
    with closing(storage._connect()) as db:
        run_analysis(db, now_ms=now)


async def collect():
    """Low-cost prediction path after V2 registration; no market I/O."""
    if not enabled():
        return
    try:
        def work():
            with closing(storage._connect()) as db:
                init(db)
                with source_connection(storage.DB_PATH) as source:
                    observe(db, source, now_ms=int(time.time()*1000))
        await asyncio.to_thread(work)
    except Exception:
        log.exception("V3 observation failed in isolated research task")


def overview(db=None, *, now_ms=None, limit=20):
    if db is None:
        with closing(storage._connect()) as connection:
            return overview(connection, now_ms=now_ms, limit=limit)
    now = int(time.time()*1000) if now_ms is None else now_ms
    rows = samples(db)
    result = {"version": VERSION, "enabled": enabled(), "status": "UNTRAINED", "money_mode": "SHADOW_ONLY",
              "coverage": coverage(db, rows), "first_run_mode": "COLLECT_AND_COVERAGE_ONLY",
              "source_counts": dict(Counter(r["origin"] for r in rows)),
              "statuses": dict(Counter(r["status"] for r in rows)), "total_samples": len(rows),
              "reconstructed": sum(r.get("feature_provenance", {}).get("status") == "RECONSTRUCTED" for r in rows),
              "missingness": {k: sum(r.get("features", {}).get(k) is None for r in rows) for k in
                              ("source_score", "rsi_1h", "atr_pct_1h", "distance_ema20_atr", "volume_ratio_1h", "oi_change_pct", "funding_rate")},
              "recent": [], "models": {}, "analysis": None, "forward": {"status": "INSUFFICIENT_DATA", "scored": 0},
              "limitations": ["Lịch sử phục hồi là retrospective, không phải forward OOS.",
                              "Paper, replay và Shadow có fill/cost khác nhau; không gộp thành hiệu suất tiền thật."]}
    if "rei_v3_models" not in tables(db):
        return result
    for side in ("LONG", "SHORT"):
        rec = db.execute("SELECT frozen_at_ms,payload FROM rei_v3_models WHERE source_side=? ORDER BY frozen_at_ms DESC LIMIT 1", (side,)).fetchone()
        if rec:
            model = json.loads(rec[1])
            result["models"][side] = {k: v for k, v in model.items() if k not in {"model", "fit_groups", "calibration_groups", "search"}}
            result["models"][side]["age_hours"] = round((now-rec[0])/3600_000, 2)
    predictions = {r[0]: json.loads(r[1]) for r in db.execute("SELECT sample_id,payload FROM rei_v3_predictions ORDER BY observed_ms")}
    result["recent"] = list(predictions.values())[-limit:][::-1]
    source_rows = v2_dataset(db, limit=4000)
    forward, missed, avoided = [], 0, 0
    for row in source_rows:
        p = predictions.get(row["cohort_id"])
        if p and p.get("forward_eligible") and row.get("outcomes") and row["label_closed_at_ms"] > p["observed_ms"]:
            forward.append((p, row))
            skipped = p["action"] == "NO_TRADE" or row["controls"].get(p["action"], {}).get("entered_at_ms") is None
            missed += bool(skipped and row["outcomes"]["REVERSE_NOW"] > 0)
            avoided += bool(skipped and row["outcomes"]["REVERSE_NOW"] < 0)
    from .reverse_intelligence import metrics
    scored = [(p, r) for p, r in forward if p["score"] is not None]
    result["forward"] = {"status": "FORWARD_SHADOW_ONLY" if forward else "INSUFFICIENT_DATA",
        "resolved": len(forward), "scored": sum(p["score"] is not None for p, _ in forward),
        "policy": metrics([r["outcomes"].get(p["action"], 0.) for p, r in forward]),
        "controls": {a: metrics([r["outcomes"][a] for _, r in forward]) for a in ("REVERSE_NOW", "WAIT_CONFIRMATION", "BASE_CONTROL")},
        "fills": sum(r["controls"].get(p["action"], {}).get("entered_at_ms") is not None for p, r in forward),
        "missed_winners": missed, "avoided_losses": avoided, "validated_for_money": False}
    result["forward"]["scored_policy"] = metrics([r["outcomes"].get(p["action"], 0.) for p, r in scored])
    result["forward"]["per_side"] = {side: {"n": sum(p["source_side"] == side for p, _ in forward),
        "scored": sum(p["source_side"] == side for p, _ in scored),
        "policy": metrics([r["outcomes"].get(p["action"], 0.) for p, r in scored if p["source_side"] == side])}
        for side in ("LONG", "SHORT")}
    result["forward"]["score_distribution"] = {str(low): sum(low <= p["score"] < low+20 for p, _ in scored) for low in range(0, 101, 20)}
    result["historical_by_policy"] = {policy: {"sample_count": sum(r.get("label_policy") == policy for r in rows),
        "stored_net_r": metrics([r["net_r"] for r in sorted(rows, key=lambda r: r["closed_ms"]) if r.get("label_policy") == policy]),
        "basis": "SOURCE_PAPER_OR_SHADOW_NOT_V3_POLICY"} for policy in sorted({r.get("label_policy", "UNKNOWN") for r in rows})}
    latest = db.execute("SELECT created_at_ms,payload FROM rei_v3_runs WHERE run_id='latest-analysis'").fetchone()
    if latest:
        analysis = json.loads(latest[1])
        analysis["retrospective"].pop("predictions", None)
        result["analysis"] = {**analysis, "evaluated_at_ms": latest[0]}
    result["status"] = "RESEARCH_CLASSIFIER" if any(m.get("status") == "RESEARCH_CLASSIFIER" for m in result["models"].values()) else "INSUFFICIENT_DATA"
    if result["status"] == "RESEARCH_CLASSIFIER":
        result["first_run_mode"] = "EXPLORATORY_SHADOW_SCORE"
    return result


def report_lines(summary):
    if not summary:
        return []
    return ["## Reverse Entry V3 — lịch sử và Shadow tách biệt",
            f"Trạng thái: {summary['status']}; nguồn: {summary['source_counts']}; trạng thái mẫu: {summary['statuses']}.",
            f"Phục hồi chỉ báo: {summary['reconstructed']}/{summary['total_samples']}; thiếu: {summary['missingness']}.",
            f"Coverage theo nguồn / chiều Base (proxy riêng): {summary.get('coverage', {})}.",
            f"Chế độ: {summary.get('first_run_mode', 'COLLECT_AND_COVERAGE_ONLY')}; không có model thì score=null, NO_TRADE.",
            f"Kết quả gốc theo policy (không phải backtest V3): {summary.get('historical_by_policy', {})}.",
            f"Mô hình theo hướng Base / cửa sổ train / tuổi: {summary['models']}.",
            f"Walk-forward / holdout retrospective: {summary['analysis']}.",
            f"Forward Shadow độc lập / fills / missed winner / avoided loss: {summary['forward']}.",
            "Score là classifier nghiên cứu; thiếu đối chứng thì RISK_GATE. Không có xác nhận lợi nhuận tiền thật."]


def main():
    parser = argparse.ArgumentParser(description="V3 research only: source SQLite mode=ro, output SQLite riêng.")
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--reports", type=Path)
    parser.add_argument("--output-db", required=True, type=Path)
    parser.add_argument("--reconstruct", action="store_true", help="Chỉ gọi public historical futures OHLCV")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    target = args.output_db.resolve()
    if args.source_db and target == args.source_db.resolve() or args.reports and args.reports.resolve() in target.parents:
        parser.error("Output phải độc lập với DB/báo cáo nguồn.")
    if not args.source_db and not args.reports:
        parser.error("Cần nguồn DB hoặc reports; không tự tạo mẫu huấn luyện.")
    with sqlite3.connect(target) as db:
        db.row_factory = sqlite3.Row
        init(db)
        if args.source_db:
            with source_connection(args.source_db) as source:
                import_database(source, db)
        if args.reports:
            import_reports(args.reports, db)
        if args.reconstruct:
            async def recover():
                history = FuturesHistory(db)
                try:
                    return await reconstruct_pending(db, history, limit=args.limit)
                finally:
                    await history.close()
            asyncio.run(recover())
            async def recover_proxies():
                history = FuturesHistory(db)
                try:
                    return await reconstruct_entry_proxies(db, history, limit=args.limit)
                finally:
                    await history.close()
            asyncio.run(recover_proxies())
        now = int(time.time()*1000)
        run_analysis(db, now_ms=now)
        frozen_models(db, samples(db), now)
        print(json.dumps(overview(db, now_ms=now), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
