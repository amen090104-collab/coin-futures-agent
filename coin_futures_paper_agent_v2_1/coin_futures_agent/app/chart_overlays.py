"""Map actual trade timestamps to exchange candles, without invented markers."""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
from typing import Any

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
               "1h": 3_600_000, "4h": 14_400_000}


def time_ms(value: str | int | float) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def locate_candle(candles: list[dict[str, Any]], timestamp: str | int | float) -> int | None:
    """Return containing candle. No nearest-bar invention if trade is off chart.

    Binance close_time is open_time+interval_ms-1. Trade execution stamped exactly
    at next open belongs to the new candle, not the just-closed candle.
    """
    if not candles:
        return None
    target = time_ms(timestamp)
    idx = bisect_right([int(x["open_time"]) for x in candles], target) - 1
    if idx < 0 or idx >= len(candles):
        return None
    candle = candles[idx]
    return idx if int(candle["open_time"]) <= target <= int(candle["close_time"]) else None


def build_trade_overlays(candles: list[dict[str, Any]], trade: dict[str, Any]) -> dict[str, Any]:
    entry_idx = locate_candle(candles, trade["opened_at"])
    exit_idx = locate_candle(candles, trade["closed_at"]) if trade.get("closed_at") else None
    markers: list[dict[str, Any]] = []
    for kind, idx, at, price in (
        ("ENTRY", entry_idx, trade["opened_at"], trade["entry_price"]),
        ("EXIT", exit_idx, trade.get("closed_at"), trade.get("exit_price")),
    ):
        if idx is not None and price is not None:
            markers.append({
                "type": kind, "candle_index": idx,
                "candle_open_time": int(candles[idx]["open_time"]),
                "event_time": at, "price": float(price),
                "trade_id": trade.get("id"), "position_id": trade.get("position_id"),
                "strategy_id": trade.get("strategy_id"), "side": trade.get("side"),
                "exit_reason": trade.get("exit_reason") if kind == "EXIT" else None,
                "net_pnl": trade.get("net_pnl"), "r_multiple": trade.get("r_multiple"),
            })
    return {
        "trade_id": trade.get("id"), "strategy_id": trade.get("strategy_id"),
        "entry_visible": entry_idx is not None, "exit_visible": exit_idx is not None,
        "markers": markers,
        "levels": {"entry": trade.get("entry_price"), "stop": trade.get("stop_loss"),
                   "target": trade.get("take_profit"), "exit": trade.get("exit_price")},
        "entry_index": entry_idx, "exit_index": exit_idx,
    }


def build_coin_overlays(
    candles: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [build_trade_overlays(candles, x) for x in trades]
