# 技能區

技能是「把一種工作打包成 agent 可以照著做的說明和腳本」。這裡放每個技能的**主版本**。框架本身不附技能：拿到技能包後把整個 `<代號>/` 資料夾放進這裡，再 `python scripts/ws.py install <代號>`（或 `--all`）。`.claude/skills/`（Claude Code）和 `.agents/skills/`（Codex）是 `ws.py install` 複製出來的副本，兩邊內容必須一模一樣，不手改。

```
skills/<代號>/
  SKILL.md            入口：檔頭的 name、description、metadata.version
  CHANGELOG.md        版本紀錄，只往上追加
  tests.md            驗收題；能用程式驗證的寫成 scripts/test_*.py
  scripts/            腳本
  references/         參考資料（選用）
  profile.example/    專案 profile 的去識別化示範（選用）
  profiles/<專案>/    某個專案的慣例和參數（選用；安裝時用 --profile 裝成 profile/）
```

## 指令

```bash
python scripts/ws.py skills                                  # 安裝狀態，和主版本比較
python scripts/ws.py install <代號>                           # 安裝或更新到兩邊
python scripts/ws.py install <代號> --profile <專案>          # 連同 profiles/<專案>/ 一起裝成 profile/
python scripts/ws.py install --all                           # 全部重裝（不含 _template）
python scripts/ws.py new skill <前綴-三位數-描述>              # 從 _template 建立新技能
```

## 規則

- 代號寫成「前綴-三位數-英文簡短描述」，例如 `rhino-002-sequence-fasteners`；資料夾名稱等於 SKILL.md 的 `name`。
- 改技能：改 `skills/<代號>/`，升 `metadata.version`（改規則升次版本、修錯字升修正、改輸入輸出格式升主版本），在 CHANGELOG 加一筆，再 `ws.py install <代號>`。
- 工作中發現技能的問題，先記在專案的 LOG；換專案也會發生的，由 [experience-curator](../docs/harness/roles/experience-curator.md) 整合回來。
- 專案的私人內容（圖號、案名、案件經驗）只放 `profiles/<專案>/`，不寫進 SKILL.md 本體。
- 安裝紀錄 `.skill-source` 記版本、profile 和每個檔案的 SHA256；副本被改過時 `ws.py check` 會提醒，`ws.py install` 要加 `--force` 才覆寫。
