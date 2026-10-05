# V4.0 - Resilient Trading & Spot Research

## Reliability
- SQLite uses WAL + synchronous FULL + busy timeout.
- Closing a paper trade and booking its PnL now happen atomically in one transaction.
- Startup reconciles legacy trades that might exist without a matching account PnL event.
- Database backup on startup, shutdown and every configured interval.
- Backup retention is configurable and backups are ignored by Git.

## Offline / sudden shutdown recovery
- Binance requests retry with exponential backoff.
- System Guardian checks Futures connectivity every 30 seconds.
- OFFLINE state pauses Futures scanner/monitor and Spot Research.
- When connectivity returns, state becomes RECOVERING.
- Open positions replay missed 1-minute candles from the last monitored point.
- SL / TP / time-exit are reconstructed from missed candles before new entries resume.
- Recovery is serialized with the normal paper monitor to avoid races.
- Recovery replay is bounded by each position's max-hold deadline.

## Control Center
- New V4 dashboard shows network state, last backup, last recovery and system events.
- Manual buttons: Futures scan, paper monitor, Spot Research, database backup, recovery.
- Windows run.bat now uses a local .venv and opens the dashboard automatically.
- update.bat performs a local agent.db + .env backup before git pull.

## Spot Research Agent
- Separate Binance Spot research path; it never sends real orders.
- Ranks liquid USDT spot assets using 1H / 4H / 1D trend, RSI, volume, ATR, 7D/30D momentum, BTC regime and stored news context.
- Outputs research score, verdict, risk level, supporting reasons and risks.
- Stores research snapshots in SQLite for later comparison.

## Data preservation
- Existing agent.db schema is extended with new tables using CREATE TABLE IF NOT EXISTS.
- Existing open positions and trade history remain compatible.
- V3.1 Data Collection Mode remains available.
