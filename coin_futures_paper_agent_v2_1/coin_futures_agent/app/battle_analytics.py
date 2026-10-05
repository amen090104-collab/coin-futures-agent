from __future__ import annotations

from typing import Any

from .analytics import build_dashboard_analytics
from .battle_config import STRATEGIES, STRATEGY_IDS
from .battle_storage import (
    battle_account_balance,
    battle_open_positions,
    battle_recent_trades,
)
from .config import settings


def build_strategy_battle_dashboard() -> dict[str, Any]:
    strategies: list[dict[str, Any]] = []
    combined_positions: list[dict[str, Any]] = []
    combined_trades: list[dict[str, Any]] = []

    for strategy_id in STRATEGY_IDS:
        trades = battle_recent_trades(5000, strategy_id)
        positions = battle_open_positions(strategy_id)
        balance = battle_account_balance(strategy_id)
        analytics = build_dashboard_analytics(
            trades,
            positions,
            balance,
            settings.timezone,
            settings.taker_fee_bps,
        )
        for position in analytics["open_positions"]:
            position["strategy_id"] = strategy_id
            position["strategy_name"] = STRATEGIES[strategy_id]["name"]
        for trade in trades:
            trade["strategy_name"] = STRATEGIES[strategy_id]["name"]

        combined_positions.extend(analytics["open_positions"])
        combined_trades.extend(trades)
        strategies.append(
            {
                "strategy_id": strategy_id,
                **STRATEGIES[strategy_id],
                "starting_balance": settings.battle_start_balance,
                "analytics": analytics,
            }
        )

    combined_trades.sort(key=lambda x: (str(x.get("closed_at") or ""), int(x.get("id") or 0)))

    eligible = [s for s in strategies if int(s["analytics"]["closed"]) > 0]
    leader_pnl = (
        max(eligible, key=lambda s: float(s["analytics"]["realized_pnl"]))["strategy_id"]
        if eligible else None
    )
    leader_wr = (
        max(eligible, key=lambda s: float(s["analytics"]["win_rate"]))["strategy_id"]
        if eligible else None
    )
    min_closed = min(
        (int(s["analytics"]["closed"]) for s in strategies),
        default=0,
    )

    return {
        "strategies": strategies,
        "open_positions": combined_positions,
        "trades": combined_trades[-300:],
        "leader_net_pnl": leader_pnl,
        "leader_win_rate": leader_wr,
        "min_closed_per_case": min_closed,
        "sample_ready": min_closed >= 30,
        "recommended_comparison_sample": 30,
    }
