"""agent_guard 的測試：用模擬的 hook 事件確認該擋的擋、不該擋的放行。 python scripts/hooks/test_agent_guard.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_guard.py")


def fire(tool, args, kind="PreToolUse", response=None, raw=None):
    event = {"hook_event_name": kind, "tool_name": tool, "tool_input": args}
    if kind == "PostToolUse":
        event["tool_response"] = response
    r = subprocess.run([sys.executable, GUARD], input=raw if raw is not None else json.dumps(event),
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


class Blocked(unittest.TestCase):
    def blocked(self, tool, args, word):
        code, _, err = fire(tool, args)
        self.assertEqual(code, 2, err)
        self.assertIn(word, err)

    def test_run_command(self):
        self.blocked("mcp__rhino__run_command", {"slot": "a", "command": "_-Make2D"}, "第一準則")
        self.blocked("mcp__plugin_rhino-mcp_rhino__run_command", {"slot": "a", "command": "_Open"}, "第一準則")

    def test_open_doc(self):
        self.blocked("mcp__rhino__open_doc", {"slot": "a", "path": "work/x/working/b/dwg/A1.DWG"}, "cadcraft")
        self.blocked("mcp__rhino__open_doc", {"slot": "a", "path": "m.3dm"}, "OpenHeadless")

    def test_missing_slot(self):
        self.blocked("mcp__rhino__run_python", {"script": "print(1)"}, "slot")
        self.blocked("mcp__rhino__get_context", {}, "slot")

    def test_commands_inside_scripts(self):
        self.blocked("mcp__rhino__run_python", {"slot": "a", "script": "import rhinoscriptsyntax as rs\nrs.Command('_Save')"}, "第一準則")
        self.blocked("mcp__rhino__run_csharp", {"slot": "a", "script": 'RhinoApp.RunScript("_Open", false);'}, "第一準則")
        self.blocked("mcp__rhino__run_python", {"slot": "a", "script": "Rhino.RhinoDoc.Open(p)"}, "OpenHeadless")

    def test_raw_is_read_only(self):
        self.blocked("Write", {"file_path": "/repo/work/demo/raw/dwg/a.dwg"}, "唯讀")
        self.blocked("Edit", {"file_path": "C:\\ws\\work\\Demo2\\raw\\doc\\n.txt"}, "唯讀")

    def test_manual_router(self):
        self.blocked("Bash", {"command": '"C:/Users/x/AppData/Roaming/McNeel/Rhinoceros/ai/bin/rhino-mcp-router.exe" -v 8'}, "router")
        self.blocked("PowerShell", {"command": "cd x; & 'C:\\a\\rhino-mcp-router.exe'"}, "router")

    def test_cadcraft_dash_command(self):
        self.blocked("Bash", {"command": "cadcraft-cli run a.dwg --cmd '-xref {\"option\":\"bind\"}'"}, "等號")

    def test_dialog_esc_needs_pid(self):
        self.blocked("PowerShell", {"command": "py .claude/skills/mcp-002-rhino-cadcraft-ops/scripts/rhino_dialogs.py esc"}, "--pid")
        self.blocked("Bash", {"command": "py x/rhino_dialogs.py --process Rhino.exe esc; echo"}, "--pid")


    def test_cadcraft_mcp(self):
        self.blocked("mcp__cadcraft__command_line", {"text": "line 0,0 1,1"}, "execute")
        self.blocked("mcp__cadcraft__save", {"path": "work/x/raw/dwg/a.dwg"}, "唯讀")
        self.blocked("mcp__cadcraft__execute",
                     {"command": "saveas", "params": {"path": "C:\\ws\\work\\x\\raw\\dwg\\a.dwg"}}, "唯讀")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "work", "x", "output", "b")
            os.makedirs(out)
            done = os.path.join(out, "a_v01.pdf")
            open(done, "w").close()
            self.blocked("mcp__cadcraft__execute", {"command": "plot", "params": {"path": done, "layout": "L"}}, "不覆寫")
            code, _, err = fire("mcp__cadcraft__execute",
                                {"command": "plot", "params": {"path": os.path.join(out, "a_v02.pdf")}})
            self.assertEqual(code, 0, err)


class Allowed(unittest.TestCase):
    def allowed(self, tool, args):
        code, out, err = fire(tool, args)
        self.assertEqual(code, 0, err)

    def test_dialog_esc_with_pid(self):
        self.allowed("PowerShell", {"command": "py .claude/skills/mcp-002-rhino-cadcraft-ops/scripts/rhino_dialogs.py esc --pid 28544"})
        self.allowed("Bash", {"command": "py x/rhino_dialogs.py list"})

    def test_normal_calls(self):
        self.allowed("mcp__rhino__list_slots", {})
        self.allowed("mcp__rhino__spawn_slot", {"version": 8})
        self.allowed("mcp__rhino__run_python", {"slot": "a", "script": "d = Rhino.RhinoDoc.OpenHeadless(p)\nprint(1)"})
        self.allowed("mcp__rhino__get_context", {"slot": "a"})
        self.allowed("Write", {"file_path": "/repo/work/demo/working/20261117_x/dwg/a.txt"})
        self.allowed("Write", {"file_path": "/repo/docs/harness/DRAWING.md"})
        self.allowed("Bash", {"command": "grep -rn rhino-mcp-router docs/"})
        self.allowed("Bash", {"command": "cadcraft-cli run a.dwg --cmd=-xref {} --cmd 'layout.set {}'"})
        self.allowed("Bash", {"command": "python scripts/ws.py file demo work/demo/raw/x.dwg"})
        self.allowed("mcp__github__run_command", {"command": "x"})
        self.allowed("mcp__cadcraft__open", {"path": "work/x/raw/dwg/a.dwg"})
        self.allowed("mcp__cadcraft__save", {})
        self.allowed("mcp__cadcraft__save", {"path": "work/x/working/b/dwg/a.dwg"})
        self.allowed("mcp__cadcraft__execute", {"command": "line", "params": {"points": [[0, 0], [1, 1]]}})

    def test_broken_input_never_blocks(self):
        self.assertEqual(fire("", {}, raw="not json")[0], 0)
        self.assertEqual(fire("", {}, raw="[1,2]")[0], 0)
        self.assertEqual(fire("", {}, raw="")[0], 0)


class After(unittest.TestCase):
    def test_empty_result_adds_a_note(self):
        code, out, _ = fire("mcp__rhino__run_python", {"slot": "a"}, "PostToolUse", response=[{"type": "text", "text": ""}])
        self.assertEqual(code, 0)
        self.assertIn("additionalContext", out)
        code, out, _ = fire("mcp__rhino__run_python", {"slot": "a"}, "PostToolUse", response="")
        self.assertIn("additionalContext", out)

    def test_normal_result_is_silent(self):
        code, out, _ = fire("mcp__rhino__run_python", {"slot": "a"}, "PostToolUse", response=[{"type": "text", "text": '{"objects": 12}'}])
        self.assertEqual((code, out.strip()), (0, ""))


if __name__ == "__main__":
    unittest.main()
