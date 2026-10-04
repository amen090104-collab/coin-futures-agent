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
