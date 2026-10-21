# Cài đặt và cập nhật Windows

Phạm vi: máy Windows cá nhân, Python 3.13.5, Git for Windows, không cần quyền administrator. Không triển khai Render. Đây là mã chờ kiểm duyệt, **chưa phải bản phát hành được duyệt**.

## Người đang dùng `local-reverse-v2` ở `5340114`

1. Sau khi người duyệt chấp thuận, tải gói `windows-local-bootstrap` từ CI của đúng commit đã duyệt. Giải nén vào thư mục riêng; không chép đè lên thư mục Agent cũ.
2. Bấm **CAI_DAT_VAO_BAN_V2.bat**. Trong cửa sổ chọn thư mục, chọn thư mục Agent cũ có `app`, `requirements.txt`, `.env` và `agent.db` (không chọn thư mục repository bên ngoài).
3. Installer tạo ba launcher trên Desktop: **CHAY_AGENT**, **CAP_NHAT_AGENT**, **QUAY_LAI_BAN_CU**. Mã hỗ trợ nằm trong `.agent-updater/bootstrap`, không đổi nhánh, không chép đè `.env`, DB hoặc file Git đang theo dõi. Không cần nhập Git commands.
4. Dừng cửa sổ Agent cũ bằng **Ctrl+C** một lần. Từ đây dùng **CHAY_AGENT** để chạy; launcher giữ khóa DB và chỉ bind `127.0.0.1`. Không dùng `run.bat` cũ còn bind `0.0.0.0` trên bản V2 chưa cập nhật.
5. Khi muốn cập nhật, bấm **CAP_NHAT_AGENT**. Cửa sổ hiện Current version / Available version. Nếu chưa có bản local được duyệt, chương trình hiện `NO_NEWER_APPROVED_VERSION` và không cài gì.

DB Windows của người dùng chưa được cung cấp cho nhóm phát triển. Các bài test dùng bản sao Git tại đúng commit V2 và DB fixture ở WAL mode, không chứng minh mọi biến thể DB riêng đều tương thích. Backup/preflight vẫn bắt buộc trên máy thật.

## Máy mới hoặc checkout đã có V3

Cài Python 3.13.5 và Git cho user hiện tại; bấm **CAI_DAT_AGENT.bat**. Nó chỉ tạo `.env` từ mẫu nếu chưa có, tạo `.venv` nếu thiếu, kiểm tra dependencies và mở trình duyệt. Các lần sau bấm `run.bat`. Không yêu cầu PowerShell, không dùng `python -c` nhiều lớp dấu nháy. Không tự bật V3 hoặc thay thông số giao dịch.

## Update thực hiện gì

- Kiểm tra Git/Python, working tree, remote đúng repository, dung lượng ít nhất 2 GB cộng khoảng ba lần dung lượng dữ liệu, đường dẫn DB/reports, quyền ghi và phiên bản được duyệt.
- File untracked thông thường như `chay_agent_v2.bat`/ghi chú được thông báo bằng số lượng và giữ nguyên; không chạy/xóa/ghi đè hoặc đưa vào source mới. File Git đã theo dõi bị sửa vẫn chặn Update, hướng dẫn nhờ người bảo trì xử lý, không yêu cầu reset.
- Không pull `main`, checkout/reset nhánh hiện tại hay sửa file Git đang theo dõi. Fetch đúng SHA, kiểm tra đó là hậu duệ của V2 `5340114`, giải nén source vào `.agent-updater/releases/<SHA>/code` và cài dependencies vào venv riêng của release. Bản cũ/venv cũ còn nguyên. Dependency resolver/pip check chạy trên máy người dùng; dependencies hiện chưa có lock hash đầy đủ cho mọi nền tảng.
- Dừng agent do supervisor quản lý bằng tín hiệu file local; chờ giải phóng khóa và cổng. Agent chạy ngoài supervisor phải được người dùng dừng bằng Ctrl+C. Không kill theo tên tiến trình.
- Sao lưu bằng SQLite Backup API, gồm các transaction đã commit trong WAL; chạy `integrity_check`, lưu `.env`, DB bổ sung và reports cùng checksum/manifest. Vị trí: `backups/updates/<timestamp>/`. Không upload backup. Backup lỗi hoặc schema không tương thích thì dừng cập nhật.
- Preflight migration chỉ thực hiện trên DB sao lưu trong thư mục tạm. Không chạy lifespan/scheduler hay truy cập market trong preflight.
- Ghi journal trước khi chuyển con trỏ phiên bản, chạy một worker dưới khóa DB, kiểm tra HTTP local trả đúng SHA và PID. Thành công mới ghi COMMITTED và mở trình duyệt.
- Health/start lỗi: dừng đúng tiến trình con, kiểm tra backup rồi phục hồi DB/.env và con trỏ code cũ. Hiện hướng dẫn bấm `run.bat` hoặc CHAY_AGENT để chạy lại. Không tự khởi động nhiều agent.
- Mất điện khi journal còn PREPARED: bấm Update để phục hồi trước; launcher Run từ chối khởi động vào trạng thái chưa hoàn tất.

