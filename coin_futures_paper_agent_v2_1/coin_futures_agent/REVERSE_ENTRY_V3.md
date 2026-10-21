# Reverse Entry V3 — thực hiện Issue #18

Nhánh nghiên cứu từ Reverse Entry V2 `5340114`, chỉ opt-in Shadow. Không thay A/B/C/D, REV-E, tài khoản, balances hoặc thuật toán V2. Không gửi lệnh thật, không triển khai Render. Kiểm tra theo Issue [#18](https://github.com/amen090104-collab/coin-futures-agent/issues/18).

## Luồng dữ liệu

`DB nguồn (chỉ SELECT) / báo cáo JSON → rei_v3_samples → lịch sử public futures → features + provenance → classifier theo hướng Base → quan sát V3 đóng băng → báo cáo / dashboard`.

- `rei_v3_store.py`: schema/migration riêng, importer idempotent, kiểm tra schema version. Adapter cho legacy/Battle trades, `reverse_lab_signals/cases`, `v44_pending/shadow_positions`, V2 cohorts/cases và JSON daily-report/reverse-lab. Strategy Lab chỉ nhận vị thế có bằng chứng nguồn thực sự ngược hướng; không suy ra Reverse từ tên chiến lược. V2 chỉ nhập outcome CLOSED; EXPIRED được giữ trong đối chứng V2, không giả làm trade thắng/thua. Reverse Lab export chỉ có recent cohorts; không giả định đó là toàn bộ DB.
- Payload dùng allowlist các trường nghiên cứu; không sao chép JSON tùy ý chứa thông tin nhạy cảm. Giữ ID nguồn, cohort, thời gian signal/decision/entry/closed/label-known/import, net R, cost basis. Thiếu hướng nguồn hoặc outcome hợp lệ thì bỏ qua và đếm lý do.
- Import giữ tất cả policy đủ điều kiện, nhưng classifier lịch sử chỉ học label Case C `REVERSE_RR2`; không trộn RR/cost của Case D/E/F như cùng policy. Cùng cohort chỉ tính một nhãn; Case C được ưu tiên khi có nhiều trường hợp tương quan. Lane forward NOW từ V2 huấn luyện riêng, chưa gộp với lịch sử khi chưa chứng minh tương thích cost/fill.
- `rei_v3_market.py`: chỉ GET public USD-M futures, không API key: REST `https://fapi.binance.com/fapi/v1/klines`, dự phòng archive chính thức `https://data.binance.vision/data/futures/um/{monthly|daily}/klines/...`. REST 403/451, symbol thiếu/delisted hoặc network unavailable chuyển sang archive monthly, monthly 404 chuyển daily đúng ngày UTC. Không đổi sang spot/ticker hiện tại, không đổi tên symbol. 418/429 phải chờ, không chuyển nguồn để vượt rate limit.
- Mỗi symbol/BTC dùng 220 nến đã đóng, các khung 15m/1h/4h. End = đầu khung tại decision UTC trừ 1 ms. Không dùng nến tại entry/exit muộn hơn. RSI/ATR/EMA/volume/trend/relative strength/BTC regime được tính lại với công thức `enrich` hiện có. EMA warm-up cố định có thể khác snapshot cũ; provenance ghi phiên bản `completed-220-utc-v2`. Nến tương lai có trong archive bị lọc trước khi tính indicator.
- Archive phải khớp SHA256 từ `.CHECKSUM` chính thức; ZIP chỉ chứa đúng một CSV mong đợi, giới hạn kích thước. Cache ZIP và cửa sổ có checksum/provenance/fetched-at, kiểm tra lại khi đọc. Sai checksum, gap/stale, duplicate hoặc không đủ 220 nến thì không huấn luyện. Schema V3 từ 1 lên 2 chỉ thêm bảng archive/proxy; không sửa bảng giao dịch.
- Thiếu signal time nhưng có entry: `rei_v3_entry_context` lưu lane `ENTRY_PROXY`, `feature_asof_ms=entry_ms`, completed candles trước entry, `usable_at_original_signal=false`, `forward_oos=false`. Không sửa signal time/features/status nguồn, không đưa proxy vào classifier, holdout hay OOS tại signal. Không có entry hợp lệ thì không dựng proxy.
- Cache immutable theo symbol/interval/start/end/version, SHA256, fetched-at và max source time. Tối đa ba thử/request và 160 HTTP attempts/client, backoff và Retry-After; ban dài được nhường sang job sau. Tốc độ serial tối đa khoảng 4 request/giây; mỗi lane tối đa 50 mẫu, mặc định background 2 mẫu mỗi 5 phút. Job commit từng mẫu, retry sau một giờ và tiếp tục sau restart. Các lỗi thiếu lịch sử từ provider cũ được xét lại một lần với policy archive mới.
- Score gốc chỉ đọc từ record gốc. Không tái tạo proprietary Score/News Guardian/order-book. OI/funding lịch sử thiếu snapshot là `None`, không đổi thành 0; v1 phục hồi này chưa dùng funding history endpoint để tránh đánh đồng funding tại thời điểm khác.

## Mô hình và kiểm định

Logistic L2 và empirical neighbors dùng cùng bộ features V2; training-only median/scale, missing indicators. L2/learning rate và minimum sample gates là lựa chọn nghiên cứu đăng ký trước, không tuyên bố tối ưu. Cần ít nhất 30 fit trên 7 ngày, 12 calibration trên 2 ngày tiếp theo, cả nhãn thắng và thua. Family được chọn bằng Brier trên calibration, không bằng nhãn test.

Mỗi hướng Base LONG/SHORT có mô hình riêng. Purge mọi nhãn còn mở/vừa biết qua ranh giới; embargo một giờ. Label chỉ được dùng khi known trước freeze. Với lịch sử tải sau sự kiện, `label_available_ms` là lúc import cho mô hình forward; chỉ backtest ghi rõ retrospective mới dùng `historical_label_known_ms = closed_ms`. Đây là giả định nhãn đã có tại lúc đóng, không khẳng định máy cũ đã quan sát được outcome đúng lúc đó.

20% ngày quyết định cuối của tập lịch sử có features hợp lệ được giữ làm holdout theo cohort. Danh sách được lưu một lần trong `rei_v3_runs/holdout-v1`, không xoay lại theo dữ liệu mới. Toàn bộ held-out groups bị loại khỏi mọi fit/calibration và phân tích differentiators; chỉ tính kết quả kiểm định. Đây vẫn là **held-out retrospective**, không phải forward OOS thực sự. Chưa đăng ký riêng một regime tương lai làm holdout; cần thống nhất trước vòng kiểm chứng tiếp theo.

Walk-forward đóng băng mô hình đầu mỗi ngày UTC, chỉ dùng labels có sẵn trước cutoff/embargo; báo riêng cold start và dự đoán có điểm, bins điểm, Brier và từng chiều. Drawdown R là serial, không phải equity của portfolio lệnh chồng lấn.

Classifier 0–100 mô tả liên hệ thắng/thua, **không phải xác suất thắng đã hiệu chỉnh**, không xác nhận kỳ vọng lợi nhuận. Mô hình lịch sử một nhãn không biết outcome của WAIT hoặc Base ở cùng cơ hội nên vẫn `RISK_GATE/NO_TRADE` dù có điểm. Khi đủ bộ NOW/WAIT/Base forward V2, policy riêng theo chronological calibration V2 có thể đề xuất REVERSE_NOW / WAIT_CONFIRMATION / NO_TRADE trong Shadow. Điểm policy đó được giữ riêng `paired_score/model_id`, không tráo với classifier lịch sử.

Chi phí của lịch sử dùng net R đã lưu; không coi replay fill giống fill cũ. Công cụ replay OHLC của V2 vẫn dùng được với dataset/bars/cost đã đóng băng; V3 chưa tự tạo full historical NOW/WAIT/Base counterfactual khi thiếu risk/cost nguồn. Forward V2 đã có fee/slippage/max hold đóng băng, fill/censor, C/D controls và đối chiếu Case C/REV-A..E. Chưa mô hình funding/spread/portfolio capacity đầy đủ. Không báo lợi nhuận V3 cho phần chưa được đo.

## Thu thập, UI và báo cáo

`REVERSE_ENTRY_V3_ENABLED=false` mặc định. Muốn nghiên cứu sau review: bật V3 cùng `REVERSE_ENTRY_INTELLIGENCE_ENABLED` và `V44_SHADOW_ENABLED` trên máy local bằng quyết định riêng của người vận hành; PR này không thay `.env` hiện tại. Background cycle độc lập, lỗi nghiên cứu không thay paper. Supervisor Windows một process/worker; process lock ngăn hai launcher cùng DB. Nếu chạy trực tiếp Uvicorn/Render thì lock supervisor không áp dụng: vẫn cần một replica hoặc distributed lease trong triển khai khác.

Quan sát V3 được đóng băng sau V2 registration, trước outcome. Bản ghi được thấy muộn hơn 60 giây hoặc đã có outcome ⇒ `MISSED_DECISION_WINDOW`, không ghi làm forward OOS. Không chấm lại dự đoán cũ sau khi biết kết quả. Tách origin/coverage/model age/missingness theo nguồn, hiển thị UNTRAINED / INSUFFICIENT_DATA / MISSING_FEATURE / NO_MODEL / RISK_GATE và lý do. Không dùng điểm 0 thay cho score chưa tồn tại.

GET `/research/reverse-entry-v3` và `/api/dashboard` chỉ đọc. Dashboard có coverage theo nguồn/chiều Base: số records/cohort, có signal/score, đủ điều kiện phục hồi, READY cohort/Case C fit, proxy và signal không phục hồi. Cohort không đồng nghĩa mẫu độc lập thống kê. Khi chưa có model, `first_run_mode=COLLECT_AND_COVERAGE_ONLY`, không tạo score giả. Có numeric score nếu trained, reason codes, yếu tố tăng/giảm điểm (ablation, không nhân quả), matched win/loss, cửa sổ train/calibration, walk-forward/holdout, fill/missed winner/avoided loss và phân phối score. Các summary mới được chụp vào JSON/MD/HTML của hai Labs; repair ngày cũ chỉ render từ payload đã lưu.

## CLI an toàn

Chạy từ thư mục ứng dụng bằng Python của project; DB nguồn mở mode=ro, DB output phải tách khỏi DB/báo cáo nguồn:

```text
python -m app.rei_v3 --source-db <ban-sao-agent.db> --output-db <thu-muc-nghien-cuu>/rei-v3.db
python -m app.rei_v3 --reports <reports-root> --output-db <thu-muc-nghien-cuu>/rei-v3.db --reconstruct --limit 10
python -m app.rei_v3_smoke --output-dir <thu-muc-moi>/public-history-smoke
```

Có thể kết hợp hai nguồn. Re-run tiếp tục job/cache đã lưu; không xóa hay sửa nguồn. Smoke chủ động thử ba cửa sổ lịch sử thật (BTC/ETH, 15m/1h/4h), chỉ lưu cache public và provenance, exit 0 khi tất cả xác minh, exit 2 khi còn BLOCKED/PARTIAL. Không đọc DB giao dịch hoặc huấn luyện. Giữ DB nghiên cứu và output JSON ngoài repository công khai. Không đưa DB/.env/backups vào PR, issue hay artifact CI.

## Bằng chứng hiện có và giới hạn nghiệm thu

Đã đọc schema DB mẫu cloud qua SQLite mode=ro: Battle/Reverse/Strategy Lab không có giao dịch đã đóng; chưa có DB Windows người dùng. Snapshot reports `84c57a08cef48cbdf45226fe8320f589265ae627` (có ngày 20/10/2026): 962 Paper + 251 Shadow = 1213 records, chung 285 cohort, đều có signal time và source score, READY=0. Không phải 1213 cơ hội độc lập hay mẫu đủ features. Đợt review 21/10 đã thử ba cửa sổ nến thật: 0/3 xác minh, REST HTTP 451 và archive ProxyError. Phục hồi trên máy có quyền truy cập vẫn pending; chưa có features thực tế để huấn luyện, walk-forward/OOS V3 và khả năng sinh lợi **chưa kiểm chứng**. Xem [báo cáo xử lý review](docs/acceptance/PR19_REVIEW_2026-10-21.md).

Ảnh nghiệm thu ở `docs/acceptance` dùng **fixture tổng hợp, không phải hiệu suất giao dịch**: trạng thái thiếu dữ liệu và trạng thái classifier có điểm nhưng RISK_GATE. Test fixture không phải dữ liệu huấn luyện thực tế. Kiểm thử Windows CI dùng Python 3.13.5, đường dẫn Unicode/spaces, launcher CMD, clone đúng V2 SHA, WAL, .env giả lập, supervisor thật với ASGI fixture và lỗi có kiểm soát; chưa phải nghiệm thu trên DB/máy riêng của người dùng.

## Bước tiếp theo

1. Review PR và CI hai nền tảng; không tự merge/publish/deploy.
2. Chạy installer/backup/preflight trên bản sao DB Windows, kiểm tra schema adapter và coverage. Không chia sẻ `.env`/DB lên GitHub.
3. Chạy smoke trên máy truy cập được REST/archive chính thức, rồi tiếp tục reconstruction theo batch và audit timestamps/checksums. Không dùng symbol mapping chưa có bằng chứng.
4. Đăng ký trước regime/time holdout mới, xác minh chi phí/fill và matched NOW/WAIT/Base; thu Shadow đủ mẫu độc lập trước mọi thay đổi policy.
5. Chỉ người bảo trì được publish release đã duyệt; người dùng chủ động bấm Update. Xem [hướng dẫn Windows](WINDOWS_UPDATE_V3.md).
