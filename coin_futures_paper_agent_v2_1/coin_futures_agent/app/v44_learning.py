"""V4.4 unattended research evaluation with cohort-level paired validation.

Evidence is exploratory until the prospectively held-out cohort set has been
observed. No automatic PAPER promotion, no order creation, no hyperparameter
search. Always include failed and censored trials in reporting.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .storage import _connect
from .v44_research import init_research, register_hypothesis, research_overview, utcnow
from .report_sync import report_root


HYPOTHESES = (
    ("ENTRY_PENDING", "Pending confirmations avoid late entries",
     "Compare filled, expired, cancelled and missed opportunities over initial signal cohorts."),
    ("EXIT_B_VS_A", "Partial TP / Trend Runner improves Trend-Aware exit",
     "EX-B minus EX-A on the same cohort and identical initial entry, stop and market path."),
    ("MARKET_RESTRICTIONS", "Market context restrictions improve outcomes",
     "Measure both rejected winners and avoided losses; blocked signals must be recorded."),
)


def _bootstrap_interval(deltas: list[float], *, n_samples: int = 400) -> tuple[float, float] | None:
    if len(deltas) < 2:
        return None
    rng = random.Random(4404)
    n = len(deltas)
    estimates = sorted(mean(deltas[rng.randrange(n)] for _ in range(n)) for _ in range(n_samples))
    return round(estimates[int(0.025*(n_samples-1))],4), round(estimates[int(0.975*(n_samples-1))],4)


def compare_exit_variants() -> dict[str, Any]:
    init_research()
    with _connect() as db:
        rows = db.execute("""SELECT cohort_id,variant,status,net_r,entered_at
            FROM v44_shadow_positions WHERE variant IN ('EXIT_A_TREND','EXIT_B_RUNNER')""").fetchall()
    cohorts=defaultdict(dict)
    for row in rows:
        cohorts[row["cohort_id"]][row["variant"]]=dict(row)
    paired=[]
    incomplete=0
    days=set()
    for variants in cohorts.values():
        a=variants.get("EXIT_A_TREND")
        b=variants.get("EXIT_B_RUNNER")
        if not a or not b or a["status"]!="CLOSED" or b["status"]!="CLOSED" or a["net_r"] is None or b["net_r"] is None:
            incomplete+=1
            continue
        paired.append(float(b["net_r"])-float(a["net_r"]))
        days.add(str(a["entered_at"])[:10])
    interval=_bootstrap_interval(paired)
    min_independent=30
    # Time-split holdout and hypothesis preregistration are required before
    # calling a strategy validated. This preliminary experiment cannot self-promote.
    verdict="INSUFFICIENT_DATA" if len(paired)<min_independent or len(days)<5 else (
        "PROMISING_EXPLORATORY" if interval and interval[0]>0 else
        "WEAKENED_EXPLORATORY" if interval and interval[1]<0 else "INCONCLUSIVE"
    )
    return {
        "comparison":"EXIT_B_RUNNER_MINUS_EXIT_A_TREND",
        "complete_matched_cohorts":len(paired),
        "incomplete_or_censored_cohorts":incomplete,
        "observed_days":len(days),
        "mean_delta_r":round(mean(paired),4) if paired else None,
        "bootstrap_95pct_interval":interval,
        "verdict":verdict,"out_of_sample_validated":False,
        "paper_promotion":"USER_APPROVAL_REQUIRED",
        "limitations":["same-market cohorts can be correlated",
                       "exploratory confidence intervals ignore experiment selection",
                       "holdout cohort protocol not yet completed"],
    }


def pending_outcomes() -> dict[str, Any]:
    init_research()
    with _connect() as db:
        rows=db.execute("SELECT status,COUNT(*) AS n FROM v44_pending GROUP BY status").fetchall()
    counts={r["status"]:r["n"] for r in rows}
    return {"states":counts,
            "missed_winner_attribution":"NOT_YET_VERIFIED",
            "evidence":"INSUFFICIENT_FOR_CAUSAL_CONCLUSION"}


def research_snapshot() -> dict[str, Any]:
    init_research()
    ids=[register_hypothesis(title,rationale,{"key":key,"version":"v4.4-shadow.1"})
         for key,title,rationale in HYPOTHESES]
    exits=compare_exit_variants()
    pending=pending_outcomes()
    with _connect() as db:
        for (key,title,rationale),hid in zip(HYPOTHESES,ids):
            evaluation=exits if key=="EXIT_B_VS_A" else pending if key=="ENTRY_PENDING" else {"verdict":"INSUFFICIENT_DATA"}
            db.execute("""UPDATE v44_hypotheses SET status=?,evaluation_json=? WHERE hypothesis_id=?""",
                       (evaluation.get("verdict","INSUFFICIENT_DATA"),json.dumps(evaluation),hid))
    summary=research_overview(limit=40)
    return {"version":"v4.4-shadow.1","generated_at":utcnow(),"mode":"SHADOW",
            "exit_comparison":exits,"pending_outcomes":pending,"overview":summary,
            "out_of_sample_validated":False,"promotion_requires_user_approval":True}


def write_research_report(day: str, root: Path | None = None) -> dict[str, Any]:
    # Never backfill a historic day with current aggregates. Only today's/yesterday's
    # snapshot may be generated as research-state-at-publication.
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    from .config import settings
    local=datetime.now(ZoneInfo(settings.timezone)).date()
    if day not in {local.isoformat(),(local-timedelta(days=1)).isoformat()}:
        raise ValueError("Historical V4.4 research report cannot be reconstructed from future state")
    payload=research_snapshot()
    payload["report_day"]=day
    directory=(root or report_root())/day
    directory.mkdir(parents=True,exist_ok=True)
    (directory/"v44-research.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    exit_data=payload["exit_comparison"]
    markdown=[
        f"# V4.4 Shadow Research — {day}",
        f"Generated: {payload['generated_at']}",
        "Status: EXPLORATORY / NOT PAPER-APPROVED",
        f"Matched closed cohorts: {exit_data['complete_matched_cohorts']}",
        f"Incomplete/censored cohorts: {exit_data['incomplete_or_censored_cohorts']}",
        f"Mean EX-B minus EX-A: {exit_data['mean_delta_r']} R",
        f"Bootstrap 95% interval (descriptive only): {exit_data['bootstrap_95pct_interval']}",
        f"Finding: **{exit_data['verdict']}**",
        "No live/paper strategy mutations performed.",
        "Open questions: prospective out-of-sample test, event attribution, missed winners.",
    ]
    (directory/"v44-research.md").write_text("\n\n".join(markdown)+"\n",encoding="utf-8")
    return payload
