"""Evidence-first investigation of EVERY closed Paper loss (LONG and SHORT).

Offline only. Each target loss may use only earlier, already-closed peers from
the same case and side to propose testable filters. No claim of causation, no
changed TP/SL outcomes, and no live or Paper orders. Store unresolved losses.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
from statistics import median

VERSION = "loss-inquiry-preregistered-v1"
FEATURES = ("score", "rsi_1h", "atr_pct_1h", "volume_ratio_1h",
            "distance_ema20_atr", "oi_change_pct")
MIN_PEER_WINS = 8
MIN_PEER_LOSSES = 8
MIN_SELECTED = 8
MAX_PREVIOUS_PEERS = 200
MAX_HYPOTHESES_PER_LOSS = 3


def timestamp(value):
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def _number(trade, field):
    x = trade.get("feature_values") or {}
    if not isinstance(x, dict):
        return None
    return finite(x.get(field))


def _mean_r(rows):
    values = [finite(t.get("r_multiple")) for t in rows]
    return round(sum(values) / len(values), 5) if values and None not in values else None


def _suggestions(target, peers):
    previous_wins = [p for p in peers if p["net_pnl"] > 0]
    previous_losses = [p for p in peers if p["net_pnl"] < 0]
    baseline = _mean_r(peers)
    proposals = []
    for field in FEATURES:
        observed = _number(target, field)
        win_features = [_number(x, field) for x in previous_wins]
        lose_features = [_number(x, field) for x in previous_losses]
        win_values = [x for x in win_features if x is not None]
        lose_values = [x for x in lose_features if x is not None]
        if observed is None or len(win_values) < MIN_PEER_WINS or len(lose_values) < MIN_PEER_LOSSES:
            continue
        wcenter, lcenter = median(win_values), median(lose_values)
        if abs(wcenter - lcenter) < 1e-12:
            continue
        boundary = round((wcenter + lcenter) / 2.0, 6)
        comparator = ">=" if wcenter > lcenter else "<="
        select = (lambda value: value >= boundary) if comparator == ">=" else (
            lambda value: value <= boundary)
        # The candidate must be capable of rejecting the examined losing case.
        if select(observed):
            continue
        prior_known = [p for p in peers if _number(p, field) is not None]
        historical_pass = [p for p in prior_known if select(_number(p, field))]
        historical_fail = [p for p in prior_known if not select(_number(p, field))]
        if len(historical_pass) < MIN_SELECTED or len(historical_fail) < MIN_SELECTED:
            continue
        both_win_loss = (sum(x["net_pnl"] > 0 for x in historical_pass) / len(historical_pass),
                         sum(x["net_pnl"] > 0 for x in historical_fail) / len(historical_fail))
        improvement = both_win_loss[0] - both_win_loss[1]
        if improvement <= 0.05:
            continue
        pass_r = _mean_r(historical_pass)
        fail_r = _mean_r(historical_fail)
        # Historical association is evidence to investigate, not an OOS test.
        proposal = {
            "id": f'{field}_{comparator}_{boundary}',
            "rule": {"feature": field, "operator": comparator, "threshold": boundary},
            "observed_at_entry": observed,
            "prior_win_median": round(wcenter, 6),
            "prior_loss_median": round(lcenter, 6),
            "prior_known_wins": len(win_values),
            "prior_known_losses": len(lose_values),
            "peer_baseline_mean_R": baseline,
            "peer_rule_pass": {"count": len(historical_pass),
                               "win_rate": round(both_win_loss[0], 4),
                               "mean_R": pass_r},
            "peer_rule_fail": {"count": len(historical_fail),
                               "win_rate": round(both_win_loss[1], 4),
                               "mean_R": fail_r},
            "descriptive_win_rate_difference": round(improvement, 4),
            "status": "EXPLORATORY_ONLY_REQUIRES_INDEPENDENT_TEST_AND_FORWARD_SHADOW",
            "this_loss_would_be_filtered": True,
            "missed_winners_in_prior_data": sum(p["net_pnl"] > 0 for p in historical_fail),
            "is_verified_cause": False,
        }
        proposals.append(proposal)
    return sorted(proposals, key=lambda p: (
        -p["descriptive_win_rate_difference"],
        p["rule"]["feature"], p["id"]))[:MAX_HYPOTHESES_PER_LOSS]


def investigate_losses(rows):
    # Sort by actual UTC time, not lexicographic ISO representations. Closed
    # labels are only eligible as prior evidence AFTER they are known.
    usable = []
    invalid = 0
    for x in rows:
        opened, closed = timestamp(x.get("opened_at")), timestamp(x.get("closed_at"))
        if opened is None or closed is None or closed < opened or finite(x.get("net_pnl")) is None:
            invalid += 1
            continue
        usable.append((opened, closed, x))
    usable.sort(key=lambda r: (r[0], str(r[2].get("id"))))
    previous = defaultdict(list)
    reviewed = []
    for opened, closed, row in usable:
        group = (row.get("strategy_id"), row.get("side"))
        # Include every Paper case, including configurable E and F. Do not
        # classify E/F as Reverse without saved entry-time configuration.
        visible = [r for r in previous[group][-MAX_PREVIOUS_PEERS:]
                   if r[1] <= opened]
        if row["net_pnl"] < 0:
            peers = [r[2] for r in visible if r[2]["net_pnl"] != 0]
            candidates = _suggestions(row, peers)
            reviewed.append({
                "id": str(row["id"]),
                "strategy_id": row.get("strategy_id"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "opened_at": row.get("opened_at"),
                "closed_at": row.get("closed_at"),
                "realized_R": finite(row.get("r_multiple")),
                "earlier_closed_same_case_side": len(peers),
                "entry_time_features_available": [f for f in FEATURES
                                                  if _number(row, f) is not None],
                "hypotheses": candidates,
                "status": "HYPOTHESES_REQUIRE_UNSEEN_TEST"
                          if candidates else "NO_SUPPORTED_EXPLANATION_YET",
                "cause_proven": False,
                "entry_exit_counterfactual_verified": False,
                "shadow_executed": False,
                "needed": "1m OHLC, point-in-time signal and chronological fee/slippage replay",
            })
        previous[group].append((opened, closed, row))
    grouped = defaultdict(lambda: {"losses": 0, "with_hypotheses": 0, "without_hypotheses": 0})
    for x in reviewed:
        key = x["strategy_id"] + "/" + x["side"]
        grouped[key]["losses"] += 1
        grouped[key]["with_hypotheses" if x["hypotheses"] else "without_hypotheses"] += 1
    return {
        "version": VERSION,
        "scope": "EVERY_VALID_CLOSED_PAPER_LOSS_ALL_CASES_LONG_AND_SHORT",
        "total_closed_trades_considered": len(usable),
        "invalid_or_untimed_trades": invalid,
        "total_losses_investigated": len(reviewed),
        "losses_with_testable_hypotheses": sum(bool(x["hypotheses"]) for x in reviewed),
        "losses_without_supported_hypotheses": sum(not x["hypotheses"] for x in reviewed),
        "by_case_and_side": dict(sorted(grouped.items())),
        "loss_cases": reviewed,
        "causal_findings_verified": 0,
        "historical_results_are_descriptive_only": True,
        "forward_shadow_market_replay_implemented": False,
        "human_review_needed_before_trading": True,
        "real_orders": 0, "paper_orders": 0,
    }
