#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把預設的文字與標註樣式（STD 樣式）套進 DWG。

樣式定義在 docs/harness/modes/drawing/annotation-styles/annotation-styles.json，尺寸是紙面 mm。
套到比例 1:N 時，文字樣式的固定字高 = 紙面字高 × N，標註樣式的 DIMSCALE = N；
樣式名稱是 <prefix>-<代號>-<N>，例如 STD-NOTE-50、STD-LIN-50。N=1 是圖紙空間（版面）用的。

用法（Windows 上把 python 換成 py）：
    python scripts/annotation_styles.py list
    python scripts/annotation_styles.py commands --scale 50                 # 只印出 cadcraft 指令（JSON），不執行
    python scripts/annotation_styles.py apply <輸入.dwg> <輸出.dwg> --scale 1 50 [--fonts zh] [--layers] [--current 50]
    python scripts/annotation_styles.py template <輸出.dwg> --scale 1 10 50  # 從空白公制圖建立只有樣式的圖

在專案腳本裡：
    import annotation_styles as st
    cc.run(圖, [cc.cmd(c, **p) for c, p in st.commands([1, 50], fonts="zh")] + [...自己的指令...], save=新檔)

每次 cadcraft-cli run 都是新的工作階段：樣式存在圖裡會留下來，但「目前樣式」不會，
所以畫文字和標註的那一次 run 開頭要自己設 style.current／dimstyle.current（或在 mtext 帶 style）。
只用 Python 標準庫。寫入保護（不寫 raw/、不覆寫 output/）沿用技能 mcp-002 的 cadcraft_tool。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "workspace.json").is_file())
CATALOG = ROOT / "docs" / "harness" / "modes" / "drawing" / "annotation-styles" / "annotation-styles.json"


def _cadcraft_tool():
    """技能 mcp-002 的共用入口；位置從 workspace.json 的技能區（skills.path）讀。"""
    ws = json.loads((ROOT / "workspace.json").read_text(encoding="utf-8"))
    scripts = ROOT / ws.get("skills", {}).get("path", "skills") / "mcp-002-rhino-cadcraft-ops" / "scripts"
    sys.path.insert(0, str(scripts))
    import cadcraft_tool
    return cadcraft_tool


def load():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _n(scale):
    return ("%g" % scale)


def name(code, scale, cat=None):
    return "%s-%s-%s" % ((cat or load())["prefix"], code, _n(scale))


def text(code, scale, cat=None):
    """畫文字時要帶的參數：{"style": 樣式名稱, "height": 模型單位的字高}。

    cadcraft 的 mtext 不會自動採用樣式的固定字高（0.17.1 實測：不帶 height 就用 TEXTSIZE），所以 height 一定要帶。
    用法：cc.cmd("mtext", at=[x, y], text="…", **st.text("NOTE", 50))
    """
    cat = cat or load()
    t = next((t for t in cat["文字樣式"] if t["代號"] == code), None)
    if t is None:
        raise ValueError("沒有這個文字樣式：%s" % code)
    return {"style": name(code, scale, cat), "height": round(t["紙面字高"] * scale, 6)}


def commands(scales, fonts="source", layers=False, current=None, cat=None):
    """回傳 [(指令代號, 參數), …]。scales 是比例分母的清單，例如 [1, 50]。"""
    cat = cat or load()
    if fonts not in cat["字型組"]:
        raise ValueError("沒有這個字型組：%s（有 %s）" % (fonts, "、".join(cat["字型組"])))
    fontset = cat["字型組"][fonts]
    out = []
    for s in scales:
        if s <= 0:
            raise ValueError("比例要大於 0：%s" % s)
        for t in cat["文字樣式"]:
            if t["空間"] == "paper" and s != 1:
                continue
            out.append(("style", {"name": name(t["代號"], s, cat), "font": fontset[t["字型"]],
                                  "height": round(t["紙面字高"] * s, 6), "widthFactor": 1.0}))
        for d in cat["標註樣式"]:
            p = {"name": name(d["代號"], s, cat)}
            p.update(cat["標註樣式共同變數"])
            p.update(d["變數"])
            p["DIMSCALE"] = float(s)
            p["DIMTXSTY"] = name(d["文字樣式"], s, cat)
            out.append(("dimstyle", p))
    if layers:
        for l in cat["圖層"]:
            out.append(("layer.new", {"name": l["名稱"], "color": l["color"], "lineweight": l["lineweight"]}))
    if current is not None:
        out.append(("style.current", {"name": name("NOTE", current, cat)}))
        out.append(("dimstyle.current", {"name": name("LIN", current, cat)}))
    return out


