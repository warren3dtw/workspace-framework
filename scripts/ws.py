#!/usr/bin/env python3
"""工作架構的工具。只用 Python 標準庫。設定在根目錄的 workspace.json。

用法：python scripts/ws.py <指令> [參數]

  status                                 進行中的計畫和下一步（續作時先跑這個）
  check                                  檢查工作架構：設定、專案資料夾、計畫、連結、技能
  new project <代號> --mode drawing[,animation] [--title 標題]   建立完整／已登記專案：docs/projects/<代號>/ 和 work/<代號>/
  new plan <專案> <英文名稱> [--title 標題]                       在專案底下開新計畫
  install <代號>|--all [--profile <專案>] [--force]
                                         從 skills/<代號>/ 安裝或更新技能，Claude（.claude/skills）和 Codex（.agents/skills）兩邊同時寫入；
                                         --profile 把 skills/<代號>/profiles/<專案>/ 裝成 profile/
  new skill <代號>                        從範本建立新技能 skills/<代號>/
  skills                                 已安裝的技能，以及和主版本（skills/）的比較
  mem [--need GB]                        記憶體夠不夠（實體可用和可分配都要 ≥ 需要量＋保留 2 GB）；不夠退出碼 2，就停止並告訴使用者
  file <專案> <檔案...> [--to raw|working] [--sub 子資料夾] [--move]
                                         把檔案依副檔名放進 work/<專案>/raw/<類型>/（預設複製），印出 SHA256；
                                         --to working 時 --sub 必填，是「日期_內容」資料夾，放進 working/<日期_內容>/<類型>/

四個區：
  技能區  workspace.json 的 skills.path（目前是 skills/）：技能的主版本
  工作區  work/<專案>/：raw/<類型>/ 輸入、working/<日期_內容>/<類型>/ 儲存、output/<日期_內容>/ 輸出；只放檔案
  文件區  docs/harness/ 共用的流程規則；docs/projects/<專案>/ 專案的事實、紀錄和計畫
"""
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "workspace.json"
PROJECT_FILES = ["README.md", "PROJECT.md", "LOG.md"]
OLD_PROJECT_FILES = ["FEATURES.md", "CHANGELOG.md", "FEEDBACK.md", "DELIVERY.md"]
DRIVE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])")
PLAN_FILES = ["plan.md", "specs.md", "tasks.md"]
LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"```.*?```", re.S)
ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def skills_root(cfg):
    path = Path(cfg.get("skills", {}).get("path", "skills"))
    return path if path.is_absolute() else ROOT / path


