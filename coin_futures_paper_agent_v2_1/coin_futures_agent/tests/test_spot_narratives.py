from app.spot_narratives import _dedupe_events, _match_narratives, _trend_score


def _article(title, source="WireA", impact=80):
    return {
        "source": source,
        "title": title,
        "summary": title,
        "url": "https://example.test/" + source,
        "published_at": "2026-10-07T00:00:00+00:00",
        "sentiment": "BULLISH",
        "sentiment_score": 40,
        "impact_score": impact,
        "category": "PROJECT",
        "symbols": [],
    }


def test_narrative_mapping_and_duplicate_cluster():
    a = _article("RWA tokenization adoption expands")
    assert "RWA" in _match_narratives(a)

    xs = [
        _article("RWA tokenization adoption expands", "WireA", 90),
        _article("RWA tokenization adoption expands", "WireB", 82),
        _article("RWA tokenization adoption expands", "WireA", 75),
    ]
    events = _dedupe_events(xs)
    assert len(events) == 1
    assert events[0]["articles"] == 3
    assert events[0]["source_count"] == 2


def test_narrative_score_rewards_independent_evidence():
    one_source = [_article(f"AI agent compute story {i}", "WireA", 80) for i in range(4)]
    many_sources = [
        _article(f"AI agent compute story {i}", f"Wire{i}", 80)
        for i in range(4)
    ]
    assert _trend_score(many_sources, 2) > _trend_score(one_source, 2)
