from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from .binance import BinanceClient
from .config import settings
from .storage import (
    get_news_guardian_event,
    get_system_state,
    recent_news,
    recent_news_guardian_events,
    save_news_guardian_event,
    set_system_state,
    update_news_guardian_event,
)

SYSTEMIC_CATEGORIES = {"MACRO", "REGULATION", "EXCHANGE", "MARKET"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: str | None) -> datetime:
    if not value:
        return _now()
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return out if out.tzinfo else out.replace(tzinfo=timezone.utc)
    except Exception:
        return _now()


def _symbols(article: dict[str, Any]) -> set[str]:
    value = article.get("symbols") or []
    if isinstance(value, str):
        return {value.replace("USDT", "").upper()}
    return {str(x).replace("USDT", "").upper() for x in value if x}


def _event_key(article: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(article.get("url") or ""),
            str(article.get("published_at") or ""),
            str(article.get("title") or ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _cooldown_minutes(impact: float) -> int:
    if impact >= 95:
        return settings.news_cooldown_extreme_min
    if impact >= settings.news_high_impact:
        return settings.news_cooldown_high_min
    return settings.news_cooldown_medium_min


def _is_related(primary: dict[str, Any], article: dict[str, Any]) -> bool:
    pcat = str(primary.get("category") or "")
    acat = str(article.get("category") or "")
    ps = _symbols(primary)
    other = _symbols(article)
    if ps and other and ps.intersection(other):
        return True
    if pcat and pcat == acat:
        return True
    if pcat in SYSTEMIC_CATEGORIES and acat in SYSTEMIC_CATEGORIES:
        return True
    return False


def analyze_news_cluster(
    articles: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    fresh_cutoff = now - timedelta(minutes=max(1, settings.news_guardian_fresh_minutes))
    fresh = [x for x in articles if _dt(x.get("published_at")) >= fresh_cutoff]
    if not fresh:
        return {
            "mode": "NORMAL",
            "status": "NORMAL",
            "impact_score": 0.0,
            "direction": "UNCLEAR",
            "confidence": 0.0,
            "scope": "MARKET",
            "symbols": [],
            "reason": "No fresh high-impact news.",
        }

    fresh.sort(
        key=lambda x: (
            float(x.get("impact_score") or 0),
            _dt(x.get("published_at")),
        ),
        reverse=True,
    )
    primary = fresh[0]
    primary_impact = float(primary.get("impact_score") or 0)
    if primary_impact < settings.news_caution_impact:
        return {
            "mode": "NORMAL",
            "status": "NORMAL",
            "impact_score": primary_impact,
            "direction": "UNCLEAR",
            "confidence": 0.0,
            "scope": "MARKET",
            "symbols": [],
            "reason": "Fresh news is below the caution threshold.",
        }

    cluster_cutoff = now - timedelta(hours=max(1, settings.news_guardian_cluster_hours))
    cluster = [
        x
        for x in articles
        if _dt(x.get("published_at")) >= cluster_cutoff and _is_related(primary, x)
    ]
    if primary not in cluster:
        cluster.insert(0, primary)

    weighted_sum = 0.0
    total_weight = 0.0
    bullish_weight = 0.0
    bearish_weight = 0.0
    neutral_weight = 0.0
    sources: set[str] = set()

    for article in cluster:
        age_min = max(0.0, (now - _dt(article.get("published_at"))).total_seconds() / 60)
        freshness = max(
            0.15,
            1.0 - age_min / max(60.0, settings.news_guardian_cluster_hours * 60.0),
        )
        impact = max(1.0, float(article.get("impact_score") or 0))
        weight = freshness * (0.35 + impact / 100.0)
        score = float(article.get("sentiment_score") or 0)
        weighted_sum += score * weight
        total_weight += weight
        sources.add(str(article.get("source") or "unknown"))
        if score >= 12:
            bullish_weight += weight * min(1.0, abs(score) / 50.0)
        elif score <= -12:
            bearish_weight += weight * min(1.0, abs(score) / 50.0)
        else:
            neutral_weight += weight * 0.6

    cluster_score = weighted_sum / total_weight if total_weight else 0.0
    if cluster_score >= 12:
        direction = "BULLISH"
    elif cluster_score <= -12:
        direction = "BEARISH"
    else:
        direction = "UNCLEAR"

    directional_total = bullish_weight + bearish_weight + neutral_weight
    dominance = (
        abs(bullish_weight - bearish_weight) / directional_total
        if directional_total > 0
        else 0.0
    )
    magnitude = min(1.0, abs(cluster_score) / 45.0)
    source_bonus = min(0.10, max(0, len(sources) - 1) * 0.035)
    confidence = min(100.0, max(0.0, (0.62 * dominance + 0.38 * magnitude + source_bonus) * 100))
    if direction == "UNCLEAR":
        confidence = min(confidence, 59.0)

    primary_symbols = sorted(_symbols(primary))
    category = str(primary.get("category") or "MARKET")
    if (
        category == "MACRO"
        or not primary_symbols
        or ("BTC" in primary_symbols and primary_impact >= settings.news_high_impact)
    ):
        scope = "MARKET"
        affected_symbols: list[str] = []
    else:
        scope = "SYMBOL"
        affected_symbols = primary_symbols

    if primary_impact >= settings.news_high_impact:
        ambiguous = direction == "UNCLEAR" or confidence < settings.news_direction_confidence
        if ambiguous:
            if scope == "SYMBOL" or primary_impact >= settings.news_market_lock_impact:
                mode = "EVENT_LOCK"
            else:
                mode = "CAUTION"
        else:
            mode = "DIRECTIONAL_WARNING"
    else:
        mode = "CAUTION"

    cooldown_min = _cooldown_minutes(primary_impact)
    cooldown_until = now + timedelta(minutes=cooldown_min)

    return {
        "mode": mode,
        "status": mode,
        "event_key": _event_key(primary),
        "headline": str(primary.get("title") or ""),
        "primary_url": str(primary.get("url") or ""),
        "primary_source": str(primary.get("source") or ""),
        "published_at": str(primary.get("published_at") or ""),
        "category": category,
        "scope": scope,
        "symbols": affected_symbols,
        "impact_score": round(primary_impact, 1),
        "direction": direction,
        "confidence": round(confidence, 1),
        "cluster_score": round(cluster_score, 1),
        "cluster_articles": len(cluster),
        "cluster_sources": sorted(sources),
        "cooldown_minutes": cooldown_min,
        "cooldown_until": cooldown_until.isoformat(),
        "related_news": [
            {
                "source": x.get("source"),
                "title": x.get("title"),
                "published_at": x.get("published_at"),
                "sentiment": x.get("sentiment"),
                "sentiment_score": x.get("sentiment_score"),
                "impact_score": x.get("impact_score"),
                "category": x.get("category"),
                "symbols": x.get("symbols") or [],
                "url": x.get("url"),
            }
            for x in cluster[:12]
        ],
        "reason": (
            f"{len(cluster)} related article(s), cluster score {cluster_score:+.1f}, "
            f"direction {direction}, confidence {confidence:.1f}%."
        ),
    }


async def evaluate_news_guardian() -> dict[str, Any]:
    now = _now()
    if not settings.news_guardian_enabled:
        state = {
            "mode": "DISABLED",
            "status": "DISABLED",
            "updated_at": now.isoformat(),
            "blocks_entries": False,
        }
        set_system_state("news_guardian", state, now.isoformat())
        return state

    articles = recent_news(
        limit=300,
        hours=max(settings.news_lookback_hours, settings.news_guardian_cluster_hours),
    )
    decision = analyze_news_cluster(articles, now)
    previous = get_system_state("news_guardian", {}) or {}

    if decision["mode"] == "NORMAL":
        state = {
            **decision,
            "updated_at": now.isoformat(),
            "blocks_entries": False,
            "is_new_event": False,
        }
        set_system_state("news_guardian", state, now.isoformat())
        return state

    reference_symbol = "BTCUSDT"
    if decision["scope"] == "SYMBOL" and decision["symbols"]:
        reference_symbol = f"{decision['symbols'][0]}USDT"

    reference_price = 0.0
    client = BinanceClient()
    try:
        try:
            reference_price = await client.mark_price(reference_symbol)
        except Exception:
            if reference_symbol != "BTCUSDT":
                reference_symbol = "BTCUSDT"
                try:
                    reference_price = await client.mark_price(reference_symbol)
                except Exception:
                    reference_price = 0.0
            else:
                reference_price = 0.0
    finally:
        await client.close()

    event = {
        "event_key": decision["event_key"],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "status": decision["mode"],
        "scope": decision["scope"],
        "symbols": decision["symbols"],
        "category": decision["category"],
        "impact_score": decision["impact_score"],
        "direction": decision["direction"],
        "confidence": decision["confidence"],
        "cooldown_until": decision["cooldown_until"],
        "reference_symbol": reference_symbol,
        "reference_price": reference_price,
        "headline": decision["headline"],
        "payload": decision,
        "reactions": {},
        "prediction_result": "PENDING",
    }
    event_id = save_news_guardian_event(event)
    persisted = get_news_guardian_event(event_id) or event

    previous_key = previous.get("event_key") if isinstance(previous, dict) else None
    previous_event_mode = (
        previous.get("event_mode") or previous.get("mode")
        if isinstance(previous, dict)
        else None
    )
    is_new_event = (
        previous_key != decision["event_key"]
        or previous_event_mode != decision["mode"]
    )

    persisted_cooldown = persisted.get("cooldown_until") or decision.get("cooldown_until")
    cooldown_dt = _dt(persisted_cooldown) if persisted_cooldown else None
    cooldown_complete = bool(cooldown_dt and now >= cooldown_dt)
    effective_mode = "POST_EVENT" if cooldown_complete else decision["mode"]

    state = {
        **decision,
        "mode": effective_mode,
        "status": effective_mode,
        "event_mode": decision["mode"],
        "event_id": event_id,
        "reference_symbol": persisted.get("reference_symbol", reference_symbol),
        "reference_price": float(persisted.get("reference_price") or reference_price),
        "cooldown_until": persisted_cooldown,
        "updated_at": now.isoformat(),
        "blocks_entries": not cooldown_complete,
        "is_new_event": is_new_event and not cooldown_complete,
    }
    set_system_state("news_guardian", state, now.isoformat())
    return state


def news_entry_guard(symbol: str) -> dict[str, Any]:
    if not settings.news_guardian_enabled:
        return {"allowed": True, "reason": "guardian disabled"}

    state = get_system_state("news_guardian", {}) or {}
    mode = state.get("mode", "NORMAL") if isinstance(state, dict) else "NORMAL"
    if mode in {"NORMAL", "DISABLED"}:
        return {"allowed": True, "reason": "normal"}

    cooldown_until = _dt(state.get("cooldown_until")) if state.get("cooldown_until") else None
    now = _now()
    if cooldown_until and now >= cooldown_until:
        return {
            "allowed": True,
            "reason": "news cooldown completed; normal scanner confirmation required",
            "mode": mode,
        }

    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    scope = state.get("scope", "MARKET")
    affected = {str(x).upper() for x in state.get("symbols", [])}
    applies = scope == "MARKET" or base.upper() in affected
    if not applies:
        return {"allowed": True, "reason": "news event does not affect this symbol", "mode": mode}

    return {
        "allowed": False,
        "reason": f"{mode}: {state.get('headline', 'high-impact news')}",
        "mode": mode,
        "cooldown_until": state.get("cooldown_until"),
        "direction": state.get("direction"),
        "confidence": state.get("confidence"),
    }


def news_guardian_overview() -> dict[str, Any]:
    state = get_system_state("news_guardian", {}) or {}
    return {
        "state": state,
        "events": recent_news_guardian_events(30),
    }


async def review_news_guardian_events() -> dict[str, Any]:
    now = _now()
    events = recent_news_guardian_events(100)
    client = BinanceClient()
    updated = 0
    errors: list[dict[str, Any]] = []
    horizons = {
        "5m": 5,
        "15m": 15,
        "1h": 60,
        "4h": 240,
    }

    try:
        for event in events:
            reference = float(event.get("reference_price") or 0)
            if reference <= 0:
                continue
            created = _dt(event.get("created_at"))
            reactions = dict(event.get("reactions") or {})
            changed = False

            for label, minutes in horizons.items():
                if label in reactions:
                    continue
                target = created + timedelta(minutes=minutes)
                if now < target:
                    continue
                try:
                    target_ms = int(target.timestamp() * 1000)
                    df = await client.klines_1m_between(
                        str(event.get("reference_symbol") or "BTCUSDT"),
                        target_ms - 60_000,
                        target_ms + 180_000,
                    )
                    if df.empty:
                        continue
                    rows = df[df["close_time"] >= target_ms]
                    candle = rows.iloc[0] if not rows.empty else df.iloc[-1]
                    px = float(candle["close"])
                    pct = (px / reference - 1) * 100
                    reactions[label] = {
                        "price": px,
                        "change_pct": round(pct, 3),
                        "at": datetime.fromtimestamp(
                            float(candle["close_time"]) / 1000,
                            tz=timezone.utc,
                        ).isoformat(),
                    }
                    changed = True
                except Exception as exc:
                    errors.append({"event_id": event["id"], "horizon": label, "error": str(exc)[:300]})

            prediction = str(event.get("prediction_result") or "PENDING")
            old_prediction = prediction
            direction = str(event.get("direction") or "UNCLEAR")
            one_hour = reactions.get("1h")
            if one_hour and direction in {"BULLISH", "BEARISH"}:
                change = float(one_hour.get("change_pct") or 0)
                if abs(change) < 0.20:
                    prediction = "MIXED"
                elif (direction == "BULLISH" and change > 0) or (
                    direction == "BEARISH" and change < 0
                ):
                    prediction = "CORRECT"
                else:
                    prediction = "WRONG"
            elif direction == "UNCLEAR" and one_hour:
                prediction = "NO_DIRECTION"

            if prediction != old_prediction:
                changed = True

            if changed:
                update_news_guardian_event(
                    int(event["id"]),
                    reactions=reactions,
                    prediction_result=prediction,
                    updated_at=now.isoformat(),
                )
                updated += 1
    finally:
        await client.close()

    return {"updated_events": updated, "errors": errors, "checked": len(events)}
