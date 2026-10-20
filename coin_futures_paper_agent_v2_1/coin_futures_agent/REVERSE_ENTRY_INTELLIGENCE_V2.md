# Reverse Entry Intelligence V2 — nghiên cứu và Shadow độc lập

Version `reverse-entry-v2.1`. Nhánh phát triển bắt đầu từ `codex/stabilize-v44`.
Đây là công cụ thu thập/kiểm chứng; chưa có kết luận chiến lược sinh lợi.
Không sửa A/B/C/D, logic REV-E, risk, phí hoặc số dư paper hiện tại.

## Tách bạch dữ liệu và kết luận

Report export hiện có chỉ đủ nghiên cứu mô tả: trade ID, score nguồn, side,
regime, MFE/MAE, lý do thoát và reason codes. Các bucket tổng hợp hoặc code
`RSI_SHORT_ZONE` không thay thế RSI numeric tại thời điểm tín hiệu. Không lấy
Paper lịch sử làm fill Shadow và không suy diễn feature từ kết quả tương lai.

Công cụ CLI kiểm tra thiếu feature, trùng ID, ngày không khớp, outcome xung đột,
tách hướng nguồn, regime, ba phần thời gian, score bucket và giờ entry UTC.
Kết quả mô tả không được gọi là bằng chứng nhân quả hay kiểm định mô hình.
Repository mã nguồn có thể công khai; không commit dữ liệu/export/đầu ra phân
tích từ repository báo cáo riêng vào nhánh mã nguồn.

## Thành phần

| Tệp | Trách nhiệm |
|---|---|
| `app/reverse_intelligence.py` | Feature schema, logistic L2, empirical neighbors, calibration, dự đoán và walk-forward thuần |
| `app/reverse_intelligence_store.py` | Bảng mới, freeze cohort/model/cost, thu thập nến, monitor Shadow và tổng hợp |
| `app/reverse_intelligence_research.py` | CLI chỉ đọc, phân tích exports, replay OHLC và walk-forward |
| `app/scanner.py` | Thêm metadata provenance khi opt-in; không đổi điểm Base/REV-E |
| `app/main.py` | Task thu thập sau paper, monitor riêng, GET API/dashboard |
| `app/reverse_research.py`, `app/v44_learning.py` | Chèn snapshot tổng hợp V2 vào báo cáo mới của hai Lab |

Không thêm package mới: dùng NumPy, pandas và SQLite đã có. Gradient boosting
chưa được thêm vì dataset đủ chuẩn chưa có; thêm họ mô hình khi chưa có dữ liệu
sẽ không cung cấp bằng chứng tốt hơn. REV-E cũ giữ nguyên, là đối chứng riêng.

## Thu thập opt-in

Mặc định `REVERSE_ENTRY_INTELLIGENCE_ENABLED=false`. Module chỉ chạy khi flag
này **và** `V44_SHADOW_ENABLED` cùng true. Không yêu cầu bật tiền thật hoặc key
Binance; chỉ dùng endpoint đọc dữ liệu public từ client hiện có. Không thay
giá trị flag/biến môi trường đang chạy trong lần phát triển này.

- Scanner tiếp tục tính điểm như cũ. Metadata V2 phân biệt OI/funding đo được
  bằng 0 với dữ liệu không có; OI hiện là thay đổi `sumOpenInterestValue`, có
  ảnh hưởng giá, không được diễn giải như thay đổi số hợp đồng thuần túy.
- Mỗi hàng Base có bias LONG/SHORT được ghi một lần theo scan/coin/source side,
  dù Case C không mở. Plan không hợp lệ, thiếu core hoặc provenance tương lai
  vẫn được ghi để kiểm tra selection bias, nhưng không tạo fill hoặc label giả.
- Nếu hợp lệ, freeze core/optional features, timestamp có dữ liệu, hướng Base,
  regime, giá/khoảng stop, phí/slippage/max hold và prediction/model ID.
