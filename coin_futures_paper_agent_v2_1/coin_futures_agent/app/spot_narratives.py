from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .storage import _connect


NARRATIVES: dict[str, dict[str, Any]] = {
    "RWA": {
        "label": "Real World Assets / Tokenization",
        "keywords": ["rwa", "real world asset", "real-world asset", "tokenization", "tokenized", "treasury fund"],
        "coins": ["ONDO", "LINK", "POLYX", "MKR"],
    },
    "AI": {
        "label": "AI / AI Agents / Compute",
        "keywords": ["artificial intelligence", " ai ", "ai agent", "gpu", "compute network", "decentralized ai"],
        "coins": ["TAO", "FET", "RENDER", "AKT", "NEAR", "WLD"],
    },
    "DEPIN": {
        "label": "DePIN / Decentralized Infrastructure",
        "keywords": ["depin", "decentralized physical", "decentralized infrastructure", "wireless network", "storage network"],
        "coins": ["RENDER", "FIL", "AR", "AKT", "HNT"],
    },
    "DEFI": {
        "label": "DeFi / Lending / DEX",
        "keywords": ["defi", "decentralized finance", "dex", "lending", "liquidity protocol", "yield protocol"],
        "coins": ["AAVE", "UNI", "CRV", "MKR", "LDO", "ENA"],
    },
    "L2": {
        "label": "Layer 2 / Rollups",
        "keywords": ["layer 2", "layer-2", "rollup", "zk rollup", "arbitrum", "optimism"],
        "coins": ["ARB", "OP", "STRK", "ZK", "POL"],
    },
    "ETF_INSTITUTIONAL": {
        "label": "ETF / Institutional Adoption",
        "keywords": ["etf", "institutional", "blackrock", "fidelity", "asset manager", "wall street"],
        "coins": ["BTC", "ETH", "SOL", "XRP"],
    },
    "MEME": {
        "label": "Memecoin",
        "keywords": ["memecoin", "meme coin", "meme token"],
        "coins": ["DOGE", "SHIB", "PEPE", "BONK", "WIF"],
    },
    "GAMING": {
        "label": "Gaming / GameFi",
        "keywords": ["gamefi", "web3 gaming", "blockchain game", "gaming token"],
        "coins": ["IMX", "GALA", "SAND", "AXS", "RON"],
    },
    "PAYMENTS_STABLECOIN": {
        "label": "Payments / Stablecoins",
        "keywords": ["stablecoin", "payments", "payment network", "cross-border payment"],
        "coins": ["XRP", "XLM", "TRX", "ENA"],
    },
    "RESTAKING": {
        "label": "Restaking / Staking Infrastructure",
        "keywords": ["restaking", "eigenlayer", "liquid staking", "staking protocol"],
        "coins": ["EIGEN", "ETH", "LDO"],
    },
    "PRIVACY": {
        "label": "Privacy",
        "keywords": ["privacy coin", "privacy protocol", "zero knowledge privacy"],
        "coins": ["ZEC", "XMR"],
    },
}


