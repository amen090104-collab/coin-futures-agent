from datetime import datetime, timedelta, timezone

from app import storage
from app.news_guardian import analyze_news_cluster, news_entry_guard


NOW = datetime(2026, 10, 6, 1, 30, tzinfo=timezone.utc)


def _article(
    title,
    *,
    impact,
    sentiment,
    score,
    category="MACRO",
    symbols=None,
    minutes_ago=2,
    source="TestWire",
):
    return {
        "source": source,
        "title": title,
        "summary": title,
        "url": "https://example.test/" + title.replace(" ", "-"),
        "published_at": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
        "sentiment": sentiment,
        "sentiment_score": score,
        "impact_score": impact,
        "category": category,
        "symbols": symbols or [],
    }


def test_unclear_high_impact_market_news_triggers_event_lock():
    xs = [
        _article("FOMC decision", impact=96, sentiment="NEUTRAL", score=0, source="Federal Reserve"),
        _article("Markets read statement as dovish", impact=88, sentiment="BULLISH", score=54, minutes_ago=4),
        _article("Markets read statement as hawkish", impact=87, sentiment="BEARISH", score=-54, minutes_ago=5),
    ]
    out = analyze_news_cluster(xs, NOW)
    assert out["mode"] == "EVENT_LOCK"
    assert out["scope"] == "MARKET"
    assert out["direction"] == "UNCLEAR"
    assert out["confidence"] < 70


def test_clear_high_impact_direction_becomes_directional_warning():
    xs = [
        _article("Spot ETF approved", impact=93, sentiment="BULLISH", score=72, category="REGULATION", symbols=["BTC"], source="SEC"),
        _article("ETF inflows accelerate", impact=84, sentiment="BULLISH", score=54, category="REGULATION", symbols=["BTC"], minutes_ago=8),
    ]
    out = analyze_news_cluster(xs, NOW)
    assert out["mode"] == "DIRECTIONAL_WARNING"
    assert out["scope"] == "MARKET"
    assert out["direction"] == "BULLISH"
    assert out["confidence"] >= 70


def test_medium_impact_news_enters_caution_mode():
    xs = [
        _article("Exchange listing update", impact=76, sentiment="BULLISH", score=36, category="EXCHANGE", symbols=["SOL"]),
    ]
    out = analyze_news_cluster(xs, NOW)
    assert out["mode"] == "CAUTION"
    assert out["scope"] == "SYMBOL"
    assert out["symbols"] == ["SOL"]


def test_entry_guard_blocks_only_affected_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    future = datetime.now(timezone.utc) + timedelta(minutes=20)
    storage.set_system_state(
        "news_guardian",
        {
            "mode": "EVENT_LOCK",
            "scope": "SYMBOL",
            "symbols": ["BTC"],
            "headline": "BTC-specific event",
            "cooldown_until": future.isoformat(),
            "direction": "UNCLEAR",
            "confidence": 42,
        },
    )

    assert news_entry_guard("BTCUSDT")["allowed"] is False
    assert news_entry_guard("ETHUSDT")["allowed"] is True
