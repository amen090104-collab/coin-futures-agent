from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .config import settings
from .storage import recent_news, save_news_articles


@dataclass(frozen=True)
class NewsSource:
    name: str
    url: str


DEFAULT_SOURCES = [
    NewsSource("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    NewsSource("Cointelegraph", "https://cointelegraph.com/rss"),
    NewsSource("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    NewsSource("SEC", "https://www.sec.gov/news/pressreleases.rss"),
]

# Common aliases. We also detect explicit uppercase tickers from the current scan universe.
ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("bitcoin", "btc"),
    "ETH": ("ethereum", "ether", "eth"),
    "SOL": ("solana", "sol"),
    "XRP": ("xrp", "ripple"),
    "DOGE": ("dogecoin", "doge"),
    "BNB": ("bnb", "binance coin"),
    "ADA": ("cardano",),
    "AVAX": ("avalanche", "avax"),
    "LINK": ("chainlink",),
    "DOT": ("polkadot",),
    "TRX": ("tron", "trx"),
    "TON": ("toncoin", "the open network"),
    "SUI": ("sui",),
    "APT": ("aptos",),
    "ARB": ("arbitrum", "arb"),
    "OP": ("optimism",),
    "NEAR": ("near protocol",),
    "LTC": ("litecoin", "ltc"),
    "BCH": ("bitcoin cash", "bch"),
    "UNI": ("uniswap", "uni"),
    "AAVE": ("aave",),
    "HYPE": ("hyperliquid", "hype"),
    "ZEC": ("zcash", "zec"),
}

POSITIVE = {
    "approve": 2, "approved": 2, "approval": 2, "adoption": 2, "adopts": 2,
    "launch": 1, "launches": 1, "partnership": 1, "partners": 1, "upgrade": 1,
    "inflow": 1, "inflows": 1, "record": 1, "rally": 2, "surge": 2, "jumps": 2,
    "gain": 1, "gains": 1, "bullish": 2, "breakout": 1, "rebound": 1,
    "wins": 1, "victory": 1, "expands": 1, "growth": 1, "buy": 1, "buys": 1,
}
NEGATIVE = {
    "hack": 3, "hacked": 3, "exploit": 3, "breach": 3, "attack": 2, "stolen": 3,
    "lawsuit": 2, "sues": 2, "investigation": 2, "ban": 3, "bans": 3,
    "crash": 3, "plunge": 3, "plunges": 3, "drop": 1, "drops": 1, "falls": 1,
    "liquidation": 2, "liquidations": 2, "outflow": 1, "outflows": 1,
    "fraud": 3, "shutdown": 3, "halts": 2, "rejection": 2, "rejects": 2,
    "bearish": 2, "default": 3, "bankruptcy": 3, "delist": 2, "delisting": 2,
}
HIGH_IMPACT = {
    "sec", "cftc", "federal reserve", "fed", "fomc", "cpi", "ppi", "pce", "inflation",
    "interest rate", "rates", "nonfarm", "payroll", "jobs report", "etf", "hack", "exploit",
    "breach", "liquidations", "binance", "coinbase", "kraken", "tariff", "war", "sanction",
    "lawsuit", "regulation", "regulator", "bankruptcy", "default",
}

POSITIVE_PHRASES = {
    "rate cut": 4,
    "cuts rates": 4,
    "cut interest rates": 4,
    "dovish": 3,
    "inflation cools": 3,
    "cooling inflation": 3,
    "lower than expected inflation": 3,
    "etf approved": 4,
    "etf approval": 4,
    "spot etf approved": 5,
    "record inflows": 3,
    "withdrawals resume": 3,
}

NEGATIVE_PHRASES = {
    "rate hike": 4,
    "raises rates": 4,
    "higher for longer": 4,
    "hawkish": 3,
    "inflation accelerates": 3,
    "hotter than expected inflation": 3,
    "higher than expected inflation": 3,
    "etf rejected": 4,
    "etf rejection": 4,
    "etf delayed": 2,
    "withdrawals halted": 5,
    "halts withdrawals": 5,
    "files for bankruptcy": 5,
}


def _clean(text: str | None) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _published(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _find_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node.iter():
        tag = child.tag.split("}")[-1].lower()
        if tag in names and child.text:
            return child.text
    return ""


def parse_feed(xml_text: str, source: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for item in root.iter():
        tag = item.tag.split("}")[-1].lower()
        if tag not in {"item", "entry"}:
            continue
        title = _clean(_find_text(item, ("title",)))
        if not title:
            continue
        link = _find_text(item, ("link",))
        if not link:
            for child in item.iter():
                ctag = child.tag.split("}")[-1].lower()
                if ctag == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        summary = _clean(_find_text(item, ("description", "summary", "content")))
        published = _published(_find_text(item, ("pubdate", "published", "updated", "date")))
        items.append({
            "source": source,
            "title": title[:500],
            "summary": summary[:1400],
            "url": link.strip(),
            "published_at": published,
        })
    return items


def classify_article(article: dict[str, Any], universe: set[str] | None = None) -> dict[str, Any]:
    text = f"{article.get('title','')} {article.get('summary','')}".lower()
    words = re.findall(r"[a-z0-9$-]+", text)
    pos = sum(POSITIVE.get(w, 0) for w in words)
    neg = sum(NEGATIVE.get(w, 0) for w in words)
    phrase_pos = sum(weight for phrase, weight in POSITIVE_PHRASES.items() if phrase in text)
    phrase_neg = sum(weight for phrase, weight in NEGATIVE_PHRASES.items() if phrase in text)
    raw = pos - neg + phrase_pos - phrase_neg
    sentiment = "BULLISH" if raw >= 2 else "BEARISH" if raw <= -2 else "NEUTRAL"
    sentiment_score = max(-100, min(100, raw * 18))

    lower = text
    if any(k in lower for k in ("hack", "exploit", "breach", "stolen", "attack")):
        category = "SECURITY"
    elif any(k in lower for k in ("sec", "cftc", "regulation", "regulator", "lawsuit", "ban", "court")):
        category = "REGULATION"
    elif any(k in lower for k in ("federal reserve", " fed ", "cpi", "ppi", "inflation", "interest rate", "tariff", "bond", "jobs report")):
        category = "MACRO"
    elif any(k in lower for k in ("binance", "coinbase", "kraken", "exchange", "listing", "delist")):
        category = "EXCHANGE"
    elif any(k in lower for k in ("liquidation", "rally", "price", "market", "breakout", "plunge", "surge")):
        category = "MARKET"
    else:
        category = "PROJECT"

    hit = sum(1 for k in HIGH_IMPACT if k in lower)
    impact = min(100, 30 + hit * 18 + min(abs(raw) * 6, 28))
    if category in {"SECURITY", "MACRO", "REGULATION"}:
        impact = max(impact, 65)

    symbols: set[str] = set()
    universe = universe or set()
    for sym, aliases in ALIASES.items():
        if universe and sym not in universe:
            continue
        for alias in aliases:
            if re.search(rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])", lower):
                symbols.add(sym)
                break
    # Explicit uppercase tickers in title are safer than scanning body text.
    for token in re.findall(r"\$?([A-Z][A-Z0-9]{1,9})\b", article.get("title", "")):
        if token in universe:
            symbols.add(token)

    return {
        **article,
        "sentiment": sentiment,
        "sentiment_score": int(sentiment_score),
        "impact_score": int(impact),
        "category": category,
        "symbols": sorted(symbols),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


async def fetch_and_store_news(universe: set[str] | None = None) -> dict[str, Any]:
    sources = list(DEFAULT_SOURCES)
    if settings.extra_news_rss:
        for i, url in enumerate(settings.extra_news_rss.split(","), start=1):
            url = url.strip()
            if url:
                sources.append(NewsSource(f"Custom{i}", url))

    headers = {
        "User-Agent": "coin-futures-agent-paper/4.2 (+market-news-research; contact=local-paper-agent)"
    }
    timeout = httpx.Timeout(18.0)
    articles: list[dict[str, Any]] = []
    errors: list[str] = []
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        async def one(src: NewsSource):
            try:
                r = await client.get(src.url)
                r.raise_for_status()
                parsed = parse_feed(r.text, src.name)[: settings.news_max_per_source]
                return [classify_article(x, universe) for x in parsed], None
            except Exception as exc:
                return [], f"{src.name}: {exc}"

        results = await asyncio.gather(*(one(s) for s in sources))
        for xs, err in results:
            articles.extend(xs)
            if err:
                errors.append(err)

    saved = save_news_articles(articles)
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": [s.name for s in sources],
        "received": len(articles),
        "saved_or_updated": saved,
        "errors": errors,
        "summary": market_news_summary(settings.news_lookback_hours),
    }


def market_news_summary(hours: int = 24) -> dict[str, Any]:
    xs = recent_news(limit=250, hours=hours)
    if not xs:
        return {
            "hours": hours,
            "articles": 0,
            "market_bias": "NO_DATA",
            "market_score": 0,
            "risk_level": "UNKNOWN",
            "high_impact": 0,
            "bullish": 0,
            "bearish": 0,
            "neutral": 0,
        }
    total_weight = 0.0
    weighted_score = 0.0
    high = 0
    bullish = bearish = neutral = 0
    now = datetime.now(timezone.utc)
    for x in xs:
        try:
            age_h = max(0.0, (now - datetime.fromisoformat(x["published_at"])).total_seconds() / 3600)
        except Exception:
            age_h = 12.0
        freshness = max(0.20, 1.0 - age_h / max(hours, 1))
        impact_w = 0.5 + float(x.get("impact_score") or 0) / 100
        w = freshness * impact_w
        weighted_score += float(x.get("sentiment_score") or 0) * w
        total_weight += w
        if int(x.get("impact_score") or 0) >= 75:
            high += 1
        s = x.get("sentiment")
        bullish += s == "BULLISH"
        bearish += s == "BEARISH"
        neutral += s == "NEUTRAL"
    score = round(weighted_score / total_weight if total_weight else 0.0, 1)
    bias = "BULLISH" if score >= 12 else "BEARISH" if score <= -12 else "MIXED"
    risk = "HIGH" if high >= 4 else "MEDIUM" if high >= 1 else "LOW"
    return {
        "hours": hours,
        "articles": len(xs),
        "market_bias": bias,
        "market_score": score,
        "risk_level": risk,
        "high_impact": high,
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
    }


def symbol_news_context(symbol: str, hours: int = 24) -> dict[str, Any]:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    xs = recent_news(limit=120, hours=hours, symbol=base)
    if not xs:
        return {
            "symbol": base,
            "articles": 0,
            "bias": "NO_DATA",
            "score": 0,
            "high_impact": 0,
            "headlines": [],
        }
    high = sum(int(x.get("impact_score") or 0) >= 75 for x in xs)
    denom = sum(max(1, int(x.get("impact_score") or 0)) for x in xs)
    numer = sum(float(x.get("sentiment_score") or 0) * max(1, int(x.get("impact_score") or 0)) for x in xs)
    score = round(numer / denom if denom else 0.0, 1)
    bias = "BULLISH" if score >= 12 else "BEARISH" if score <= -12 else "MIXED"
    return {
        "symbol": base,
        "articles": len(xs),
        "bias": bias,
        "score": score,
        "high_impact": high,
        "headlines": [x["title"] for x in xs[:3]],
    }