def option(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            sys.exit(f"{name} 後面要接值")
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return default


def project_dirs(pid):
    return ROOT / "docs" / "projects" / pid, ROOT / "work" / pid


def plans_of(pid, archived=False):
    base = project_dirs(pid)[0] / "plans"
    folder = base / "archive" if archived else base
    return sorted(p for p in folder.glob("*/") if p.is_dir() and p.name != "archive")


def stage_table(tasks_text):
    """讀 tasks.md 的「階段與存檔點」表。回傳 [(階段, 狀態, 下一步)]。"""
    m = re.search(r"^## 階段與存檔點\s*\n(.*?)(?=^## |\Z)", tasks_text, re.S | re.M)
    if not m:
        return []
    rows = [l.strip() for l in m.group(1).splitlines() if l.strip().startswith("|")]
    if len(rows) < 2:
        return []
    head = [c.strip() for c in rows[0].strip("|").split("|")]
    find = lambda name: next((i for i, h in enumerate(head) if name in h), None)
    i_stage, i_status, i_next = 0, find("狀態"), find("下一步")
    out = []
    for row in rows[2:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < len(head):
            cells += [""] * (len(head) - len(cells))
        out.append((cells[i_stage], cells[i_status] if i_status is not None else "",
                    cells[i_next] if i_next is not None else ""))
    return out


LAYERS = ("raw", "working", "output")
BATCH_RE = re.compile(r"^\d{8}_\S+$")  # working／output 的「日期_內容」資料夾，例如 20261117_木結構圖繪製


def type_of(path, cfg):
    """依副檔名判斷檔案類型（workspace.json 的 work_layout.types）。找不到回傳 other。"""
    ext = Path(path).suffix.lower()
    for name, exts in cfg["work_layout"]["types"].items():
        if ext in exts:
            return name
    return "other"


def check_work(cfg, pid, errors, warnings):
    """work/<專案>/ 只能有 raw、working、output 三層；raw 和 working 的檔案要放在類型資料夾裡。"""
    work = project_dirs(pid)[1]
    types = set(cfg["work_layout"]["types"])
    extra = set(cfg["work_layout"].get("working_extra", {}))
    for entry in sorted(work.iterdir()):
        if entry.name not in LAYERS and entry.name not in (".gitkeep", ".DS_Store", "Thumbs.db"):
            errors.append(f"work/{pid}/{entry.name}：work/<專案>/ 只放 raw、working、output 三層；流程和文件放 docs/projects/{pid}/")
    for layer in ("raw", "working"):
        base = work / layer
        if not base.is_dir():
            errors.append(f"work/{pid}/{layer}/ 不存在")
            continue
        entries = sorted(base.iterdir())
        if layer == "working":  # 日期_內容 資料夾底下再依類型分
            for batch in [e for e in entries if e.is_dir() and BATCH_RE.match(e.name)]:
                entries.remove(batch)
                entries += sorted(batch.iterdir())
        for entry in entries:
            rel = entry.relative_to(ROOT).as_posix()
            if entry.is_file():
                if entry.name != ".gitkeep":
                    warnings.append(f"{rel}：檔案要放進類型資料夾，例如 .../{type_of(entry, cfg)}/")
            elif entry.name not in types and not (layer == "working" and entry.name in extra):
                warnings.append(f"{rel}：不是已知的類型（{'、'.join(sorted(types | (extra if layer == 'working' else set())))}）")
            elif entry.name in types and entry.name != "other":
                for f in entry.rglob("*"):
                    if f.is_file() and f.name != ".gitkeep" and type_of(f, cfg) not in (entry.name, "other"):
                        warnings.append(f"{f.relative_to(ROOT).as_posix()}：副檔名是 {type_of(f, cfg)}，卻放在 {entry.name}/")
    if not (work / "output").is_dir():
        errors.append(f"work/{pid}/output/ 不存在")
    else:
        for entry in sorted((work / "output").iterdir()):
            if entry.is_file() and entry.name not in (".gitkeep", ".DS_Store", "Thumbs.db"):
                warnings.append(f"work/{pid}/output/{entry.name}：交付要放進 output/<日期_內容>/ 資料夾")


def plan_state(folder):
    plan = (folder / "plan.md").read_text(encoding="utf-8") if (folder / "plan.md").exists() else ""
    title = re.search(r"^# (.+)$", plan, re.M)
    status = re.search(r"^(?:狀態|- 狀態|\| 狀態 \|)[：:｜| ]*\s*([^\n|]+)", plan, re.M)
    rows = stage_table((folder / "tasks.md").read_text(encoding="utf-8")) if (folder / "tasks.md").exists() else []
    pending = [r for r in rows if r[1] and "已驗收" not in r[1] and "不適用" not in r[1]]
    return {"title": title.group(1).strip() if title else folder.name,
            "status": status.group(1).strip() if status else "", "rows": rows, "pending": pending}


# ---------------- status ----------------
def cmd_status(args):
    cfg = config()
    any_plan = False
    for p in cfg["projects"]:
        plans = plans_of(p["id"])
        print(f"== {p['id']}｜{p.get('title', '')}｜模式 {'、'.join(p.get('modes', []))}｜{p.get('status', '')}")
        if not plans:
            print("  （沒有進行中的計畫）")
        for folder in plans:
            any_plan = True
            st = plan_state(folder)
            rel = folder.relative_to(ROOT).as_posix()
            print(f"  - {st['title']}（{rel}）")
            if st["status"]:
                print(f"      計畫狀態：{st['status'][:80]}")
            if st["pending"]:
                stage, status, nxt = st["pending"][0]
                print(f"      從這裡接續：{stage[:60]}｜{status[:20]}｜下一步：{nxt[:120] or '（沒寫）'}")
            elif st["rows"]:
                print("      存檔點表的階段都已驗收或不適用；確認後可以結案歸檔")
            else:
                print("      tasks.md 沒有「階段與存檔點」表，或表是空的")
    if not any_plan:
        print("\n沒有進行中的計畫。開新計畫：python scripts/ws.py new plan <專案> <英文名稱> --title \"標題\"")
    tool_env()


# ---------------- 工具環境 ----------------
BASELINE_PATH = ROOT / "docs" / "harness" / "cadcraft-baseline.json"
VERSION_RE = re.compile(r"cadcraft-cli\s+(\S+)(?:\s+\(([0-9a-f]+)\))?")


def find_cadcraft():
    """cadcraft-cli 的位置：環境變數 CADCRAFT_CLI、標準安裝位置、PATH。找不到回傳 None。"""
    import os
    env = os.environ.get("CADCRAFT_CLI")
    if env:
        return env if Path(env).is_file() else None
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
        for name in ("cadcraft-cli.exe", "cadcraft-cli"):
            if base and (Path(base) / "ArtCraft" / "CADCraft" / name).is_file():
                return str(Path(base) / "ArtCraft" / "CADCraft" / name)
    return shutil.which("cadcraft-cli")


def measure_cadcraft():
    """實測這台電腦的 cadcraft-cli：{"version", "commit"}；沒裝或量不到回傳 None。"""
    exe = find_cadcraft()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = VERSION_RE.search(r.stdout or "")
    return {"version": m.group(1), "commit": m.group(2) or ""} if m else None


def tool_env():
    """量這台電腦的 CADCraft 版本，和基準版本比；實測值只寫在本機的 .runtime/（不進 git）。不擋工作。"""
    import platform
    try:
        base = json.loads(BASELINE_PATH.read_text(encoding="utf-8")) if BASELINE_PATH.is_file() else {}
    except ValueError:
        base = {}
    got = measure_cadcraft()
    host = re.sub(r"[^A-Za-z0-9_.-]", "_", platform.node() or "unknown")
    try:
        folder = ROOT / ".runtime" / "environment"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{host}.json").write_text(json.dumps(
            {"measured": datetime.datetime.now().isoformat(timespec="seconds"), "cadcraft-cli": got,
             "baseline": base.get("version")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    want = base.get("version")
    print("\n== 工具環境（這台電腦）")
    if not got:
        print(f"  CADCraft CLI：沒有裝或量不到；基準版本 {want or '還沒訂'}")
    elif not want:
        print(f"  CADCraft CLI {got['version']}；還沒訂基準版本：python scripts/cadcraft_smoke.py --set-baseline")
    elif got["version"] == want and (not base.get("commit") or not got["commit"] or got["commit"] == base["commit"]):
        print(f"  CADCraft CLI {got['version']}，和基準版本相同（{base.get('verified', '')} 驗證）")
    else:
        print(f"  提醒：CADCraft CLI 是 {got['version']}，基準版本是 {want}。")
        print("        兩台電腦裝同一版；要換基準就先跑 python scripts/cadcraft_smoke.py，通過後加 --set-baseline。")
        print("        版本不同時，技能 mcp-002「已知的工具行為」和既有腳本的結果要重新查證。")


# ---------------- check ----------------
def git_ignored(paths):
    """回傳被 .gitignore 排除的路徑集合（相對於 ROOT 的字串）。"""
    if not paths:
        return set()
    try:
        # 用 bytes 傳：文字模式在 Windows 會把 \n 轉成 \r\n，git 就只認得最後一筆
        p = subprocess.run(["git", "-c", "core.quotepath=false", "check-ignore", "--stdin"], cwd=ROOT,
                           input="\n".join(paths).encode("utf-8"), capture_output=True)
        return set(p.stdout.decode("utf-8", errors="replace").splitlines())
    except OSError:
        return set()


def check_links(errors, notes):
    from urllib.parse import unquote
    roots = [ROOT / "docs", ROOT / "README.md", ROOT / "AGENTS.md", ROOT / ".claude", skills_root(config())]
    files = []
    for r in roots:
        files += [r] if r.is_file() else sorted(r.rglob("*.md")) if r.exists() else []
    broken = []
    for f in files:
        if ".claude/skills" in f.as_posix():
            continue  # 技能的副本；連結在主版本 skills/ 檢查
        text = FENCE.sub("", f.read_text(encoding="utf-8", errors="ignore"))
        for target in LINK.findall(text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = (f.parent / unquote(target.split("#")[0])).resolve()
            if not path.exists():
                try:
                    rel = path.relative_to(ROOT).as_posix()
                except ValueError:
                    rel = str(path)
                broken.append((f.relative_to(ROOT).as_posix(), target, rel))
    ignored = git_ignored([b[2] for b in broken])
    for src, target, rel in broken:
        if rel in ignored:
            notes.append(f"{src} → {target}（案件資料不進 git，只在本機）")
        else:
            errors.append(f"{src}：連結不存在 {target}")


def cmd_check(args):
    cfg = config()
    errors, warnings, notes = [], [], []
    harness = ROOT / cfg["harness"]["path"]
    for name in ("DEVELOPMENT.md", "TESTING.md", "README.md", "CHANGELOG.md", "FEEDBACK.md"):
        if not (harness / name).exists():
            errors.append(f"{cfg['harness']['path']}/{name} 不存在")
    m = re.search(r"^## (\d+\.\d+\.\d+)", (harness / "CHANGELOG.md").read_text(encoding="utf-8"), re.M) \
        if (harness / "CHANGELOG.md").exists() else None
    if m and m.group(1) != cfg["harness"].get("version"):
        errors.append(f"docs/harness/CHANGELOG.md 最上面的版本 {m.group(1)} 和 workspace.json 的 {cfg['harness'].get('version')} 不同")
    for mode, spec in cfg["modes"].items():
        for d in spec.get("docs", []):
            if not (harness / d).is_dir():
                errors.append(f"模式 {mode} 的規則資料夾 {cfg['harness']['path']}/{d} 不存在")

    sroot = skills_root(cfg)
    if not sroot.is_dir():
        errors.append(f"技能區 {cfg.get('skills', {}).get('path', 'skills')} 不存在")
    else:
        for folder in sorted(p for p in sroot.iterdir() if p.is_dir()):
            if not (folder / "SKILL.md").is_file():
                errors.append(f"{folder.relative_to(ROOT).as_posix()}：缺少 SKILL.md")
            elif skill_version(folder) is None:
                errors.append(f"{folder.relative_to(ROOT).as_posix()}/SKILL.md：檔頭沒有 version")

    ids = [p["id"] for p in cfg["projects"]]
    if len(ids) != len(set(ids)):
        errors.append("workspace.json 的專案代號重複")
    declared = set(ids)
    for folder in sorted((ROOT / "docs" / "projects").glob("*/")):
        if folder.name not in declared:
            errors.append(f"docs/projects/{folder.name} 沒有登記在 workspace.json")
    for folder in sorted((ROOT / "work").glob("*/")):
        if folder.name not in declared:
            check_work(cfg, folder.name, errors, warnings)
            out_dir = folder / "output"
            if out_dir.is_dir() and any(f.is_file() for f in out_dir.rglob("*")):
                warnings.append(f"work/{folder.name} 是僅工作資料夾專案，但 output/ 已經有交付：改成已登記專案（python scripts/ws.py new project <小寫代號> --mode <模式> --title \"標題\"），做法見 DEVELOPMENT 的「僅工作資料夾專案什麼時候要登記」")
            else:
                notes.append(f"work/{folder.name} 是僅工作資料夾專案：不要求登記 workspace.json 或建立 docs/projects/{folder.name}/")
    installed = {p.name for p in (ROOT / ".claude" / "skills").glob("*/")} | \
                {p.name for p in (ROOT / ".agents" / "skills").glob("*/")}
    for p in cfg["projects"]:
        pid = p["id"]
        docs, work = project_dirs(pid)
        if not ID_RE.fullmatch(pid):
            errors.append(f"專案代號 {pid} 只能用英文小寫、數字和連字號")
        for mode in p.get("modes", []):
            if mode not in cfg["modes"]:
                errors.append(f"{pid}：模式 {mode} 不在 workspace.json 的 modes")
        if not docs.is_dir():
            errors.append(f"{pid}：docs/projects/{pid}/ 不存在")
            continue
        for name in PROJECT_FILES:
            if not (docs / name).exists():
                errors.append(f"{pid}：缺少 docs/projects/{pid}/{name}")
        for name in OLD_PROJECT_FILES:
            if (docs / name).exists():
                errors.append(f"{pid}：docs/projects/{pid}/{name} 是舊的文件，內容併進 PROJECT 或 LOG 後刪掉")
        scripts = [f for f in (work / "working").rglob("*") if f.suffix in (".py", ".ps1", ".js", ".ts", ".tsx", ".mjs")
                   and "node_modules" not in f.parts] if (work / "working").is_dir() else []
        for f in [docs / n for n in PROJECT_FILES] + scripts:
            if f.is_file():
                bad = [i for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                       if DRIVE.search(line) and "environ" not in line and "Program Files" not in line]
                if bad:
                    warnings.append(f"{f.relative_to(ROOT).as_posix()}：第 {bad[0]} 行等 {len(bad)} 處寫了磁碟代號，改成相對於 repo 根目錄的路徑")
        if not work.is_dir():
            errors.append(f"{pid}：work/{pid}/ 不存在")
        else:
            check_work(cfg, pid, errors, warnings)
        for s in p.get("skills", []):
            if s not in installed:
                warnings.append(f"{pid}：用到的技能 {s} 沒有安裝在 .claude/skills/ 或 .agents/skills/")
        for archived in (False, True):
            for folder in plans_of(pid, archived):
                rel = folder.relative_to(ROOT).as_posix()
                for name in PLAN_FILES:
                    if not (folder / name).exists():
                        errors.append(f"{rel}：計畫缺少 {name}")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-.+", folder.name):
                    errors.append(f"{rel}：計畫資料夾要寫成 YYYY-MM-DD-名稱")
                if not archived and (folder / "plan.md").exists():
                    st = plan_state(folder)
                    if re.match(r"^(完成|已完成|取消|已取消|已結案)", st["status"]) and "待" not in st["status"]:
                        warnings.append(f"{rel}：計畫已結束（{st['status'][:20]}），移到 plans/archive/")
    roles = ROOT / cfg["harness"]["path"] / "roles"
    for f in sorted((ROOT / ".claude" / "agents").glob("*.md")):
        if not (roles / f.name).exists():
            errors.append(f".claude/agents/{f.name} 沒有對應的 {cfg['harness']['path']}/roles/{f.name}；角色的內容寫在 roles，兩個工具共用")
    check_links(errors, notes)
    skill_report(cfg, warnings, quiet=True)
    infos = []
    check_parity(errors, warnings, infos)

    print(f"工作架構：{len(cfg['projects'])} 個專案，{len([f for f in sroot.glob('*/SKILL.md') if not f.parent.name.startswith('_')])} 個技能（{cfg.get('skills', {}).get('path', 'skills')}），"
          f"流程規則 {cfg['harness'].get('version')}")
    for e in errors:
        print(f"  錯誤：{e}")
    for w in warnings:
        print(f"  提醒：{w}")
    for i in infos:
        print(f"  說明：{i}")
    if notes:
        print(f"  只在本機的檔案（{len(notes)} 個連結，不算錯誤）：")
        for n in notes[:8]:
            print(f"    - {n}")
    code = 1 if errors else 0
    print(f"\n共 {len(errors)} 個錯誤，{len(warnings)} 個提醒")
    sys.exit(code)


# ---------------- Claude 和 Codex 一致 ----------------
SKILL_DIRS = {"Claude Code": ROOT / ".claude" / "skills", "Codex": ROOT / ".agents" / "skills"}
CLAUDE_ALLOWED = {"settings.json", "settings.local.json", "skills", "agents"}
AGENTS_ALLOWED = {"skills"}


def tree(folder):
    import hashlib
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and p.name != MARK and "__pycache__" not in p.parts}


def check_parity(errors, warnings, infos):
    """Claude Code 和 Codex 要讀到一樣的規則和技能。

    - 規則只寫在 AGENTS.md 和 docs/：CLAUDE.md 只能引用 AGENTS.md；.claude/ 不能有 rules/ 這類只有 Claude 讀得到的規則
    - 兩邊的技能清單相同，每個技能的檔案逐一相同，安裝的模式和 profile 相同
    """
    claude_md = ROOT / "CLAUDE.md"
    if not claude_md.exists() or "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
        errors.append("CLAUDE.md 要引用 @AGENTS.md，讓 Claude Code 和 Codex 讀同一份入口")
    else:
        body = [l for l in claude_md.read_text(encoding="utf-8").splitlines() if l.strip() and l.strip() != "@AGENTS.md"]
        if any(l.lstrip().startswith(("-", "#", "|", "1.")) for l in body) or len(body) > 3:
            errors.append("CLAUDE.md 只能引用 AGENTS.md 和一句說明；規則寫在 AGENTS.md 或 docs/，Codex 才讀得到")
    for base, allowed, who in ((ROOT / ".claude", CLAUDE_ALLOWED, "Claude Code"), (ROOT / ".agents", AGENTS_ALLOWED, "Codex")):
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name not in allowed:
                errors.append(f"{entry.relative_to(ROOT).as_posix()}：只有 {who} 讀得到；規則寫進 AGENTS.md 或 docs/harness/")
    if (ROOT / ".claude" / "agents").is_dir():
        roles = sorted(p.stem for p in (ROOT / ".claude" / "agents").glob("*.md") if p.name != "README.md")
        if roles:
            infos.append(f"角色（{'、'.join(roles)}）的內容在 docs/harness/roles/，兩個工具共用；.claude/agents/ 只是 Claude Code 的委派入口")
    found = {who: {p.name for p in d.glob("*/") if p.is_dir()} if d.is_dir() else set() for who, d in SKILL_DIRS.items()}
    names = sorted(set().union(*found.values()))
    for name in names:
        missing = [who for who, s in found.items() if name not in s]
        if missing:
            errors.append(f"技能 {name} 只裝在一邊，{'、'.join(missing)} 沒有；用 python scripts/ws.py install {name} 兩邊一起裝")
            continue
        a, b = (SKILL_DIRS[w] / name for w in SKILL_DIRS)
        if tree(a) != tree(b):
            diff = sorted(set(tree(a).items()) ^ set(tree(b).items()))
            errors.append(f"技能 {name} 兩邊的檔案不同（例如 {diff[0][0]}）；改過的內容先寫回 skills/{name}/，再 ws.py install {name}")
        marks = [json.loads((d / MARK).read_text(encoding="utf-8")) if (d / MARK).exists() else {} for d in (a, b)]
        keys = ("version", "mode", "profile")
        if [tuple(m.get(k) for k in keys) for m in marks][0] != [tuple(m.get(k) for k in keys) for m in marks][1]:
            errors.append(f"技能 {name} 兩邊安裝的版本或 profile 不同")


# ---------------- install ----------------
MARK = ".skill-source"          # 安裝紀錄：版本、profile、每個檔案的 SHA256
SKIP_INSTALL = {"profiles", "profile.example", "__pycache__"}


def skill_version(folder):
    """SKILL.md 檔頭的 version；沒有回傳 None。"""
    f = folder / "SKILL.md"
    if not f.is_file():
        return None
    head = f.read_text(encoding="utf-8").split("\n---", 1)[0]
    m = re.search(r"^\s*version:\s*(\S+)", head, re.M)
    return m.group(1).strip("\"'") if m else None


def files_of(folder):
    import hashlib
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and p.name != MARK and "__pycache__" not in p.parts}


def install_one(cfg, sid, profile, force):
    src = skills_root(cfg) / sid
    if not (src / "SKILL.md").is_file():
        have = sorted(p.parent.name for p in skills_root(cfg).glob("*/SKILL.md"))
        sys.exit(f"沒有技能 {sid}。有：{'、'.join(have)}")
    if profile and not (src / "profiles" / profile).is_dir():
        have = sorted(p.name for p in (src / "profiles").glob("*/")) if (src / "profiles").is_dir() else []
        sys.exit(f"技能 {sid} 沒有 profiles/{profile}。有：{'、'.join(have) or '（沒有；照 profile.example/ 建一份）'}")
    for target in SKILL_DIRS.values():
        dest = target / sid
        if dest.exists() and not force and (dest / MARK).exists():
            old = json.loads((dest / MARK).read_text(encoding="utf-8"))
            if files_of(dest) != old.get("files", {}):
                sys.exit(f"{dest.relative_to(ROOT).as_posix()} 安裝後被改過；先把要留的內容寫回 skills/{sid}/，再加 --force 重裝")
    version = skill_version(src)
    for target in SKILL_DIRS.values():
        dest = target / sid
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=lambda d, names: [n for n in names if n in SKIP_INSTALL
                                                            and Path(d) == src or n == "__pycache__"])
        if profile:
            shutil.copytree(src / "profiles" / profile, dest / "profile")
        (dest / MARK).write_text(json.dumps({"skill": sid, "version": version, "profile": profile or "",
                                             "installed": datetime.date.today().isoformat(),
                                             "files": files_of(dest)}, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(f"已安裝 {sid} {version}{'（profile ' + profile + '）' if profile else ''}：.claude/skills/{sid}/、.agents/skills/{sid}/")


def cmd_install(args):
    if not args or args[0].startswith("--") and args[0] != "--all":
        sys.exit("用法：ws.py install <代號>|--all [--profile <專案>] [--force]")
    cfg = config()
    profile = option(args, "--profile")
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    if args[0] == "--all":
        if profile:
            sys.exit("--all 不能和 --profile 一起用")
        for f in sorted(skills_root(cfg).glob("*/SKILL.md")):
            if f.parent.name.startswith("_"):
                continue  # _template 是範本，不安裝
            install_one(cfg, f.parent.name, None, force)
    else:
        install_one(cfg, args[0], profile, force)


# ---------------- skills ----------------
def skill_report(cfg, warnings, quiet=False):
    rows = []
    for base in SKILL_DIRS.values():
        for folder in sorted(base.glob("*/")):
            rel = folder.relative_to(ROOT).as_posix()
            mark = folder / MARK
            if not mark.exists():
                rows.append((rel, "", "", "不是用 ws.py install 安裝的"))
                warnings.append(f"{rel} 沒有安裝紀錄；用 python scripts/ws.py install {folder.name} --force 重裝")
                continue
            info = json.loads(mark.read_text(encoding="utf-8"))
            src = skills_root(cfg) / folder.name
            state = []
            if files_of(folder) != info.get("files", {}):
                state.append("安裝後改過")
                warnings.append(f"{rel} 安裝後改過：要留的內容寫回 skills/{folder.name}/，再 ws.py install {folder.name} --force")
            if not src.is_dir():
                state.append("主版本不存在")
                warnings.append(f"{rel} 在 skills/ 沒有主版本")
            else:
                current = skill_version(src)
                expect = {k: v for k, v in files_of(src).items() if k.split("/")[0] not in SKIP_INSTALL}
                got = {k: v for k, v in info.get("files", {}).items() if k.split("/")[0] != "profile"}
                if current != info.get("version") or expect != got:
                    state.append(f"主版本已更新（{current}）")
                    warnings.append(f"{rel}（{info.get('version')}）和主版本 skills/{folder.name}/（{current}）的內容不同；ws.py install {folder.name}")
            rows.append((rel, info.get("version", ""), info.get("profile", ""), "、".join(state) or "和主版本一致"))
    if not quiet:
        for rel, ver, prof, state in rows:
            print(f"{rel:48} {ver or '':8} {prof:16} {state}")
    return rows


def cmd_skills(args):
    skill_report(config(), [], quiet=False)
    print("\n安裝或更新：python scripts/ws.py install <代號> [--profile <專案>]（或 --all），Claude 和 Codex 兩邊同時寫入")


def new_skill(cfg, sid):
    if not ID_RE.fullmatch(sid):
        sys.exit("技能代號只能用英文小寫、數字和連字號，例如 rhino-004-roof-panels")
    dest = skills_root(cfg) / sid
    if dest.exists():
        sys.exit(f"skills/{sid}/ 已經存在")
    tpl = skills_root(cfg) / "_template"
    if not tpl.is_dir():
        sys.exit("沒有範本 skills/_template/")
    shutil.copytree(tpl, dest)
    for f in dest.rglob("*.md"):
        f.write_text(f.read_text(encoding="utf-8").replace("<代號>", sid)
                     .replace("<日期>", datetime.date.today().isoformat()), encoding="utf-8")
    print(f"已建立 skills/{sid}/。寫好 SKILL.md、tests.md 後用 python scripts/ws.py install {sid} 安裝到兩邊。")


# ---------------- new ----------------
def cmd_new(args):
    if len(args) < 2 or args[0] not in ("project", "plan", "skill"):
        sys.exit(__doc__)
    what = args.pop(0)
    cfg = config()
    if what == "skill":
        return new_skill(cfg, args[0])
    today = datetime.date.today().isoformat()
    title = option(args, "--title")
    if what == "plan":
        if len(args) < 2:
            sys.exit("用法：ws.py new plan <專案> <英文名稱> [--title 標題]")
        pid, name = args[0], args[1]
        if pid not in {p["id"] for p in cfg["projects"]}:
            sys.exit(f"沒有專案 {pid}。有：{'、'.join(p['id'] for p in cfg['projects'])}")
        if not ID_RE.fullmatch(name):
            sys.exit("計畫名稱只能用英文小寫、數字和連字號，例如 roof-plan")
        base = project_dirs(pid)[0] / "plans"
        dest, n = base / f"{today}-{name}", 2
        while dest.exists():
            dest, n = base / f"{today}-{name}-{n}", n + 1
        dest.mkdir(parents=True)
        tpl = ROOT / cfg["harness"]["path"] / "templates"
        for f in PLAN_FILES:
            text = (tpl / f).read_text(encoding="utf-8")
            if f == "plan.md":
                text = text.replace("建立日期：待填（建立實際計畫時必填）", f"建立日期：{today}", 1)
                if title:
                    text = re.sub(r"^# .*$", f"# {title}", text, count=1, flags=re.M)
            (dest / f).write_text(text, encoding="utf-8")
        print(f"已建立 {dest.relative_to(ROOT).as_posix()}/。先寫 plan 和 specs，再開始做；每個階段結束或要停時更新 tasks 的存檔點表。")
        return
    pid = args[0]
    modes = (option(args, "--mode") or "general").split(",")
    if not ID_RE.fullmatch(pid):
        sys.exit("專案代號只能用英文小寫、數字和連字號")
    if pid in {p["id"] for p in cfg["projects"]}:
        sys.exit(f"專案 {pid} 已經存在")
    bad = [m for m in modes if m not in cfg["modes"]]
    if bad:
        sys.exit(f"沒有模式 {'、'.join(bad)}。有：{'、'.join(cfg['modes'])}")
    docs, work = project_dirs(pid)
    title = title or pid
    rules = "、".join(f"[{d}](../../harness/{d}/)" for m in modes for d in cfg["modes"][m]["docs"]) or "只用共用規則"
    files = {
        "README.md": f"# {title}\n\n專案 `{pid}` 的文件入口。模式：{'、'.join(modes)}。\n\n| 文件 | 內容 |\n|---|---|\n"
                     f"| [PROJECT](PROJECT.md) | 專案的事實、成果和狀態、待確認事項（唯一來源） |\n| [LOG](LOG.md) | 未解決的項目、交付紀錄、照日期寫的變更和問題 |\n"
                     f"| [plans/](plans/) | 計畫；結束後移到 plans/archive/ |\n\n檔案在 `work/{pid}/`：`raw/<類型>/` 輸入（唯讀）、`working/<日期_內容>/<類型>/` 儲存、`output/<日期_內容>/` 輸出（例如 `20261117_木結構圖繪製`）。文件和腳本裡的路徑都相對於 repo 根目錄。\n\n共用規則：[DEVELOPMENT](../../harness/DEVELOPMENT.md)、[TESTING](../../harness/TESTING.md)；"
                     f"模式的規則：{rules}。\n",
        "PROJECT.md": f"# 專案資料：{title}\n\n這是專案事實的唯一來源。待確認不是預設值；只在影響這次工作時補問。\n\n| 項目 | 目前值 | 來源／確認方式 |\n|---|---|---|\n"
                      f"| 專案代號 | {pid} | 建立時 |\n| 模式 | {'、'.join(modes)} | 建立時 |\n| 目標 | 待確認 | 首次需求 |\n| 範圍與不包含 | 待確認 | 首次需求 |\n"
                      f"| 最終交付與驗收人 | 待確認 | 建立規格時 |\n| 軟體與版本 | 待確認 | 連線後查證 |\n| 工作目錄 | work/{pid}/ | 工作架構 |\n"
                      f"| 案件資料是否進 git | 待確認 | 第一次加入案件檔案前詢問使用者 |\n| 技能的專案 profile | 待確認 | 用到需要 profile 的技能時建立 |\n\n"
                      f"## 待確認事項\n\n| ID | 問題 | 影響的工作 | 何時必須確認 | 狀態 |\n|---|---|---|---|---|\n| Q-001 | 目標與交付要求 | 建立規格 | 第一個計畫開始前 | 待確認 |\n\n"
                      f"## 成果\n\n狀態：未開始、執行中、待審查、已接受、已取消。\n\n| ID | 名稱 | 狀態 | 來源與證據 | 已知問題 |\n|---|---|---|---|---|\n",
        "LOG.md": f"# 紀錄：{title}\n\n變更、交付、問題都記在這一份，照日期往下寫。規則見共用的 [DEVELOPMENT](../../harness/DEVELOPMENT.md)。\n\n## 未解決\n\n目前沒有。\n\n| ID | 項目 |\n|---|---|\n\n## 交付\n\n目前沒有交付紀錄。\n\n| 成果 ID | 來源版本 | 產物與版本 | 日期 | 驗收證據 | 驗收人 | 狀態／限制 |\n|---|---|---|---|---|---|---|\n\n## 日期紀錄\n\n每筆開頭標 [變更]、[交付] 或 [問題]。問題要寫現象、原因、怎麼處理、驗證結果。\n\n## {today}\n\n- [變更] 建立專案。\n",
    }
    for name, text in files.items():
        (docs / name).parent.mkdir(parents=True, exist_ok=True)
        (docs / name).write_text(text, encoding="utf-8")
    for d in ("plans", "plans/archive"):
        (docs / d).mkdir(parents=True, exist_ok=True)
        (docs / d / ".gitkeep").touch()
    for d in LAYERS:
        (work / d).mkdir(parents=True, exist_ok=True)
        (work / d / ".gitkeep").touch()
    cfg["projects"].append({"id": pid, "title": title, "modes": modes, "status": "進行中", "skills": []})
    save_config(cfg)
    print(f"已建立專案 {pid}：docs/projects/{pid}/、work/{pid}/，並登記到 workspace.json。先填 PROJECT.md，再開第一個計畫。")


def cmd_file(args):
    """把檔案放進 work/<專案>/raw/<類型>/（或 working/），依副檔名決定類型，印出 SHA256。"""
    import hashlib
    cfg = config()
    to = option(args, "--to", "raw")
    sub = option(args, "--sub")
    move = "--move" in args
    args = [a for a in args if a != "--move"]
    if len(args) < 2:
        sys.exit("用法：ws.py file <專案> <檔案...> [--to raw|working] [--sub 子資料夾] [--move]")
    pid, files = args[0], args[1:]
    folder_only = (ROOT / "work" / pid / "raw").is_dir() and not (Path(pid).is_absolute() or ".." in Path(pid).parts)
    if pid not in {p["id"] for p in cfg["projects"]} and not folder_only:
        sys.exit(f"沒有專案 {pid}，也沒有 work/{pid}/raw/。已登記的有：{'、'.join(p['id'] for p in cfg['projects'])}")
    if to not in ("raw", "working"):
        sys.exit("--to 只能是 raw 或 working；輸出由 agent 直接寫進 output/<交付名稱>/")
    if sub and (Path(sub).is_absolute() or ".." in Path(sub).parts):
        sys.exit("--sub 只能是相對的子資料夾名稱")
    if to == "working" and not (sub and BATCH_RE.match(Path(sub).parts[0])):
        sys.exit("--to working 要用 --sub 指定「日期_內容」資料夾，例如 --sub 20261117_木結構圖繪製")
    work = project_dirs(pid)[1]
    for f in files:
        src = Path(f).expanduser()
        if not src.is_file():
            print(f"略過（不是檔案）：{f}")
            continue
        if to == "working":  # working/<日期_內容>/<類型>/<其餘子資料夾>
            first, *rest = Path(sub).parts
            dest_dir = work / to / first / type_of(src, cfg) / Path(*rest) if rest else work / to / first / type_of(src, cfg)
        else:
            dest_dir = work / to / type_of(src, cfg) / (sub or "")
        dest = dest_dir / src.name
        if dest.exists():
            same = hashlib.sha256(dest.read_bytes()).hexdigest() == hashlib.sha256(src.read_bytes()).hexdigest()
            print(f"{'已經有相同的檔案' if same else '已經有同名但內容不同的檔案，沒有覆寫'}：{dest.relative_to(ROOT).as_posix()}")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        (shutil.move if move else shutil.copy2)(str(src), dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        ignored = bool(git_ignored([dest.relative_to(ROOT).as_posix()]))
        print(f"{dest.relative_to(ROOT).as_posix()}｜sha256 {digest}｜{'不進 git' if ignored else '會進 git（如果這是案件資料，先問要不要進 git）'}")


MEM_RESERVE_GB = 2.0      # 留給使用者和系統的記憶體，不拿來跑工作


def _top_processes(n=5):
    """Windows：用 tasklist 取記憶體用量最大的幾個程序（名稱、PID、GB）。"""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, timeout=20).stdout
        text = out.decode("mbcs", errors="replace") if sys.platform == "win32" else out.decode(errors="replace")
    except Exception:
        return []
    rows = []
    for line in text.splitlines():
        cells = [c.strip('"') for c in line.split('","')]
        if len(cells) >= 5:
            kb = re.sub(r"[^0-9]", "", cells[4])
            if kb and cells[1].isdigit():
                rows.append((cells[0], int(cells[1]), round(int(kb) / 1024 / 1024, 2)))
    return sorted(rows, key=lambda r: -r[2])[:n]


def _memory_status():
    """回傳 (實體可用 GB, 實體總量 GB, 可分配 GB)；判斷不了回傳 None。"""
    if sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = MS(); ms.dwLength = ctypes.sizeof(MS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return None
        g = 1024 ** 3
        return ms.ullAvailPhys / g, ms.ullTotalPhys / g, ms.ullAvailPageFile / g
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        v = {}
        for line in meminfo.read_text().splitlines():
            k, _, rest = line.partition(":")
            v[k] = int(rest.split()[0]) / 1024 / 1024
        commit = v.get("CommitLimit", 0) - v.get("Committed_AS", 0)
        return v.get("MemAvailable", 0), v.get("MemTotal", 0), max(commit, 0)
    return None


def cmd_mem(args):
    """記憶體夠不夠：ws.py mem [--need GB]。
    夠（實體可用和可分配都 ≥ 需要量＋保留 2 GB）退出碼 0；不夠 2；判斷不了 3。
    不夠或判斷不了時停止，告訴使用者數字和佔用最多的程序，不強制執行。"""
    need = 0.0
    if "--need" in args:
        need = float(args[args.index("--need") + 1])
    st = _memory_status()
    if st is None:
        print("無法判斷記憶體（這個系統沒有支援的查詢方式）：先問使用者再執行大型工作。")
        sys.exit(3)
    avail, total, commit = st
    want = need + MEM_RESERVE_GB
    ok = avail >= want and commit >= want
    print(f"實體記憶體：可用 {avail:.1f} GB／總共 {total:.1f} GB；可分配（含分頁檔）{commit:.1f} GB")
    print(f"這次需要 {need:.1f} GB＋保留 {MEM_RESERVE_GB:.0f} GB = {want:.1f} GB → {'夠' if ok else '不夠'}")
    if not ok:
        print("佔用最多的程序：")
        for name, pid, gb in _top_processes():
            print(f"  {name}（PID {pid}）{gb:.2f} GB")
        print("停止：告訴使用者以上數字，等使用者釋放記憶體或決定怎麼做；不強制執行、不自行結束別人的程序。")
        sys.exit(2)


COMMANDS = {"status": cmd_status, "file": cmd_file, "install": cmd_install, "check": cmd_check, "new": cmd_new, "skills": cmd_skills, "mem": cmd_mem}


def main():
    args = sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
