from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .storage import recent_news


COIN_NARRATIVES: dict[str, list[str]] = {
    "BTC": ["Bitcoin", "Institutional Adoption", "Store of Value"],
    "ETH": ["Ethereum", "DeFi", "Layer 2", "Institutional Adoption"],
    "SOL": ["Solana", "DeFi", "Memecoin", "Payments"],
    "XRP": ["Payments", "Regulation", "Institutional Adoption"],
    "LINK": ["Oracle", "RWA", "Cross-chain", "Institutional Infrastructure"],
    "ONDO": ["RWA", "Tokenization"],
    "AAVE": ["DeFi", "Lending", "RWA"],
    "UNI": ["DeFi", "DEX"],
    "ARB": ["Layer 2", "Ethereum"],
    "OP": ["Layer 2", "Ethereum"],
    "SUI": ["Layer 1", "DeFi", "Gaming"],
    "APT": ["Layer 1", "DeFi", "Gaming"],
    "NEAR": ["Layer 1", "AI"],
    "FET": ["AI", "AI Agents"],
    "TAO": ["AI", "Decentralized AI"],
    "RENDER": ["AI", "DePIN", "GPU Compute"],
    "FIL": ["DePIN", "Storage"],
    "HYPE": ["DeFi", "DEX", "Perpetuals"],
    "DOGE": ["Memecoin"],
    "SHIB": ["Memecoin"],
    "PEPE": ["Memecoin"],
}

NARRATIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "RWA": ("rwa", "real world asset", "real-world asset", "tokenization", "tokenized asset"),
    "AI": ("artificial intelligence", " ai ", "ai token", "gpu", "compute"),
    "AI Agents": ("ai agent", "agentic", "autonomous agent"),
    "DePIN": ("depin", "decentralized physical infrastructure", "gpu network", "storage network"),
    "DeFi": ("defi", "decentralized finance", "lending protocol", "dex", "liquidity protocol"),
    "Layer 2": ("layer 2", "layer-2", "rollup", "optimistic rollup", "zk rollup"),
    "Layer 1": ("layer 1", "layer-1", "mainnet"),
    "Memecoin": ("memecoin", "meme coin", "meme token"),
    "ETF": ("etf", "exchange-traded fund"),
    "Institutional Adoption": ("institutional", "blackrock", "fidelity", "bank", "asset manager"),
    "Regulation": ("sec", "cftc", "regulation", "regulator", "lawsuit", "court"),
    "Payments": ("payment", "payments", "remittance", "settlement"),
    "Stablecoin": ("stablecoin", "usdt", "usdc"),
    "Gaming": ("gaming", "gamefi", "web3 game"),
    "Cross-chain": ("cross-chain", "interoperability", "bridge"),
    "Security Risk": ("hack", "exploit", "breach", "stolen"),
    "Token Unlock": ("token unlock", "unlock schedule", "vesting"),
}


def coin_narratives(symbol: str) -> list[str]:
    base = symbol.replace("USDT", "").upper()
    return list(COIN_NARRATIVES.get(base, []))


def _article_narratives(article: dict[str, Any]) -> set[str]:
    text = f" {article.get('title','')} {article.get('summary','')} ".lower()
    found: set[str] = set()
    for narrative, keys in NARRATIVE_KEYWORDS.items():
        if any(key in text for key in keys):
            found.add(narrative)
    for sym in article.get("symbols") or []:
        found.update(COIN_NARRATIVES.get(str(sym).upper(), []))
    return found


def _age_hours(value: str) -> float:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - d).total_seconds() / 3600)
    except Exception:
        return 999.0


