# V5.0 - Adaptive Strategy Research Platform

## Goal

V5.0 turns the paper agent from a fixed four-case experiment into a configurable research platform. Existing A/B/C/D remain as baseline cases and existing paper history is preserved.

## Futures

- Dynamic Strategy Case registry stored in SQLite.
- Create, clone, edit, pause/resume and version cases without editing Python source.
- Per-case filters: score range, BTC regime, LONG/SHORT, volume, OI, funding, ATR, distance from EMA20 in ATR units, risk and max-open limits.
- Per-case direction (BASE/REVERSE), R:R and exit mode.
- Exit modes:
  - FIXED_RR
  - STRUCTURE_TARGET
  - ADAPTIVE
- Optional break-even and adaptive trailing protection, based only on excursion already observed before the next candle.
- Entry thesis snapshot is saved with every new paper position.
- Closed trades receive post-trade attribution so a win/loss can be separated from external high-impact news.
- Trade Detail API returns historical candles plus Entry, Exit, SL and TP markers for replay/review.
- Existing V4.2 fixed geometry helper remains backward compatible.

## Strategy evaluation

- Net PnL, win rate, Profit Factor, expectancy and drawdown.
- Avg win/loss R, holding time and losing streak.
- Segments by score, BTC regime, side and exit mode.
- Weekly stability.
- News-aware quality-adjusted PnL.
- Deterministic Monte Carlo diagnostics after enough samples.
- Research readiness gates. Readiness is diagnostic only and is not an automatic approval for live trading.

## Spot Research

Spot Research is now news-first.

- Narrative/sector mapping (RWA, AI, DePIN, DeFi, L2, ETF/institutional, meme, gaming, payments/stablecoin, restaking, privacy).
- Narrative trend score and lifecycle: NEW/RISING/HOT/MATURE/FADING/WATCH.
- Duplicate-news clustering so copies of the same story do not count as independent events.
- Supporting evidence with source URLs.
- Narrative-to-coin relevance.
- Technical indicators remain secondary context rather than the primary research score.
- No automatic spot orders or BUY/SELL instruction.

## Dashboard

New V5 dashboard includes:

- Overview
- Strategy Control
- Trade Journal / chart replay
- Spot Narratives
- Strategy Evaluation / readiness
- System status

## Upgrade / migration

No reset is required when upgrading from V4.2. On first V5 startup:

- A/B/C/D are seeded into the dynamic case registry.
- Existing battle trades and account history remain in the same database.
- New database tables are created non-destructively.
- New cases receive their own paper account when created.

Keep the agent paper-only while V5 collects enough samples for validation.