- Core: source score, RSI 1h, EMA-distance/ATR, ATR% 1h, volume ratio. Optional:
  OI, funding, relative strength, signed EMA distance, trend flags Reverse,
  one-hot BTC regime và giờ UTC. Unknown regime tách khỏi NEUTRAL; missing
  optional có missing indicator, median/scaler chỉ fit trên training cũ.
- Task chạy sau xử lý paper; lỗi collection không thay đường quyết định paper.
  Cần theo dõi log collection và dung lượng đĩa khi bật opt-in.

Chỉ tạo/ghi bốn bảng mới: `rei_v2_cohorts`, `rei_v2_models`, `rei_v2_cases`,
`rei_v2_bars`. Không update/insert vào bảng paper, Strategy Cases, REV-E hay
Reverse Lab cũ. Không migrate, sửa hoặc xóa lịch sử. Nến lưu một lần theo
coin/minute với SHA-256 và `first_seen_at_ms`; bar bị sửa sau đó không đè dữ
liệu cũ. Snapshot model bất biến theo `model_id`/training digest.

Dataset có thể tăng nhanh khi nhiều coin/candle được theo dõi. Không tự xóa dữ
liệu để giới hạn kích thước. Cần thiết kế archive/backup được chủ sở hữu chấp
thuận trước khi chạy nhiều ngày. Training dùng cửa sổ 4.000 opportunity gần
nhất trước cutoff, tối đa 2.000 nhãn hợp lệ mỗi hướng. UI chỉ tổng hợp 2.000
cohort gần nhất và công khai giới hạn đó.

## Các đối chứng và giả định khớp

Mỗi cohort hợp lệ có 5 Shadow control, cùng khoảng rủi ro và chi phí freeze:

- `REVERSE_NOW`: logic execution REV-A, open phút tương lai đầu tiên sau quan sát.
- `WAIT_CONFIRMATION`: logic REV-B, hai nến 1m đóng xác nhận, vào open phút sau.
- `BASE_CONTROL`: theo hướng Base, fixed 2R, cùng thời điểm quan sát và fill model.
- `REV_C_CONTROL`, `REV_D_CONTROL`: cùng execution của REV-C/D nhưng trên cohort
  V2 độc lập. Không sửa engine hoặc vị thế Reverse Lab cũ.

V2 không tạo case paper mới. `REVERSE_NOW`/`WAIT_CONFIRMATION` chọn control được
đăng ký đồng thời; đánh giá policy dùng outcome control đó khi đã kết thúc.
`NO_TRADE` là 0R theo opportunity. WAIT hết hạn là no-entry 0R, không phải lệnh
thua; thống kê phân biệt khuyến nghị entry, entry có fill và fill chưa xác minh.
Số cohort không được gọi là số giao dịch khớp.

SL ưu tiên khi OHLC cùng chạm SL/TP, stop gap theo open bất lợi, phí taker và
slippage hai chiều, trailing có hiệu lực từ nến sau. Chỉ dùng nến đóng. Gap,
bar sai hoặc recovery quá 48 giờ → CENSORED, không gán outcome thắng/thua.
Monitor giữ cursor bền vững và compare-and-swap khi lưu để tránh ghi đè pass
đồng thời; lock scheduler vẫn cần theo hướng dẫn stabilization.

Funding cashflow, liquidation, spread/order book, partial exchange fills chưa
mô hình đầy đủ. Không gọi chi phí này là “đầy đủ như giao dịch thật”. Phí/slip
được freeze vào cohort để đổi config sau đó không làm thay label cũ. Hàm
`replay(cohort, bars, override_costs=...)` cho phép stress phí/slip trên bản sao,
không sửa kết quả đã lưu.

## Thuật toán Score V2

Mô hình tách theo **hướng nguồn**: Base LONG → Reverse SHORT; Base SHORT →
Reverse LONG. Không lấy dữ liệu nhiều của một hướng để giả vờ đủ mẫu hướng kia.

