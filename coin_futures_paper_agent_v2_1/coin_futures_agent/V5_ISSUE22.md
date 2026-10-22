# Bản vá V5 — Issue #22

Tiếp tục từ V5 `30a18955ca80ef4b5b9ba89519fc3c920be321c8` / PR #21. Dùng cùng cách giải nén ZIP rồi chạy `update.bat`; không cài lại V2/V3. Version ứng dụng vẫn 5.0.0, phân biệt bản vá bằng full source SHA; module nghiên cứu là `rei-v3.3`, schema vẫn 2. Không thay đổi `strategy.build_trade_plan`, A/B/C/D/REV-E, tham số giao dịch, `.env` hay dữ liệu Paper/balances/reports.

## Kết luận từ bằng chứng hiện có

Issue #22 ghi lại chẩn đoán read-only thật từ Windows; chưa cung cấp DB hoặc frame gốc.

| Số đo người dùng | Điều xác nhận được | Điều chưa thể kết luận |
|---|---|---|
| 5.755 cohort V2, 72 quality OK, 5.683 không có plan | Collector xét mọi dòng LONG/SHORT trong scan, kể cả dòng chưa vượt bộ lọc giao dịch | Không thể quy 5.683 dòng thành lỗi mã; chưa biết phân bố score/volume/ATR/stop/frame |
| Missing core/optional theo script cũ đều 0 | V3 dùng `quality_ok=false` để gắn `MISSING_FEATURE`, dù plan có thể mới là thứ thiếu | Không có đủ bằng chứng để khẳng định cả 91 dòng đều do một bộ lọc cụ thể |
| 4.046 predictions: 3.955 muộn, 91 MISSING_FEATURE | Mã cũ đưa backfill muộn vào danh sách dự đoán gần đây; không cấp forward score cho chúng | Không thể biến chúng thành forward OOS bằng cách đổi nhãn |
| 1.668 historical rows, 74 READY, 1.594 pending | READY chỉ nói đặc trưng đã có, không nói đã đủ mẫu train | Chưa biết 74 dòng thuộc lane/policy/group/ngày/label clock nào |
| Frozen LONG/SHORT training_n=0 | `fit` lọc nguồn, policy, provenance, group, holdout và label cutoff trước khi đếm | Chưa thể chỉ đúng bao nhiêu mẫu bị loại ở mỗi gate trên máy người dùng |

Lỗi xác nhận: thông báo thiếu feature sai nguyên nhân và danh sách recent bị lấn bởi backfill. Thiếu chẩn đoán ở điểm `build_trade_plan` trả None đã che mất nguyên nhân gốc. Bản vá ghi lý do từ **đúng row/frame khi scan mới chạy**, không suy ngược bằng settings hoặc trạng thái hiện tại cho lịch sử cũ.

## Các thay đổi

`rei_plan_diagnostics.inspect_plan` gọi builder gốc đúng một lần, không sửa builder/threshold. Ghi first-failing gate và snapshot các ngưỡng/giá trị liên quan: `PLAN_OK`, `SCORE_BELOW_THRESHOLD`, `VOLUME_BELOW_MIN`, `ATR_ABOVE_MAX`, `STOP_TOO_NARROW`, `STOP_TOO_WIDE`, `MISSING_15M_FRAME`, `FRAME_INDICATOR_INVALID`, `ATR_NON_POSITIVE`, `PLAN_RISK_INVALID`, `BUILD_EXCEPTION`. Exception chỉ ghi loại, không ghi nội dung tùy ý. Trường hợp không xác định giữ `PLAN_GATE_UNRECORDED`.

Cohort mới giữ `scan_id`, cohort ID, timestamp, plan reason/context và research eligibility. Log `REI_PLAN_GATES` có scan/time/counts theo chiều Base. Dashboard/JSON có latest scan, rolling 24h, cửa sổ tối đa 10.000 cohort và cờ truncated, missing core/optional riêng, plan/feature/timestamp riêng. Cohort legacy thiếu reason giữ `LEGACY_PLAN_REASON_UNRECORDED`; không sửa payload lịch sử để bịa lại nguyên nhân.

Features hợp lệ + timestamp đúng có thể dùng cho thống kê quan sát dù bị lọc plan. `SKIPPED_BY_TRADE_FILTER` không phải thiếu chỉ báo. Paired-policy/control vẫn đòi plan/risk hợp lệ; không tạo fill/outcome/backtest cho dòng bị loại. `MISSING_FEATURE` chỉ còn dùng khi core thiếu/sai; `TIMESTAMP_INVALID` tách riêng. OI/funding không có snapshot vẫn null, không lấy giá trị hiện tại bù lịch sử.

Quan sát mới quá 60 giây hoặc đã có outcome dùng `HISTORICAL_OBSERVED_LATE`, không cấp score, không forward eligible. Overview loại cả mã mới và mã legacy `MISSED_DECISION_WINDOW` khỏi recent, đếm riêng. Bản ghi prediction/model đã freeze không bị UPDATE. UI chỉ thêm phần giải thích hiện tại cho legacy `MISSING_FEATURE`, giữ trạng thái gốc.

## Vì sao READY có thể đi cùng training_n=0

Mỗi chiều LONG/SHORT có ba bảng bằng chứng độc lập:

- `historical_for_frozen_model`: Paper/Export và policy Case C `REVERSE_RR2`, dùng `label_available_ms` (thời điểm thực sự nhập/biết nhãn).
- `historical_retrospective`: cùng lịch sử, dùng `historical_label_known_ms` để nghiên cứu hồi cứu; **không phải dữ liệu đã biết khi model online freeze**.
- `forward_shadow`: chỉ `FORWARD_SHADOW_V2`, control `REVERSE_NOW`; không gộp các variant thành mẫu độc lập.

