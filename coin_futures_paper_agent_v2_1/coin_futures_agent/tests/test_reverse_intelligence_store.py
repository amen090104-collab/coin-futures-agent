"""Isolated Shadow/HTTP fixtures only. Never read the runtime database or network."""
import asyncio
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from app import storage
from app.config import settings
from app import reverse_intelligence_store as rei
from app.reverse_intelligence_research import replay
from app.reverse_research import init_reverse_lab
from app.battle_storage import init_battle_db


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "v44_shadow_enabled", True)
    monkeypatch.setattr(settings, "reverse_entry_intelligence_enabled", True)
    storage.init_db()
    init_battle_db()
    init_reverse_lab()
    monkeypatch.setattr(rei, "build_trade_plan", lambda *a: SimpleNamespace(
        score=80., signal_price=100., entry=100., stop_loss=99.))
    return tmp_path


def scan(stamp="1970-01-01T00:01:00Z"):
    return {"created_at": stamp, "btc_regime": "NEUTRAL", "all": [{
        "symbol": "XUSDT", "bias": "LONG", "long_score": 80., "short_score": 10.,
        "rsi_1h": 55., "distance_ema20_atr": 1., "atr_pct_1h": 2., "volume_ratio_1h": 1.2,
        "oi_change_pct": 0., "funding_rate": 0., "price": 100., "atr_15m": 1., "ema20_15m": 99.,
        "research_provenance": {"available_at_ms": 60_000, "max_source_time_ms": 59_999,
                                "oi_observed": False, "funding_observed": False}}]}


def bar(index, o=100., h=100.3, l=99.7, c=100.):
    return {"open_time": index * 60_000, "close_time": (index + 1)*60_000-1,
            "open": o, "high": h, "low": l, "close": c}


class FakeMarket:
    def __init__(self, bars): self.bars = bars
    async def klines_1m_between(self, *args): return pd.DataFrame(self.bars)


def original_tables():
    with storage._connect() as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if not r[0].startswith(("rei_v2_", "sqlite_"))]
        return {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}"')] for name in names}


def test_collect_all_base_opportunities_without_case_c_and_preserve_existing_tables(isolated):
    before = original_tables()
    result = rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    assert result["registered"] == 1
    assert rei.register(scan(), {"XUSDT": object()}, [], observed_ms=80_000)["registered"] == 0
    row = rei.dataset()[0]
    assert row["legacy_cohort_id"] is None and row["quality_ok"]
    assert row["features"]["oi_change_pct"] is None
    assert row["features"]["funding_rate"] is None
    assert set(row["controls"]) == set(rei.CONTROL_VARIANTS)
    assert row["prediction"]["action"] == "NO_TRADE" and row["prediction"]["score"] is None
    assert all(c["cursor_ms"] == 120_000 for c in row["controls"].values())
    assert original_tables() == before


def test_disabled_collector_makes_no_schema_or_data_changes(isolated, monkeypatch):
    monkeypatch.setattr(settings, "reverse_entry_intelligence_enabled", False)
    assert rei.register(scan(), {}, [], observed_ms=70_000)["status"] == "DISABLED"
    assert asyncio.run(rei.monitor())["status"] == "DISABLED"
    with storage._connect() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='rei_v2_cohorts'").fetchone()


def test_future_feature_timestamp_is_recorded_as_invalid_without_simulated_fills(isolated):
    data = scan()
    data["all"][0]["research_provenance"]["max_source_time_ms"] = 90_000
    rei.register(data, {"XUSDT": object()}, [], observed_ms=70_000)
    row = rei.dataset()[0]
    assert not row["quality_ok"] and not row["controls"] and not row["outcomes"]


def test_invalid_plan_remains_visible_in_opportunity_log(isolated, monkeypatch):
    monkeypatch.setattr(rei, "build_trade_plan", lambda *a: None)
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    assert not rei.dataset()[0]["quality_ok"]
    assert rei.overview()["cohorts"] == 1