Mọi lỗi hiển thị mã lỗi hữu hạn. Không in stdout/stderr của Git/pip, nội dung `.env`, URL xác thực hoặc credentials. Log runtime ứng dụng chỉ nằm trong console local như trước.

## Phê duyệt release — dành cho người bảo trì

PR không tự tạo release hoặc thay manifest phê duyệt. `approved_release.json` mặc định có `approved_release: null`.

Update đọc GitHub stable release mới nhất, chỉ nhận tag dạng `local-v3.0.0`. Body release là JSON bên dưới. Trước khi thực thi, nó xác minh PR đã merge, SHA thuộc head/merge commit của PR, cả hai check GitHub Actions `test (ubuntu-latest, Python 3.12)` và `test (windows-latest, Python 3.13.5)` đều thành công. Tag không quyết định code thực thi: luôn fetch SHA đầy đủ. Release không đúng định dạng, chưa merge, CI lỗi hoặc offline sẽ không cài.

```json
{
  "approved_release": {
    "sha": "<SHA 40 ký tự của commit đã duyệt>",
    "reviewed": true,
    "review_url": "https://github.com/amen090104-collab/coin-futures-agent/pull/<PR>"
  }
}
```

Người bảo trì cũng có thể phân phối gói bootstrap **đã duyệt** với pin trong `approved_release.json` (cùng cấu trúc, bên ngoài có `manifest_version: 1`). Pin local cũng phải qua kiểm tra PR đã merge và cả hai CI thành công, không phải đường bỏ qua gate. Không ký mật mã manifest ở phiên bản này; quyền publish release/duyệt gói là ranh giới tin cậy. Không cần token GitHub trong `.env` cho public release feed.

CI checkout rõ `github.event.pull_request.head.sha`; không đóng gói từ synthetic test merge. Gói chỉ có 7 file allowlist và `BUILD_INFO.json`. `code_sha` phải bằng SHA duyệt đầy đủ; từng file phải khớp SHA256 và bytes Git blob của chính revision đó (không dùng working-tree bytes bị đổi CRLF). Người bảo trì chạy từ checkout của SHA được duyệt:

```text
python build_windows_bootstrap.py windows-local-bootstrap.zip --expected-sha <SHA-40-ky-tu>
python build_windows_bootstrap.py windows-local-bootstrap.zip --expected-sha <SHA-40-ky-tu> --verify
```

Review 21/10: chưa phát hành, giữ `approved_release: null` và PR Draft. CI fixture không thay được smoke nến thật hoặc nghiệm thu máy/DB riêng. Lần Shadow đầu khi chưa có model chỉ `COLLECT_AND_COVERAGE_ONLY`, không có score. Xem [bằng chứng và blocker](docs/acceptance/PR19_REVIEW_2026-10-21.md).

