# Strategy Battle V4.1

> V4.1 runs three synchronized paper strategies on the same Futures signals so win rate and profitability can be compared fairly.

## Cases
- **CASE A - BASE 1:2**: current strategy.
- **CASE B - BASE 1:1**: same Entry/SL, TP at 1R.
- **CASE C - REVERSE 1:2**: opposite side of the current signal, mirrored stop distance, TP at 2R.

Each case starts with **10,000 USDT independently**.

## One-time upgrade reset
After pulling V4.1, stop the agent and run:

```bat
reset_strategy_battle.bat
```

Type `RESET` when prompted. The script backs up the old database and .env before clearing old Futures paper history.

Then run:

```bat
run.bat
```

The dashboard at `http://127.0.0.1:8000` will show the A/B/C comparison.

See `CHANGELOG_V4.1.md` for the experiment rules and reset details.

---

# Coin Research & Paper Platform V4.0

> V4 adds crash-safe paper accounting, automatic backup/recovery, a System Guardian for offline events, a new Control Center, and a dedicated Spot Research Agent.

## V4 quick start on Windows
1. Run `update.bat` when you want to safely update an existing Git clone. It backs up `agent.db` and `.env` before `git pull`.
2. Run `run.bat`. V4 creates/uses a local `.venv`, checks dependencies, starts the server and opens the dashboard.
3. Dashboard: `http://127.0.0.1:8000`.

## What happens if Wi-Fi or power is lost?
- Existing open positions remain in `agent.db`.
- While Binance is offline, new Futures entries and Spot Research pause.
- When Binance reconnects, V4 replays missed 1-minute candles before resuming entries.
- If a missed candle hit SL/TP, the trade is reconstructed and closed through the same accounting path used by live monitoring.
- Database backups are created at startup, shutdown, periodically, and manually from the dashboard.

## Spot Research Agent
The Spot Research tab is an automated quantitative + news research agent. It ranks opportunities and explains supporting factors and risks. It is **research-only** and does not place spot buy/sell orders.

See `CHANGELOG_V4.md` for details.

---

# Coin Futures Paper Agent V3.1

> V3.1 = V3.0 + Data Collection Mode để tăng tốc thu thập mẫu paper trading.

## Điểm mới V3
- Dashboard V3 tại `http://127.0.0.1:8000`.
- Equity, realized/unrealized PnL, max drawdown, profit factor, open risk/notional.
- PnL và R hiện tại của từng lệnh đang mở.
- Trạng thái scanner: đang chạy, thời gian quét, số coin đã quét và lỗi gần nhất.
- Hiệu suất theo ngày, LONG/SHORT và từng reason code/setup.
- API mới: `GET /analytics`.
- Xem chi tiết tại `CHANGELOG_V3.md`.

---

## Data Collection Mode (tạm thời)

Bản hiện tại mặc định bật `DATA_COLLECTION_MODE=true` để thu thập mẫu nhanh hơn.

Khi bật:
- mọi setup vượt qua các filter chiến lược hiện tại đều có thể mở paper trade;
- không còn giới hạn 3 lệnh mới mỗi scan;
- tối đa 50 lệnh mở, nhưng vẫn chỉ 1 lệnh/coin tại một thời điểm;
- daily-loss guard tạm bỏ qua;
- risk/lệnh giảm còn 0.10% để paper balance không bị biến dạng quá nhanh;
- Entry/SL/TP, score threshold, volume filter, ATR filter và logic đóng lệnh vẫn giữ nguyên.

Muốn quay về chế độ bình thường, thêm hoặc sửa trong `.env`:

```env
DATA_COLLECTION_MODE=false
```

---

# Coin Futures Paper Agent v2.1

> Paper trading only. v2.1 adds a Vietnamese dashboard and automatic market-news research.

## Quick start
1. Run `run.bat` on Windows.
2. Open `http://127.0.0.1:8000`.
3. Use the dashboard buttons instead of Swagger for normal use.
4. The agent scans automatically every 15 minutes, monitors positions every 60 seconds, and refreshes news every 10 minutes by default.

## News research
The agent reads CoinDesk RSS and Cointelegraph RSS, classifies headline/summary sentiment, assigns impact/category, detects coin mentions, and builds a 24h market-news bias. News context is recorded with new paper trades, but it does not alter the quantitative score in v2.1.

## Upgrade from v2
See `UPGRADE_FROM_V2.txt`. Keep your old `agent.db` and `.env` to preserve paper-trading history and settings.

---

# Coin Futures Paper Agent v2

Agent theo dõi khoảng 50 hợp đồng Binance USD-M Futures, tự tạo kế hoạch Entry/SL/TP và **paper trading**. Không gửi lệnh tiền thật.

## Chức năng chính

