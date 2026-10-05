# V4.1 - Strategy Battle

## Experiment design
V4.1 compares three paper strategies on the same source signals:

- CASE A - BASE 1:2: current strategy, original direction, TP = 2R.
- CASE B - BASE 1:1: same direction, same Entry/SL as A, TP = 1R.
- CASE C - REVERSE 1:2: opposite direction to the original signal; stop distance is mirrored to the other side; TP = 2R.

Each case has its own independent 10,000 USDT paper account and uses the same configured risk percentage.

## Fair comparison rules
- Entries are cohort-based: one source signal creates A/B/C together.
- If one case closes early, it cannot re-enter that symbol until the other cases in that symbol have also closed.
- A/B/C creation is atomic in SQLite: either all three positions are stored or none are.
- Dashboard only treats the sample as minimally ready when every case has at least 30 closed trades. 50-100 per case is preferred.

## Reset
Run `reset_strategy_battle.bat` once after upgrading.
It requires typing `RESET` and:
- creates a backup of agent.db;
- backs up .env;
- archives old reports;
- clears old Futures paper positions/trades/balances/reports/recommendations/scans;
- resets IDs;
- starts A/B/C at 10,000 USDT each.

Spot Research, news history and System Guardian logs are not deleted.

## Dashboard and reports
- V4.1 dashboard has a Strategy Battle comparison table.
- Open positions and history are labeled CASE A / B / C.
- Daily report at 23:58 compares all three cases separately.
- Win rate is shown together with Net PnL, Profit Factor, Avg R and Drawdown; the system does not choose a winner from win rate alone.

## Reliability
V4.0 recovery, offline replay, crash-safe SQLite closing, backups and System Guardian remain active for all Strategy Battle positions.
