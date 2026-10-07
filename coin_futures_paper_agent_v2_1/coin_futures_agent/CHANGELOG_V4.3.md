# Changelog V4.3 - Adaptive Research Platform

## Strategy Control / Dynamic Cases
- Strategy cases are stored in SQLite instead of being limited to hard-coded A/B/C/D.
- Create, clone, edit, pause/resume cases from the dashboard.
- Per-case filters: score min/max, BTC regime, LONG/SHORT, volume, OI, ATR, BASE/REVERSE, R:R, risk %, max open.
- Every edit increments a case version and is recorded in strategy history.
- Existing A/B/C/D are seeded automatically and remain compatible with V4.2 data.

## Futures research intelligence
- Trade Detail endpoint and dashboard view with candle chart and Entry/SL/TP/Exit markers.
- Entry thesis and signal snapshot are persisted with each new trade.
- Post-trade attribution separates outcome from thesis quality:
  - THESIS_CONFIRMED
  - NEWS_ASSISTED_WIN
  - NEWS_SHOCK_LOSS
  - LATE_ENTRY_OR_EXTENDED
  - THESIS_FAILED
  - RISK_EXIT
- News timeline is shown around the trade.
- Strategy Evaluation adds expectancy, PF, break-even win rate, longest losing streak, drawdown, weekly consistency, attribution and MFE/MAE exit research.
- Optional per-case management modes:
  - FIXED: legacy behavior and default for A/B/C/D.
  - BREAKEVEN_0_8R: after a prior closed candle proves MFE >= 0.8R, the stop moves to entry.
  - TRAIL_AFTER_1R: after a prior closed candle proves MFE >= 1R, a conservative R-based trailing stop can lock profit.
- Adaptive stop activation intentionally uses only prior closed-candle excursion to avoid optimistic intrabar look-ahead.
- Research readiness never auto-promotes a strategy to live. Out-of-sample and real-execution validation remain explicit manual gates.

## Spot Narrative Research
- Spot Research is now news-first.
- Detects and ranks narratives such as RWA, AI, AI Agents, DePIN, DeFi, L2, L1, Memecoin, ETF, institutional adoption, regulation, payments, stablecoins, gaming and cross-chain.
- Maps coins to one or more narratives.
- Narrative lifecycle: NEW / RISING / HOT / MATURE / FADING.
- Ranking uses fresh article count, independent-source breadth, impact and velocity.
- Dashboard shows clickable evidence articles.
- Technical score remains secondary context only; Spot Research does not place orders.

## Reporting
- Daily battle reports support dynamic cases.
- Report type: DAILY_INTELLIGENCE_V43.
- Adds daily-report.json alongside Markdown and HTML for future automatic report sync/analysis.

## Compatibility
- Paper trading remains the default.
- Existing V4.2 database data is preserved.
- No reset is required merely to upgrade to V4.3.
- New cases receive their own independent paper account when created.
