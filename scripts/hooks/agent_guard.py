#!/usr/bin/env python3
"""Claude Code 的 hook：在工具呼叫前攔下已知會出錯或浪費時間的操作。規則和原因見 docs/harness/HOOKS.md。

從標準輸入讀 hook 事件的 JSON。PreToolUse：違反規則時在 stderr 寫原因並以退出碼 2 結束（Claude Code 會擋下
這次呼叫，把原因交給 agent）；其他情況退出碼 0。PostToolUse：只補充提醒，不擋。
這支腳本本身出錯時一律退出碼 0，不擋工作。只用 Python 標準庫。

    python scripts/hooks/agent_guard.py < 事件.json
"""
import json
import os
import re
import sys

# Rhino MCP 的工具名稱：直接註冊時是 mcp__rhino__<工具>，由外掛安裝時是 mcp__plugin_<外掛>_rhino__<工具>。
RHINO_TOOL = re.compile(r"^mcp__(?:plugin_[^_].*?_)?rhino__(?P<tool>.+)$")
# 不對單一 slot 操作的工具，不要求帶 slot。
NO_SLOT_NEEDED = {"list_slots", "spawn_slot"}
# CADCraft 的 MCP（cadcraft-cli mcp）。
CADCRAFT_TOOL = re.compile(r"^mcp__(?:plugin_[^_].*?_)?cadcraft__(?P<tool>.+)$")
OUTPUT_PATH = re.compile(r"(^|[\\/])work[\\/][^\\/]+[\\/]output[\\/]", re.I)
SAVE_COMMANDS = {"save", "qsave", "saveas", "wblock", "plot", "exportpdf"}
DRAWING_EXT = (".dwg", ".dxf")
RAW_PATH = re.compile(r"(^|[\\/])work[\\/][^\\/]+[\\/]raw[\\/]", re.I)
# 以 router 執行檔當指令（行首，或接在 ; & | 之後），不含只是把路徑當參數的查詢。
ROUTER_AS_COMMAND = re.compile(r"(?:^|[;&|]\s*|&\s+)[\"']?[^\s\"';&|]*rhino-mcp-router(?:\.exe)?[\"']?(?=\s|$)", re.I | re.M)
# rhino_dialogs.py esc：使用者 2026-11-24 允許對卡住的 slot 送 Esc，但一定要指定 --pid（只送給自己的 slot）。
DIALOG_ESC = re.compile(r"rhino_dialogs\.py[\"']?\s+(?:--\S+\s+\S+\s+)*esc\b(?P<rest>[^\n;&|]*)", re.I)
# cadcraft-cli 的 --cmd 後面用空白接以 - 開頭的指令代號，會被當成旗標。
CMD_DASH = re.compile(r"cadcraft-cli[^\n]*--cmd[ \t]+[\"']?-[A-Za-z]")
# 在 Rhino 腳本裡下指令或換掉目前文件。
SCRIPT_BANNED = (
    (re.compile(r"RhinoApp\.RunScript\s*\(|\brs\.Command\s*\(|rhinoscriptsyntax\.Command\s*\("),
     "腳本裡用 RunScript／rs.Command 下 Rhino 指令。第一準則：只用 Rhino SDK（RhinoCommon），不下指令。"),
    (re.compile(r"RhinoDoc\.Open\s*\("),
     "腳本裡用 RhinoDoc.Open 會換掉 slot 的文件，router 會失去這個 slot。讀檔用 RhinoDoc.OpenHeadless，"
     "或 Rhino.FileIO.File3dm.Read。"),
)


def check_rhino(tool, args):
    if tool == "run_command":
        return ("第一準則：不用 run_command 下 Rhino 指令（互動提示會卡住 slot）。"
                "改用 run_python／run_csharp 呼叫 Rhino SDK；SDK 做不到就停止並回報。")
    if tool == "open_doc":
        path = str(args.get("path") or args.get("file") or args.get("filePath") or "")
        if path.lower().endswith(DRAWING_EXT):
            return ("不用 open_doc 開 DWG／DXF：它是匯入，曾讓 slot 卡住（H-010）。"
                    "DWG 的讀取和修改交給 cadcraft-cli（技能 mcp-002-rhino-cadcraft-ops 的 cadcraft_tool.py inspect）。")
        return ("open_doc 實際是匯入（doc.Import）：不採用檔案的單位和公差，clearFirst 也可能留下重複物件。"
                "讀取用 run_python 裡的 RhinoDoc.OpenHeadless；確定要匯入到目前文件時，在腳本裡用 SDK 匯入並檢查單位。")
    if tool in ("run_python", "run_csharp"):
        script = str(args.get("script") or args.get("code") or "")
        for pattern, why in SCRIPT_BANNED:
            if pattern.search(script):
                return why
    if tool not in NO_SLOT_NEEDED and not args.get("slot"):
        return ("這次 Rhino MCP 呼叫沒有帶 slot。每次呼叫都要明確帶本專案 lease 的 slot，"
                "不依賴預設或別的 router 接管（adopted）的 slot。先 list_slots 確認。"
                "（這個工具如果本來就沒有 slot 參數，把它加進 scripts/hooks/agent_guard.py 的 NO_SLOT_NEEDED。）")
    return None


