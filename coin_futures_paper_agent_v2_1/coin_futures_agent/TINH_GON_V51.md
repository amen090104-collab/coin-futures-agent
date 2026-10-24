# Trading Bot V5.1 - che do tinh gon (khong xoa du lieu)

## Ly do
Agent cu co nhieu nhom research chay song song: V4.4 Shadow, Reverse Lab,
Spot, Reverse V2/V3, Paper Strategy Battle, news va reports. Bat tat ca khi
dang tim loi se lam kho phan biet duong giao dich Paper va research.

## Giu lai
- Quet Futures va tinh tin hieu LONG/SHORT.
- Paper Strategy Battle A-F, quan ly lenh, news guardian va gioi han rui ro.
- Reverse V2 input collector + V3 learning/reconstruction neu cac co cu da duoc bat.
- Bao cao ngay, dong bo GitHub (neu da cau hinh), health check va DB backups.
- update.bat/rollback, toan bo database va history cu.

## Bo qua chi khi bat che do lean
- V4.4 legacy Shadow scan/monitor va Reverse Lab cu.
- Spot Research nen.
- Data collection mode mo rong so lenh Paper. Khi LEAN, Paper dung gioi han
  thong thuong va daily loss guard, du DATA_COLLECTION_MODE=true trong .env.
- Khong xoa cac bang da co. Khong thay doi bat ky so du hay lich su nao.

## Bat/tat
1. Dung Agent bang Ctrl+C.
2. Trong .env, them hoac sua `RUNTIME_PROFILE=lean`.
   Default `full` de bao toan hanh vi cu. Doi ve `RUNTIME_PROFILE=full`
   neu can chay lai cac nghien cuu cu.
3. Khoi dong `run.bat`. Trang `/health` cho biet `runtime_profile` va
   `data_collection_mode_effective`.
4. Chay `CHAN_DOAN_V5.bat` co san o thu muc Agent goc: ban va moi tu dong
   tao ca `v5-diagnostics.json` va `AGENT_KIEM_TRA.json`. `KIEM_TRA_AGENT.bat`
   cung co trong thu muc ma nguon V5.1.1 de chay audit rieng neu can.
   Cong cu chi doc database va loai bo secret/trade rows; khong gui .env/agent.db.

## Neu Reverse V3 van NO_TRADE
`lean` khong bo qua cac chot data quality, frozen model hay OOS;
`NO_TRADE` khi chua du evidence la dung. Dung `CHAN_DOAN_V5.bat` de
kiem tra cohort, READY, train/calibration va gate cua v3.

## Phat hanh
Thay doi phai duoc review/CI va phat hanh qua GitHub Release da duyet truoc
khi su dung updater. Day la PR nguon, khong phai ban da cai tren may Windows.
KHONG git reset, khong xoa .env/agent.db/backups va khong bat tien that.
