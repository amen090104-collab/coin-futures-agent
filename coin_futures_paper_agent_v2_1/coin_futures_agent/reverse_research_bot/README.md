# Reverse Research Bot — chạy độc lập trên Windows

**Mục tiêu:** Trading Bot chỉ chạy 6 Case Paper A–F. Research Bot chạy song song trong một tiến trình riêng, dùng bản sao lịch sử chỉ đọc. Không đặt lệnh thật, không tạo lệnh Paper cho Trading, không gửi dữ liệu lên GitHub.

## Dữ liệu được giữ
- `agent.db`: nguồn dữ liệu gốc của Trading Bot, không sửa/xóa.
- `reports/YYYY-MM-DD/trade-history.json` và `.csv`: file ngày được Trading Bot tự lưu trên máy.
- `history_archives/all-history-YYYYMMDDTHHMMSSZ.zip`: bản sao lưu đầu tiên gồm SQLite có WAL, báo cáo và backup cũ; file ZIP có manifest SHA-256, không gồm `.env`, token và mã nguồn updater.
- `reverse_research_data/latest.json`: báo cáo nghiên cứu mới nhất; cùng thư mục chứa lịch sử nghiên cứu theo ngày.

## Sau khi bản mới đã được nghiệm thu, phát hành và cập nhật
1. Dừng Trading Bot; mở **BACKUP_HISTORY.bat** trong thư mục Agent gốc để sao lưu toàn bộ lịch sử hiện có. Chương trình giữ dữ liệu nguồn, xác thực checksum và dừng nếu thiếu dung lượng. ZIP không có mật khẩu, nên lưu tại ổ đĩa riêng tư.
2. Chạy **RUN_CA_HAI_BOT.bat**. Nó tự kiểm tra có backup ban đầu chưa, sau đó mở 6 Case Paper và Reverse Research chạy song song. Ctrl+C dừng hai tiến trình.
3. Hoặc chạy **RESEARCH_BOT.bat** để chỉ chạy Research mà không bật Trading Bot.
4. Bot Research đọc lịch sử cũ từ ZIP và kiểm tra file trade của các ngày đã hoàn tất mỗi 10 phút, học lại khi có giao dịch mới.

## Research làm được gì
- Thống kê thắng/thua từng Case, điều kiện RSI/ATR/volume/score và các cặp BASE-vs-REVERSE cùng cohort.
- Huấn luyện riêng LONG và SHORT từ dữ liệu đã đóng lệnh, phân chia theo thời gian, chỉ dùng thông tin đã biết tại thời điểm vào lệnh; thử ngưỡng trên validation và trình bày test ngoài mẫu riêng.
- Tự đánh giá giả thuyết thay TP ở 0.5R, 1R, 1.5R, 2R bằng MFE/MAE nhưng **KHÔNG được ghi nhận đó là lệnh thắng mới**. Để xác nhận cần phát lại thứ tự nến, phí và trượt giá ở bước tiếp theo.
- Nếu thiếu dữ liệu hoặc nhãn chưa xuất hiện tại mốc tập huấn luyện, báo INS UFFICIENT_DATA/IN SUFFICIENT_HISTORY, không gán kết quả ảo.

## Giới hạn quan trọng
- Đây là **research offline**, không phải chiến lược đã chứng minh có lợi nhuận. Không dùng mô hình để tự mở lệnh.
- ZIP chỉ chứa lịch sử **hiện còn trên máy**. File cũ chỉ còn trên GitHub mà không còn trong database phải nhập thêm bằng bước phục hồi riêng.
- Code Reverse Lab cũ trong Trading được tắt ở LEAN nhưng chưa xóa vật lý, và các bảng Reverse trong SQLite chưa bị xóa, đến khi người dùng xác nhận bản backup trên Windows.
- PR #28 mới là source. Không tự merge, không tự phát hành hay cài đặt lên máy trước khi CI Windows, Ubuntu và backup từ máy thật đã kiểm tra.

## Chạy thủ công khi phát triển
    python reverse_research_bot/backup_history.py --root .
    python reverse_research_bot/bot.py --root . --once
    python reverse_research_bot/bot.py --root . --watch --interval 600
