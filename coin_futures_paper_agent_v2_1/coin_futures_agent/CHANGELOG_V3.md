# Coin Futures Paper Agent V3.0

## Dashboard & vận hành
- Dashboard V3 tiếng Việt tách riêng khỏi dashboard V2.1 để dễ rollback.
- Hiển thị Equity = Paper balance + PnL đang mở.
- Hiển thị PnL chưa đóng và R hiện tại cho từng vị thế.
- Hiển thị Open Risk, Open Notional, Profit Factor, Avg R và Max Drawdown.
- Scanner có trạng thái rõ ràng: đang quét / sẵn sàng / lỗi, thời gian quét và số coin đã quét.
- Bảng vị thế có giá gần nhất, PnL mở, R mở và thời gian giữ lệnh.

## Phân tích hiệu suất
- Thống kê theo ngày: số lệnh, win rate, net PnL, Avg R.
- So sánh LONG và SHORT.
- Thống kê reason code/setup: số lệnh, số thắng, win rate, net PnL và Avg R.
- Thêm endpoint GET /analytics.
- /api/dashboard trả dữ liệu analytics để giao diện sử dụng.

## An toàn thay đổi
- Không thay đổi scoring, Entry/SL/TP hay logic đóng lệnh cốt lõi trong V3.0.
- V3 tập trung quan sát và đo lường trước khi tối ưu strategy để tránh overfit.
- Thêm test cho analytics và workflow compile/test.

## Lưu ý
PnL đang mở dùng last_price được paper monitor cập nhật định kỳ, không phải tick realtime.