def test_monitor_uses_future_closed_bars_and_labels_first_seen_time(isolated):
    before = original_tables()
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    candles = [bar(2, h=100.5, l=97., c=99.)]
    asyncio.run(rei.monitor(client=FakeMarket(candles), observed_ms=200_000))
    row = rei.dataset()[0]
    now = row["controls"]["REVERSE_NOW"]
    assert now["status"] == "CLOSED" and now["net_r"] > 1.
    assert now["entered_at_ms"] == 120_000
    assert now["available_at_ms"] == 200_000 > now["closed_at_ms"]
    with storage._connect() as db:
        assert db.execute("SELECT first_seen_at_ms FROM rei_v2_bars").fetchone()[0] == 200_000
    assert original_tables() == before


def test_gap_censors_instead_of_inventing_a_win(isolated):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    asyncio.run(rei.monitor(client=FakeMarket([bar(3)]), observed_ms=250_000))
    row = rei.dataset()[0]
    assert all(c["status"] == "CENSORED" for c in row["controls"].values())
    assert row["outcomes"] == {} and row["label_available_at_ms"] == 0


def test_costs_are_frozen_at_registration_and_replay_can_stress_them(isolated, monkeypatch):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    row = rei.dataset()[0]
    candles = [bar(2, h=100.5, l=97., c=99.)]
    baseline = replay(row, candles)["REVERSE_NOW"]
    expensive = replay(row, candles, override_costs={"fee_bps": 30., "slippage_bps": 15.})["REVERSE_NOW"]
    assert expensive["net_r"] < baseline["net_r"]
    monkeypatch.setattr(settings, "taker_fee_bps", 100.)
    asyncio.run(rei.monitor(client=FakeMarket(candles), observed_ms=200_000))
    assert rei.dataset()[0]["controls"]["REVERSE_NOW"]["net_r"] == baseline["net_r"]


def test_replay_detects_missing_minutes(isolated):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    states = replay(rei.dataset()[0], [bar(3)])
    assert all(s["status"] == "CENSORED" and s["net_r"] is None for s in states.values())


