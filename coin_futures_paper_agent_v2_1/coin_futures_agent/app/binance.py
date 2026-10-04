import asyncio
from typing import Any

import httpx
import pandas as pd

from .config import settings


class BinanceClient:
    def __init__(self) -> None:
        self.base = settings.binance_base_url.rstrip("/")
        self.sem = asyncio.Semaphore(settings.max_concurrency)
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": "coin-futures-agent-paper/2.0"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with self.sem:
            r = await self.client.get(f"{self.base}{path}", params=params)
            r.raise_for_status()
            return r.json()

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

    async def klines(self, symbol: str, interval: str, limit: int = 220) -> pd.DataFrame:
        raw = await self._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        cols = [
            "open_time", "open", "high", "low", "close", "volume", "close_time",
            "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
        ]
        df = pd.DataFrame(raw, columns=cols)
        for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    async def oi_history(self, symbol: str, period: str = "15m", limit: int = 5) -> list[dict[str, Any]]:
        return await self._get(
            "/futures/data/openInterestHist",
            {"symbol": symbol, "period": period, "limit": limit},
        )
