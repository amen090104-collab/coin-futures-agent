# V4.4 — ổn định vận hành, giai đoạn 1

Tài liệu cho nhánh `codex/stabilize-v44`, dựa trên kiểm toán ngày 20/10/2026.
Không đổi strategy, gate REV-E, risk, phí, lịch giao dịch hoặc tham số A/B/C/D.
Không kèm migration dữ liệu giao dịch, reset tài khoản, deploy hay bật tích hợp.

## Những lỗi đã sửa

| Lỗi | Nguyên nhân | Khắc phục |
|---|---|---|
| Recovery đệ quy khi Battle=false | Nhánh legacy gọi lại dispatcher | Gọi đúng `paper.recover_open_positions`; test cả hai engine |
| Báo RECOVERED khi chưa tạo báo cáo | Không kiểm tra kết quả job và artifact | Chỉ RECOVERED khi job OK và đủ bộ file hợp lệ; PARTIAL/ERROR/SKIPPED không thành thành công |
| Thiếu báo cáo nghiên cứu không được phát hiện/retry | Catch-up chỉ kiểm tra hai JSON chính; writer exception bị bỏ qua | Theo dõi toàn bộ JSON/MD/HTML theo flags; lỗi riêng từng module; startup và hourly retry kiểm tra đầy đủ |
| Báo cáo lịch sử dùng cumulative hiện tại | GET fallback/POST/generator không chặn ngày cũ | Chỉ tính mới cho hôm nay/hôm qua; ngày khác phải có snapshot; GET thiếu trả 404, POST rebuild trả 409 |
| Legacy không sync được | Generator viết file MD phẳng, sync đòi JSON trong thư mục ngày | Legacy xuất cùng bộ `YYYY-MM-DD/daily-report.{json,md,html}` tại report_root tuyệt đối |

### Hợp đồng artifact và trạng thái

- Legacy cần 3 file daily-report. Battle cần thêm 3 file daily-analysis.
- Khi Battle và V4.4 bật, thêm 3 file v44-research. Reverse thêm 3 file nếu flag tương ứng bật.
- JSON phải parse được và ngày phải khớp thư mục; MD/HTML không được trống. Analysis phải tham chiếu đúng `created_at` của snapshot nguồn.
- `/reports/github-sync/status` trả thêm `complete`, `required`, `missing_or_invalid` cho từng ngày cục bộ.
- `RECOVERED` chứng minh bộ báo cáo cục bộ đã hoàn chỉnh. Trạng thái xuất bản GitHub nằm riêng trong `github_sync`; không đồng nghĩa đã upload thành công.
- Lỗi research trả PARTIAL và tên module/error; báo cáo chuẩn vẫn được tạo khi có thể. Lần retry kế tiếp sửa phần thiếu, không tính lại các snapshot hợp lệ.
- Nếu research JSON đã có, khôi phục MD/HTML từ chính JSON đó, giữ nguyên bytes JSON và `generated_at`; không gọi engine nghiên cứu hoặc cập nhật research summary khi chỉ render lại.
- Ghi từng file bằng temporary file cùng thư mục và `os.replace`. Đây là atomic theo từng file, không phải giao dịch nguyên tử của cả bộ; completeness check phát hiện phần còn thiếu sau crash.

### Giới hạn thời gian cần hiểu đúng

Job 00:10 vẫn được phép hoàn tất báo cáo **hôm qua**, như workflow trước đây. Số giao dịch theo ngày được lấy trong khoảng ngày đó; các trường cumulative/market/research phản ánh thời điểm snapshot được tạo (`created_at`/`generated_at`), không phải toàn bộ đều là số liệu as-of 23:59:59.

Nhánh này chặn dựng lại từ live state cho **ngày trước hôm qua hoặc ngày tương lai**. Không triển khai engine tái dựng mọi chỉ tiêu as-of cho lịch sử tùy ý. Ngày cũ không có JSON nghiên cứu sẽ báo PARTIAL thay vì tạo số liệu giả; cần tìm snapshot/backup gốc. Analysis ngày cũ chỉ được tính từ daily-report JSON đã lưu, không từ tài khoản hiện tại.

