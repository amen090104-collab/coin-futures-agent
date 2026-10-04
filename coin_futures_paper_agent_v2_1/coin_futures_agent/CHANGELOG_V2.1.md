# Coin Futures Paper Agent v2.1

## Nâng cấp giao diện
- Dashboard tiếng Việt, tối ưu cho desktop/laptop và dùng được trên điện thoại.
- Nút **Quét ngay**, **Cập nhật tin**, **Kiểm tra lệnh**, **Làm mới** ngay trên trang chủ.
- Tabs: Tổng quan, Scanner 50 coin, Lệnh đang chạy, Lịch sử giao dịch, Tin tức thị trường, Báo cáo & Khắc phục.
- Hiển thị Top LONG/SHORT, điểm score, RSI, volume ratio, OI, funding, ATR và lý do tín hiệu.
- Bảng lệnh paper và lịch sử lệnh dễ đọc hơn.
- Báo cáo/nguyên nhân thua/đề xuất sửa chiến lược gom vào cùng giao diện.

## News Research
- Tự cập nhật RSS mỗi 10 phút mặc định.
- Nguồn mặc định: CoinDesk RSS và Cointelegraph RSS.
- Tự phân loại: BULLISH / BEARISH / NEUTRAL.
- Tự chấm Impact 0-100 và nhóm tin: MACRO, REGULATION, SECURITY, EXCHANGE, MARKET, PROJECT.
- Tự nhận diện các coin phổ biến và ticker nằm trong universe scan.
- Tạo Market News Bias 24h, News Risk và số lượng high-impact news.
- Khi mở paper trade, agent ghi lại bối cảnh news 24h vào `entry_context` và `reason_text`.
- Khi lệnh thua, postmortem có thể phát hiện xung đột giữa hướng lệnh và tin tức, hoặc nhiều high-impact news.

## Lưu ý chiến lược
News trong v2.1 là **research context**, chưa tự đổi LONG/SHORT score và chưa tự block lệnh. Điều này cố ý để tránh overfit hoặc phản ứng sai với headline. Sau khi có đủ paper data có thể backtest News Filter ở bản sau.
