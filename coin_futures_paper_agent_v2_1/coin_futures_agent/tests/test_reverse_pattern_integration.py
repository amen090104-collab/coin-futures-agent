"""Prospective REV-E integration tests, isolated SQLite, no network/orders."""
import json

from app import storage
from app.battle_storage import init_battle_db
from app.reverse_execution import VARIANTS
from app.reverse_pattern import VARIANT as E, compact_features
from app.reverse_research import (
    init_reverse_lab, register_reverse_signals, reverse_lab_snapshot,
)


BASE_MS = 1_700_000_000_000
DAY_MS = 86_400_000


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "isolated-pattern.db")
    storage.init_db()
    init_battle_db()
    init_reverse_lab()


def row_features():
    return {
        "symbol": "BTCUSDT", "rsi_1h": 44.0,
        "distance_ema20_atr": 1.1, "volume_ratio_1h": 1.2,
        "oi_change_pct": 1.4, "atr_pct_1h": 2.0,
        "relative_strength_1h_pct": -.4,
        "trend_1h_short": True, "trend_1h_long": False,
        "trend_4h_short": True, "trend_4h_long": False,
    }


def offered(now):
    return [{
        "strategy_id": "REVERSE_RR2", "symbol": "BTCUSDT",
        "side": "LONG", "position_id": 999, "score": 80.0,
        "signal_price": 100.0, "entry_price": 100.0, "stop_loss": 98.0,
        "entry_context": {"cohort_id": f"{now}::BTCUSDT",
                          "source_signal_side": "SHORT"},
    }]


def incoming():
    return {"created_at": "2026-10-19T00:00:00Z",
            "btc_regime": "BEARISH", "all": [row_features()]}


def seed_past(win=True, include_future_close=False):
    # 50 historically closed REV-A observations spanning 10 independent days.
    # These are synthetic integration-test fixtures, never Paper backfills.
    feat = compact_features(row_features(), base_score=80,
                            source_side="SHORT", btc_regime="BEARISH")
    with storage._connect() as db:
        for i in range(50):
            at = BASE_MS + (i // 5) * DAY_MS + (i % 5) * 600_000
            cid = f"past-{i}"
            db.execute("""INSERT INTO reverse_lab_signals(
                cohort_id,symbol,case_c_position_id,source_side,reverse_side,
                score,observed_at_ms,signal_price,risk_distance,btc_regime,
                features_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(
                cid, "BTCUSDT", 10000+i, "SHORT", "LONG", 80.0, at,
                100.0, 2.0, "BEARISH",
                json.dumps({"pattern_features": feat}), "2023-11-14T00:00:00Z"))
            close = at + 3_600_000
            if include_future_close and i == 49:
                close = BASE_MS + 30 * DAY_MS
            db.execute("""INSERT INTO reverse_lab_cases(
                cohort_id,symbol,variant,side,score,signal_price,risk_distance,
                status,cursor_ms,expires_at_ms,closed_at_ms,net_r,state_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                cid,"BTCUSDT","REV_A_FIXED_2R","LONG",80.0,100.0,2.0,
                "CLOSED",at+60000,at+5400000,close,
                1.8 if win else -1.1,"{}"))


def test_ready_pattern_frozen_and_keeps_all_legacy_cases(tmp_path,monkeypatch):
    prepare(tmp_path,monkeypatch)
    seed_past(win=True,include_future_close=True)
    now=BASE_MS+12*DAY_MS
    result=register_reverse_signals(offered(now),incoming(),observed_ms=now)
    assert result["registered"]==1
    assert result["sample"][0]["pattern_status"]=="RESEARCH_CANDIDATE"
    with storage._connect() as db:
        children=[dict(x) for x in db.execute(
            "SELECT * FROM reverse_lab_cases WHERE cohort_id=?",
            (f"{now}::BTCUSDT",)).fetchall()]
        assert len(children)==len(VARIANTS)
        pattern=next(x for x in children if x["variant"]==E)
        assert pattern["status"]=="WAIT_ENTRY"
        frozen=json.loads(pattern["state_json"])["pattern_decision"]
        assert frozen["eligible"] is True
        assert frozen["training_n"]==49  # future closure is excluded
        assert all(x["net_r"] is None for x in children)
        assert db.execute("SELECT COUNT(*) FROM battle_trades").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM battle_positions").fetchone()[0]==0
    again=register_reverse_signals(offered(now),incoming(),observed_ms=now)
    assert again["registered"]==0
    snap=reverse_lab_snapshot()
    assert snap["pattern_learning"]["eligible_at_signal"]==1
    assert snap["variants"][E]["pending"]["WAIT_ENTRY"]==1
    assert snap["recent_cohorts"][0]["reverse_pattern"]["eligible"] is True
    assert snap["pattern_learning"]["out_of_sample_validated"] is False


def test_losing_history_skips_rev_e_but_keeps_controls(tmp_path,monkeypatch):
    prepare(tmp_path,monkeypatch)
    seed_past(win=False)
    now=BASE_MS+12*DAY_MS
    result=register_reverse_signals(offered(now),incoming(),observed_ms=now)
    assert result["registered"]==1
    assert result["sample"][0]["pattern_status"]=="NO_ESTIMATED_EDGE"
    with storage._connect() as db:
        children=[dict(x) for x in db.execute(
            "SELECT * FROM reverse_lab_cases WHERE cohort_id=?",
            (f"{now}::BTCUSDT",)).fetchall()]
        pattern=next(x for x in children if x["variant"]==E)
        assert pattern["status"]=="EXPIRED"
        assert pattern["reason"]=="PATTERN_NO_ESTIMATED_EDGE"
        assert pattern["net_r"] is None
        assert sum(x["status"]!="EXPIRED" for x in children)==4
    snap=reverse_lab_snapshot()
    assert snap["pattern_learning"]["eligible_at_signal"]==0
    assert snap["variants"][E]["pending"]["EXPIRED"]==1
