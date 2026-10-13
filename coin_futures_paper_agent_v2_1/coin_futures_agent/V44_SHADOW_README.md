# V4.4 Adaptive Intelligence — SHADOW DEVELOPMENT

Status: DRAFT, NOT VALIDATED. Draft code is isolated from existing paper accounts and must not be treated as a production-ready release.

## Implemented on the feature branch
- Trend Intelligence from completed 15m, 1h and 4h candles: direction, trend phase, continuation, exhaustion and quality labels.
- Market breadth context and news risk classification, affecting Shadow entries only.
- Breakout, Pullback and Retest suitability with WAIT and NO_TRADE.
- Persistent Pending Signal manager with expiry, cancellation, confirmation journal.
- Three research variants: ENTRY_ADAPTIVE, EXIT_A_TREND, EXIT_B_RUNNER.
- Additive SQLite v44_ research tables: no reset and no editing of existing A/B/C/D/E/F.
- Hypothesis registry, preliminary paired-cohort analysis, descriptive bootstrap intervals.
- Read-only V4.4 Strategy Lab in dashboard, plus GET /research/v44.
- Research report at 00:10 when enabled, in v44-research.json and v44-research.md.

## Disabled by default
New research settings in local .env:
  V44_SHADOW_ENABLED=false
  V44_SHADOW_SCAN_MAX=12
  V44_SHADOW_MONITOR_INTERVAL_MIN=5

Only turn on in a TEST environment after checking CI, backing up agent.db and confirming the upgrade behaves as intended. The default off avoids impact on active paper strategies. Toggle back to false to disable research.

## Existing run steps
Run the unchanged run.bat and open http://127.0.0.1:8000.
The app does not require real-money exchange credentials for this research.
There are no live-trading capabilities in this feature.

## Unverified / limitations
- Trend scores are heuristic, NOT calibrated forecast probabilities.
- Out-of-sample hypothesis promotion is NOT implemented or validated.
- Gap/restart and fee/fill consistency need independent integration tests.
- The source-signal cohort matching to C/F still requires a rigorous audit.
- Missed-winner evaluation and causally credible News attribution are incomplete.
- Extra scanner API calls and monitoring overhead require load tests.
- Shadow runner behavior is exploratory and partial-fill economics simplified.
- The results must not automatically authorize a new paper or live case.

## Remaining gates before merge
CI success, backed-up database migration rehearsal, persistent shadow monitoring QA,
replay/no-lookahead checks, full cost accounting, paired sample validation, and
independent review of news-event attribution.
