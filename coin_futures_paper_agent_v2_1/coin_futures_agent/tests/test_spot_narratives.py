from app.spot_narratives import coin_narratives, enrich_coin_with_narratives


def test_coin_taxonomy_and_enrichment():
    assert "RWA" in coin_narratives("LINKUSDT")
    research = {
        "narratives": [
            {
                "narrative": "RWA",
                "trend_score": 88.0,
                "state": "HOT",
                "bias": "POSITIVE",
                "evidence": [
                    {
                        "source": "Official",
                        "title": "Tokenization expands",
                        "url": "https://example.com/a",
                        "symbols": ["LINK"],
                    }
                ],
            }
        ]
    }
    row = enrich_coin_with_narratives(
        {"symbol": "LINKUSDT", "base": "LINK", "score": 70},
        research,
    )
    assert row["narrative_score"] == 88.0
    assert row["research_conclusion"] == "STRONG_NARRATIVE_RESEARCH"
    assert row["news_evidence"][0]["title"] == "Tokenization expands"
