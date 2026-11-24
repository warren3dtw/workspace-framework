# profile 示範

`skills/<代號>/profiles/<專案>/` 放這個技能在某個專案的慣例和參數，安裝時用 `python scripts/ws.py install <代號> --profile <專案>` 裝成 `profile/`。資料夾名稱等於專案代號。

這裡放去識別化的示範，讓人知道要準備哪些檔案、每個欄位是什麼意思。不可以出現業主、案名、設計單位、人名、圖號、本機路徑。

| 檔案 | 放什麼 |
|---|---|
| `conventions.md` | 圖號規則、編號族、圖層命名這類換專案就會變的慣例 |
| `config.json` | 腳本參數 |
| `cases.md` | 案件經驗、圖面錯誤紀錄 |
