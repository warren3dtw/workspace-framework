# 給所有 agent 的入口

這個 repo 是一套給 AI agent 用的工作架構，分三個區，用 git 管理：

| 區 | 位置 | 放什麼 |
|---|---|---|
| 技能區 | `workspace.json` 的 `skills.path`（目前是 [`skills/`](skills/README.md)） | 技能的主版本：`skills/<代號>/`，專案的慣例放 `skills/<代號>/profiles/<專案>/` |
| 工作區 | `work/<專案>/` | 只放檔案，分三層：`raw/<類型>/` 輸入（唯讀）、`working/<日期_內容>/<類型>/` 儲存、`output/<日期_內容>/` 輸出（例如 `20261117_木結構圖繪製`） |
| 文件區 | `docs/harness/`、`docs/projects/<專案>/` | 所有流程、規則、文件：共用的流程規則（harness）；每個專案的 PROJECT（事實和成果）、LOG（變更、交付、問題）和計畫 |

專案清單和各自的模式（drawing 繪圖、animation 動畫、general 通用）寫在 `workspace.json`。

## 每次開工

1. `python scripts/ws.py status`：有哪些進行中的計畫，從哪裡接續。
2. 確認這次是哪個專案，讀 `docs/projects/<專案>/README.md`、`PROJECT.md` 和 `LOG.md` 的「未解決」。`archive/` 平常不用讀。
3. 讀共用規則 [`docs/harness/DEVELOPMENT.md`](docs/harness/DEVELOPMENT.md)，再依專案的模式讀 `docs/harness/modes/<模式>/`。
4. 要用或改技能：讀 [`skills/README.md`](skills/README.md)，`python scripts/ws.py skills` 看安裝狀態。

| 你要做的事 | 讀這個 |
|---|---|
| 做專案的工作（建模、出圖、動畫） | 專案的 README、PROJECT，加上 [`docs/harness/`](docs/harness/README.md) |
| 新增技能、改進技能 | [`skills/README.md`](skills/README.md) |
| 改流程規則 | `docs/harness/`，並記 [FEEDBACK](docs/harness/FEEDBACK.md)、[CHANGELOG](docs/harness/CHANGELOG.md) |
| 把專案的經驗整合回技能和流程規則（排程或手動） | [`docs/harness/roles/experience-curator.md`](docs/harness/roles/experience-curator.md) |
| 在 `work` 開新專案 | 只建立 `work/<名稱>/raw/`、`working/`、`output/` 三個空資料夾，不建立文件、不登記 `workspace.json`；有給檔案路徑就用 `ws.py file` 複製進 `raw/` |
| 建立完整／已登記專案 | `python scripts/ws.py new project <代號> --mode drawing` |

## 所有角色都要遵守

- 操作 Rhino 一律透過目前工作階段原生提供的 Rhino MCP 呼叫 Rhino SDK，不使用 Rhino command（Rhino 指令列命令）驅動開檔、存檔、建模、修改、查詢或匯出；操作前先核對 MCP 工具 schema、專案的 slot lease、作用中的 Rhino 實例與文件。原生 Rhino MCP 工具未注入時停止並回報，不自行啟動另一個 router 程序、建立 stdio 橋接、模擬鍵盤或改走 Rhino command。每個進行中的專案先透過目前原生 router 建立專屬 Rhino slot，所有呼叫明確帶同一 slot；不得採用其他 router 已接管的實例。這是所有 Rhino 操作的第一準則。唯一的例外：Rhino 跳出的對話框擋住 MCP 時，可以用技能 `mcp-002-rhino-cadcraft-ops` 的 `rhino_dialogs.py` 讀出是哪個視窗，並只關掉白名單裡列出的視窗（直接觸發按鈕，不送按鍵、不點座標）；不在白名單的停止並回報，新增白名單要先問使用者。第二個例外：slot 的腳本空回傳、`rhino_dialogs.py list` 沒有對話框、送 `print` 也是空的時，可以用同一支腳本的 `esc --pid <自己 slot 的 PID>` 對那個 Rhino 主視窗送一次 Esc（使用者 2026-11-24 允許），再送 `print` 確認；仍然卡住就停止，請使用者在 Rhino 按 Esc。
- 記憶體不夠就告知使用者，不強制執行：大型工作（開 50 MB 以上的 IFC／3dm／DWG、開 Rhino slot、多程序計算）前先跑 `python scripts/ws.py mem --need <GB>`，退出碼不是 0、或執行中因記憶體不足崩潰，就停下來把數字和佔用最多的程序告訴使用者，不重試、不硬跑、不自行結束別人的程序。細則見 DEVELOPMENT 的「記憶體不夠就停」。
- 流程的份量跟著工作大小走：只讀取的查詢直接做；一次對話做得完、範圍清楚、不改規格的小任務不開計畫，做完在專案 LOG 記一筆；其餘才開計畫。安全規則不分大小都要遵守。定義見 DEVELOPMENT 的「工作分級」。
- 操作 Rhino 或 CADCraft 前先讀技能 `mcp-002-rhino-cadcraft-ops`：DWG 交給 `cadcraft-cli`（不用 Rhino 的 `open_doc`）；讀 3dm 用 `RhinoDoc.OpenHeadless`；預檢只做一次；一件工作寫成一支腳本一次送出；同一步最多重試一次，第二次失敗就停止並回報。
- 寫給使用者的文字用繁體中文。英文術語第一次出現時附中文。
- 專案的事實只寫在專案的 `PROJECT.md`；流程規則只寫在 `docs/harness/`；技能只寫在 `skills/`。不在別處複製。
- 先補這次需要的資訊再動手，不猜指令、尺寸、公差、版本或工具名稱。修改前記規格和任務，修改後驗收；沒有執行的檢查不得標通過。
- 來源不覆寫，交付用沒用過的新版本。
- 文件和腳本裡的路徑一律相對於 repo 根目錄，不寫磁碟代號，換電腦才不用改（寫法見 DEVELOPMENT 的「路徑怎麼寫」）。
- 一個案子開一個專案。
- 使用者說「在 `work` 開新專案」時，意思固定為只建立 `work/<使用者指定名稱>/raw/`、`working/`、`output/` 三個空資料夾；保留名稱大小寫，不加 `.gitkeep` 或其他檔案，不修改 `workspace.json`，不建立 `docs/projects/`。只有使用者明確要求完整、正式或已登記專案時，才用 `ws.py new project`；不要把前者自行擴充成後者。使用者同時給了檔案路徑時，建好三個資料夾後用 `python scripts/ws.py file <名稱> <路徑...>` 把那些檔案複製進 `raw/<類型>/`（不移動、不改原檔，同名不覆寫），把每個檔案的 `raw/` 位置和 SHA256 回報給使用者；路徑是資料夾或不存在時先問，不自己猜（見 DEVELOPMENT 的「在 work 開新專案」的固定意思）。使用者只給路徑、沒說要做什麼，而且路徑在 repo 外面時，不動檔案，先問：開新專案（名稱是什麼），還是存到現有的哪一個專案（列出 `workspace.json` 的專案和 `work/` 下的僅工作資料夾專案）；得到答案後一樣用 `ws.py file` 複製進那個專案的 `raw/`（見 DEVELOPMENT 的「只給路徑時先問」）。例外：這種專案第一次要把成果放進 `output/` 之前，先告訴使用者並登記成完整專案再交付（見 DEVELOPMENT 的「僅工作資料夾專案什麼時候要登記」）。
- 案件資料要不要進 git，第一次加入前先問；答案記在 PROJECT，不進 git 的路徑寫進根目錄的 `.gitignore`。
- 整個任務完成而且 `python scripts/ws.py check` 通過才 commit，只納入這次的變更，不自動 push。一律在 `main` 上工作，不開分支。唯一的例外是雲端工作階段：在它指定的分支 commit 並 push 到該分支，不動 `main`（見 DEVELOPMENT 的「雲端工作階段」）。
- 技能只改主版本（`skills/<代號>/`）。`.claude/skills/`（Claude Code）和 `.agents/skills/`（Codex）是程式安裝出來的副本，不手改；改完主版本用 `python scripts/ws.py install <代號>` 兩邊同時更新，`ws.py check` 會檢查兩邊一模一樣。工作中發現技能的問題，先記在專案的 LOG，不必當場改。
- 技能和筆記不是設計依據。實際設計以現行規範原文和專業簽證為準。

