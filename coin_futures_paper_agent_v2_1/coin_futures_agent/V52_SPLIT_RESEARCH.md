# V5.2 — 6 Case Trading + Reverse Research Bot doc lap

Trang thai: PR #28 DRAFT chua merge, chua release va chua cai len Windows; phu thuoc PR #27.

## 1. Trading Bot
- Chi tao va quan ly lenh Paper theo Case A-F, scan Futures, News Guardian, sao luu, bao cao ngay.
- Trang Lean gom 4 khu vuc: 6 Case, Scan, Lich su, He thong.
- KHONG chay job / init / monitor / bao cao Reverse Lab V2/V3 cu trong Lean, KHONG tao Reverse entry proposal.
- Van giu cac bang Reverse cu trong agent.db va source module cu de quay lai/an toan, KHONG xoa co hoc.

## 2. Reverse Research Bot
- La process rieng, Python standard library, khong import Trading runtime va khong ghi vao agent.db.
- Nguon seed: verified ZIP all-history do BACKUP_HISTORY.bat tao (SQLite WAL + tat ca bao cao va backup cu, loai bo secrets).
- Sau ngay moi doc reports/YYYY-MM-DD/trade-history.json duoc Trading Bot luu tren may; khong day GitHub.
- Bao cao rieng reverse_research_data/latest.json: thong ke LONG/SHORT, Case, winner-vs-loser, so sanh cohort, thu nghiem gia thuyet TP.
- Model do gia trien khai moi dung thu nghiem offline, nhan insufficient khi thieu du lieu/label va can kiem dinh forward.
- KHONG ghi lenh gia, khong trading real, khong cho Trading Bot duoc phep dung model nay de tu giao dich.

## 3. Chay song song sau khi merge va phat hanh da duyet
1. Dung Trading Bot cu.
2. Bam BACKUP_HISTORY.bat de tao ban sao ZIP. Copy ZIP ra o khac de du phong.
3. Bam RUN_CA_HAI_BOT.bat de chay 6 Case Paper va Reverse Research cung luc.
4. Bam Ctrl+C tren cua so de dung Trader, worker Research se duoc dung cung.
5. Can chay Research rieng thi bam RESEARCH_BOT.bat.
6. Lich su Reverse cu chi duoc xoa khoi ma nguon / database sau khi ban kiem chung archive tren Windows.

## 4. Gioi han hien tai
- Cach thu 0.5R, 1R, 1.5R, 2R dua tren MFE/MAE khong chung minh lenh se thang vi khong biet thu tu gia cham TP, SL.
- Chua co replay nen day du va chua xac nhan loi nhuan tu mo hinh. Khong bat live trading.
- CI GitHub khong co quyen backup o Windows ca nhan, phai chay backup tren may nguoi dung.
- Du lieu da mat tren may tu truoc khong the lay lai chi tu source; neu chi o reports GitHub cu thi can import rieng (khong tu dong tai).
- Khong xoa files o GitHub trong PR nay do chua nghiem thu backup; PR sau se don source/module cu da khong dung.
