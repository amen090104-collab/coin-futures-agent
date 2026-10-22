# Trading Bot V5.1 — Reverse V3.4 và updater GitHub không ZIP

Tiếp tục từ PR #23 / `fd829fc9a28af91ee87b0b671550ce37d3d6762c`, theo Issue #24 và bình luận ưu tiên của chủ dự án. Bản vá không thay A/B/C/D/E/F/REV-E, số dư, lịch sử Paper, `.env` hoặc tự bật Shadow/real. Không sửa main, không deploy Render hoặc tự merge/publish.

## Bằng chứng thật và giới hạn

Chẩn đoán Windows ngày 22/10/2026 (nguồn: Issue #24) có 1.930 records / 423 cohort, 1.729 READY / 391 cohort; Paper signal model eligible 290 (LONG 73, SHORT 217), 193 pending và 8 lịch sử không hỗ trợ. Phục hồi đã hoạt động: 149 batch, 1.490 attempted, +1.482 READY; batch cuối 10 READY / 7 requests / 6,3 giây. Đây là số đo người dùng trước bản vá này, không phải tốc độ mới do Codex đo lại.

Scan mới có 43 `SCORE_BELOW_THRESHOLD`, 2 `PLAN_OK`, không thiếu core. Không nới bộ lọc để biến 43 dòng còn lại thành lệnh. Historical SHORT có fit101/cal58/9 ngày fit nhưng model online cũ fit0/split-purged101. LONG có fit65/cal2 nên chưa đủ calibration. Chỉ có tổng hợp chẩn đoán, không có các hàng DB/nhãn thật trên máy người dùng; không thể công bố trọng số, accuracy/OOS/profit thật từ các tổng hợp này.

## Hai đồng hồ và hai loại model

Lỗi cũ: nhãn đóng từ trước nhưng vừa được import hôm nay bị so với **ranh giới calibration của quá khứ**. Dù đã biết nhãn ở hiện tại, mọi hàng fit vẫn có `label_available_ms` sau ranh giới lịch sử, nên liên tục bị purge. Không sửa bằng cách gán lùi label time.

`rei_v3_models.train` tách:

- **HISTORICAL_RESEARCH_MODEL**: phục hồi tại signal bằng nến đã hoàn tất, chronology theo event time, label clock historical close. Model/manifest tạo hôm nay; walk-forward/holdout chỉ là nghiên cứu hồi cứu, không phải hệ thống đã dự đoán ở quá khứ.
- **FORWARD_FROZEN_MODEL**: được tạo ở thời gian thực sau khi nhãn thực sự nhập/biết và qua embargo1h. Mọi nhãn fit/calibration phải có `label_available_ms < frozen_at_ms - 1h`. Partition fit/cal theo thời điểm tín hiệu; outcome fit phải đóng trước calibration start trừ embargo. Nhãn arrival được so với **freeze thật hiện tại**, không giả rằng import đã xảy ra trước partition quá khứ.

Một model mới vì thế có thể học dữ liệu cũ đã nhập từ hơn một giờ trước để dự đoán tín hiệu **sắp tới**. Nó không cấp score cho quan sát cũ/muộn hoặc sửa bất kỳ prediction/model đã freeze. Tên khóa `v34::FORWARD_FROZEN_MODEL::<UTC-day>::<side>` tách hẳn bảng ghi legacy. Chỉ persist model đã fit/calibrate hợp lệ; attempt thiếu dữ liệu có thể thử lại sau khi nhãn đủ tuổi. Sau khi freeze thành công trong ngày, giữ bất biến đến ngày kế tiếp. Freeze timestamp là thời gian tạo thật, không backdate về 00:00 UTC (07:00 Việt Nam).

Giữ one-group-one-label, policy Case C `REVERSE_RR2`, PIT provenance, loại entry proxy, holdout đã lưu, tối thiểu 9 ngày / 7 ngày fit / 30 fit / 12 calibration và hai lớp thắng/thua. Hàng thiếu/0 label time hoặc feature window fetched trong tương lai không được dùng cho model online. Baseline hồi cứu có digest dataset/holdout, fold cutoffs, model IDs và nhãn rõ development walk-forward / held-out retrospective.

## Điểm, ngưỡng và quyết định

So sánh logistic L2 và empirical-neighbors trên partition calibration, rồi fit regularized Platt calibration chỉ bằng partition này. Score=null khi chưa có calibrator hợp lệ, khác score=0. Calibration-fit Brier chỉ là số đo trên dữ liệu fit calibrator; Brier/score-bin/net-R holdout và walk-forward được báo riêng. Score nghiên cứu 0–100 **chưa được gọi là xác suất thắng đã xác minh hoặc lợi nhuận**.

Ngưỡng vào lệnh lấy từ quantile score fit và chọn trên calibration có stored Case C net R sau phí; không đặt cứng 50/70 rồi gọi tối ưu, không chọn bằng holdout. Nếu không có calibration edge thì vẫn có classifier score nhưng gate threshold không đạt. Lợi nhuận stored Case C được lọc theo score không phải backtest fill V3 mới.

Mỗi tín hiệu mới có Base LONG/SHORT, Reverse SHORT/LONG, source score, calibrated model score, model ID/kind/freeze time, tất cả gate, action `REVERSE_LONG` / `REVERSE_SHORT` / `WAIT_CONFIRMATION` / `NO_TRADE`. Plan hợp lệ hiện entry **tham chiếu**, SL/TP/2R và quy tắc khớp lệnh; không biến giá tham chiếu thành fill. Lệnh NOW vào open 1m tương lai có slippage; WAIT cần hai nến 1m xác nhận đã đóng rồi mới vào open tiếp theo.

Gate thực thi gồm: source plan không đổi, đầy đủ features/PIT, cùng chiều model, calibrator, researched threshold, model freeze trước quyết định, future entry window, news snapshot đủ mới và được phép, regime đã biết, phí/slippage hợp lệ, max concurrent V3, policy chọn Reverse, kiểm định policy và opt-in. Tín hiệu muộn quá 60s hoặc đã qua open dự kiến không được score/execute như forward OOS.

Hai kiểm định độc lập:

1. Policy NOW/WAIT/Base V2 dùng matched Shadow cohort, walk-forward theo thời gian, nhãn đã biết trước cutoff.
2. **Policy kết hợp V3 score-threshold + NOW/WAIT** chỉ dùng proposal V3 đã freeze thực sự trước kết quả, ghép với đúng controls và cửa sổ entry tương lai. Không dùng retrospective score thay forward proof.

Floor review giữ từ công cụ V2: tối thiểu 100 cohort OOS và 14 ngày độc lập; expectancy dương, khoảng tin cậy day-cluster95% chênh Base dương và serial R drawdown không xấu hơn NOW. Đây là điều kiện nghiên cứu bảo thủ, không phải ngưỡng tối ưu đã tìm được. Khi chưa đủ: NO_TRADE, chỉ rõ từng gate. Proposal có model/calibration/risk hợp lệ vẫn được ghi để đối chiếu controls tương lai, kể cả quyết định bỏ qua bởi score; không bịa fill để thu thập dữ liệu. Sau khi đủ bằng chứng, V3 Shadow opt-in mới được đặt lệnh mô phỏng.

Mặc định flag mới `REVERSE_ENTRY_V3_SHADOW_EXECUTION_ENABLED=false`. Nếu người dùng tự chọn true, chỉ mở ledger `rei_v3_orders`, tối đa `REVERSE_ENTRY_V3_MAX_OPEN` (mặc định3) riêng. Không chạm positions/accounts của chiến lược cũ. Reuse các nến public immutable V2 đã thu; `advance_reverse` giữ fee, adverse slippage, stop-first khi OHLC mơ hồ, gap/TTL/timeout. Không gọi API order. Funding/liquidation chưa mô hình hóa, drawdown R nối tiếp không phải equity portfolio.

Dashboard và báo cáo hàng ngày hiện hai bank model, candidate plan, gates/reasons, proposal/control comparisons và fills/performance ledger V3. `CHAN_DOAN_V5.bat` tiếp tục read-only, giờ có model banks và Shadow execution summary. Chưa có model/qualified orders thì báo đúng 0/null, không tạo minh họa như số đo thật.

## Cập nhật không ZIP từ đúng fd829fc9

BAT hiện có ở fd829fc9 luôn gọi `--from-package`, nên **không thể tự tìm release mới**. Chỉ publish PR/release không sửa được file BAT đang nằm trên máy. Không yêu cầu người dùng tải ZIP nữa.

Sau khi PR được duyệt/merge và maintainer publish release Paper/Shadow đã duyệt, mở CMD **một lần** tại folder Agent gốc (Explorer address bar gõ `cmd`). Dán dòng trong `KICH_HOAT_UPDATER_MOT_LAN.txt` của đúng release/PR đã duyệt. File hướng dẫn được builder tạo từ full40 SHA và SHA256 chính xác của bootstrap; lệnh dùng Python trong `.venv` đang có, Git origin/credentials sẵn có, fetch đúng SHA, kiểm tra hash rồi chạy bootstrap. Không checkout/pull main, không chép ZIP, không gõ PAT.

Bootstrap đọc installed state thật, kiểm tra release đã duyệt, PR merged và CI, source-tree digest, then stage/backup/health/atomic transaction. **Không đổi BAT cũ trước khi đủ điều kiện**; chưa có approved release thì báo `UPDATE_BLOCKED_UNAPPROVED`, không giả cài thành công. Nếu gián đoạn ở bootstrap đầu tiên trước khi launcher ổn định được ghi xong, chạy lại chính dòng bootstrap để recover journal; không reset/xóa DB.

Sau bootstrap, mỗi lần chỉ:

1. Dừng Agent bằng Ctrl+C.
2. Double-click **cùng `update.bat`**.
3. Chờ thành công rồi chạy `run.bat` / `chay_agent_v2.bat`.

BAT mới cố định gọi `.agent-updater/update_driver.py`. Driver xác minh updater source pin/checksums, chọn updater đã duyệt; updater chọn Agent version/venv riêng. Pointer updater giữ nguyên qua voluntary code rollback, nên không mắc kẹt ở BAT cũ sau rollback. Lần cài lại release đang có đúng SHA trả `NO_NEW_VERSION`; không reinstall/downgrade loop. Tag V5 semver được so số, hỗ trợ v5.1/v5.2/...; cùng version mà khác SHA bị chặn để tránh rebuild âm thầm.

Release được lấy từ GitHub, không từ moving main hoặc local JSON tự khai approved. Protocol2 có full SHA, version, source-tree SHA256, execution_mode Paper/Shadow và merged PR URL; hai platform checks mới nhất phải success. Source tải qua Git origin và attested với archive/checksums trước khi chạy. HTTP chỉ outbound; không thêm update API cho app đang bind network. Chỉ cập nhật khi người dùng bấm, không update theo scheduler/startup.

Root `.env`, SQLite WAL, thêm DB, reports/sync và launcher có backup/checksum/journal. Update lỗi phục hồi dữ liệu/launcher/pointer trước update. Rollback chủ động sau thành công chỉ đổi code, **giữ Paper trades mới**. Disk low, tracked edits, Git offline, Agent đang chạy, unapproved/draft/prerelease, version/hash/CI sai đều chặn. Không tự nâng quyền, reset Git hoặc tắt antivirus.

Private repo: Git source dùng origin credentials sẵn có. Metadata API dùng existing HTTPS Git Credential Manager; không đọc report token/.env, không in credential. SSH origin có thể dùng existing `gh` login cho metadata. Nếu không có quyền API thì chặn rõ, không coi HTTP404 là “đã duyệt”. Không tự xin quyền hay tạo PAT mới.

## Phát hành để người dùng cập nhật

`build_approved_release.py` tạo draft `release-manifest.json` reviewed=false và một dòng bootstrap có hash. Draft không được installer chấp nhận. Maintainer review/merge đúng source, đợi CI Ubuntu/Windows thành công, rồi chủ động chạy workflow **Publish reviewed V5 Paper Shadow release** với SHA/tag/PR URL. Script tự xác minh merged review/CI/version trước tạo manifest reviewed=true; workflow mới tạo tag/release. Không gọi software release là model đã có lợi nhuận. Codex không chạy bước publish hoặc merge trong nhiệm vụ này.

## Kiểm thử và thực nghiệm

Baseline fd829fc9: local312 passed/1 skipped, Windows313 passed. Các regression mới kiểm tra hai clocks, same-day import, midnight/embargo/late-label, chronological purge/holdout/correlated variants, calibrator/one-class, model-source side, frozen bytes, NO_TRADE gates/news/capacity, next-open/WAIT/fees/stop-first, private credential redaction, semver/CI/source checksum và rollback.

E2E Windows Python3.13.5 dựng installed fd829fc9 bằng mã Git thật và fixture DB/WAL/model legacy. Giữ nguyên BAT cũ, xác minh nó không gọi release feed; chạy command bootstrap không ZIP; nhận v5.1.0; cài release fixture thứ hai bằng chính BAT; health-check native CMD; train read-only từ fixture; rollback giữ post-update Paper data, rồi update lại bằng updater đã giữ. Git/venv/pip/backup/app health/CMD thực sự chạy; release API/dependency network là fixture có nhãn. Artifacts có transcript/hash và learning evidence, không private DB/.env/training rows.

Fixture clocks tái hiện SHORT101fit/58cal/9 ngày fit và LONG65fit/2cal. Kết quả chỉ chứng minh đường huấn luyện hoạt động đúng, **không phải win rate/expectancy thực nghiệm của dữ liệu người dùng**. Thực nghiệm read-only trên snapshot reports thật ở cloud được bàn giao riêng; khi chưa có READY/đủ dữ liệu thì model vẫn untrained. Không upload DB thật lên CI để biến test fixture thành bằng chứng tiền thật.

Có thể kiểm chứng trên máy riêng, không sửa nguồn:

```text
python -m app.rei_v3_train --source-db <agent.db-da-sao-chep> --output-dir <thu-muc-output-moi>
```

Lệnh chạy bằng Python/code của release mới; output `experiment.redacted.json` và `private-models.json`. Giữ file model private. Nó huấn luyện candidate để xem xét, không import lại dữ liệu, không ghi model vào DB nguồn và không mở lệnh. Khi chạy Agent với V3 research đã opt-in từ trước, worker sẽ tự freeze model hợp lệ ở thời gian mới; flag execution mới vẫn false cho tới khi người dùng tự chọn.