`POST /reports/daily/{day}/analysis/run` là thao tác repair từ snapshot, không tự làm mới báo cáo nguồn. Lần hoàn tất lịch 00:10 là đường chủ động refresh báo cáo hôm qua. Không tự chuyển đổi file MD legacy cũ thành dữ liệu JSON lịch sử vì MD không chứa đủ snapshot đáng tin cậy. Không xóa/viết lại dữ liệu báo cáo sản xuất trong quá trình phát triển nhánh này.

## Bảo vệ API quản trị: đã xác minh và đề xuất

Kiểm tra cấu trúc FastAPI xác nhận **không có auth middleware, auth dependency toàn cục hoặc dependency trên các route ghi**. Các endpoint POST/PATCH strategy-cases, recovery, scan, backup, report generation/sync và research monitor đều chưa kiểm tra danh tính ở lớp ứng dụng. Một số GET báo cáo hôm nay/hôm qua còn có thể tạo file khi thiếu; vì vậy không thể coi mọi GET đều chỉ đọc.

Không có bằng chứng về gateway bên ngoài hoặc cấu hình Render thực tế trong repository. Không gọi endpoint quản trị trên sản xuất để thử quyền.

Phương án tối thiểu trước khi public Render:

1. Đặt toàn bộ dashboard/API sau gateway có đăng nhập OIDC hoặc reverse proxy xác thực, bao gồm API GET chứa lịch sử. Chặn truy cập trực tiếp origin; ưu tiên app chỉ có private ingress và gateway là điểm vào công khai duy nhất.
2. Nếu origin vẫn public, ứng dụng phải xác minh danh tính/chữ ký của gateway trên mọi request cần bảo vệ. Không chỉ tin header do client tự gửi. Một lớp đăng nhập chỉ ở hostname đẹp nhưng vẫn truy cập trực tiếp được `*.onrender.com` không đủ an toàn.
3. Quyền xem và quyền thao tác quản trị cần tách. Chỉ role quản trị mới được POST/PATCH; nếu dùng cookie session phải có chống CSRF và cấu hình cookie phù hợp. CORS không thay thế auth.
4. Endpoint health dành cho nền tảng chỉ trả liveness tối thiểu; `/health` hiện có thông tin hệ thống/tài khoản và `ok=true` kể cả OFFLINE. Đừng đưa toàn bộ endpoint này ra public như một readiness check được bảo mật sẵn.
5. Credential của proxy/integration đặt trong secret manager của nền tảng; không đưa vào command, Git, log hay tài liệu. Không bật GitHub sync/Telegram trong lúc kiểm thử bằng dữ liệu thật.

Chưa thêm cơ chế auth tùy ý trong PR này vì cần chốt nhà cung cấp danh tính, topology và hành vi dashboard/session. Đây vẫn là điều kiện chặn mở public, không phải hạng mục đã được giải quyết bằng việc thêm tài liệu.

## Scheduler: giới hạn và phòng tránh chạy trùng

Scheduler được khởi tạo trong module và start trong FastAPI lifespan của **mỗi worker**. `replace_existing=True`, `max_instances=1`, `coalesce=True` và các `asyncio.Lock` chỉ kiểm soát job trong một tiến trình; không khóa giữa worker, replica, deployment cũ/mới hoặc ứng dụng chạy tay trên máy khác.

Khuyến nghị vận hành khi còn dùng SQLite và scheduler nội bộ:

- Một Uvicorn worker, một replica; không dùng `--reload` trên production. Chỉ một tiến trình sở hữu `agent.db` và scheduler. Không chạy thêm instance từ PC trỏ vào cùng workload sản xuất.
- Không dùng cron/service thứ hai gọi cùng job theo lịch. Đối chiếu log startup, PID/deployment identity và heartbeat để phát hiện hai scheduler.
- Khi triển khai cần tính tới khả năng deployment cũ và mới chồng thời gian; một replica cấu hình không tự chứng minh không có overlap. Nếu nền tảng không bảo đảm độc quyền, cần leader/lease liên tiến trình trước khi tự động deploy.
- Muốn scale: tách scheduler/worker khỏi API; dùng lease phân tán có expiry/heartbeat và fencing, hoặc hàng đợi với khóa/idempotency theo `(job, report_date, module)`. Không chỉ tăng `max_instances` và không coi SQLite WAL là leader lock.
- Regression test trong nhánh này xác nhận concurrent analysis bị khóa trong một process; chưa có cơ chế election/lease đa tiến trình mới.

