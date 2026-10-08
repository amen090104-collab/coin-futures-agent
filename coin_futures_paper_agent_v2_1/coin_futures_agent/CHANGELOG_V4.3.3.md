# V4.3.3 — Decision Replay & Daily Analysis

## Chart / Coin Intelligence
- On Coin Detail and Trade Replay, ENTRY and EXIT are now **large, candle-aligned arrows**, not dots.
  - Green upward arrow: LONG entry.
  - Red downward arrow: SHORT entry.
  - EXIT arrow carries TP / SL / TIME / NEWS / BE / TRAIL label and result-based color.
  - Related case arrows on one candle are grouped with a count; hover for details and filter by case.
- Show/hide: Entry/Exit, SL/TP, Trade Path.
- Zoom in/out, auto zoom, drag-to-pan and mousewheel zoom.
- Trade Replay: play/pause/step/reset/speed; reveals one closed historical candle at a time. Future EXIT markers remain hidden until the replay reaches them.
- Timestamp alignment uses Binance candle open/close times. Events outside loaded history are never snapped to an unrelated candle.
- 1m view supports full trade path to a bounded 2,500-candle limit; long trades show a clear timeframe warning.

## Decision Journal
- New `trade_decision_journal` SQLite table. Records:
  - Source thesis and strategy-version snapshot at entry.
  - Favorable price excursion milestones +0.5R/+1R/+2R.
  - Actual effective dynamic stop decisions based on prior closed candles.
  - Exit reason, PnL, R and News Guardian forced exits.
- Events are idempotent by position and event key.
- Historical trades created before V4.3.3 show synthetic events with explicit `RECONSTRUCTED` source; no fabricated live decisions.

## Exit Simulator (research only)
- Five what-if scenarios from the *same stored entry and stop*:
  - Fixed 1R.
  - Fixed 2R.
  - Breakeven after 0.8R, TP 2R.
  - Trail after 1R, TP 2R.
  - Half TP at 1R, trailing runner to 2R.
- Uses only future closed 1m OHLC candles **in chronological order**, without leaking future information into earlier decisions.
- Conservative stop-first handling if stop and target are both within one OHLC bar.
- Stop activation only from previously closed-bar excursion.
- Accounts for paper taker fee, configured slippage, gap-through stops and max hold.
- Missing intervals/unresolved paths are reported as `CENSORED`, **not** assumed wins.
- Endpoint `POST /trades/{trade_id}/exit-simulate`.

## 00:10 local Daily Analysis
- Agent at 23:58 produces daily-report JSON/MD/HTML as before.
- At 00:05 GitHub upload retry runs as before.
- **00:10 Asia/Ho_Chi_Minh**: agent finalizes *yesterday's* daily report, including trades closed in its final two minutes, then creates:
  - `reports/YYYY-MM-DD/daily-analysis.json`
  - `reports/YYYY-MM-DD/daily-analysis.md`
  - `reports/YYYY-MM-DD/daily-analysis.html`
  - `reports/research-history.json`
- Includes case and coin comparisons, prior 7/30 report history, entry/exit research, attribution and four sample-gated hypotheses.
- Automatic sync uploads all six daily files, `reports/latest.json`, `reports/latest-analysis.json` and `reports/research-history.json` when GitHub sync is configured.
- 00:20 sync retry. Startup catches up if the computer was off at 00:10.
- Telegram brief sent when configured; generation and GitHub upload do not depend on Telegram success.
- Manual analysis via `POST /reports/daily/YYYY-MM-DD/analysis/run` or Daily Reports → Generate. Historical stored reports are not regenerated from future cumulative data.
- Read through `GET /reports/daily/YYYY-MM-DD/analysis`, `/analysis/markdown`, `/analysis/html`.

## Research integrity
- Analysis is explicitly **deterministic research**, not an external LLM.
- Hypotheses require minimum segment samples and remain exploratory.
- NEWS_ASSISTED means temporal correlation and heuristic classification, not causal proof.
- A/B/C/D baselines, trade rules and SQLite data are not reset or modified.
- Paper trading only. No auto-activation of live money trading.

## Checks
- Python tests: journal, candle mapping, simulator no-lookahead/gaps, daily analysis idempotency.
- GitHub CI tests JavaScript syntax for chart module and embedded dashboard script; Node marker tests.
