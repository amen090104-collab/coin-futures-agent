from app.review import analyze_loss


def test_loss_review_detects_common_risks():
    trade = {
        "side": "LONG",
        "net_pnl": -50,
        "score": 76,
        "exit_reason": "STOP_LOSS",
        "holding_minutes": 90,
        "mfe_r": 1.2,
        "reason_codes": ["BREAKOUT_1H"],
        "entry_context": {
            "btc_regime": "BEARISH",
            "volume_ratio_1h": 0.9,
            "oi_change_pct": 0.1,
            "funding_rate": 0.001,
            "atr_pct_1h": 5.2,
            "distance_ema20_atr": 1.6,
        },
    }
    causes, fixes = analyze_loss(trade)
    assert len(causes) >= 5
    assert len(fixes) >= 5
