# 工作架構（空框架）

一個 repo 裝下所有工作：技能區、工作區、文件區，用 git 管理，AI agent（Claude Code、Codex）從 `AGENTS.md` 進入。知識庫是另一個 repo，可以串聯進來。

```
workspace.json            設定：技能區在哪、知識庫在哪、有哪些專案、各自的模式
knowledge/llm-wiki/       知識庫（另一個 repo，ws.py kb link 下載，不進這個 repo 的 git）
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

## 串聯知識庫

知識庫是另一個 repo，空的知識庫框架在 [knowledge-framework](https://github.com/warren3dtw/knowledge-framework)。兩個 repo 各自下載、各自 commit；`workspace.json` 的 `knowledge.repo` 預設就是這個網址，用自己的知識庫時換成自己的網址：

```bash
python scripts/ws.py kb link                      # 照 workspace.json 的網址下載到 knowledge/llm-wiki/
python scripts/ws.py kb link <知識庫 repo 網址>    # 或換成別的知識庫，網址記進 workspace.json
python scripts/ws.py kb status                    # 串聯狀態
python scripts/ws.py kb pull                      # 更新知識庫
python scripts/ws.py kb skill <代號> --bare       # 從知識庫取技能到 skills/，並裝進 .claude 和 .agents
python scripts/ws.py kb ingest-skill <代號>        # 把改進帶回知識庫
```

細節見 `AGENTS.md` 的「串聯知識庫」。

放了案件資料的 repo 要維持私人。
