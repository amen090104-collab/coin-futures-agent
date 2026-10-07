from types import SimpleNamespace

from app.trade_journal import build_decision_thesis


def test_decision_thesis_preserves_entry_snapshot():
    row = {
        "reasons_long": ["1h breakout", "volume expansion"],
        "reasons_short": [],
        "long_score": 88,
        "short_score": 31,
        "rsi_1h": 64,
        "volume_ratio_1h": 1.7,
        "atr_pct_1h": 2.2,
        "oi_change_pct": 1.4,
        "funding_rate": 0.0002,
        "distance_ema20_atr": 2.3,
    }
    plan = SimpleNamespace(
        side="LONG",
        score=88.0,
        entry_context={"btc_regime": "BULLISH"},
    )
    spec = {
        "strategy_id": "CASE_E",
        "name": "Adaptive E",
        "version": 3,
        "direction_mode": "BASE",
        "rr": 1.5,
        "exit_mode": "ADAPTIVE",
    }
    out = build_decision_thesis(
        row,
        plan,
        spec,
        {"articles": 2, "high_impact": 0, "bias": "BULLISH"},
        {"target_reason": "nearest structure 1.3R"},
    )
    assert out["thesis"]["side"] == "LONG"
    assert out["thesis"]["score"] == 88.0
    assert out["case_snapshot"]["version"] == 3
    assert out["market_snapshot"]["distance_ema20_atr"] == 2.3
    assert any("entry trễ" in x for x in out["thesis"]["risks"])