def init_narrative_db() -> None:
    with _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS narrative_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                narrative TEXT NOT NULL,
                trend_score REAL NOT NULL,
                lifecycle TEXT NOT NULL,
                article_count INTEGER NOT NULL,
                independent_sources INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_narrative_snapshots
            ON narrative_snapshots(narrative, created_at DESC);
            """
        )


def _dt(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _recent_articles(days: int = 14) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with _connect() as con:
        rows = con.execute(
            """
            SELECT source,title,summary,url,published_at,sentiment,sentiment_score,
                   impact_score,category,symbols
            FROM news_articles
            WHERE published_at>=?
            ORDER BY published_at DESC
            """,
            (since.isoformat(),),
        ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        try:
            d["symbols"] = json.loads(d.get("symbols") or "[]")
        except Exception:
            d["symbols"] = []
        out.append(d)
    return out


def _match_narratives(article: dict[str, Any]) -> list[str]:
    text = f" {article.get('title','')} {article.get('summary','')} ".lower()
    hits = []
    for key, cfg in NARRATIVES.items():
        if any(k in text for k in cfg["keywords"]):
            hits.append(key)
    return hits


def _cluster_key(article: dict[str, Any]) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", str(article.get("title") or "").lower())
    stop = {"the", "a", "an", "to", "of", "in", "on", "for", "and", "with", "as", "is", "are", "from"}
    tokens = [x for x in text.split() if len(x) > 2 and x not in stop]
    return " ".join(tokens[:7]) or text[:80]


def _dedupe_events(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in articles:
        groups[_cluster_key(article)].append(article)
    events: list[dict[str, Any]] = []
    for key, xs in groups.items():
        xs.sort(key=lambda x: (float(x.get("impact_score") or 0), _dt(x.get("published_at"))), reverse=True)
        primary = xs[0]
        events.append(
            {
                "event_key": key,
                "primary": primary,
                "articles": len(xs),
                "sources": sorted({str(x.get("source") or "") for x in xs}),
                "source_count": len({str(x.get("source") or "") for x in xs}),
            }
        )
    events.sort(
        key=lambda e: (
            float(e["primary"].get("impact_score") or 0),
            _dt(e["primary"].get("published_at")),
        ),
        reverse=True,
    )
    return events


def _lifecycle(current: int, previous: int, score: float) -> str:
    if current == 0:
        return "DORMANT"
    if previous == 0 and current >= 2:
        return "NEW"
    growth = (current - previous) / max(previous, 1)
    if score >= 80 and growth >= 0:
        return "HOT"
    if growth >= 0.5:
        return "RISING"
    if score >= 65:
        return "MATURE"
    if growth <= -0.35:
        return "FADING"
    return "WATCH"


def _trend_score(current: list[dict[str, Any]], previous_count: int) -> float:
    if not current:
        return 0.0
    sources = len({str(x.get("source") or "") for x in current})
    impacts = [float(x.get("impact_score") or 0) for x in current]
    avg_impact = sum(impacts) / len(impacts)
    primary_bonus = sum(1 for x in current if x.get("source") in {"Federal Reserve", "SEC"})
    growth = (len(current) - previous_count) / max(previous_count, 1)
    growth_component = max(-10.0, min(20.0, growth * 12.0))
    score = (
        18.0
        + min(24.0, len(current) * 3.0)
        + min(20.0, sources * 5.0)
        + min(22.0, avg_impact * 0.28)
        + min(8.0, primary_bonus * 4.0)
        + growth_component
    )
    return round(max(0.0, min(100.0, score)), 1)


def _coin_relevance(
    narrative: str,
    current: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cfg = NARRATIVES[narrative]
    stats: dict[str, dict[str, Any]] = {}
    for coin in cfg["coins"]:
        stats[coin] = {
            "symbol": coin,
            "direct_articles": 0,
            "positive": 0,
            "negative": 0,
            "sources": set(),
            "relevance": 55,
        }
    for article in current:
        symbols = [str(x).upper() for x in article.get("symbols", [])]
        for coin in set(cfg["coins"]) | set(symbols):
            if coin not in stats:
                stats[coin] = {
                    "symbol": coin,
                    "direct_articles": 0,
                    "positive": 0,
                    "negative": 0,
                    "sources": set(),
                    "relevance": 35,
                }
            if coin in symbols:
                stats[coin]["direct_articles"] += 1
                stats[coin]["relevance"] += min(10, float(article.get("impact_score") or 0) / 12)
                stats[coin]["sources"].add(str(article.get("source") or ""))
                if article.get("sentiment") == "BULLISH":
                    stats[coin]["positive"] += 1
                elif article.get("sentiment") == "BEARISH":
                    stats[coin]["negative"] += 1
    rows = []
    for d in stats.values():
        rows.append(
            {
                **{k: v for k, v in d.items() if k != "sources"},
                "independent_sources": len(d["sources"]),
                "relevance": round(min(100.0, float(d["relevance"])), 1),
            }
        )
    rows.sort(key=lambda x: (x["relevance"], x["direct_articles"]), reverse=True)
    return rows[:12]


def run_narrative_research() -> dict[str, Any]:
    init_narrative_db()
    now = datetime.now(timezone.utc)
    split = now - timedelta(days=7)
    articles = _recent_articles(14)
    by_narrative: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prev_by_narrative: Counter[str] = Counter()
    for article in articles:
        hits = _match_narratives(article)
        if _dt(article.get("published_at")) >= split:
            for hit in hits:
                by_narrative[hit].append(article)
        else:
            for hit in hits:
                prev_by_narrative[hit] += 1

    rows: list[dict[str, Any]] = []
    for key, cfg in NARRATIVES.items():
        current = by_narrative.get(key, [])
        previous = int(prev_by_narrative.get(key, 0))
        score = _trend_score(current, previous)
        lifecycle = _lifecycle(len(current), previous, score)
        events = _dedupe_events(current)
        independent_sources = len({str(x.get("source") or "") for x in current})
        pos = sum(1 for x in current if x.get("sentiment") == "BULLISH")
        neg = sum(1 for x in current if x.get("sentiment") == "BEARISH")
        bias = "POSITIVE" if pos >= neg + 2 else "NEGATIVE" if neg >= pos + 2 else "MIXED"
        evidence = [
            {
                "source": e["primary"].get("source"),
                "title": e["primary"].get("title"),
                "url": e["primary"].get("url"),
                "published_at": e["primary"].get("published_at"),
                "impact_score": e["primary"].get("impact_score"),
                "sentiment": e["primary"].get("sentiment"),
                "articles_in_cluster": e["articles"],
                "independent_sources_in_cluster": e["source_count"],
            }
            for e in events[:6]
        ]
        row = {
            "narrative": key,
            "label": cfg["label"],
            "trend_score": score,
            "lifecycle": lifecycle,
            "bias": bias,
            "articles_7d": len(current),
            "articles_prev_7d": previous,
            "independent_sources": independent_sources,
            "independent_events": len(events),
            "positive_articles": pos,
            "negative_articles": neg,
            "evidence": evidence,
            "coins": _coin_relevance(key, current),
            "interpretation": (
                "Narrative đang được nhiều nguồn nhắc đến; xem evidence trước khi tự đưa ra định hướng."
                if score >= 65
                else "Narrative hiện chưa có đủ mật độ tin để coi là trend mạnh."
            ),
        }
        rows.append(row)

    rows.sort(key=lambda x: x["trend_score"], reverse=True)
    created_at = now.isoformat()
    with _connect() as con:
        for row in rows:
            con.execute(
                """
                INSERT INTO narrative_snapshots(
                    created_at,narrative,trend_score,lifecycle,article_count,
                    independent_sources,payload
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    created_at, row["narrative"], row["trend_score"], row["lifecycle"],
                    row["articles_7d"], row["independent_sources"], json.dumps(row),
                ),
            )
    return {
        "created_at": created_at,
        "method": "news-first narrative research; technical indicators are secondary context only",
        "narratives": rows,
        "top_trends": rows[:8],
    }