1. Model đóng băng tại đầu ngày UTC. Nhãn chỉ dùng nếu feature đã có trước
   quyết định và tất cả NOW/WAIT/BASE đã kết thúc, close ≤ available_at < cutoff.
   `label_available_at_ms` là lúc monitor biết kết quả, không phải timestamp
   đóng nến quá khứ. Điều này chống leakage khi recovery trễ.
2. Dùng training cũ rồi hai ngày calibration gần nhất; training outcome phải
   có trước bắt đầu calibration, thêm embargo 1 phút. Không random split; các
   giao dịch còn mở/chồng sang cutoff bị purge bằng close/available timestamp.
3. Evidence gate nghiên cứu: ≥30 fit rows trên ≥7 ngày fit; ≥12 calibration rows
   trên hai ngày. Đây là lựa chọn preregistered, chưa chứng minh tối ưu.
4. So sánh logistic L2 (optimizer/L2 cố định) và empirical neighbors. Mỗi họ
   ước lượng khả năng net-R >0 và expected net-R cho NOW/WAIT/BASE. Logistic EV
   dùng mean thắng/nonpositive trong fit; neighbors dùng outcome của các mẫu
   tương tự trong fit. Đây là estimator thử nghiệm, không mô hình nhân quả.
5. Ngưỡng candidate gồm 0 và percentile score trên **fit**: 25/50/75/90.
   Chọn họ/ngưỡng bằng mean net-R trên calibration, yêu cầu ≥5 entry khuyến nghị
   và serial drawdown không vượt control NOW trên calibration. Không dùng nhãn
   test để chọn ngưỡng. Nếu không có candidate dương, từ chối tạo model entry.
6. Dự đoán NOW hoặc WAIT chỉ khi EV của lựa chọn đó dương, vượt BASE_CONTROL và
   score vượt ngưỡng đã freeze. Nếu Base tốt hơn hoặc thiếu bằng chứng → NO_TRADE.

Điểm = 100 × output classifier/frequency của action Reverse có EV cao hơn.
**Đây là chỉ số chưa hiệu chỉnh, không được trình bày như xác suất thắng.**
Ngưỡng là kết quả lựa chọn trên calibration trong grid đã nêu; không gọi là
ngưỡng tối ưu thị trường. Không tự điều chỉnh A/B/C/D/REV-E hay promote paper.

Giải thích yếu tố dùng ablation: đưa một feature về median training rồi đo
đổi score/estimated R. Đây là độ nhạy của mô hình, không phải tác động nhân quả.

## Walk-forward và đánh giá

Mỗi ngày test UTC có model đóng băng đầu ngày, fit/calibration chỉ từ dữ liệu
đã biết trước cutoff. Manifest ghi fit IDs, calibration IDs, label cutoffs,
scaler, weights/neighbors, search diagnostics và digest. Không dùng future
label, future scaler hoặc OOS return để chọn model. Chưa có kết luận từ một
dataset không đủ provenance.

Output phân biệt cold-start, scored OOS, chưa resolved, attempted/filled entry,
policy R theo opportunity, expectancy trên entry đã fill, số mẫu, PF R,
win rate, total net R và **serial R drawdown**. Drawdown này không phải equity
portfolio khi nhiều coin giữ cùng lúc. Có thống kê hướng nguồn/regime, skipped
winners/avoided losses và paired delta với NOW/WAIT/BASE.

CI bootstrap theo cụm ngày (500 lần, seed cố định) chỉ có khi ≥3 ngày; dưới
100 cặp/14 ngày scored vẫn ghi INSUFFICIENT_SAMPLE. Ngay cả khi vượt gate,
status vẫn exploratory để con người review; `out_of_sample_validated=false`.
Gate không thay thế giai đoạn holdout hoàn toàn không đụng tới sau nghiên cứu.