Misfire grace hiện là 30 giây và job store ở bộ nhớ. Startup/hàng giờ có catch-up cho **hôm qua**; không cam kết tự khôi phục nhiều ngày mất máy. Các báo cáo thiếu quá cũ phải phục hồi từ backup, không tính cumulative hôm nay gắn nhãn ngày cũ.

## Đề xuất cấu hình Render — chưa triển khai

Giả định repository root là working directory ban đầu và persistent disk mount tại `/var/data`; cần xác minh trên service thực tế trước khi dùng. Python 3.12 tương thích CI. Không chạy `run.sh` nguyên bản trên Render vì script cài dependency ở startup và cố định port 8000.

```sh
# Build command
python -m pip install -r coin_futures_paper_agent_v2_1/coin_futures_agent/requirements.txt

# Start command — đề xuất, không được thực thi trong công việc này
app_dir="$PWD/coin_futures_paper_agent_v2_1/coin_futures_agent"
cd /var/data
REPORTS_DIR=/var/data/reports BACKUP_DIR=/var/data/backups \
python -m uvicorn app.main:app --app-dir "$app_dir" \
  --host 0.0.0.0 --port "$PORT" --workers 1
```

`agent.db` hiện relative theo cwd, nên đổi cwd sang persistent disk là chủ ý. `.env` cũng được đọc theo cwd: không dựa vào một `.env` ở checkout khi đã đổi cwd. Trước deploy phải kiểm tra đúng DB cũ, disk persistence, backup/restore và gateway auth; không chạy lệnh sao chép/reset DB tùy tiện. Thiết lập flags giao dịch/nghiên cứu phải giữ nguyên giá trị đã được chủ sở hữu phê duyệt.

Kiểm tra riêng khả năng egress Binance/news/GitHub từ vùng Render. Lỗi proxy của máy phát triển không chứng minh Render gặp cùng lỗi. Không suy ra quyền GitHub API ghi từ việc Git clone thành công.

## Kiểm thử và hạn chế còn lại

Baseline trước sửa: 102 test Python pass. 11 ca regression ban đầu chạy trên mã cũ: 10 fail, 1 pass; các failure tái hiện recovery/reporting đã kiểm toán. Các test mới dùng DB và thư mục tạm, mock HTTP/GitHub và không start lifespan/server thật. Lệnh chạy full suite có thể chặn socket để bảo đảm không gọi dịch vụ bên ngoài.

Kết quả cuối trên nhánh: **141/141 Python test pass** (102 ca cũ + 39 ca regression), không skip; có một cảnh báo deprecation Starlette/TestClient đã tồn tại. Compile Python, JavaScript syntax (trade_charts và script inline dashboard), test marker/candle alignment và `git diff --check` đều pass. Các lệnh compile dùng cache dưới `/tmp`; không khởi động ứng dụng với DB sản xuất.

Các ca bổ sung bao gồm: cả engine recovery; xác minh artifact trước RECOVERED; ma trận flags; lỗi riêng Reverse writer rồi retry; giữ nguyên snapshot khi sửa MD/HTML; old-date API/generator guard; invalid date trước DB access; legacy sync qua HTTP mock; corrupted historical JSON không upload; analysis/source mismatch; atomic file replacement failure; bootstrap catch-up; sync retry không bỏ qua nghiên cứu thiếu; concurrent analysis trong một process.

Chưa kiểm chứng: triển khai/auth gateway thực tế, multi-instance election, live GitHub publishing, hoặc readiness qua nhiều ngày trên Render. Không có migration để dựng lại snapshot lịch sử đã mất; không có thay đổi chiến lược, mô hình điểm, risk hoặc tiền thật.
