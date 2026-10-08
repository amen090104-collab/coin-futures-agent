# Changelog V4.3.2 - Coin Intelligence + Rich Auto Reports

## Coin Intelligence
- Click a coin from Futures Scanner, Open Positions, Trade History, Cohort Analysis, Spot Research or Daily Reports.
- Coin Detail shows:
  - 1m / 5m / 15m / 1h / 4h candle chart.
  - historical trade markers and open-position markers.
  - complete paper trade history for the coin.
  - per-case performance.
  - LONG vs SHORT performance.
  - BTC regime performance.
  - score-bucket performance.
  - Win Rate, Net PnL, Profit Factor, Expectancy, Max Drawdown, MFE and MAE.
  - recent coin-specific news.
  - Spot narrative/sector context.
- Each historical trade still opens the detailed Trade Replay with Entry/SL/TP/Exit, thesis snapshot, News Timeline and outcome attribution.

## Daily Intelligence Report
- Report type upgraded to DAILY_INTELLIGENCE_V432.
- The 23:58 report now adds:
  - daily coin performance.
  - cumulative best/worst coins.
  - trade outcome attribution.
  - deterministic research findings.
  - research-readiness table.
  - MFE/MAE exit research.
  - attribution label on each closed trade.
- JSON, Markdown and HTML carry the same richer research data.
- Telegram summary includes best/worst coin and attribution counts.

## GitHub Report Sync
- Keeps the V4.3.1 automatic flow:
  - 23:58 report generation.
  - immediate GitHub publication.
  - 00:05 retry for the previous day on transient failure.
  - reports/YYYY-MM-DD/daily-report.json
  - reports/YYYY-MM-DD/daily-report.md
  - reports/YYYY-MM-DD/daily-report.html
  - reports/latest.json
- Dashboard now exposes sync configuration and last sync status.
- Manual Sync button is available in Daily Reports.

## Compatibility
- No database reset is required.
- Existing V4.2/V4.3/V4.3.1 trades remain readable.
- Existing A/B/C/D case history is preserved.
- Paper research remains the default; this release does not enable real-money trading.
