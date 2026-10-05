import asyncio
from typing import Any

import httpx
import pandas as pd

from .config import settings


_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
]


def _frame(raw: list[list[Any]]) -> pd.DataFrame:
    df = pd.DataFrame(raw, columns=_KLINE_COLS)
    for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["open_time", "close_time"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("int64")
    return df


class _RetryingClient:
    def __init__(self, base: str, user_agent: str) -> None:
        self.base = base.rstrip("/")
        self.sem = asyncio.Semaphore(settings.max_concurrency)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": user_agent},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        attempts = max(1, int(settings.network_retries))
        for attempt in range(attempts):
            try:
                async with self.sem:
                    r = await self.client.get(f"{self.base}{path}", params=params)
                    r.raise_for_status()
                    return r.json()
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                delay = max(0.1, float(settings.network_retry_backoff_sec)) * (2 ** attempt)
                await asyncio.sleep(min(delay, 12.0))
        assert last_error is not None
        raise last_error


class BinanceClient(_RetryingClient):
    def __init__(self) -> None:
        super().__init__(settings.binance_base_url, "coin-futures-agent-paper/4.0")

    async def ping(self) -> bool:
        await self._get("/fapi/v1/ping")
        return True

    async def exchange_info(self) -> dict[str, Any]:
        return await self._get("/fapi/v1/exchangeInfo")

    async def tickers_24h(self) -> list[dict[str, Any]]:
        return await self._get("/fapi/v1/ticker/24hr")

    async def premium_index(self) -> list[dict[str, Any]]:
        data = await self._get("/fapi/v1/premiumIndex")
        return data if isinstance(data, list) else [data]

    async def mark_price(self, symbol: str) -> float:
        data = await self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(data["markPrice"])

    async def mark_prices(self) -> dict[str, float]:
        data = await self.premium_index()
        return {x["symbol"]: float(x.get("markPrice") or 0) for x in data if x.get("symbol")}

    async def klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 220,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        raw = await self._get("/fapi/v1/klines", params)
        return _frame(raw)

    async def klines_1m_between(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        """Fetch closed/recent 1m candles across an outage window, chunking Binance limits."""
        chunks: list[pd.DataFrame] = []
        cursor = max(0, int(start_ms))
        end_ms = int(end_ms)
        while cursor <= end_ms:
            df = await self.klines(symbol, "1m", 1000, start_time=cursor, end_time=end_ms)
            if df.empty:
                break
            chunks.append(df)
            last_open = int(df.iloc[-1]["open_time"])
            next_cursor = last_open + 60_000
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(df) < 1000:
                break
        if not chunks:
            return pd.DataFrame(columns=_KLINE_COLS)
        out = pd.concat(chunks, ignore_index=True)
        return out.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)

    async def oi_history(self, symbol: str, period: str = "15m", limit: int = 5) -> list[dict[str, Any]]:
        return await self._get(
            "/futures/data/openInterestHist",
            {"symbol": symbol, "period": period, "limit": limit},
        )


class BinanceSpotClient(_RetryingClient):
    def __init__(self) -> None:
        super().__init__(settings.spot_base_url, "coin-spot-research-agent/4.0")

    async def ping(self) -> bool:
        await self._get("/api/v3/ping")
        return True

    async def exchange_info(self) -> dict[str, Any]:
        return await self._get("/api/v3/exchangeInfo")

    async def tickers_24h(self) -> list[dict[str, Any]]:
        return await self._get("/api/v3/ticker/24hr")

    async def klines(self, symbol: str, interval: str, limit: int = 220) -> pd.DataFrame:
        raw = await self._get(
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )
        return _frame(raw)
