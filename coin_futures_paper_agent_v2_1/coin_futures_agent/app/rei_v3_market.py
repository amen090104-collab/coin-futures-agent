"""Bounded public USD-M futures history. No keys, current-state fallback or orders."""
from __future__ import annotations

import asyncio
import json
import re
import time

import httpx
import pandas as pd

from .indicators import enrich
from .reverse_intelligence import digest, finite

INTERVALS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
FEATURE_VERSION = "completed-220-utc-v1"


class HistoryError(ValueError):
    pass


class FuturesHistory:
    """Serial requests, durable exact-window cache, bounded retry/backoff; injectable HTTP."""
    def __init__(self, db, *, client=None, sleep=asyncio.sleep, clock=time.time):
        self.db, self.sleep, self.clock = db, sleep, clock
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        self.owned = client is None

    async def close(self):
        if self.owned:
            await self.client.aclose()

    async def bars(self, symbol, interval, decision_ms):
        if not re.fullmatch(r"[A-Z0-9]{2,30}USDT", symbol) or interval not in INTERVALS:
            raise HistoryError("UNSUPPORTED_FUTURES_SYMBOL_OR_INTERVAL")
        step = INTERVALS[interval]
        end = decision_ms // step * step - 1
        start = end + 1 - 220 * step
        if start < 0 or decision_ms > int(self.clock()*1000):
            raise HistoryError("INVALID_DECISION_TIME")
        key = digest([symbol, interval, start, end, FEATURE_VERSION])
        old = self.db.execute("SELECT payload,sha256 FROM rei_v3_market_cache WHERE cache_key=?", (key,)).fetchone()
        if old:
            raw = json.loads(old[0])
            if digest(raw) != old[1]:
                raise HistoryError("CACHE_CHECKSUM_MISMATCH")
        else:
            raw = None
            for attempt in range(3):
                try:
                    response = await self.client.get("https://fapi.binance.com/fapi/v1/klines", params={
                        "symbol": symbol, "interval": interval, "startTime": start, "endTime": end, "limit": 220})
                    if response.status_code in (418, 429):
                        if attempt == 2:
                            raise HistoryError("RATE_LIMIT_RETRY_LATER")
                        retry = finite(response.headers.get("Retry-After"))
                        # Never retry earlier than a long server ban; leave resumable work instead.
                        if retry is not None and retry > 30:
                            raise HistoryError("RATE_LIMIT_RETRY_LATER")
                        await self.sleep(max(1., retry or 2**attempt))
                        continue
                    if response.status_code in (400, 404):
                        raise HistoryError("SYMBOL_HISTORY_UNAVAILABLE")
                    response.raise_for_status()
                    raw = response.json()
                    break
                except (httpx.RequestError, httpx.HTTPStatusError):
                    if attempt == 2:
                        raise HistoryError("HISTORY_NETWORK_UNAVAILABLE") from None
                    await self.sleep(2**attempt)
            # Validate before caching; no empty/delisted response masquerades as a good cache.
            validate_bars(raw, start, end, step)
            self.db.execute("INSERT OR IGNORE INTO rei_v3_market_cache VALUES(?,?,?,?,?)",
                            (key, int(self.clock()*1000), digest(raw), json.dumps(raw),
                             json.dumps({"provider": "binance-usdm-fapi-v1-klines", "symbol": symbol,
                                         "interval": interval, "start_ms": start, "end_ms": end})))
            self.db.commit()
            await self.sleep(.25)  # <=4 requests/sec; retries remain bounded.
        validate_bars(raw, start, end, step)
        frame = pd.DataFrame([{"open_time": int(r[0]), "close_time": int(r[6]),
                               **{k: float(r[i]) for k, i in (("open", 1), ("high", 2), ("low", 3),
                                                             ("close", 4), ("volume", 5))}} for r in raw])
        return enrich(frame), {"cache_key": key, "sha256": digest(raw), "max_source_ms": end,
                              "fetched_at_ms": int(self.clock()*1000), "feature_version": FEATURE_VERSION}


def validate_bars(raw, start, end, step):
    if not isinstance(raw, list) or len(raw) != 220:
        raise HistoryError("MISSING_OR_DELISTED_HISTORY")
    for index, row in enumerate(raw):
        try:
            o, h, l, c, v = [finite(row[i]) for i in (1, 2, 3, 4, 5)]
            if (len(row) < 7 or int(row[0]) != start + index*step or int(row[6]) != int(row[0])+step-1
                    or int(row[6]) > end or None in (o, h, l, c, v)
                    or min(o, h, l, c) <= 0 or v < 0 or h < max(o, l, c) or l > min(o, h, c)):
                raise ValueError
        except (ValueError, TypeError, IndexError, OverflowError):
            raise HistoryError("GAP_STALE_OR_INVALID_CANDLE") from None


async def reconstruct(history, row):
    """Features end BEFORE decision, never at later entry/exit; exact symbol, no rename guessing."""
    decision = row.get("decision_ms", 0)
    if not decision:
        raise HistoryError("SIGNAL_TIME_UNRECOVERABLE")
    frames, evidence = {}, []
    for symbol in dict.fromkeys((row["symbol"], "BTCUSDT")):
        frames[symbol] = {}
        for interval in INTERVALS:
            frame, proof = await history.bars(symbol, interval, decision)
            frames[symbol][interval] = frame
            evidence.append(proof)
    coin, btc = frames[row["symbol"]], frames["BTCUSDT"]
    r15, r1, r4 = (coin[x].iloc[-1] for x in INTERVALS)
    b1, b4 = btc["1h"].iloc[-1], btc["4h"].iloc[-1]
    bull = b4.close > b4.ema20 > b4.ema50 and b1.close > b1.ema20
    bear = b4.close < b4.ema20 < b4.ema50 and b1.close < b1.ema20
    reverse = row["reverse_side"]
    aligned = lambda r: r.close > r.ema20 > r.ema50 if reverse == "LONG" else r.close < r.ema20 < r.ema50
    features = {"source_score": row.get("source_score"), "rsi_1h": finite(r1.rsi14),
                "distance_ema20_atr": finite(abs(r15.close-r15.ema20)/r15.atr14) if r15.atr14 > 0 else None,
                "signed_ema_distance_atr": finite((r15.close-r15.ema20)/r15.atr14) if r15.atr14 > 0 else None,
                "atr_pct_1h": finite(r1.atr_pct), "volume_ratio_1h": finite(r1.vol_ratio),
                "relative_strength_1h_pct": finite(r1.ret_1-b1.ret_1),
                "trend_1h_reverse": float(aligned(r1)), "trend_4h_reverse": float(aligned(r4)),
                "btc_bullish": float(bull), "btc_bearish": float(bear),
                "btc_neutral": float(not bull and not bear), "btc_unknown": 0.,
                # Candle archives cannot recover these point-in-time snapshots.
                "oi_change_pct": None, "funding_rate": None}
    import math
    angle = decision % 86_400_000 / 86_400_000 * 2*math.pi
    features.update(hour_sin=math.sin(angle), hour_cos=math.cos(angle))
    return features, {"status": "RECONSTRUCTED", "origin": "RETROSPECTIVE_PUBLIC_FUTURES",
                      "max_source_ms": max(p["max_source_ms"] for p in evidence), "windows": evidence,
                      "unrecoverable": ["oi_snapshot", "funding_snapshot", "news_guardian", "order_book"] +
                                       (["source_score"] if row.get("source_score") is None else []),
                      "note": "Khởi tạo EMA bằng 220 nến hoàn tất; không cam kết giống snapshot scanner cũ."}