def test_model_feature_dataset_can_be_exported_with_read_only_sqlite(isolated):
    import sqlite3
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    with sqlite3.connect(storage.DB_PATH.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        assert len(rei.dataset(db)) == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO rei_v2_models VALUES('x',1,'{}')")


def test_api_overview_reports_no_fake_probability(isolated, monkeypatch):
    from app.main import reverse_entry_api
    # Backward-compatible FULL mode keeps old research inspection for
    # historical data. LEAN moves it to the standalone worker.
    monkeypatch.setattr(settings, "runtime_profile", "full")
    result = asyncio.run(reverse_entry_api(limit=30))
    assert result["status"] == "INSUFFICIENT_DATA" and not result["out_of_sample_validated"]
    assert not result["score_is_win_probability"]


def test_expired_confirmation_is_zero_no_entry_not_a_loss(isolated):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    state = rei.dataset()[0]["controls"]["WAIT_CONFIRMATION"]
    # Replay a complete flat future path, never skipping minutes to reach expiry.
    from app.reverse_execution import advance_reverse
    index = 2
    while state["status"] not in {"EXPIRED", "CENSORED", "CLOSED"}:
        state = advance_reverse(state, bar(index)); index += 1
    assert state["status"] == "EXPIRED" and state["net_r"] is None and state["entered_at_ms"] is None


def test_duplicate_monitor_pass_cannot_change_first_seen_or_closed_outcome(isolated):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    candles = [bar(2, h=100.5, l=97., c=99.)]
    asyncio.run(rei.monitor(client=FakeMarket(candles), observed_ms=200_000))
    first = rei.dataset()[0]["controls"]["REVERSE_NOW"]
    asyncio.run(rei.monitor(client=FakeMarket(candles), observed_ms=250_000))
    second = rei.dataset()[0]["controls"]["REVERSE_NOW"]
    assert first == second


def test_ambiguous_bar_uses_stop_first_and_includes_fees(isolated):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    states = replay(rei.dataset()[0], [bar(2, h=102., l=97., c=100.)])
    assert states["REVERSE_NOW"]["net_r"] < -1


def test_revised_market_bar_is_not_overwritten(isolated):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    asyncio.run(rei.monitor(client=FakeMarket([bar(2)]), observed_ms=200_000))
    with storage._connect() as db:
        original = dict(db.execute("SELECT * FROM rei_v2_bars").fetchone())
        # A second valid cohort needs the same minute; the saved bar is immutable.
        db.execute("UPDATE rei_v2_cases SET cursor_ms=120000 WHERE status NOT IN ('CLOSED','CENSORED','EXPIRED')")
        for rec in db.execute("SELECT cohort_id,control,payload_json FROM rei_v2_cases"):
            state = json.loads(rec["payload_json"]); state["cursor_ms"] = 120000
            db.execute("UPDATE rei_v2_cases SET payload_json=? WHERE cohort_id=? AND control=?",
                       (json.dumps(state),rec["cohort_id"],rec["control"]))
    asyncio.run(rei.monitor(client=FakeMarket([bar(2, h=100.4)]), observed_ms=250_000))
    with storage._connect() as db:
        assert dict(db.execute("SELECT * FROM rei_v2_bars").fetchone()) == original
    assert all(c["status"] == "CENSORED" for c in rei.dataset()[0]["controls"].values())


def test_unknown_btc_regime_is_not_neutral(isolated):
    row = scan()["all"][0]
    features, _, _ = rei.freeze_features(row, "LONG", None, 70_000)
    assert features["btc_unknown"] == 1 and features["btc_neutral"] == 0


def test_v2_provenance_does_not_change_existing_base_scores(isolated, monkeypatch):
    from app.scanner import _frames
    from app.scoring import score_symbol
    from app.json_safe import json_safe
    import math
    candles = pd.DataFrame([{"open_time": i*900000, "close_time": (i+1)*900000-1,
        "open": 100+math.sin(i), "high": 102+math.sin(i), "low": 98+math.sin(i),
        "close": 100+math.cos(i), "volume": 1000+i, "quote_volume": 100000+i} for i in range(220)])
    class Client:
        async def klines(self,*args): return candles.copy()
        async def oi_history(self,*args): return []
    results = []
    for flag in (False, True):
        monkeypatch.setattr(settings, "reverse_entry_intelligence_enabled", flag)
        frames, oi = asyncio.run(_frames(Client(),"XUSDT"))
        results.append(json_safe(score_symbol(frames, .0001, oi, 0)))
    assert results[0] == results[1]


def test_wait_expiry_is_stored_as_zero_but_not_a_realized_loss(isolated):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    with storage._connect() as db:
        for rec in db.execute("SELECT * FROM rei_v2_cases"):
            state = json.loads(rec["payload_json"])
            state.update(status="EXPIRED" if rec["control"] == "WAIT_CONFIRMATION" else "CLOSED",
                         entered_at_ms=None if rec["control"] == "WAIT_CONFIRMATION" else 120000,
                         closed_at_ms=200000, net_r=None if rec["control"] == "WAIT_CONFIRMATION" else -1.1)
            db.execute("UPDATE rei_v2_cases SET status=?,available_at_ms=?,payload_json=? WHERE cohort_id=? AND control=?",
                       (state["status"],250000,json.dumps(state),rec["cohort_id"],rec["control"]))
    row=rei.dataset()[0]
    assert row["outcomes"]["WAIT_CONFIRMATION"] == 0
    assert row["controls"]["WAIT_CONFIRMATION"]["net_r"] is None
    assert row["label_available_at_ms"] == 250000


def test_nonfinite_candle_censors_without_storing_fake_outcome(isolated):
    rei.register(scan(), {"XUSDT": object()}, [], observed_ms=70_000)
    asyncio.run(rei.monitor(client=FakeMarket([bar(2, h=float('nan'))]), observed_ms=200_000))
    row=rei.dataset()[0]
    assert all(c["status"] == "CENSORED" for c in row["controls"].values())
    assert not row["outcomes"]
