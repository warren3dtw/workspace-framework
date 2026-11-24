#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CADCraft 升版後的冒煙測試：跑幾個已知案例，和基準版本的結果比。

    python scripts/cadcraft_smoke.py                  # 跑測試，和 docs/harness/cadcraft-baseline.json 比
    python scripts/cadcraft_smoke.py --set-baseline   # 全部通過才把這台的版本和結果寫成新的基準

每個案例有兩種結果：
  通過／失敗  這個功能能不能用（失敗就不要用這一版出圖）。
  行為        這一版實際怎麼做（例如另存的 DWG 版本）。和基準不同不算失敗，但技能 mcp-002 的
              「已知的工具行為」和既有腳本要跟著查證。

所有檔案寫在暫存資料夾，跑完就刪；不碰 work/。只用 Python 標準庫。Windows 上把 python 換成 py。
沒有涵蓋：由 Layout 用 plot 出正式 PDF、--connect 連到開著的 CADCraft 視窗。
"""
import datetime
import json
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import annotation_styles as st  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

BASELINE = st.ROOT / "docs" / "harness" / "cadcraft-baseline.json"
SCALES = [1, 50]
TEXT = "CLT 樓板搭接 Lap Joint 123"


def case_styles(cc, tmp):
    """建立預設樣式（文字、標註、圖層），存檔重開逐項比對。"""
    todo = st.commands(SCALES, layers=True)
    out = tmp / "styles.dwg"
    got = cc.jsonl(cc.call(["run", "--metric"] + [cc.cmd(c, **p) for c, p in todo] + ["--save", str(out)]))
    bad = cc.errors_in(got)
    if bad:
        return False, {"error": json.dumps(bad[0], ensure_ascii=False)[:300]}
    problems, nt, nd = st._verify(cc, out, todo)
    return not problems, {"textStyles": nt, "dimStyles": nd, "problems": problems[:5]}


def case_annotate(cc, tmp):
    """用樣式畫中文多行文字和標註，存檔重開後內容、樣式、字高、量測值都在。"""
    src, out = tmp / "styles.dwg", tmp / "annotate.dwg"
    cc.run(src, [cc.cmd("mtext", at=[0, 0], text=TEXT, **st.text("NOTE", 50)),
                 cc.cmd("mtext", at=[0, -500], text="no height", style=st.name("NOTE", 50)),
                 cc.cmd("dimstyle.current", name=st.name("LIN", 50)),
                 cc.cmd("dimlinear", p1=[0, -1000], p2=[6000, -1000], at=[3000, -1500])], save=out)
    texts = cc.run(out, [cc.cmd("texts")])[0]["texts"]
    info = json.loads(cc.call(["info", "--compact", str(out)]))
    a = next((t for t in texts if t["text"] == TEXT), None)
    b = next((t for t in texts if t["text"] == "no height"), None)
    ok = bool(a and b and abs(a["height"] - 125) < 1e-6 and a["style"] == st.name("NOTE", 50)
              and info.get("counts", {}).get("Dimension") == 1 and info.get("counts", {}).get("MText") == 2)
    behavior = {"mtext 不帶 height 時的字高（樣式固定字高是 125）": round(b["height"], 4) if b else None}
    return ok, {"counts": info.get("counts"), "中文內容相同": bool(a), "behavior": behavior}


def case_saveas(cc, tmp):
    """另存 DWG：不指定版本時存成哪一版；指定 2018 時重開得回來。"""
    src = tmp / "annotate.dwg"
    a, b = tmp / "default.dwg", tmp / "v2018.dwg"
    cc.run(src, [cc.cmd("getvar", name="ACADVER")], save=a)   # 至少要有一個指令才會執行
    cc.run(src, [cc.cmd("saveas", path=str(b), version="2018")])
    va = cc.run(a, [cc.cmd("getvar", name="ACADVER")])[0]
    vb = cc.run(b, [cc.cmd("getvar", name="ACADVER")])[0]
    count = json.loads(cc.call(["info", "--compact", str(b)])).get("entityCount")
    ver = lambda r: r.get("value", r) if isinstance(r, dict) else r
    return count == 3 and str(ver(vb)).startswith("AC1032"), {
        "behavior": {"--save 新圖的 DWG 版本（ACADVER）": ver(va), "saveas version=2018 的 ACADVER": ver(vb)}}


def case_export(cc, tmp):
    """模型空間匯出 PDF 和 PNG（預覽用，不是正式圖紙）。"""
    src = tmp / "annotate.dwg"
    res = {}
    for ext, magic in (("pdf", b"%PDF"), ("png", b"\x89PNG")):
        out = tmp / ("export." + ext)
        cc.call(["run", str(src), "--export", str(out)])
        res[ext] = out.is_file() and out.read_bytes()[:4] == magic
    return all(res.values()), res


def case_catalog(cc, tmp):
    """這個工作架構用到的指令都還在指令目錄裡。"""
    need = ["style", "style.list", "style.current", "dimstyle", "dimstyle.list", "dimstyle.current", "mleaderstyle",
            "layer", "layer.new", "layer.set", "mtext", "text", "dimlinear", "dimaligned", "dimangular", "dimtedit",
            "texts", "usage", "shapes", "loops", "saveas", "getvar", "setvar", "purge", "plot", "exportpdf", "mview",
            "viewport.set", "layout.list"]
    ids = {c["id"] for c in json.loads(cc.call(["commands", "--compact"]))}
    missing = [n for n in need if n not in ids]
    return not missing, {"missing": missing, "behavior": {"指令總數": len(ids)}}


def case_mcp(cc, tmp):
    """MCP 伺服器：啟動、列出工具、開圖、execute、找文字、渲染。"""
    p = subprocess.Popen([cc.find_cli(), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    q = queue.Queue()

    def reader():
        for line in p.stdout:
            try:
                q.put(json.loads(line.decode("utf-8", "replace")))
            except ValueError:
                pass
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    n = [0]

    def send(method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            n[0] += 1
            msg["id"] = n[0]
        p.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        p.stdin.flush()
        while not notify:
            r = q.get(timeout=60)
            if r is None:
                raise RuntimeError("MCP 伺服器提早結束")
            if r.get("id") == n[0]:
                return r

    def tool(name, args=None):
        r = send("tools/call", {"name": name, "arguments": args or {}})
        res = r.get("result") or {}
        if "error" in r or res.get("isError"):
            raise RuntimeError("%s 失敗：%s" % (name, json.dumps(r.get("error") or res, ensure_ascii=False)[:200]))
        return res["content"]

    try:
        init = send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "smoke", "version": "0"}})["result"]
        send("notifications/initialized", notify=True)
        tools = sorted(t["name"] for t in send("tools/list")["result"]["tools"])
        need = ["open", "save", "execute", "list_commands", "inspect_drawing", "query_entities", "find_text", "render"]
        missing = [t for t in need if t not in tools]
        tool("open", {"path": str(tmp / "annotate.dwg")})
        found = json.loads(tool("find_text", {"contains": "樓板"})[0]["text"])["count"]
        styles = json.loads(tool("execute", {"command": "dimstyle.list", "params": {}})[0]["text"])["styles"]
        image = tool("render", {"width": 320, "height": 200})
        ok = not missing and found == 1 and st.name("LIN", 50) in styles and any(c.get("type") == "image" for c in image)
        return ok, {"missing": missing, "behavior": {"MCP 伺服器版本": init["serverInfo"].get("version"),
                                                     "MCP 協定": init.get("protocolVersion"), "MCP 工具": tools}}
    finally:
        try:
            p.stdin.close()
            p.wait(10)
        except Exception:
            p.kill()


CASES = [("預設樣式", case_styles), ("文字與標註", case_annotate), ("另存 DWG", case_saveas),
         ("匯出預覽", case_export), ("指令目錄", case_catalog), ("MCP 伺服器", case_mcp)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cc = st._cadcraft_tool()
    full = cc.version()
    m = __import__("re").search(r"cadcraft-cli\s+(\S+)(?:\s+\(([0-9a-f]+)\))?", full)
    version, commit = (m.group(1), m.group(2) or "") if m else (full, "")
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    print("cadcraft-cli %s（基準版本 %s）" % (version, base.get("version", "還沒訂")))
    results, behavior, failed = {}, {}, []
    with tempfile.TemporaryDirectory(prefix="cadcraft-smoke-") as d:
        tmp = Path(d)
        for label, fn in CASES:
            try:
                ok, detail = fn(cc, tmp)
            except Exception as e:  # 一個案例失敗不影響後面的
                ok, detail = False, {"error": str(e)[:400]}
            behavior.update(detail.pop("behavior", {}))
            results[label] = {"pass": ok, **detail}
            print("  %s %s%s" % ("通過" if ok else "失敗", label, "" if ok else "：" + json.dumps(detail, ensure_ascii=False)[:400]))
            if not ok:
                failed.append(label)
    old = base.get("behavior", {})
    changed = {k: {"基準": old.get(k), "這一版": v} for k, v in behavior.items() if k in old and old[k] != v}
    print("行為：")
    for k, v in behavior.items():
        mark = "（和基準不同，基準是 %s）" % json.dumps(old[k], ensure_ascii=False) if k in changed else ""
        print("  %s：%s%s" % (k, json.dumps(v, ensure_ascii=False), mark))
    print("結果：%s 個案例，%s 個失敗，%s 個行為和基準不同" % (len(CASES), len(failed), len(changed)))
    if "--set-baseline" in argv:
        if failed:
            print("有案例失敗，不更新基準。")
            return 1
        BASELINE.write_text(json.dumps({
            "說明": "CADCraft 的基準版本：兩台電腦都裝這一版。由 scripts/cadcraft_smoke.py --set-baseline 寫入，不手改。ws.py status 開工時拿這台的版本和它比。",
            "version": version, "commit": commit, "verified": datetime.date.today().isoformat(),
            "cases": {k: v["pass"] for k, v in results.items()}, "behavior": behavior,
            "沒有涵蓋": ["由 Layout 用 plot 出正式 PDF", "--connect 連到開著的 CADCraft 視窗"]},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("已把 %s 寫成基準版本：%s" % (version, BASELINE.relative_to(st.ROOT).as_posix()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