def _verify(cc, dwg, expected):
    """重開存好的圖，確認每個樣式都在而且數值相同。回傳不符的清單。"""
    want_text = {p["name"]: p for c, p in expected if c == "style"}
    want_dim = {p["name"]: p for c, p in expected if c == "dimstyle"}
    cmds = [cc.cmd("style.list")] + [cc.cmd("dimstyle.list", name=n) for n in want_dim]
    got = cc.run(dwg, cmds)
    styles = {s["name"]: s for s in got[0]["styles"]}
    bad = []
    for n, p in want_text.items():
        s = styles.get(n)
        if not s:
            bad.append("文字樣式不在圖裡：%s" % n)
        elif s["font"].lower() != p["font"].lower() or abs(s["height"] - p["height"]) > 1e-6:
            bad.append("文字樣式 %s：圖裡是 %s／%s，應該是 %s／%s" % (n, s["font"], s["height"], p["font"], p["height"]))
    for r in got[1:]:
        v = r.get("variables") or {}
        n = (r.get("style") or {}).get("name")
        p = want_dim.get(n)
        if not p:
            bad.append("標註樣式查不到：%s" % n)
            continue
        for k, val in p.items():
            if k == "name":
                continue
            g = v.get(k)
            same = abs(g - val) < 1e-6 if isinstance(val, float) and isinstance(g, (int, float)) else g == val
            if not same:
                bad.append("標註樣式 %s 的 %s：圖裡是 %r，應該是 %r" % (n, k, g, val))
    return bad, len(want_text), len(want_dim)


def _apply(a):
    cc = _cadcraft_tool()
    todo = commands(a.scale, a.fonts, a.layers, a.current)
    args = [cc.cmd(c, **p) for c, p in todo]
    out = Path(a.output)
    if a.cmd == "template":
        cc.check_write(out)
        if out.exists():
            raise cc.CadcraftError("檔案已經存在，不覆寫：%s" % out)
        got = cc.jsonl(cc.call(["run", "--metric"] + args + ["--save", str(out)]))
        bad = cc.errors_in(got)
        if bad:
            raise cc.CadcraftError("有 %s 個指令失敗，第一個：%s" % (len(bad), json.dumps(bad[0], ensure_ascii=False)[:600]))
    else:
        if out.exists() and out.resolve() != Path(a.input).resolve():
            raise cc.CadcraftError("輸出檔已經存在，不覆寫：%s" % out)
        cc.run(a.input, args, save=out)
    bad, nt, nd = _verify(cc, out, todo)
    print(json.dumps({"output": str(out), "sha256": cc.sha256(out), "cadcraft": cc.version(), "scales": a.scale,
                      "fonts": a.fonts, "textStyles": nt, "dimStyles": nd, "layers": bool(a.layers),
                      "verified": not bad, "problems": bad}, ensure_ascii=False, indent=1))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="預設的文字與標註樣式（STD 樣式）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出樣式定義（紙面 mm）")

    def common(p):
        p.add_argument("--scale", type=float, nargs="+", required=True, help="比例分母，可以多個：1 是圖紙空間，50 是 1:50")
        p.add_argument("--fonts", default="source", help="字型組：source（來源的 Arial）或 zh（微軟正黑體）")
        p.add_argument("--layers", action="store_true", help="一併建立註解圖層")
        p.add_argument("--current", type=float, help="把這個比例的 NOTE、LIN 設成目前樣式（只在同一次 run 有效）")

    common(sub.add_parser("commands", help="只印出指令"))
    p = sub.add_parser("apply", help="套進一張圖，另存新檔")
    p.add_argument("input")
    p.add_argument("output")
    common(p)
    p = sub.add_parser("template", help="從空白公制圖建立只有樣式的圖")
    p.add_argument("output")
    common(p)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        cat = load()
        print("文字樣式（紙面 mm）")
        for t in cat["文字樣式"]:
            print("  %-8s %-18s %-7g %-6s %s" % (t["代號"], t["字型"], t["紙面字高"], t["空間"], t["用途"]))
        print("標註樣式")
        for d in cat["標註樣式"]:
            print("  %-8s %s %s" % (d["代號"], d["用途"], json.dumps(d["變數"], ensure_ascii=False) if d["變數"] else ""))
        return 0
    if a.cmd == "commands":
        print(json.dumps([{"command": c, "params": p} for c, p in commands(a.scale, a.fonts, a.layers, a.current)],
                         ensure_ascii=False, indent=1))
        return 0
    try:
        return _apply(a)
    except Exception as e:  # CadcraftError 或檔案問題：印訊息，退出碼 1
        print("失敗：%s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
