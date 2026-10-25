# V5.1.1 - 6 Case Paper + Reverse Research (giao dien tinh gon)

**Trang thai:** chi la ma nguon trong PR, chua merge/phat hanh/cai len PC.

## Pham vi DUOC GIU
- Quet Futures (BTC regime, score, RSI, ATR, volume). NEN CAN thiet
  de tao giao dich mo phong A-F, dung nhu dau vao Reverse Research.
- 6 case duy nhat duoc nhan tin hieu moi trong che do lean:
  A=BASE_RR2, B=BASE_RR1, C=REVERSE_RR2, D=REVERSE_RR1,
  E=CASE_E va F=CASE_F. E/F giu nguyen cau hinh database cu;
  khong tu tao case E/F moi vi chua co tham so da xac nhan.
- Paper position entry, SL, TP, fees, slippage, PnL, winrate, PF, expectancy,
  drawdown, lich su va tinh trang lenh. Day la con so can thiet
  cho PAPER, khong phai moi thanh phan UI 'diem vao lenh'.
- Reverse Lab Shadow prospective REV-A/B/C/D va lich su Case C; V2 thu thap,
  so sanh NOW/WAIT/BASE; V3 import/reconstruct, retrospective analysis.
  Nhom nghien cuu Reverse Lab khong can bat V4.4 Shadow legacy.
- News Guardian risk, bao cao ngay + Reverse, GitHub sync, health, backup,
  local release updater/rollback. Khong ket noi endpoint dat lenh that.

## Bo khoi giao dien/chay nen CHI TRONG lean
- Bieu do nen Coin Intelligence, Entry/Exit arrows, Replay, chart zoom,
  chart Trade Detail va Exit Simulator.
- Du doan DIEM VAO LENH rieng cua V3, moi lenh V3 Shadow: V3 se
  khong tao prediction/order moi; cac lenh V3 Shadow cu neu dang mo
  van duoc cap nhat trang thai de khong bi bo roi.
- V4.4 Shadow worker chung va Spot Narrative Research worker.
- Nhung case ngoai A-F khong duoc mo lenh MOI. Hang trong database
  va lich su ngoai A-F khong bi xoa; nhung lenh da mo van tiep tuc
  duoc monitor va dong theo quy tac cu.
- Legacy FULL van ton tai de rollback chuc nang theo cau hinh;
  khong xoa code du lieu, khong git reset.

## Luu lich su giao dich LOCAL ONLY
- Agent giu giao dich goc trong `agent.db` va tu dong tao file moi ngay:
  `reports/YYYY-MM-DD/trade-history.csv` (mo Excel),
  `reports/YYYY-MM-DD/trade-history.json` (chi tiet de nghien cuu).
- Chay 23:58, hoan tat ngay truoc luc 00:10 va 00:15 gio Viet Nam;
  khoi dong lai se tu thu nhat 7 ngay gan nhat tu SQLite.
- Du lieu tu 23:58-24:00 duoc them vao khi xuat lai sau nua dem.
- Bao gom trade cua case cu de bao toan lich su, nhung khong mo them lenh
  case ngoai A-F; co co che bao ve khong ghi de file co nhieu trade hon.
- `REPORT_STORAGE_MODE=local_only` la mac dinh. KHOA tat ca upload GitHub
  ngay ca neu `REPORT_GITHUB_SYNC_ENABLED=true` trong .env cu.
  GitHub chi luu source code/releases, khong luu lich su trade moi.
- Workflow `coin-futures-reports` da doi thanh chi chay thu cong,
  khong tu push daily review cu len GitHub nua. Lich su da day len tu
  truoc KHONG duoc xoa trong dot tinh gon nay.
- Thu muc reports/ va database duoc .gitignore de khong commit nham.
- Bao cao chi duoc ghi khi Agent co chay. Khi may tat, chuc nang catch-up
  chi phuc hoi giao dich da ghi vao SQLite; khong tao lenh gia.

## An toan va tien ich
- Mac dinh V5.1.1 la `RUNTIME_PROFILE=lean` (neu .env khong override).
  Muon kich hoat legacy UI va job lai thi dat `RUNTIME_PROFILE=full`
  trong .env sau khi dung Agent. Khong sua .env cua nguoi dung tu dong.
- LEAN dung risk/daily-loss/position limits Paper thong thuong, du
  `DATA_COLLECTION_MODE=true` trong file .env cu.
- A-F la ID co dinh. Neu E/F khong co tren PC, Dashboard BAO THIEU;
  khong tu suy dien tham so hay chong du lieu cu.
- Reverse Lab phai co `REVERSE_LAB_ENABLED=true` va
  `STRATEGY_BATTLE_ENABLED=true`. V2/V3 van yeu cau cac co opt-in
  `REVERSE_ENTRY_INTELLIGENCE_ENABLED`, `REVERSE_ENTRY_V3_ENABLED`;
  khong con phu thuoc vao co `V44_SHADOW_ENABLED` khi o lean.
- V3 trong lean chi RESEARCH, khong phat sinh de xuat chot gia Entry.
  'READY' khong tu dong du dieu kien train, khong danh dong retrospective
  thanh du bao ngoai mau.
- GitHub update doi hoi Release duoc review + Windows/Ubuntu CI xanh.
  Cho den khi version nay duoc duyet, KHONG chay update vao may cu.
- Chan doan: `CHAN_DOAN_V5.bat` o thu muc goc tao `v5-diagnostics.json`
  va `AGENT_KIEM_TRA.json` (read-only, loc secret).
  Khong gui .env, agent.db hoac token.

## Nghiem thu truoc khi merge
1. CI Windows Python 3.13.5, Ubuntu xanh; no-zip updater/rollback xanh.
2. Giao dien chi 5 tab: Paper / Scanner / Reverse / History / System.
3. A-F mo lenh dung policy; case du thua khong mo moi; lenh du dang mo
   tiep tuc duoc monitor.
4. Reverse Lab doc lap V4.4, duoc register/monitor va generate daily report.
5. Khong load chart candle/Replay/Exit Simulator trong lean,
   van dung du lieu OHLC tinh SL/TP va Outcome cua Case/Reverse.
6. Database, WAL, .env, lich su/so du Paper va report cu duoc bao toan.
