"""Independent offline Reverse Research engine. Standard library only.

NO trading API, NO Binance order calls, NO GitHub/network transport. All
thresholds/model fitting are restricted to past folds. Reverse is an ANALYSIS
hypothesis: we never manufacture a simulated profit from an ambiguous candle.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import tempfile
import zipfile

MIN_TRAIN = 30
MIN_VALIDATION = 12
MIN_TEST = 12
FEATURES = ("score", "rsi_1h", "atr_pct_1h", "volume_ratio_1h",
            "oi_change_pct", "funding_rate", "distance_ema20_atr",
            "trend_1h_long", "trend_1h_short", "trend_4h_long",
            "trend_4h_short", "btc_regime")
SIDES = ("LONG", "SHORT")


def _number(value):
    if isinstance(value, bool):
        return float(value)
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _context(row):
    source = row.get("entry_context", {})
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except (ValueError, TypeError):
            return {}
    return source if isinstance(source, dict) else {}


def to_observation(row: dict, origin: str) -> dict | None:
    # Only final, closed outcomes. No feature from MFE/MAE, PnL, exit reason,
    # holding time, post-entry news or later reconstructed indicators.
    side = str(row.get("side") or "").upper()
    pnl = _number(row.get("net_pnl"))
    opened, closed = str(row.get("opened_at") or ""), str(row.get("closed_at") or "")
    if side not in SIDES or pnl is None or not opened or not closed:
        return None
    ctx = _context(row)
    score = _number(row.get("score"))
    features = {k: (score if k == "score" else ctx.get(k)) for k in FEATURES}
    for k in FEATURES:
        if k != "btc_regime":
            features[k] = _number(features[k])
        elif features[k] is not None:
            features[k] = str(features[k]).upper()
    trade_id = str(row.get("id") or "")
    if not trade_id:
        return None
    return {"id": origin + ":" + trade_id,
            "strategy_id": str(row.get("strategy_id") or "LEGACY_PAPER"),
            "symbol": str(row.get("symbol") or ""),
            "side": side, "opened_at": opened, "closed_at": closed,
            "net_pnl": pnl, "r_multiple": _number(row.get("r_multiple")),
            "exit_reason": str(row.get("exit_reason") or ""),
            "mfe_r": _number(row.get("mfe_r")),
            "mae_r": _number(row.get("mae_r")),
            "cohort_id": str(ctx.get("cohort_id") or ""),
            "feature_values": features}


def _db_records(db_path: Path):
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, key in (("battle_trades", "battle"), ("trades", "legacy")):
            if table not in tables:
                continue
            for row in db.execute("SELECT * FROM " + table + " ORDER BY id"):
                trade = to_observation(dict(row), key)
                if trade is not None:
                    yield trade


def load_backup(zip_path: Path) -> list[dict]:
    """Read verified snapshot only: never connect to the live trader DB."""
    with zipfile.ZipFile(zip_path) as z:
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("archive_version") != "all-trading-history-v1":
            raise ValueError("UNRECOGNIZED_BACKUP_MANIFEST")
        index = {row["path"]: row["sha256"] for row in manifest.get("files", [])}
        if "agent.db" not in index:
            raise ValueError("NO_VERIFIED_AGENT_DB_IN_ARCHIVE")
        with tempfile.TemporaryDirectory(prefix="reverse-readonly-") as temp:
            tmp_db = Path(temp) / "agent.db"
            sha = hashlib.sha256()
            with z.open("agent.db") as src, tmp_db.open("wb") as dst:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    sha.update(block)
                    dst.write(block)
            if sha.hexdigest() != index["agent.db"]:
                raise ValueError("SOURCE_HISTORY_CHECKSUM_MISMATCH")
            return list(_db_records(tmp_db))


def load_daily(root: Path, *, before_day: str | None = None) -> tuple[list[dict], list[str]]:
    results, rejected = [], []
    if not root.exists():
        return results, rejected
    for file in sorted(root.glob("????-??-??/trade-history.json")):
        try:
            day = file.parent.name
            if before_day and day >= before_day:
                continue  # finalized past sessions only, never today's partial
            doc = json.loads(file.read_text(encoding="utf-8"))
            if doc.get("archive_version") != "local-trades-v1" or doc.get("report_date") != day:
                raise ValueError("WRONG_DAY_OR_VERSION")
            rows = doc["trades"]
            if not isinstance(rows, list) or len(rows) != doc.get("trade_count"):
                raise ValueError("BAD_TRADE_COUNT")
            canonical = json.dumps(rows, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":"), default=str).encode("utf-8")
            if hashlib.sha256(canonical).hexdigest() != doc["sha256"]:
                raise ValueError("DAILY_SHA256_MISMATCH")
            for row in rows:
                obs = to_observation(row, "battle" if row.get("strategy_id") else "legacy")
                if obs is not None:
                    results.append(obs)
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            rejected.append(file.parent.name)
    return results, rejected


def deduplicate(*sets: list[dict]) -> list[dict]:
    # Research never increases count simply because the same trade is in the
    # initial complete SQLite archive and newer daily JSON.
    rows = {}
    for dataset in sets:
        for row in dataset:
            rows[row["id"]] = row
    return sorted(rows.values(), key=lambda x: (x["opened_at"], x["closed_at"], x["id"]))


def _matrix(rows: list[dict], norms: dict | None = None):
    keys = FEATURES[:-1]
    if norms is None:
        norms = {}
        for key in keys:
            nums = [r["feature_values"][key] for r in rows if r["feature_values"].get(key) is not None]
            center = statistics.median(nums) if nums else 0.0
            scale = statistics.pstdev(nums) if len(nums) >= 2 else 1.0
            norms[key] = [center, max(scale, 1e-6)]
    matrix = []
    for row in rows:
        ctx = row["feature_values"]
        columns = [1.0]
        for key in keys:
            center, scale = norms[key]
            val = ctx.get(key)
            columns.append(max(-6.0, min(6.0, (float(val) - center) / scale)) if val is not None else 0.0)
            columns.append(1.0 if val is None else 0.0)
        columns.extend([1.0 if str(ctx.get("btc_regime") or "") == r else 0.0
                        for r in ("UP", "DOWN", "RANGE", "NEUTRAL", "BULL", "BEAR")])
        matrix.append(columns)
    return matrix, norms


def _fit(matrix: list[list[float]], labels: list[int]) -> list[float]:
    # Deterministic ridge-regularized logistic fit; only training fold.
    weights = [0.0] * len(matrix[0])
    base = sum(labels) / len(labels)
    weights[0] = math.log(max(0.001, min(0.999, base)) /
                          max(0.001, 1.0 - min(0.999, base)))
    for _ in range(320):
        grads = [0.0] * len(weights)
        for row, label in zip(matrix, labels):
            z = max(-25.0, min(25.0, sum(w * x for w, x in zip(weights, row))))
            delta = 1.0 / (1.0 + math.exp(-z)) - label
            for idx, value in enumerate(row):
                grads[idx] += delta * value
        for idx in range(len(weights)):
            penalty = (0.0 if idx == 0 else 0.03 * weights[idx])
            weights[idx] -= 0.12 * (grads[idx] / len(matrix) + penalty)
    return weights


def _predict(matrix, weights):
    return [1.0 / (1.0 + math.exp(-max(-25.0, min(25.0,
             sum(w * x for w, x in zip(weights, row)))))) for row in matrix]


def _performance(rows, probs, cutoff):
    chosen = [row for row, p in zip(rows, probs) if p >= cutoff]
    known_r = [x["r_multiple"] for x in chosen if x["r_multiple"] is not None]
    return {"selected": len(chosen), "win_rate": round(sum(x["net_pnl"] > 0 for x in chosen) / len(chosen), 4)
            if chosen else None,
            "avg_realized_r": round(statistics.mean(known_r), 4) if len(known_r) == len(chosen)
            and chosen else None}


def evaluate_side(rows: list[dict], side: str) -> dict:
    selected = sorted((r for r in rows if r["side"] == side and r["net_pnl"] != 0),
                      key=lambda x: (x["opened_at"], x["id"]))
    n = len(selected)
    b1, b2 = int(0.60 * n), int(0.80 * n)
    if b1 < MIN_TRAIN or b2 - b1 < MIN_VALIDATION or n - b2 < MIN_TEST:
        return {"status": "INSUFFICIENT_HISTORY", "side": side, "n": n,
                "need_at_least": max(math.ceil(MIN_TRAIN / .60),
                                     math.ceil(MIN_VALIDATION / .20),
                                     math.ceil(MIN_TEST / .20)),
                "placed_paper_orders": 0}
    # Outcome visibility: a position opened in training but closed after the
    # validation boundary cannot be a known label at that historical time.
    train_start = selected[b1]["opened_at"]
    train = [x for x in selected[:b1] if x["closed_at"] <= train_start]
    validation = selected[b1:b2]
    test = selected[b2:]
    if len(train) < MIN_TRAIN or len({x["opened_at"][:10] for x in train}) < 3:
        return {"status": "TRAIN_LABELS_NOT_YET_KNOWN", "side": side,
                "n": n, "visible_train": len(train),
                "excluded_late_labels": b1 - len(train), "placed_paper_orders": 0}
    # More than one Paper case on one coin at the same signal time shares a
    # cohort: report correlated folds, never fabricate independence.
    train_x, normalizers = _matrix(train)
    val_x, _ = _matrix(validation, normalizers)
    test_x, _ = _matrix(test, normalizers)
    weights = _fit(train_x, [int(x["net_pnl"] > 0) for x in train])
    val_prob = _predict(val_x, weights)
    # Threshold selection allowed ONLY on validation data.
    candidate = [(t, _performance(validation, val_prob, t)) for t in (0.50, 0.55, 0.60, 0.65, 0.70)]
    qualified = [(t, p) for t, p in candidate if p["selected"] >= 5 and
                 p["avg_realized_r"] is not None]
    if not qualified:
        return {"status": "INSUFFICIENT_VALIDATION", "side": side,
                "n_train": len(train), "n_val": len(validation),
                "n_test": len(test), "placed_paper_orders": 0}
    chosen_cutoff, val_stats = max(qualified, key=lambda x: (x[1]["avg_realized_r"], -x[0]))
    test_prob = _predict(test_x, weights)
    test_stats = _performance(test, test_prob, chosen_cutoff)
    baseline_test = _performance(test, [1.0] * len(test), .5)
    return {"status": "RESEARCH_ONLY_NOT_DEPLOYED", "side": side, "n": n,
            "fit": len(train), "validation": len(validation), "test": len(test),
            "late_labels_purged": b1 - len(train), "selected_cutoff_on_validation": chosen_cutoff,
            "validation_only": val_stats, "out_of_sample_test": test_stats,
            "out_of_sample_baseline": baseline_test,
            "test_days": len({x["opened_at"][:10] for x in test}),
            "test_cohorts": len({x["cohort_id"] or x["id"] for x in test}),
            "warning": ("Correlated A-F cases may share a cohort; results are "
                        "descriptive and must be independently forward validated."),
            "placed_paper_orders": 0, "weights": [round(x, 6) for x in weights],
            "normalizers": normalizers}


def summarize_differences(rows):
    output = {}
    for case in sorted({x["strategy_id"] for x in rows}):
        subset = [x for x in rows if x["strategy_id"] == case]
        wins = [x for x in subset if x["net_pnl"] > 0]
        losses = [x for x in subset if x["net_pnl"] < 0]
        fields = {}
        for field in ("score", "rsi_1h", "atr_pct_1h", "volume_ratio_1h",
                      "oi_change_pct", "distance_ema20_atr"):
            w = [x["feature_values"][field] for x in wins if x["feature_values"][field] is not None]
            l = [x["feature_values"][field] for x in losses if x["feature_values"][field] is not None]
            if len(w) >= 5 and len(l) >= 5:
                fields[field] = {"win_avg": round(statistics.mean(w), 4),
                                 "loss_avg": round(statistics.mean(l), 4),
                                 "samples": [len(w), len(l)]}
        output[case] = {"closed": len(subset), "wins": len(wins), "losses": len(losses),
                        "realized_pnl": round(sum(x["net_pnl"] for x in subset), 4),
                        "win_rate": round(len(wins) / (len(wins) + len(losses)), 4)
                        if wins or losses else None, "feature_contrasts": fields}
    return output


def paired_reverse(rows):
    cohorts = defaultdict(dict)
    for r in rows:
        if r["cohort_id"]:
            cohorts[(r["cohort_id"], r["symbol"])][r["strategy_id"]] = r
    pairs = (("BASE_RR2", "REVERSE_RR2"), ("BASE_RR1", "REVERSE_RR1"))
    out = {}
    for left, right in pairs:
        found = [(x[left], x[right]) for x in cohorts.values() if left in x and right in x]
        out[left + "_VS_" + right] = {"matched_cohorts": len(found),
            "base_wins_reverse_loses": sum(a["net_pnl"] > 0 and b["net_pnl"] < 0 for a, b in found),
            "base_loses_reverse_wins": sum(a["net_pnl"] < 0 and b["net_pnl"] > 0 for a, b in found),
            "both_lose": sum(a["net_pnl"] < 0 and b["net_pnl"] < 0 for a, b in found),
            "both_win": sum(a["net_pnl"] > 0 and b["net_pnl"] > 0 for a, b in found)}
    return out


def propose_recovery_experiments(rows):
    """Hypotheses, not backdated fake wins. Intrabar ordering is unknown."""
    losers = [x for x in rows if x["net_pnl"] < 0]
    variants = []
    for tp_r in (0.5, 1.0, 1.5, 2.0):
        with_path = [x for x in losers if x["mfe_r"] is not None and x["mae_r"] is not None]
        possible = sum(x["mfe_r"] >= tp_r for x in with_path)
        variants.append({"alternative": "TP_" + str(tp_r) + "_R",
                         "observed_losers": len(losers),
                         "with_MFE_MAE": len(with_path),
                         "could_reach_target_at_some_time": possible,
                         "proven_new_wins": 0,
                         "status": "HYPOTHESIS_NEEDS_CHRONOLOGICAL_CANDLE_REPLAY",
                         "caveat": "MFE/MAE extrema cannot establish which of SL and TP was hit first"})
    return variants


def study(rows):
    return {"research_version": "reverse-independent-v1",
            "source": "PAST_CLOSED_TRADES_ONLY",
            "real_trade_orders": 0, "paper_trade_orders": 0,
            "total_unique_closed_trades": len(rows),
            "per_case_win_loss": summarize_differences(rows),
            "matched_reverse_comparisons": paired_reverse(rows),
            "long_short_models": {side: evaluate_side(rows, side) for side in SIDES},
            "loss_recovery_hypotheses": propose_recovery_experiments(rows),
            "next": ("Gather chronological OHLC bars and run honest event-by-event "
                     "counterfactual paper replay, with fees, slippage and separate "
                     "holdout before calling any alternative an improvement.")}


def save_json_atomic(path: Path, value: dict) -> None:
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".reverse-", delete=False) as tmp:
        p = Path(tmp.name)
        json.dump(value, tmp, indent=2, ensure_ascii=False, allow_nan=False, default=str)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(p, path)
