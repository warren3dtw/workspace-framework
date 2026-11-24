#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""預設的列印樣式表（CTB）：AutoCAD CTB 轉成 CADCraft 的格式，出圖時載入。

預設表在 docs/harness/modes/drawing/plot-styles/：NEW.cadcraft.json（CADCraft 用，表名 NEW.ctb），
來源備份是同一資料夾的 source-NEW.ctb。CADCraft 不會自動載入任何資料夾裡的表，
每次 cadcraft-cli run 都要先送 stylesmanager load；表載入後由 pagesetup 指定，存檔時會寫進 DWG，
之後重開這張圖不用再載入。

用法（Windows 上把 python 換成 py）：
    python scripts/plot_styles.py list                          # 預設表的內容（只列線寬或顏色不是預設值的色號）
    python scripts/plot_styles.py commands                      # 印出載入預設表的 cadcraft 指令（JSON）
    python scripts/plot_styles.py convert <來源.ctb> <輸出.json> [--name 表名]   # AutoCAD CTB → CADCraft JSON

在專案腳本裡：
    import plot_styles as ps                                    # scripts/ 要在 sys.path
    cmds = [cc.cmd(c, **p) for c, p in ps.commands()] + [...]   # 放在同一次 run 的開頭
    sheet(..., plot_style=ps.DEFAULT_NAME)                      # mcp-002 的 cadcraft_sheet；或 pagesetup 的 plotStyleTable