Control C/D mới và outcome Case C/REV-A/B/C/D/E cũ không bị trộn vào nhãn huấn
luyện. Nếu có `legacy_cohort_id` khớp chính xác, overview ghi paired delta
**mang tính ngữ cảnh**; không coi fill có thời điểm khác nhau là cùng execution.
Không có cohort khớp thì trả thiếu dữ liệu, không so sánh PnL từ mẫu rời rạc.

## API, dashboard và báo cáo

- GET `/research/reverse-entry?limit=30` trả snapshot chỉ đọc, trạng thái
  enabled/insufficient, score/action/reasons/factors và performance timeline.
- Dashboard Reverse Lab thêm panel V2: LONG/SHORT/WAIT/NO TRADE, dấu “—” khi
  chưa có điểm, các yếu tố tăng/giảm score, ngày UTC và cửa sổ dữ liệu.
- Báo cáo mới `reverse-lab.{json,md,html}` và `v44-research.{json,md,html}` có
  `reverse_entry_intelligence`. Repair snapshot cũ không tính lại dữ liệu V2
  hôm nay để gắn vào lịch sử; báo cáo cũ được giữ nguyên.

API kế thừa tình trạng chưa có auth trong ứng dụng. Cần bảo vệ gateway và
direct origin như `STABILIZATION_V44.md` trước khi public; nhánh này không tự
thay cấu hình Render hay thêm credential.

## Chạy công cụ nghiên cứu chỉ đọc

Từ thư mục ứng dụng, chọn output **mới**, ngoài thư mục báo cáo gốc:

```sh
python -m app.reverse_intelligence_research \
  --reports /path/to/coin-futures-reports/reports \
  --output-dir /path/to/private-research-output/run-001

# Khi đã có dữ liệu Shadow V2: mở SQLite ở mode=ro, không khởi động app
python -m app.reverse_intelligence_research \
  --reports /path/to/coin-futures-reports/reports \
  --sqlite /path/to/copied-agent.db \
  --output-dir /path/to/private-research-output/run-002
```

CLI tạo `BAO_CAO.md` và `analysis.json`; không ghi vào reports nguồn, không gọi
mạng, không import lịch sử Paper vào dataset V2 và từ chối ghi đè output cũ.
Có thể truyền `--dataset` thay `--sqlite` với export V2 đã kiểm tra nguồn gốc.
Không chạy CLI bằng DB chưa backup khi vẫn cần kiểm tra snapshot nhất quán;
ưu tiên bản sao WAL-safe. Không copy credential/.env vào output.

## Kiểm thử và bước tiếp theo

Unit tests dùng dữ liệu tổng hợp chỉ để chứng minh tính đúng của phần mềm,
không phải kết quả backtest thị trường. Các nhóm test: cold start, missing/range,
future feature/label và label ingest trễ, tách side, train/calibration/test,
quyết định NOW/WAIT/NO_TRADE, giữ Base khi tốt hơn, chống duplicate, readonly DB,
phí/slip freeze và stress replay, gap/censor/revised bars, WAIT expiry, stop-first,
không thay dữ liệu bảng cũ, score Base bất biến khi thêm metadata, cả hai Lab
và DOM hiển thị null-score/escape text. Chạy toàn bộ suite với socket bị chặn.

Kết quả kiểm thử của nhánh: **185/185 pass** (141 ca nền + 44 ca mới), không
skip, một cảnh báo Starlette/TestClient đã tồn tại. Python compile, JavaScript
syntax (kể cả script inline dashboard), marker/candle alignment và
`git diff --check` đều pass. Không chạy server với DB thật, không gọi order API.

Sau review: chủ sở hữu mới quyết định bật opt-in Shadow trên staging, theo dõi
coverage/missingness và disk/lag, thu đủ cả hai hướng qua nhiều regime, kiểm
tra export/model digests và replay nến, rồi chạy walk-forward/holdout riêng.
Cần dữ liệu funding/spread/liquidity và equity portfolio trước mọi thảo luận
giao dịch thật. Không deploy Render hoặc merge main từ nhánh nghiên cứu này.