def check_cadcraft(tool, args):
    """MCP 的存檔沒有 CLI 的保護：不寫進 raw/，不覆寫 output/ 裡已經有的檔案，不用 command_line。"""
    if tool == "command_line":
        return ("不用 command_line（模擬鍵盤輸入，空白等於 Enter，容易誤觸）。"
                "改用 execute {command, params}；指令和參數用 list_commands {filter} 查。")
    path = ""
    if tool == "save":
        path = str(args.get("path") or "")
    elif tool == "execute" and str(args.get("command") or "").lower() in SAVE_COMMANDS:
        params = args.get("params") if isinstance(args.get("params"), dict) else {}
        path = str(params.get("path") or "")
    if not path:
        return None
    if RAW_PATH.search(path):
        return "不寫進 raw/（來源唯讀）：%s。存到 working/<日期_內容>/。" % path
    if OUTPUT_PATH.search(path) and os.path.exists(path):
        return "output/ 裡已經有這個檔案，交付不覆寫：%s。用新的版本號。" % path
    return None


def check_write(args):
    path = str(args.get("file_path") or args.get("notebook_path") or "")
    if RAW_PATH.search(path):
        return "raw/ 是使用者給的來源，唯讀：%s。複製到 working/<日期_內容>/ 再改；新來源用 ws.py file 放進來。" % path
    return None


def check_shell(args):
    command = str(args.get("command") or "")
    if ROUTER_AS_COMMAND.search(command):
        return ("不手動啟動 rhino-mcp-router：只用工作階段原生注入的 Rhino MCP 工具。"
                "工具沒出現就停止並回報，用技能 mcp-001-rhino-cadcraft-tools 檢查設定。")
    m = DIALOG_ESC.search(command)
    if m and "--pid" not in m.group("rest"):   # 值的檢查交給腳本（argparse 要求整數）；文件裡的範例 <PID> 不擋
        return ("rhino_dialogs.py esc 要指定 --pid <slot 的 Rhino PID>（list_slots 看得到），"
                "只送給本專案 lease 的 slot，不送給別人的 Rhino。")
    if CMD_DASH.search(command):
        return "cadcraft-cli 的指令代號以 - 開頭時要寫成 --cmd=-xref {…}（等號形式），用空白會被當成旗標。"
    return None


def pre_tool_use(event):
    name = str(event.get("tool_name") or "")
    args = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    m = RHINO_TOOL.match(name)
    if m:
        return check_rhino(m.group("tool"), args)
    m = CADCRAFT_TOOL.match(name)
    if m:
        return check_cadcraft(m.group("tool"), args)
    if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return check_write(args)
    if name in ("Bash", "PowerShell"):
        return check_shell(args)
    return None


def _empty(response):
    if response is None:
        return True
    if isinstance(response, str):
        return not response.strip()
    if isinstance(response, (list, dict)):
        if not response:
            return True
        text = json.dumps(response, ensure_ascii=False)
        return not re.search(r"[0-9A-Za-z\u4e00-\u9fff]{2,}", re.sub(r'"(type|text|content)"', "", text))
    return False


def post_tool_use(event):
    name = str(event.get("tool_name") or "")
    m = RHINO_TOOL.match(name)
    if not m or m.group("tool") not in ("run_python", "run_csharp"):
        return None
    if _empty(event.get("tool_response")):
        return ("這次 Rhino 腳本回傳是空的。腳本沒有印出結果，或 slot 的腳本佇列被前一個操作卡住（H-010）。"
                "不要連續重試：先 list_slots 和 get_context 確認 slot 還在，跑 rhino_dialogs.py list 看有沒有對話框；"
                "沒有對話框、而且送 print 也是空的，可以跑一次 rhino_dialogs.py esc --pid <slot 的 PID>"
                "（使用者 2026-11-24 允許，H-031），再送 print 確認。同一步最多重試一次，"
                "仍然是空的就停止並請使用者在 Rhino 按 Esc，不換另一種開檔方式碰運氣。腳本最後要 print 一段 JSON 結果。")
    return None


def main():
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    kind = event.get("hook_event_name")
    if kind == "PreToolUse":
        reason = pre_tool_use(event)
        if reason:
            sys.stderr.write("[agent_guard] " + reason + "\n")
            return 2
    elif kind == "PostToolUse":
        note = post_tool_use(event)
        if note:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}},
                             ensure_ascii=False))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        code = main()
    except Exception as e:  # 這支腳本自己的錯不擋工作
        sys.stderr.write("[agent_guard] 腳本錯誤，未檢查：%r\n" % (e,))
        code = 0
    sys.exit(code)
