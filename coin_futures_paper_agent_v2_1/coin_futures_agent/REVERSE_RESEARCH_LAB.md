# Reverse Research Lab — prospective Case C research

Version: reverse-lab.2. **Shadow only, no paper or real-money orders**.

## What it does

The lab begins only on FUTURE source signals where existing strategy
Case C (REVERSE_RR2) actually opens. It records the exact cohort and
Paper Case C position ID. It never retrospectively fills an old signal.
Simulation can start only at the first future 1m open AFTER observation.

### Five frozen research variants

| Variant | Entry | Exit |
|---|---|---|
| REV-A | Next fully observed future-minute open | Fixed 2R |
| REV-B | Two consecutive future closed 1m reversal bars, then NEXT minute open | Fixed 2R |
| REV-C | Same open as REV-A | 50% partial at +1R; monotonic trailing runner |
| REV-D | Score >=85 immediate, otherwise one future 1m confirmation | Score-conditioned partial and trailing |
| **REV-E Pattern** | Signal-time learned score from earlier CLOSED REV-A outcomes; if insufficient/not positive, EXPIRE as no-entry | Fixed 2R; no Paper or exchange order |

### REV-E: learn winning and losing Reverse patterns, not Base score

- The Base signal supplies the source direction and a candidate; it does **not**
  automatically justify the opposite position. Score comes from historical
  outcomes of the **same source direction**.
- Each real Case C entry freezes a compact snapshot of source score, RSI 1h,
  EMA20 distance/ATR, volume ratio, OI, ATR, BTC regime, relative strength and
  closed-bar trend flags. Missing features are **not** treated as neutral.
- REV-E compares the new signal to prior **CLOSED REV-A Shadow** cohorts whose
  signal AND close timestamps both precede the new signal. Signals that are
  OPEN, censored, expired or closed in the future are never training labels.
- Similarity uses frozen numeric ranges (research hypotheses); the estimated
  net R is shrunk toward the same-direction historical mean. The displayed
  index is 0-100 and is **NOT** a calibrated win probability.
- Preliminary research gate requires >=30 past CLOSED same-direction cohorts
  from >=7 different UTC signal days, >=20 effective similar samples,
  expected net R >=+0.15 and index >=55. These are precommitted exploratory
  thresholds, NOT validated winning cutoffs.
- If insufficient, REV-E records an EXPIRED/no-entry cohort, not a loss or a
  fabricated profit; A/B/C/D still work unchanged. After REV-A finishes, the
  paired audit counts both avoided losses and missed winners for REV-E skips.
- Old Case C Paper outcomes remain a **separate descriptive analysis** of
  source reason codes and early/recent periods. They never retroactively train
  Shadow, because historical Paper and prospective Shadow have different fill
  timestamps and execution assumptions.
- Full per-signal snapshots stay in the existing local SQLite tables.
  GitHub receives only normal daily Reverse Lab summaries, no giant dataset.
- The scoring policy does not use current/future candle outcomes, does not
  auto-adjust its coefficient ranges, does not promote strategies and does
  not place real orders. It is a candidate for FUTURE walk-forward validation,
  not proof of an edge.

The distance from Case C's original entry to stop is frozen, and stop
and target are rebased to the actual future Shadow entry. Therefore paper
and Shadow do not have identical fills and cannot be treated as identical
executions.

## Research integrity & safety

- Only fully closed 1m OHLC is used for decisions and exits.
- STOP_FIRST when TP and SL hit in same candle.
- Stop gaps filled at adverse opening prices.
- Entry/exit taker fees and adverse slippage are modeled.
- Trailing can only tighten on the next candle; never widen stop.
- Missing candle, invalid candle, or recovery window beyond 48 hours:
  CENSORED, not wins.
- Paired analyses require identical originating Case C cohorts.
- Expired entries are scored at zero R against the matched fixed2R
  reference to measure avoided losses and missed winners.
- No Binance trade API calls; existing A/B/C/D/E/F and their accounts
  are unchanged.
- Results are NOT out-of-sample proven; no automated paper-case promotion.

## Results and reporting

Dashboard menu: **Reverse Research Lab**.

API endpoints:
- GET /research/reverse
- POST /research/reverse/monitor
- GET /reports/daily/YYYY-MM-DD/reverse

New daily report files, produced with the 00:10 analysis:
- reports/YYYY-MM-DD/reverse-lab.json
- reports/YYYY-MM-DD/reverse-lab.md
- reports/YYYY-MM-DD/reverse-lab.html

Reports include matched pairs, mean R, day-cluster uncertainty, missed
winners, avoided losses, BTC regime, Score, RSI, EMA/ATR, OI and funding.
The existing GitHub report sync uploads these automatically when configured.

## Start on Windows

1. Stop the Agent. Back up the agent directory (the new updater takes a
   WAL-safe SQLite backup after its first successful installation).
2. Run update.bat or git pull --ff-only origin main.
3. Ensure your .env already has V44_SHADOW_ENABLED=true and
   STRATEGY_BATTLE_ENABLED=true.
4. REVERSE_LAB_ENABLED defaults to true, so no additional setup is needed.
   Setting it to false disables only the new Reverse Lab.
5. Run run.bat and visit http://127.0.0.1:8000.
6. Open Reverse Research Lab. Cohorts begin at zero until the next actual
   Case C entry. Historic Case C trades do not become synthetic fills.

No Node.js is needed for the local Agent.

## Important limitations before any real-money discussion

- Binance real order books, spread, liquidity, partial exchange fills,
  funding cashflows, liquidation, leverage and exchange downtime are
  NOT fully simulated.
- Multi-coin trade results often depend on the same underlying market move.
- REV-D is an explicit deterministic experimental rule, not a learning
  algorithm that has already demonstrated profitability.
- Because Case C paper and Reverse Lab do not enter at the same time,
  their net R is contextual, not a causal proof.
- Use at least 100 resolved pairs over 14 separate days for preliminary
  comparison, then additionally demand untouched future-period trials.
- REV-E requires special scrutiny of no-entry periods, cohort/day correlation,
  score calibration, data availability, fees, and changing market regimes.
  Its early abstention is a deliberate insufficient-evidence result.
- Before considering money, require verified negative-scenario safety,
  exchange Testnet order lifecycle, realistic costs and explicit human
  approval. This feature does not provide a switch for live orders.
