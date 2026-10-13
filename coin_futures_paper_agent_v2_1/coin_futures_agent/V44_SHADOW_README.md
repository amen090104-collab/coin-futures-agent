# V4.4 Adaptive Intelligence + Strategy Lab

**Research release candidate.** The code implements all six agreed modules in
an isolated Shadow engine. It does not use real money, change existing paper
strategy cases, reset balances, or require Node.js.

## User-facing features

1. **Trend Intelligence**: 15m/1h/4h EMA structure, RSI, ADX, ATR, phase,
   strength, continuation, exhaustion, and risk. Estimates are heuristics,
   not certified forecasting probabilities.
2. **Adaptive Entry**: automatically evaluates Breakout, Pullback and Retest;
   enters an independent future-minute Shadow position or WAIT/NO_TRADE.
   High-confidence confirmed trend-opposite setups can be tested independently
   of the source signal. Blind reversals are prohibited.
3. **Pending Signal Manager**: durable SQLite states, expiry, cancel reasons,
   optional one-time method switch, and news/event risk rechecks. Entry fills
   use only a future observed minute open; they are hypothetical executions,
   not actual Binance trades.
4. **Smart Exit 2.0**: forward-only candidate exit policies EX-A (Trend-Aware
   fixed 2R cap), EX-B (partial 50% at +1R, potential 2R+ runner), along
   with ENTRY_ADAPTIVE and SOURCE_FIXED_2R controls. Original SL is never
   widened. Stop wins an ambiguous 1m OHLC candle, fees and slippage counted.
5. **Market & News**: scanned-universe breadth, BTC alignment, coin/BTC
   relative strength, funding context, verified news-event key, caution
   gating and risk locks. News sector tags are not treated as capital flows;
   only published-and-ingested news at decision time is used.
6. **Strategy Learning + Full Strategy Lab**: records rejected, expired,
   cancelled and accepted cohorts, outcomes and missed winners; automatically
   discovers adverse conditions, preregisters frozen skip-rule hypotheses,
   logs prospective Shadow policy decisions, evaluates on future cohorts
   using day-clustered bootstrap CIs, checks Case C/F only if matched and
   same direction, and may create PAPER PROPOSALS for **user review only**.
   No automatic promotion or change to existing cases.

## One-click upgrade on Windows

After this version is merged into the approved main branch:

1. Stop the running Agent window (preserve the old agent.db).
2. Double-click **update.bat**. It uses the SQLite backup API, including
   committed WAL changes, verifies backup integrity, saves the existing .env
   and only then runs a fast-forward pull from main.
3. Optional but recommended: test on a copy of agent.db first.
4. Double-click **enable_v44_shadow.bat**. This saves .env again and sets
   V44_SHADOW_ENABLED=true without changing unrelated settings.
5. Double-click **run.bat**. Open http://127.0.0.1:8000 then sidebar
   **V4.4 Strategy Lab**. The first cohort will appear after a scan;
   a hypothesis needs multiple closed controls and future cohorts.
6. To stop research without stopping paper strategy cases, use
   **disable_v44_shadow.bat** and restart the Agent.

Do not copy another user's .env, tokens or agent.db. You do not need Node.js
to run the Agent; it uses Python.

## Configuration (optional)

V44_SHADOW_ENABLED=false
V44_SHADOW_SCAN_MAX=12
V44_SHADOW_MONITOR_INTERVAL_MIN=5

The flag is **false by default**, so updates alone never silently increase
research network, CPU or SQLite load. Paper strategies A/B/C/D/E/F continue
under existing settings.

## Endpoints

- GET /research/v44 — current Shadow positions, pending, hypotheses, proposals
- GET /research/v44/analysis — most recent detailed research summary
- POST /research/v44/analysis/run — recompute prospective research
- POST /research/v44/monitor — manually run safe Shadow monitor
- GET /reports/daily/YYYY-MM-DD/v44 — locally generated HTML research report

The existing 00:10 analysis creates:
  reports/YYYY-MM-DD/v44-research.json
  reports/YYYY-MM-DD/v44-research.md
  reports/YYYY-MM-DD/v44-research.html

These are included in GitHub sync if existing report sync is configured.
The run on the user's PC must remain up or restart after the normal catch-up
window. Existing reports and 00:10 local analysis remain intact.

## Research integrity

- All prospective features are evaluated at signal time. Training and future
  hypothesis outcomes are separated by the hypothesis registration timestamp.
- Missing candles, stale data, unresolved trade paths and unlinked News events
  are not assumed winners. Test in sustained Shadow operations before using
  conclusions for paper strategy decisions.
- Skip-policy effects on matched cohorts are counterfactual no-trades. They
  do not establish causal prediction or live fills.
- Statistical intervals are exploratory, clustered by UTC signal day with a
  basic multiplicity correction for frozen candidate skip hypotheses.
- Trade-side opposite to Case C/F is excluded from same-direction comparisons.
- An AI-discovered policy is proposed for paper only if the held-out sample
  passes gating; **user approval is mandatory**. A paper-case implementation
  requires an explicit case configuration separately, no auto-enablement.
- No actual future market performance guarantee.

## Operational acceptance

GitHub CI verifies Python compile, existing regression tests, JavaScript
syntax, isolated WAL backup, prospective hypothesis event logging, market
event timestamps, conservative exit fills, Pending uniqueness and report
generation. CI pass does not replace multi-day real-market Shadow validation.

Set V44_SHADOW_ENABLED=false after any research data-integrity warning while
continuing to use the unchanged paper strategies.
