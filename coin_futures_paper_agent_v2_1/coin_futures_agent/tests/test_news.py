from app.news import classify_article, parse_feed


def test_parse_and_classify_news():
    xml = """<?xml version='1.0'?><rss><channel><item><title>SEC approves Bitcoin ETF as BTC rallies</title><link>https://example.com/a</link><description>Major approval drives inflows.</description><pubDate>Sun, 04 Oct 2026 05:00:00 GMT</pubDate></item></channel></rss>"""
    xs = parse_feed(xml, "Test")
    assert len(xs) == 1
    out = classify_article(xs[0], {"BTC", "ETH"})
    assert out["sentiment"] == "BULLISH"
    assert "BTC" in out["symbols"]
    assert out["impact_score"] >= 65