def build_narrative_research(hours: int = 168) -> dict[str, Any]:
    articles = recent_news(limit=500, hours=hours)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in articles:
        for narrative in _article_narratives(article):
            groups[narrative].append(article)

    rows: list[dict[str, Any]] = []
    for narrative, items in groups.items():
        recent24 = [x for x in items if _age_hours(x.get("published_at", "")) <= 24]
        prev = [x for x in items if 24 < _age_hours(x.get("published_at", "")) <= 72]
        sources = {str(x.get("source") or "") for x in items if x.get("source")}
        recent_sources = {str(x.get("source") or "") for x in recent24 if x.get("source")}
        impact = (
            sum(float(x.get("impact_score") or 0) for x in recent24) / len(recent24)
            if recent24 else
            sum(float(x.get("impact_score") or 0) for x in items) / max(len(items), 1)
        )
        sentiment = (
            sum(float(x.get("sentiment_score") or 0) for x in recent24) / len(recent24)
            if recent24 else 0.0
        )
        velocity = len(recent24) / max(len(prev) / 2, 1)
        score = min(
            100.0,
            20
            + min(len(recent24) * 6, 30)
            + min(len(recent_sources) * 7, 21)
            + min(impact * 0.22, 22)
            + min(max(velocity - 1, 0) * 7, 14),
        )
        if len(recent24) >= 4 and velocity >= 1.5 and score >= 75:
            state = "HOT"
        elif recent24 and velocity >= 1.2:
            state = "RISING"
        elif recent24 and not prev:
            state = "NEW"
        elif not recent24 and items:
            state = "FADING"
        else:
            state = "MATURE"

        related_coins = sorted({
            str(sym)
            for x in items
            for sym in (x.get("symbols") or [])
            if narrative in COIN_NARRATIVES.get(str(sym).upper(), [])
        })
        positive = sum(str(x.get("sentiment")) == "BULLISH" for x in items)
        negative = sum(str(x.get("sentiment")) == "BEARISH" for x in items)
        evidence = sorted(
            items,
            key=lambda x: (
                _age_hours(x.get("published_at", "")),
                -float(x.get("impact_score") or 0),
            ),
        )[:10]

        rows.append({
            "narrative": narrative,
            "trend_score": round(score, 1),
            "state": state,
            "articles_24h": len(recent24),
            "articles_period": len(items),
            "independent_sources_24h": len(recent_sources),
            "independent_sources_period": len(sources),
            "sentiment_score": round(sentiment, 1),
            "bias": "POSITIVE" if sentiment >= 12 else "NEGATIVE" if sentiment <= -12 else "MIXED",
            "positive_articles": positive,
            "negative_articles": negative,
            "related_coins": related_coins,
            "why_trending": [
                f"{len(recent24)} relevant articles in the last 24h",
                f"{len(recent_sources)} independent news sources in the last 24h",
                f"average recent impact {impact:.0f}/100",
                f"news velocity {velocity:.1f}x versus the previous window",
            ],
            "evidence": [
                {
                    "source": x.get("source"),
                    "title": x.get("title"),
                    "url": x.get("url"),
                    "published_at": x.get("published_at"),
                    "sentiment": x.get("sentiment"),
                    "impact_score": x.get("impact_score"),
                    "symbols": x.get("symbols") or [],
                }
                for x in evidence
            ],
        })

    rows.sort(key=lambda x: x["trend_score"], reverse=True)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        "narratives": rows,
        "hot": [x for x in rows if x["state"] in {"NEW", "RISING", "HOT"}][:12],
        "negative": [
            x for x in rows
            if x["bias"] == "NEGATIVE" or x["narrative"] in {"Security Risk", "Token Unlock"}
        ][:12],
        "method": (
            "News-first research: narrative detection uses fresh article volume, independent-source "
            "breadth, impact and velocity. It is evidence for human research, not a buy/sell signal."
        ),
    }


def enrich_coin_with_narratives(row: dict[str, Any], narrative_research: dict[str, Any]) -> dict[str, Any]:
    base = str(row.get("base") or row.get("symbol", "")).replace("USDT", "").upper()
    sectors = COIN_NARRATIVES.get(base, [])
    matched = [
        x for x in narrative_research.get("narratives", [])
        if x["narrative"] in sectors
    ]
    matched.sort(key=lambda x: x["trend_score"], reverse=True)
    evidence = []
    for item in matched[:4]:
        for ev in item.get("evidence", []):
            if base in (ev.get("symbols") or []) or not ev.get("symbols"):
                evidence.append({**ev, "narrative": item["narrative"]})
    row = dict(row)
    row["narratives"] = sectors
    row["trending_narratives"] = [
        {
            "narrative": x["narrative"],
            "trend_score": x["trend_score"],
            "state": x["state"],
            "bias": x["bias"],
        }
        for x in matched[:5]
    ]
    row["news_evidence"] = evidence[:10]
    row["narrative_score"] = round(
        max((float(x["trend_score"]) for x in matched), default=0.0),
        1,
    )
    row["research_conclusion"] = (
        "STRONG_NARRATIVE_RESEARCH"
        if row["narrative_score"] >= 75
        else "NARRATIVE_WATCH"
        if row["narrative_score"] >= 55
        else "NO_STRONG_NARRATIVE"
    )
    return row