- Tự chọn 50 USDT perpetual có thanh khoản cao theo 24h quote volume.
- Quét 15m / 1h / 4h, EMA20/50/200, RSI14, ATR14, volume ratio, breakout, OI và funding.
- Chấm riêng LONG_SCORE / SHORT_SCORE và dùng BTC làm market-regime filter.
- Tạo Entry + Stop Loss + Take Profit theo ATR + cấu trúc giá.
- Position sizing theo % rủi ro tài khoản paper.
- Theo dõi lệnh mỗi 60 giây bằng nến 1m; mô phỏng phí + slippage.
- Guardrails: tối đa số lệnh mở, rủi ro/lệnh, daily loss limit, thời gian giữ lệnh.
- Lưu lý do vào lệnh, metrics tại thời điểm vào và reason codes.
- Sau mỗi lệnh thua: tự tạo postmortem "tại sao có thể thua" + phương án cần backtest.
- Báo cáo mỗi ngày: trades, W/L, win rate, net PnL, profit factor, Avg R, drawdown, từng lệnh thua và đề xuất cải thiện.
- Đề xuất cải thiện được lưu nhưng **không tự thay rule**, tránh overfit sau vài lệnh thua.
- Dashboard web + Telegram tùy chọn.

## Chạy trên Windows

1. Cài Python 3.11 hoặc 3.12.
2. Giải nén thư mục.
3. Nhấp đúp `run.bat`.
4. Mở `http://127.0.0.1:8000`.

Lần đầu chương trình tự copy `.env.example` thành `.env`, cài thư viện và tạo `agent.db`.

## Luồng hoạt động

```text
Binance market data
  -> scan top 50
  -> score LONG/SHORT
  -> build Entry/SL/TP
  -> risk sizing
  -> open PAPER position
  -> monitor 1m candles
  -> SL / TP / time exit
  -> calculate PnL + fees + R multiple
  -> loss postmortem
  -> daily statistics
  -> improvement proposals for backtest
```

## Entry / SL / TP

- Entry: giá signal 15m đã đóng, có mô phỏng slippage.
- SL: kết hợp swing gần nhất và ATR; bỏ setup nếu stop quá nhỏ hoặc quá rộng.
- TP: mặc định `2R` (`REWARD_RISK=2.0`).
- Size: mặc định rủi ro 0.5% paper balance / lệnh.

## Cấu hình quan trọng trong `.env`

```env
TOP_N_COINS=50
SCORE_THRESHOLD=75
SCAN_INTERVAL_MIN=15
MONITOR_INTERVAL_SEC=60
PAPER_START_BALANCE=10000
RISK_PER_TRADE_PCT=0.50
MAX_OPEN_TRADES=5
MAX_DAILY_LOSS_PCT=3.0
REWARD_RISK=2.0
STOP_ATR_MULT=1.35
TAKER_FEE_BPS=5
SLIPPAGE_BPS=2
```

Phí futures thực tế tùy tài khoản/tier, nên chỉnh `TAKER_FEE_BPS` để gần tài khoản anh nhất.

## Dashboard/API

- `GET /` - dashboard.
- `GET /health` - trạng thái paper account.
- `POST /scan/run` - quét ngay.
- `GET /scan/latest` - scan mới nhất.
- `GET /positions` - lệnh paper đang mở.
- `GET /trades?limit=100` - lịch sử lệnh.
- `POST /paper/monitor` - ép kiểm tra SL/TP ngay.
- `GET /reports/daily/YYYY-MM-DD` - báo cáo ngày.
- `GET /reports/daily/YYYY-MM-DD/markdown` - báo cáo dạng text/Markdown.
- `GET /recommendations` - các đề xuất cải thiện.

Báo cáo Markdown cũng được lưu trong thư mục `reports/`.

## Cách agent phân tích lệnh thua

Agent kiểm tra các dấu hiệu có thể lặp lại như:

- đi ngược BTC regime;
- volume yếu;
- OI không xác nhận;
- funding quá crowded;
- ATR quá cao;
- entry quá xa EMA20 (đuổi giá);
- score chỉ vừa qua ngưỡng;
- breakout thất bại nhanh;
- lệnh từng đạt +1R nhưng cuối cùng quay lại SL.

Sau đó tạo phương án để **backtest**, ví dụ nâng volume filter, tăng score threshold, chờ retest breakout, chặn counter-regime hoặc thử break-even ở +1R. Agent không tự áp dụng thay đổi vào strategy đang chạy.

## Lưu ý paper simulation

- Khi cùng một nến 1m chạm cả SL và TP, mặc định agent xử lý bảo thủ: tính SL trước vì OHLC không biết thứ tự di chuyển trong nến.
- Đây là forward paper simulation, không phải backtest tick-by-tick.
- Máy phải đang chạy để agent tiếp tục scan/monitor.
- Đây là công cụ nghiên cứu, không bảo đảm lợi nhuận và chưa có kết nối đặt lệnh thật.