`fit_inputs` là đường chọn mẫu dùng chung với `fit`: READY, core hợp lệ, provenance max-source <= decision <= entry <= close, net R có thật, group duy nhất, policy/lane đúng, holdout bị loại, nhãn biết và đóng **trước cutoff UTC 00:00 trừ embargo 1 giờ**. Label time thiếu/0 bị loại rõ `LABEL_TIME_UNKNOWN`. `excluded_counts` là first-failing gates, tổng các loại trừ + training_n bằng records trong chiều đó (giới hạn history 2.000 cũng được đếm).

Sau đó vẫn cần 9 ngày dữ liệu, ít nhất 7 ngày fit, 30 mẫu fit, 12 calibration và hai lớp kết quả. Không hạ các yêu cầu này. `training_n` là số cohort sau cutoff, khác `fit_n` và số READY. Bảng có lane-ready, distinct groups, PIT-valid groups, policy counts, provenance, label clock, holdout exclusions, số ngày và các lý do chưa fit được.

Ví dụ cơ chế, **không phải phân bố đã chứng minh của 74 dòng thật**: nhãn vừa import lúc 10:00 UTC chưa thể thuộc model freeze 00:00 cùng ngày; model cũ training_n=0 giữ nguyên đến lần freeze ngày sau. Nếu chỉ có Shadow variant/khác Case C, trùng group, thuộc holdout hoặc ít ngày thì cũng chưa đủ train. UI tách evidence tính hiện tại với model đã freeze; không huấn luyện lại model của ngày cũ để tạo điểm quá khứ.

## Phục hồi có giới hạn và số đo

Lịch scheduler vẫn 5 phút, lock hiện tại giữ nguyên. Batch signal mặc định 10 thay vì 2, tối đa 50; public HTTP budget 48 requests, time budget 20 giây; proxy có tối đa 2 mẫu/5 giây riêng và dùng chung request budget. Có thể cấu hình riêng các biến nghiên cứu `REVERSE_ENTRY_V3_RECONSTRUCT_BATCH`, `REVERSE_ENTRY_V3_HISTORY_REQUEST_BUDGET`, `REVERSE_ENTRY_V3_HISTORY_TIME_BUDGET_SEC`; bản vá không tự ghi `.env`, không bật bất kỳ opt-in nào.

Giữ REST + archive USD-M chính thức, checksum, cache và PIT validation cũ. Mỗi mẫu hoàn tất commit/checkpoint riêng. Ưu tiên mẫu chưa thử để không bị kẹt ở hàng đầu; retry tăng dần 1/2/4/6 giờ. Khi lỗi mạng/access/rate limit toàn cục, dừng batch và cooldown một giờ thay vì tiếp tục gọi cho mọi mẫu. Hết budget/timeout lưu retry, giữ cache các cửa sổ đã tải và giữ nguyên mẫu chưa thử.

`reconstruction_progress` có attempted, status counts, public requests, elapsed, READY trước/sau/delta, stop reason, retry time; có cộng dồn đo được theo ngày UTC. `best_case_records_per_hour=120` và pending 1.594 tương ứng khoảng **13,33 giờ tối thiểu** chỉ là giới hạn lý thuyết khi mọi batch đủ 10/mọi request thành công. Không cam kết tốc độ đó; timeout, rate limit, cache và chất lượng dữ liệu quyết định số đo thật. Số đo từ fixture/CI không phải throughput trên DB người dùng.

## Cài và chẩn đoán trên máy Windows

1. Dừng Agent. Giải nén toàn bộ ZIP bản vá vào **folder Agent gốc đang chứa `.env`, `agent.db`, `update.bat`**, không giải nén vào folder staged code.
2. Chạy `update.bat`, chờ `V5_UPDATED_START_RUN_BAT`, rồi `run.bat`. Giữ backup/rollback như V5 trước.
3. Chạy `CHAN_DOAN_V5.bat`. File này được updater tạo có backup, đọc SQLite mode=ro/query_only bằng một snapshot WAL; không import/reconstruct/train hoặc chạy giao dịch.
4. Sau ít nhất một scan mới và một chu kỳ research, chạy lại chẩn đoán. Output `v5-diagnostics.json` chỉ chứa aggregates/reason codes và tối đa 10 cohort IDs/timestamps, không DB/.env/đường dẫn cá nhân. JSON và stdout là ASCII escaped nên không lỗi CP1252.
5. Đối chiếu source SHA, latest-scan gate counts, observed-late/timely, bảng train theo lane và `daily_measured.signal.ready_delta`. Nếu mạng bị chặn hoặc không bật research, có thể delta=0 với lý do thật; không đổi thành số liệu học thành công.

Đã có regression fixtures tái hiện đúng các tổng 5.755/72/5.683, 4.046/3.955/91, 1.668/1.594/74 và nguồn 1.063/537/68. Chia lane/nguyên nhân trong fixture là **tổng hợp để kiểm tra cơ chế**, không gán cho máy thật. Có kiểm thử builder gốc cả LONG/SHORT, cutoff/holdout/purge, không đổi frozen bytes, ASCII CP1252/read-only/WAL, retry/budget/checkpoint và E2E V2→V5 cũ→bản vá→rollback giữ Paper trade mới. Windows QA dùng Python 3.13.5; kết quả pin cuối xem PR/checks và báo cáo bàn giao.

Điều kiện nghiệm thu còn chờ: một diagnostic **thật sau vá** trên Windows có gate counts của scan mới và throughput thực tế. Repository/CI không có quyền chạy trên máy cá nhân; không tự tuyên bố điều kiện này đã đạt. PR tiếp tục chờ review; không merge, deploy hoặc bật real.
