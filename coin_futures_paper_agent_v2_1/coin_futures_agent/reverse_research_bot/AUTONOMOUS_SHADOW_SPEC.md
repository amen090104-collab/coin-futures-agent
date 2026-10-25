# Autonomous Loss Investigator and Shadow Research — acceptance spec

## Delivered in this branch (offline, not true Shadow)

- `loss_investigator.py` inspects **every closed Paper loser** across all
  cases and both directions. It compares each loss only with same-case,
  same-side trades that **closed before that loss opened**. It derives a
  bounded set of evidence-backed hypotheses from available entry-time
  features, preserves unresolved cases and the winners that a proposed
  filter could miss. It deliberately does not call these causal findings.
- `bot.py` writes local `reverse_research_data/loss-investigations.json`
  plus a brief summary inside `latest.json`; old history is untouched.
- `experiment_lab.py` runs predeclared historical tests. A candidate failing
  holdout may never be frozen as a forward candidate.
- No live Binance orders, no Paper orders, no trading configuration writes,
  no remote upload of personal history.

## Not yet delivered: independent prospective Shadow execution

**Do not mark true Shadow as active until all the following are implemented
and tested**:

1. Immutable local **signal feed before trade outcome** from six-case
   Trading Bot, including *all opportunities* (also signals not traded),
   symbol, decision timestamp UTC, case config version, side, entry-time
   score/indicators, data provenance timestamps, stable cohort/signal ID.
2. Every research hypothesis is separately versioned and **frozen before
   the signals it is evaluated on**. Its rules and evaluation budget are
   recorded, with no invisible dynamic retuning on the same holdout.
3. A **read-only candle store** with sequential immutable 1m OHLC after
   each decision. Missing, amended, stale, gapped or ambiguous candles
   result in CENSORED / UNKNOWN rather than fictional wins.
4. A separate Shadow execution simulator walks 1m candles in time order,
   applies entry/stop/TP and no-entry/expired choices, conservative
   stop-first handling for same-bar conflicts, trading fee, slippage and
   execution limits; records **every potential opportunity**, including
   missed winners and skipped trades. No Binance trade endpoints.
5. Every active hypothesis is evaluated on **forward signals after its
   freeze time**, against the same baseline opportunities and exposures.
   Report win rate, selected sample, net expectancy R, fees, drawdown,
   market-regime subgroups, confidence intervals and data-quality.
6. No automatic configuration change or activation of real trading.
   A successful Shadow candidate must still pass an independently defined
   prospective evaluation and explicit user approval.

## Continuous learning policy

- On each finalized local report: append new closed-trade observations,
  investigate all new losers and update historical summaries. Save an
  append-only hypothesis journal with data lineage.
- When reproducible entry-time signal data become available: run bounded
  retrospective OHLC tests; retire failing candidates with explanations.
- Freeze candidates before prospective Shadow starts. Collect genuinely
  future **signals** even when they produce no Paper trade.
- A hypothesis is allowed to fail. Preserve all failed and unresolved
  investigations; never manufacture a counterfactual winner.
- Research at most one time per new data revision; repeating grid search
  on the same test set must not be treated as new evidence.

## What users should expect

An individual loss can have no identifiable causal explanation. Searching
thousands of rules to turn every historical loss into a winner is
overfitting, not intelligence. Optimize net-after-cost expectancy alongside
win rate and drawdown, with evidence thresholds and conservative uncertainty.
