"""Read-only Windows diagnostic. ASCII stdout, allowlisted aggregates, no raw DB/context."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

from .rei_plan_diagnostics import cohort_diagnostics
from .rei_v3 import overview
from .version import version_info


def diagnose(db, *, now_ms=None):
    now = int(time.time()*1000) if now_ms is None else now_ms
    summary = overview(db, now_ms=now, limit=0)
    return {"diagnostic_version": "issue24-v1", "measured_at_ms": now,
            "code": version_info(), "readonly": True,
            "plan_gates": cohort_diagnostics(db, now_ms=now),
            "historical": {"total": summary["total_samples"], "origins": summary["source_counts"],
                           "statuses": summary["statuses"], "coverage": summary["coverage"]},
            "observations": summary.get("observation_counts", {}),
            "frozen_models": summary["models"], "current_training_evidence": summary["training_evidence"],
            "model_banks": summary.get('model_banks',{}), "v3_shadow_execution": summary.get('v3_execution',{}),
            "reconstruction": summary["reconstruction_progress"],
            "note": "Legacy gate reasons cannot be reconstructed without original frames; new scans record exact gates. No training or trading performed."}


def main():
    parser = argparse.ArgumentParser(description="V5 read-only diagnostic; no raw DB, .env or machine paths in output.")
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    source = args.source_db.resolve()
    if args.output_json and args.output_json.resolve() == source:
        parser.error("OUTPUT_MUST_DIFFER_FROM_SOURCE_DB")
    try:
        with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")  # One consistent WAL snapshot across all aggregate queries.
            result = diagnose(db)
        text = json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False)
        if args.output_json:
            output = args.output_json.resolve()
            temporary = output.with_name(output.name+".tmp")
            temporary.write_text(text+"\n", encoding="ascii")
            os.replace(temporary, output)
        print(text)
        return 0
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        print("V5_DIAGNOSTIC_FAILED_NO_DATA_CHANGED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
