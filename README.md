# 工作架構（空框架）

一個 repo 裝下所有工作：技能區、工作區、文件區，用 git 管理，AI agent（Claude Code、Codex）從 `AGENTS.md` 進入。

```
workspace.json            設定：技能區在哪、有哪些專案、各自的模式
AGENTS.md  CLAUDE.md      agent 的入口
skills/<代號>/            技能區：技能的主版本（框架不附技能，只有 _template/ 範本）
work/<專案>/              工作區：raw/ 輸入、working/ 儲存、output/ 輸出（只放檔案）
docs/harness/             文件區：所有專案共用的流程規則（DEVELOPMENT、TESTING、各模式、角色）
docs/projects/<專案>/     文件區：專案的事實、紀錄、計畫（plan、specs、tasks）
.claude/  .agents/        Claude Code 和 Codex 的設定、角色入口、安裝出來的技能副本
scripts/ws.py             工作架構的工具（只用 Python 標準庫）
```

目前沒有專案。開始用：

```bash
python scripts/ws.py check                                              # 檢查
python scripts/ws.py new project <代號> --mode drawing --title "標題"     # 建立第一個專案
python scripts/ws.py status                                             # 從哪裡接續
```

放了案件資料的 repo 要維持私人。