def latest_narrative_research() -> dict[str, Any]:
    init_narrative_db()
    with _connect() as con:
        ts = con.execute(
            "SELECT MAX(created_at) AS v FROM narrative_snapshots"
        ).fetchone()["v"]
        if not ts:
            return run_narrative_research()
        rows = con.execute(
            "SELECT payload FROM narrative_snapshots WHERE created_at=? ORDER BY trend_score DESC",
            (ts,),
        ).fetchall()
    parsed = []
    for row in rows:
        try:
            parsed.append(json.loads(row["payload"]))
        except Exception:
            pass
    return {
        "created_at": ts,
        "method": "news-first narrative research; technical indicators are secondary context only",
        "narratives": parsed,
        "top_trends": parsed[:8],
    }


def coin_narrative_context(symbol: str, research: dict[str, Any] | None = None) -> dict[str, Any]:
    base = symbol.replace("USDT", "").upper()
    research = research or latest_narrative_research()
    hits = []
    for narrative in research.get("narratives", []):
        for coin in narrative.get("coins", []):
            if coin.get("symbol") == base:
                hits.append(
                    {
                        "narrative": narrative["narrative"],
                        "label": narrative["label"],
                        "trend_score": narrative["trend_score"],
                        "lifecycle": narrative["lifecycle"],
                        "bias": narrative["bias"],
                        "coin_relevance": coin.get("relevance"),
                        "evidence": narrative.get("evidence", [])[:3],
                    }
                )
                break
    hits.sort(key=lambda x: (x["trend_score"], x["coin_relevance"]), reverse=True)
    conviction = 0.0
    if hits:
        weights = [float(x["trend_score"]) * float(x.get("coin_relevance") or 0) / 100 for x in hits[:3]]
        conviction = sum(weights) / len(weights)
    return {
        "symbol": base,
        "narratives": hits,
        "news_conviction": round(min(100.0, conviction), 1),
    }
