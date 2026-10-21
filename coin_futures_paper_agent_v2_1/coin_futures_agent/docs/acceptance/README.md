# Bằng chứng nghiệm thu Issue #18

Hai ảnh dưới đây là giao diện thật được render bằng Chromium, **dữ liệu fixture tổng hợp**, không phải kết quả giao dịch hay bằng chứng lợi nhuận.

- [Thiếu dữ liệu / chưa có điểm](v3-untrained.png)
- [Classifier có điểm / vẫn giữ RISK_GATE](v3-scored-risk-gate.png)

Baseline trước thay đổi: 185 tests đạt. Suite mới bao gồm importer legacy/Battle/Reverse/V2, nhãn xung đột, dedupe/ID reuse, missing indicator, UTC/closed candles, retries/cache/resume, label timing, group/purge/holdout, daily model freeze, late observation không thành OOS, pure historical report repair, render/escaping, WAL backup/integrity, failed/interrupted backup, offline/dirty/Git absent/disk/lock, rollback, supervisor thực và bootstrap từ đúng V2 SHA.

CI chạy Ubuntu Python 3.12 và Windows Python 3.13.5. Kiểm thử CMD được bỏ qua trên Linux và chạy trên Windows. E2E supervisor chạy ASGI fixture không có jobs/trading, cổng loopback ngẫu nhiên. Transaction tests cũ dùng staging fixture; E2E mới clone `local-reverse-v2` từ `5340114`, thực sự fetch/archive revision, tạo venv, chạy pip offline/pip check từ dependencies đã cài cho test, migration probe, WAL backup, health và rollback. Public release/PR/CI feed và ASGI app vẫn là fixture; không chạy lifespan ứng dụng cũ hoặc chạm lịch sử thật.

[Xử lý hai review ngày 21/10/2026](PR19_REVIEW_2026-10-21.md): coverage thực theo nguồn/Base, lane proxy, official archives, smoke BLOCKED và kiểm chứng SHA artifact.

Chưa được nghiệm thu: DB Windows riêng, môi trường GUI/antivirus/proxy của người dùng, cài wheel dependencies trên máy đó, full market reconstruction, historical counterfactual fill/cost và hiệu quả forward OOS. Gói ZIP CI chỉ gồm allowlist mã nguồn/tài liệu/checksum, không có DB, `.env` hoặc reports thật. PR/CI pass không tự phê duyệt release.