只用 Python 標準庫。轉換只處理色彩相依（.ctb）的表；遇到 CADCraft 格式表達不了的設定
（淡化、指定線型、端點／接合／填滿樣式）會報錯停下，不默默丟掉。
"""
import argparse
import json
import re
import sys
import zlib
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "workspace.json").is_file())
FOLDER = ROOT / "docs" / "harness" / "modes" / "drawing" / "plot-styles"
DEFAULT_FILE = FOLDER / "NEW.cadcraft.json"
DEFAULT_NAME = "NEW.ctb"

# CTB 裡代表「用物件本身的設定」的值
_OBJ_LINEWEIGHT, _OBJ_LINETYPE, _OBJ_END, _OBJ_JOIN, _OBJ_FILL = 255, 31, 4, 5, 73


def decode_ctb(data):
    """AutoCAD CTB／STB 二進位檔 → 文字（PIAFILEVERSION_2.0 標頭 + zlib）。"""
    head = b"pmzlibcodec"
    i = data.find(head)
    if not data.startswith(b"PIAFILEVERSION_") or i < 0:
        raise ValueError("不是 AutoCAD 的 CTB／STB 檔（缺 PIAFILEVERSION 或 pmzlibcodec 標頭）")
    # 標頭之後是 4 位元組 checksum、4 位元組解壓後大小、4 位元組壓縮大小，然後是 zlib 資料
    return zlib.decompress(data[i + len(head) + 12:]).decode("latin-1")


def ctb_to_cadcraft(text, name, description):
    if "aci_table_available=TRUE" not in text:
        raise ValueError("這是具名樣式表（STB），目前只轉色彩相依的 CTB")
    lw_part = text[text.index("custom_lineweight_table{"):]
    lw = {int(a): float(b) for a, b in re.findall(r"^ (\d+)=([\d.]+)$", lw_part, re.M)}
    body = text[text.index("plot_style{"):text.index("custom_lineweight_table{")]
    styles = []
    for n, block in re.findall(r"^ (\d+)\{\n(.*?)\n \}", body, re.M | re.S):
        d = dict(re.findall(r"^  (\w+)=(.*)$", block, re.M))
        aci = int(n) + 1
        unsupported = [k for k, v in (("screen", "100"), ("linetype", str(_OBJ_LINETYPE)),
                                      ("end_style", str(_OBJ_END)), ("join_style", str(_OBJ_JOIN)),
                                      ("fill_style", str(_OBJ_FILL))) if d.get(k) != v]
        if unsupported:
            raise ValueError("色號 %d 有轉換還沒處理的設定：%s" % (aci, ", ".join("%s=%s" % (k, d.get(k)) for k in unsupported)))
        policy = int(d["color_policy"])          # bit 1 混色、bit 2 轉灰階、bit 4 指定顏色
        s = {"name": "Color_%d" % aci}
        if policy & 4:
            s["color"] = "#%06x" % (int(d["color"]) & 0xFFFFFF)
        if policy & 2:
            s["grayscale"] = True
        idx = int(d["lineweight"])
        if idx != _OBJ_LINEWEIGHT:
            s["lineweight"] = int(round(lw[idx] * 100))   # CADCraft 的線寬單位是 0.01 mm
        styles.append(s)
    if len(styles) != 255:
        raise ValueError("樣式數是 %d，應該是 255" % len(styles))
    return {"cadcraftPlotStyleTable": 1, "description": description, "kind": "colorDependent",
            "name": name, "styles": styles}


def load(path=DEFAULT_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def commands(path=DEFAULT_FILE):
    """載入預設表的指令：[("stylesmanager", {...})]。放在每次 run 的開頭。"""
    return [("stylesmanager", {"action": "load", "path": Path(path).resolve().as_posix()})]


def object_color_table(path=DEFAULT_FILE):
    """同一張表，但每個色號都用物件原色（線寬不變）。表名 <原名>_objcolor.ctb。
    給全彩物件疊印用：CADCraft 會把全彩物件換成最接近的色號再查表（AutoCAD 保留全彩顏色），
    出一份這個表的 PDF，再用技能 mcp-002 的 pdf_check.truecolor_overlay 疊回正式 PDF。"""
    t = load(path)
    stem = t["name"][:-4] if t["name"].lower().endswith(".ctb") else t["name"]
    return dict(t, name=stem + "_objcolor.ctb", description=t["description"] + "; object colours",
                styles=[{k: v for k, v in s.items() if k not in ("color", "grayscale")} for s in t["styles"]])


def _describe(s):
    parts = []
    parts.append("顏色 " + (s["color"] if "color" in s else "物件顏色") + ("（灰階）" if s.get("grayscale") else ""))
    parts.append("線寬 " + ("%.2f mm" % (s["lineweight"] / 100.0) if "lineweight" in s else "物件線寬"))
    return "、".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="預設的列印樣式表（CTB）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出預設表的內容")
    sub.add_parser("commands", help="印出載入預設表的 cadcraft 指令")
    oc = sub.add_parser("objcolor", help="寫出「線寬照表、顏色用物件原色」的表（全彩物件疊印用）")
    oc.add_argument("out")
    c = sub.add_parser("convert", help="AutoCAD CTB 轉 CADCraft JSON")
    c.add_argument("src")
    c.add_argument("out")
    c.add_argument("--name", help="表名（預設用來源檔名）")
    c.add_argument("--description", default="")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        t = load()
        print("%s（%s）：%s" % (t["name"], DEFAULT_FILE.relative_to(ROOT).as_posix(), t["description"]))
        base = {"color": "#000000", "lineweight": 0}
        for s in t["styles"]:
            if {k: v for k, v in s.items() if k != "name"} != base:
                print("  %-10s %s" % (s["name"], _describe(s)))
        print("  其餘色號：顏色 #000000、線寬 0.00 mm")
    elif a.cmd == "commands":
        for cmd, p in commands():
            print(json.dumps({"cmd": cmd, "params": p}, ensure_ascii=False))
    elif a.cmd == "objcolor":
        out = Path(a.out)
        if out.exists():
            sys.exit("輸出檔已經存在，不覆寫：%s" % out)
        out.write_text(json.dumps(object_color_table(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"out": out.as_posix(), "name": object_color_table()["name"]}, ensure_ascii=False))
    else:
        src, out = Path(a.src), Path(a.out)
        if out.exists():
            sys.exit("輸出檔已經存在，不覆寫：%s" % out)
        if any(part == "raw" for part in out.resolve().parts):
            sys.exit("不寫進 raw/：%s" % out)
        name = a.name or src.name
        table = ctb_to_cadcraft(decode_ctb(src.read_bytes()), name, a.description or "Converted from %s" % src.name)
        out.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"out": out.as_posix(), "name": name, "styles": len(table["styles"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