## 依模式的重點

細則在 `docs/harness/`，這裡只列每次都要記得的事。Claude Code 和 Codex 讀的是同一份，不在 `.claude/` 或 `.agents/` 另寫規則。

- **所有專案**：開工先跑 `python scripts/ws.py status`。規格先於執行；驗收要有證據，沒測不能通過；續作從 tasks 的階段表接續，每個階段依 DEVELOPMENT 存檔。結束時更新專案的 PROJECT（成果和狀態）和 LOG 並依規則歸檔。task 等級的修改不備份，實質改變 specs 才在變更前備份受影響的工作檔一次。問題記在專案的 LOG，規則本身的問題記在 `docs/harness/FEEDBACK.md`。
- **交付**：來源不覆寫，交付存新版本，寫入前確認位置和版本沒有用過；待審查不得標成已接受。交付紀錄寫在專案 LOG 的「交付」表。
- **繪圖（drawing）**：先確認 Rhino 實例、文件和工具行為，讀 `docs/harness/modes/drawing/`。草圖 → Rhino → DWG → CADCraft → PDF，每個階段存檔並記來源版本。草圖一定要貼進 Rhino 校正比例，立面向使用者確認，以規則重建比對殘差、不逐線描（DRAWING 的 D1）。用 CADCraft 出 PDF 照 CADCRAFT-PLOT：預設 STD 樣式和 NEW.ctb、引線一律用多重引線、全彩物件疊印保留顏色、出圖後跑文字碰撞檢查 0 處才通過。
- **動畫（animation）**：操作 Rhino 前定位實例和文件並核對工具 schema，讀 `docs/harness/modes/animation/`。普通 Rhino group 作組裝單元，重疊或跨樓層要先釐清；先編號，使用者核准後才匯出；鋼木相依只提建議。逐格以絕對幀數計算，保持 GUID／單元對應、組內剛性和終態。JSON／GLB／設定／影片同修訂並記 SHA256，bundle 不等於影片。順序審查用預覽，沒要求不輸出影片。

## 指令

全部只用 Python 標準庫。Windows 上把 `python` 換成 `py`。

```bash
python scripts/ws.py status                                   # 進行中的計畫和下一步
python scripts/ws.py check                                    # 檢查工作架構和技能
python scripts/ws.py new plan <專案> <英文名稱> --title "標題"   # 開新計畫
python scripts/ws.py new project <代號> --mode drawing,animation --title "標題"   # 建立完整／已登記專案
python scripts/ws.py file <專案> <檔案...>                     # 把使用者給的檔案依類型放進 raw/，印出 SHA256
python scripts/ws.py skills                                   # 已安裝的技能和主版本的比較
python scripts/ws.py mem --need 4                             # 大型工作前查記憶體；退出碼不是 0 就停下來告訴使用者
python scripts/ws.py new skill rhino-004-roof-panels         # 從範本建立新技能
python scripts/ws.py install rhino-002-sequence-fasteners --profile <專案>   # 從 skills/ 安裝或更新技能（Claude 和 Codex 兩邊同時）；--all 全部
```
