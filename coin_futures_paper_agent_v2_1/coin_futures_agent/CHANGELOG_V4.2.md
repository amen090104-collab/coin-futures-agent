# V4.2 - Strategy Battle Pro

## Four synchronized paper strategies
- CASE A - BASE 1:2
- CASE B - BASE 1:1
- CASE C - REVERSE 1:2
- CASE D - REVERSE 1:1

Every qualifying source signal creates the four cases as one atomic cohort. Each case has an independent paper account.

## News Guardian
News Guardian is an event-risk layer above Strategy Battle.

Sources:
- CoinDesk
- Cointelegraph
- Federal Reserve official press-release RSS
- SEC official press-release RSS
- optional custom RSS feeds from EXTRA_NEWS_RSS

The engine clusters related recent articles and records:
- impact score
- market or symbol scope
- BULLISH / BEARISH / UNCLEAR direction
- confidence
- related headlines and sources
- cooldown
- 5m / 15m / 1h / 4h price reaction
- prediction result

Modes:
- NORMAL: normal trading
- CAUTION: affected new entries pause during cooldown
- DIRECTIONAL_WARNING: high-impact direction is reasonably clear; new affected entries pause during cooldown
- EVENT_LOCK: high-impact direction is too uncertain; affected open Strategy Battle positions close as NEWS_RISK_EXIT and entries remain locked through cooldown

For a market-wide ambiguous event, the default full-market EVENT_LOCK threshold is impact 90. Symbol-specific ambiguous events can lock at the high-impact threshold.

News classification is automated and can be wrong. It is a risk-management research layer, not a guaranteed price predictor.

## Professional analytics
- equity curve per case
- Net PnL, Profit Factor, Win Rate
- Expectancy, Avg Win R, Avg Loss R
- Max Drawdown
- TP / SL / TIME_EXIT / NEWS_RISK_EXIT rates
- score buckets 75-79 / 80-84 / 85-89 / 90+
- BTC BULLISH / BEARISH / NEUTRAL regime matrix
- BASE vs REVERSE factor comparison
- 1:1 vs 1:2 factor comparison
- best/worst/recent cohort analysis

## Daily Strategy Intelligence Report
At 23:58 Asia/Ho_Chi_Minh:
- A/B/C/D daily comparison
- cumulative sample status
- factor analysis
- analytical commentary
- News Guardian events and prediction accuracy
- best/worst cohorts
- trade details
- Markdown + HTML output under reports/YYYY-MM-DD/

## Scheduler stability
- scheduler misfire grace: 30 seconds
- health check default: 60 seconds
- worker last-run status displayed on dashboard
- favicon request returns 204 instead of console 404 noise

## Clean V4.2 experiment
Run reset_strategy_battle.bat once after upgrading to start A/B/C/D and News Guardian accuracy from a clean experiment state. The reset creates backups first.