## Rollback

Sau update thành công, bấm **QUAY_LAI_BAN_CU**, rồi **CHAY_AGENT**. Rollback chủ động chỉ đổi code về bản trước, sao lưu mới và **giữ giao dịch mới phát sinh sau update**. Vì migration V3 chỉ thêm bảng riêng, bản V2 bỏ qua chúng. Không tự phục hồi DB cũ sau một phiên chạy thành công vì việc đó sẽ mất giao dịch mới.

Rollback tự động của một update chưa thành công thì phục hồi DB/.env từ backup trước update. Nếu có tiến trình chưa dừng hoặc backup checksum sai, nó chặn restore; giữ nguyên backup để xử lý tại máy. Không xóa reports phát sinh sau khởi động lỗi; cần kiểm tra riêng trước khi sync lại.

## DB và reports bổ sung

DB chính của ứng dụng hiện là `<thư mục Agent>/agent.db`. Updater tự thêm các file `*.db` khác ngay trong thư mục này. Có thể khai báo đường dẫn tương đối trong `local_update_settings.json`:

```json
{"databases": ["research/history.db"], "reports": ["reports", "reports-extra"]}
```

`REPORTS_DIR` trong môi trường hoặc `.env` được đưa vào backup. Path ngoài thư mục Agent, `..`, symlink và thư mục trạng thái/backup bị từ chối thay vì bỏ sót âm thầm. Cấu hình thư mục reports nằm ngoài Agent cần người bảo trì bổ sung hỗ trợ trước khi Update; không chỉnh `.env` tự động.

## Mã lỗi thường gặp

| Mã | Việc cần làm |
|---|---|
| `GIT_NOT_INSTALLED` / `PYTHON_3_12_OR_NEWER_REQUIRED` | Cài Git/Python cho user rồi bấm lại. |
| `DIRTY_WORKING_TREE_COMMIT_OR_SAVE_CHANGES_FIRST` | Giữ nguyên thay đổi; nhờ người bảo trì xử lý. Không reset hard. |
| `UNMANAGED_AGENT_STOP_OLD_WINDOW_WITH_CTRL_C_THEN_RETRY` | Ctrl+C cửa sổ Agent cũ rồi bấm lại. |
| `OFFLINE_CANNOT_VERIFY_APPROVED_RELEASE` | Kiểm tra mạng; không có thay đổi code/DB. |
| `PUBLISHED_RELEASE_NOT_REVIEWED_OR_CI_NOT_GREEN` | Chờ release được duyệt và CI đạt. |
| `COMMAND_FAILED_CHECK_GIT_NETWORK_OR_DEPENDENCIES` | Kiểm tra Git/mạng/Python/dependencies; chưa chuyển phiên bản. |
| `LOCAL_CHECK_OR_BACKUP_FAILED` | Kiểm tra dung lượng, quyền file/SQLite lock và backup; không gửi `.env`. |
| `NEW_AGENT_HEALTH_CHECK_FAILED` | Đã chặn/rollback update; dùng launcher chạy bản cũ. |

Không có nút/endpoint HTTP thực thi cập nhật. `/local/health` chỉ trả `{ok, release_sha, pid}`; API quản trị cũ vẫn chưa có authentication, vì vậy chỉ dùng launcher bind localhost hoặc gateway có xác thực nếu thay đổi cách chạy.

Windows có giới hạn đường dẫn executable trong một số cấu hình: nested venv/release có thể vượt giới hạn dù thư mục Agent mở được. Nếu lỗi ở bước tạo venv, giữ nguyên dữ liệu và nhờ người bảo trì kiểm tra đường dẫn; ưu tiên cài vào thư mục ngắn khi chuẩn bị bản sao nghiệm thu. Updater không tự di chuyển project hoặc đổi cấu hình hệ thống.
