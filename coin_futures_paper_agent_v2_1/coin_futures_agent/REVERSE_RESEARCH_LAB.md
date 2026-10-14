# Reverse Research Lab — prospective Case C research

Version: reverse-lab.1. **Shadow only, no paper or real-money orders**.

## What it does

The lab begins only on FUTURE source signals where existing strategy
Case C (REVERSE_RR2) actually opens. It records the exact cohort and
Paper Case C position ID. It never retrospectively fills an old signal.
Simulation can start only at the first future 1m open AFTER observation.

### Four frozen research variants

| Variant | Entry | Exit |
|---|---|---|
| REV-A | Next fully observed future-minute open | Fixed 2R |
| REV-B | Two consecutive future closed 1m reversal bars, then NEXT minute open | Fixed 2R |
| REV-C | Same open as REV-A | 50% partial at +1R; monotonic trailing runner |
| REV-D | Score >=85 immediate, otherwise one future 1m confirmation | Score-conditioned partial and trailing |

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
- Before considering money, require verified negative-scenario safety,
  exchange Testnet order lifecycle, realistic costs and explicit human
  approval. This feature does not provide a switch for live orders.
