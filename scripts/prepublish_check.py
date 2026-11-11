# -*- coding: utf-8 -*-
"""发布前隐私自检：证明「个人数据不会上传」。

设计原则
--------
1. 不依赖 git 仓库：当前项目有意不执行 git init / commit / push，
   所以自带一个轻量 .gitignore 解释器，模拟 `git add -A` 的跟踪集合。
   若恰好已是 git 仓库，会用只读的 `git ls-files` 交叉核对。
2. 不写任何文件，全程只读。
3. 敏感字面量一律用 Unicode 转义 / 字符串拼接构造，
   避免检查器自身被自己的规则命中（自指悖论）。
4. 本地存在 data/ 时，把真实书单当作「指纹库」反向比对所有待提交文件；
   公开仓库 clone 里没有 data/，自动降级为结构检查并给出提示。

用法
----
    python scripts/prepublish_check.py            # 普通模式
    python scripts/prepublish_check.py --strict  # 任一 ERROR 即 exit 1
    python scripts/prepublish_check.py --list    # 顺带打印完整待提交清单
"""
from __future__ import annotations

import fnmatch
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRICT = "--strict" in sys.argv
SHOW_LIST = "--list" in sys.argv

# --------------------------------------------------------------------------
# 敏感特征（全部转义构造，禁止在本文件出现明文）
# --------------------------------------------------------------------------
BOOKS_MERGED = os.path.join(ROOT, "data", "books" + ".merged.json")
CONFIG_LOCAL = os.path.join(ROOT, "config" + ".local.json")
DEMO_JSON = os.path.join(ROOT, "scripts", "demo_library.json")
PUBLIC_HTML = os.path.join(ROOT, "docs", "index.html")

# 内容里出现即视为硬泄漏的特征（书库身份 / 私有目录名）
BAD_LITERALS = [
    ("书库目录特殊字符", "\u2764"),
    ("真实书库目录名", "13\u4e66\u5e93"),
    ("私人二级目录名", "\u5f85\u7406"),
    ("私人导出目录名", "kindle mobi\u7535\u5b50\u4e66"),
]

# 已知公开示例书目（gen_demo.py 抓取的 30 本名著）。
# 这些书名同时可能出现在用户私人书库里（名著谁都有），但它们是公开知识，
# 发布它们不构成隐私泄露；指纹交叉比对时跳过，避免把「demo 含名著」误判成泄露。
# 注意：此处为「硬编码策展清单」，不从 demo_library.json 反读——若有人往 demo 里
# 塞入用户私书，该书名不在本清单内，仍会被指纹检查抓住。
KNOWN_DEMO_TITLES = {
    "红楼梦", "百年孤独", "一九八四", "活着", "围城", "老人与海", "傲慢与偏见",
    "骆驼祥子", "万历十五年", "明朝那些事儿", "人类简史", "资治通鉴", "时间简史",
    "自私的基因", "未来简史", "上帝掷骰子吗", "穷查理宝典", "经济学原理", "小狗钱钱",
    "乌合之众", "看见", "苏菲的世界", "沉思录", "艺术的故事", "设计中的设计",
    "自卑与超越", "史蒂夫·乔布斯传", "小王子", "芥子园画传", "营造法式",
    "上帝掷骰子吗？",   # 豆瓣书名带全角问号，与无问号版均列入白名单
}

# 绝对路径 / 本机用户名 / 用户目录。
# 盘符规则用 lookbehind + (?!/) 排除 https:// / http:// / file:// 这类协议串，
# 否则源码里每个 URL 都会被误判成本机路径。
BAD_REGEX = [
    ("盘符绝对路径", re.compile(r"(?<![A-Za-z0-9+.\-])[A-Za-z]:[\\/](?!/)")),
    ("本机 Users 路径", re.compile(r"(?i)(?:[/\\]|\b)Users[/\\][A-Za-z0-9._-]+[/\\]")),
    ("Windows UNC 路径", re.compile(r"^\\\\|[\"']\\\\\\\\[A-Za-z0-9]")),
]

# 个人信息字段带「非空值」才报警；只在 .json 数据文件里查，
# 避免把 build_html.py 白名单断言里的字段名字面量误判成真实数据。
PII_REGEX = [
    ("我的评分含实际值", re.compile('"my' + '_rating"\\s*:\\s*(?!0|null|false|""|\\{\\}|\\[\\])')),
    ("我的评分(旧键)含实际值", re.compile('"my' + '_rate"\\s*:\\s*(?!0|null|false|""|\\{\\}|\\[\\])')),
    ("阅读进度含实际值", re.compile('"page' + '_read"\\s*:\\s*(?!0|null|false|""|\\{\\}|\\[\\])')),
    ("笔记索引含实际值", re.compile('"note' + 'Index"\\s*:\\s*(?!null|false|""|\\{\\}|\\[\\])')),
    ("状态导出含实际值", re.compile('"mine' + '_rating"\\s*:\\s*(?!0|null|false|""|\\{\\}|\\[\\])')),
]

# 备份 / 恢复产物只走路径黑名单与 PII 内容检查；
# 文件名常量出现在 .gitignore、recover_state.py 里属于工具定义，不算数据。
BACKUP_STATE_KEYS = ["ebooklib_library" + "_state_v3", '"hidden"', '"notes"']

# 路径黑名单：命中即 ERROR（相对仓库根目录，正斜杠）
PATH_BLOCK_DIRS = ("data/", "reports/", "_compare_tmp/", ".workbuddy/",
                   ".git/", "__pycache__/", ".venv/", ".idea/", ".vscode/")
PATH_BLOCK_EXACT = {
    "config.local.json", "config.json", "skmap.json", "library_final.json",
    "books.raw.json", "books.merged.json", "books.json", "snapshot.json",
    "douban_cache.json", "douban_enriched.json", "overrides.json",
    "overrides_by_id.json", "famous_authors.txt",
}
PATH_BLOCK_GLOBS = [
    "*.html",            # 根目录成品 HTML（docs/ 下的例外由白名单处理）
    "*.py[cod]",
    "我的书库数据_*.json",
    "onelines_*.json",
    "*.log",
    "*.bak",
    "*.tmp",
    ".env", ".env.*", ".netrc", ".npmrc", "id_rsa", "id_rsa.pub",
    "*.pem", "*.key", "credentials*.json",
]
# 明确允许出现在公开仓库的 HTML（Pages 页面 / 构建模板，非导出成品）
PATH_ALLOW_HTML = {"docs/index.html", "scripts/app_template.html"}

TEXT_EXT = {".py", ".js", ".json", ".md", ".html", ".bat", ".txt", ".gitignore",
            ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh", ".css", ""}
MAX_TEXT_BYTES = 2 * 1024 * 1024        # 单个文本文件超过 2MB 视为可疑
MAX_TRACKED_BYTES = 8 * 1024 * 1024     # 任何跟踪文件超过 8MB 视为可疑

errors: list[str] = []
warns: list[str] = []
notes: list[str] = []
counts: dict[str, int] = {}


def err(cat: str, msg: str) -> None:
    errors.append("[%s] %s" % (cat, msg))


def warn(cat: str, msg: str) -> None:
    warns.append("[%s] %s" % (cat, msg))


# --------------------------------------------------------------------------
# 轻量 .gitignore 解释器（够覆盖本项目规则，语义对齐 git 的主要行为）
# --------------------------------------------------------------------------
def load_rules():
    p = os.path.join(ROOT, ".gitignore")
    if not os.path.exists(p):
        err("忽略规则", ".gitignore 不存在")
        return []
    rules = []
    with io.open(p, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\r\n").strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            if neg:
                line = line[1:].strip()
            if not line:
                continue
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = line.startswith("/")
            if anchored:
                line = line.lstrip("/")
            # 含斜杠的规则天然锚定到根
            scoped = anchored or ("/" in line)
            rules.append({"neg": neg, "scoped": scoped, "dir_only": dir_only,
                          "pat": line, "raw": raw.rstrip("\r\n")})
    # 内建：git 自身目录永远不跟踪
    rules.append({"neg": False, "scoped": False, "dir_only": True,
                  "pat": ".git", "raw": "(builtin .git/)"})
    return rules


def _glob_to_re(pat: str) -> "re.Pattern":
    """把 .gitignore 通配符转成正则：`*` 不跨 `/`，`**` 跨层级，与 git 语义一致。"""
    out, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "[":
            j = pat.find("]", i + 1)
            if j > 0:
                out.append(pat[i:j + 1])
                i = j + 1
                continue
        out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


def match_rule(rule, rel: str) -> bool:
    pat, parts = rule["pat"], rel.split("/")
    if rule["scoped"]:
        rx = rule.get("_rx")
        if rx is None:
            rx = rule["_rx"] = _glob_to_re(pat)
        if rx.match(rel):
            return True
        if rule["dir_only"] and rel.rstrip("/") == pat:
            return True
        return rule["dir_only"] and rel.startswith(pat + "/")
    # 无斜杠规则：匹配任意层级的段名
    return any(fnmatch.fnmatchcase(seg, pat) for seg in parts)


def is_ignored(rel: str, rules) -> bool:
    ignored = False
    for rule in rules:
        if match_rule(rule, rel):
            ignored = not rule["neg"]
    return ignored


def simulate_add(rules):
    """返回 (待跟踪文件, 被忽略文件)，均为相对根目录的正斜杠路径。"""
    tracked, ignored = [], []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        keep = []
        for d in sorted(dirnames):
            rel = os.path.relpath(os.path.join(dirpath, d), ROOT).replace("\\", "/")
            if os.path.isdir(os.path.join(dirpath, d, ".git")):
                # 嵌套的独立仓库：git 只记录 gitlink，不跟踪其内部文件
                ignored.append(rel + "/ (嵌套仓库)")
                continue
            if is_ignored(rel + "/", rules) or is_ignored(rel, rules):
                ignored.append(rel + "/")
            else:
                keep.append(d)
        dirnames[:] = keep
        for fn in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fn), ROOT).replace("\\", "/")
            if is_ignored(rel, rules):
                ignored.append(rel)
            else:
                tracked.append(rel)
    return sorted(tracked), sorted(ignored)


def git_crosscheck(tracked):
    """已是 git 仓库时，用只读命令核对模拟结果；不是则跳过。"""
    try:
        probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            notes.append("当前不是 git 仓库，按 .gitignore 模拟跟踪集合（符合「只准备到可发布状态」）")
            return
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false",
             "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            warn("跟踪集合", "git ls-files 执行失败，仅用模拟结果：" + out.stderr.strip()[:120])
            return
        actual = set(x.replace("\\", "/") for x in out.stdout.splitlines() if x)
        simulated = set(tracked)
        extra = sorted(actual - simulated)
        missing = sorted(simulated - actual)
        if extra:
            err("跟踪集合", "git 会跟踪但模拟未发现的文件：" + ", ".join(extra[:8]))
        if missing:
            warn("跟踪集合", "模拟认为会跟踪但 git 排除：" + ", ".join(missing[:8]))
        if not extra and not missing:
            notes.append("git ls-files 交叉核对一致（%d 个文件）" % len(actual))
    except (OSError, subprocess.SubprocessError):
        notes.append("未检测到可用 git 命令，使用内置 .gitignore 解释器")


# --------------------------------------------------------------------------
# 真实书单指纹（只在本地存在时启用）
# --------------------------------------------------------------------------
def real_fingerprints():
    feats = set()
    src = []
    if not os.path.exists(BOOKS_MERGED):
        return feats, src
    try:
        with io.open(BOOKS_MERGED, "r", encoding="utf-8") as f:
            d = json.load(f)
        books = d.get("books") or []
        rootname = str(d.get("source_root_name") or "")
        if len(rootname) >= 2:
            feats.add(rootname)
        for b in books:
            t = str(b.get("title") or "").strip()
            han = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
            # 高辨识度指纹：≥2 个汉字且长度≥6，或长度≥10 的 ASCII 串。
            # 过滤 "2010-1" 这类纯数字短串，它会撞上代码注释里的日期示例。
            if len(t) >= 6 and (han >= 2 or len(t) >= 10) and not t.startswith("示例"):
                feats.add(t)
            rel = str(b.get("rel") or "")
            if len(rel) >= 12:
                feats.add(rel.replace("\\", "/"))
                feats.add(rel)
            for fl in (b.get("files") or []):
                r = str(fl.get("rel") or "")
                if len(r) >= 12:
                    feats.add(r.replace("\\", "/"))
        src.append("books.merged.json (%d 本)" % len(books))
    except (ValueError, OSError, TypeError) as e:
        warn("真实书单指纹", "读取本地书单失败，交叉比对降级：" + str(e)[:100])
    # 本地私有配置里的书库路径 / 目录名
    if os.path.exists(CONFIG_LOCAL):
        try:
            with io.open(CONFIG_LOCAL, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            root = str(cfg.get("source_root") or "")
            if root:
                feats.add(root)
                feats.add(root.replace("\\", "/"))
                tail = re.split(r"[\\/]", root.replace("\\", "/"))[-1]
                if len(tail) >= 2:
                    feats.add(tail)
            name = str(cfg.get("source_name") or "")
            if len(name) >= 2:
                feats.add(name)
            src.append("config.local.json")
        except (ValueError, OSError) as e:
            warn("真实书单指纹", "读取本地配置失败：" + str(e)[:100])
    return feats, src


# --------------------------------------------------------------------------
# 各项检查
# --------------------------------------------------------------------------
def check_ignore_rules(ignored, rules):
    must = ["data/books.merged.json", "data/douban_enriched.json",
            "reports/", "_compare_tmp/", "config.local.json",
            "我的书库.html", "一键恢复.html", "我的书库数据_找回备份.json",
            ".workbuddy/", "scripts/__pycache__/"]
    iset = set(ignored)
    missed = []
    for m in must:
        # 规则级校验：不依赖本机是否真有该文件，只要 .gitignore 规则能拦住它就通过。
        # 这样公开 clone（没有这些私有文件）也能正常跑自检。
        if is_ignored(m, rules):
            continue
        # 兜底：本机确有该文件且已被 ignore 列表收录时也算通过
        if m in iset:
            continue
        missed.append(m)
    counts["忽略规则"] = len(must) - len(missed)
    if missed:
        err("忽略规则", "以下私有路径未被 .gitignore 隔离：" + ", ".join(missed))
    else:
        notes.append("忽略规则自测：%d/%d 条私有路径已隔离" % (len(must), len(must)))
    # 反向：确认 docs/index.html 没被误伤
    if is_ignored("docs/index.html", rules):
        err("忽略规则", "docs/index.html 被忽略，Pages 页面不会发布")


def check_paths(tracked):
    bad = []
    for rel in tracked:
        if any(rel.startswith(d) or ("/" + d) in rel for d in PATH_BLOCK_DIRS):
            bad.append((rel, "位于私有目录"))
            continue
        base = rel.rsplit("/", 1)[-1]
        if rel in PATH_BLOCK_EXACT or base in PATH_BLOCK_EXACT:
            bad.append((rel, "私有数据文件名"))
            continue
        hit = next((g for g in PATH_BLOCK_GLOBS if fnmatch.fnmatchcase(base, g)), None)
        if hit:
            if base.endswith(".html") and rel in PATH_ALLOW_HTML:
                continue
            # 根目录 .html 一律禁止；docs/ 下仅放行 index.html
            if base.endswith(".html") and rel.startswith("docs/") and rel != "docs/index.html":
                continue
            bad.append((rel, "命中黑名单 " + hit))
        size = os.path.getsize(os.path.join(ROOT, rel))
        if size > MAX_TRACKED_BYTES:
            bad.append((rel, "文件过大 %.1fMB，疑似真实书单" % (size / 1048576.0)))
    counts["路径黑名单"] = len(tracked)
    for rel, why in bad[:20]:
        err("路径黑名单", "%s —— %s" % (rel, why))
    if len(bad) > 20:
        err("路径黑名单", "…另有 %d 个文件" % (len(bad) - 20))
    return len(bad)


def read_text(rel):
    p = os.path.join(ROOT, rel)
    ext = os.path.splitext(rel)[1].lower()
    if ext not in TEXT_EXT or os.path.getsize(p) > MAX_TEXT_BYTES:
        return None
    try:
        with io.open(p, "r", encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, OSError):
        return None


# 内置豆瓣评分包 = 豆瓣 Top250 + 二十个大类高分榜，纯公开书目数据。
# 它和本地书单必然有重合（都收名著畅销书），这种重合不是隐私泄漏，
# 交叉比对前整块剔除；但评分包本身另有 check_douban_pack 的字段白名单把关。
_PACK_BLOCK_RE = re.compile(r'<script id="DOUBAN_PACK"[^>]*>.*?</script>', re.S)


def strip_public_pack(text):
    return _PACK_BLOCK_RE.sub('<script id="DOUBAN_PACK"></script>', text)


PACK_PATH = os.path.join(ROOT, "scripts", "douban_pack.json")
PACK_ALLOWED_KEYS = {"t", "a", "r", "v", "i"}


def check_douban_pack():
    """评分包只允许 书名/作者/评分/评价人数/豆瓣id 五个字段，不许夹带私货。"""
    if not os.path.exists(PACK_PATH):
        return
    try:
        with io.open(PACK_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        err("评分包", "无法解析 scripts/douban_pack.json：" + str(e)[:80])
        return
    items = d.get("items") or []
    if not items:
        warn("评分包", "douban_pack.json 里没有条目")
        return
    extra = [k for it in items for k in it if k not in PACK_ALLOWED_KEYS]
    if extra:
        err("评分包", "出现非公开字段：%s" % "、".join(sorted(set(extra))[:6]))
    blob = json.dumps(items, ensure_ascii=False)
    if re.search(r"[A-Za-z]:[\\/](?![\\/])", blob) or "/Users/" in blob or "/home/" in blob:
        err("评分包", "含本地绝对路径")
    if any(len(it.get("t") or "") > 120 for it in items):
        err("评分包", "存在异常超长书名，疑似整段正文混入")
    notes.append("内置评分包 %d 本，字段白名单校验通过" % len(items))


def check_content(tracked, feats):
    hits = []
    scanned = 0
    # 预筛：文本里连特征首 2 字都没有的，跳过
    buckets: dict[str, list[str]] = {}
    for feat in feats:
        buckets.setdefault(feat[:2], []).append(feat)
    for rel in tracked:
        text = read_text(rel)
        if text is None:
            continue
        text = strip_public_pack(text)
        scanned += 1
        for label, lit in BAD_LITERALS:
            if lit in text:
                line = text[:text.index(lit)].count("\n") + 1
                hits.append((rel, line, label))
        for label, rx in BAD_REGEX:
            m = rx.search(text)
            if m:
                line = text[:m.start()].count("\n") + 1
                hits.append((rel, line, label))
        # 个人信息只在 JSON 数据文件里查；源码里的字段名是白名单断言，不是数据
        if rel.lower().endswith(".json"):
            for label, rx in PII_REGEX:
                m = rx.search(text)
                if m:
                    line = text[:m.start()].count("\n") + 1
                    hits.append((rel, line, label))
            for key in BACKUP_STATE_KEYS:
                if key in text:
                    line = text[:text.index(key)].count("\n") + 1
                    hits.append((rel, line, "含个人状态备份键 " + key[:24]))
        # 真实书单交叉比对（评分包是公开榜单，另有字段白名单把关，不参与指纹比对）
        if rel.replace("\\", "/") == "scripts/douban_pack.json":
            continue
        for key, group in buckets.items():
            if key not in text:
                continue
            for feat in group:
                if feat in KNOWN_DEMO_TITLES:   # 已知公开示例书目，跳过敏感误报
                    continue
                if feat in text:
                    line = text[:text.index(feat)].count("\n") + 1
                    hits.append((rel, line, "真实书单指纹: " + feat[:40]))
                    break
            if len(hits) > 40:
                break
        if len(hits) > 40:
            break
    counts["内容特征"] = scanned
    seen = set()
    for rel, line, label in hits:
        k = (rel, label)
        if k in seen:
            continue
        seen.add(k)
        err("内容特征", "%s:%d 含 %s" % (rel, line, label))
    if feats:
        notes.append("真实书单指纹 %d 条，逐字比对 %d 个文本文件" % (len(feats), scanned))
    else:
        warn("内容特征", "本地无 data/，真实书单交叉比对跳过（公开 clone 模式）")
    return len(seen)


def check_public_html():
    if not os.path.exists(PUBLIC_HTML):
        err("公开页结构", "docs/index.html 不存在，请先跑 python scripts/build_public.py")
        return
    with io.open(PUBLIC_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    for ph in ("__LIBRARY_DATA__", "__SCAN_JS__"):
        if ph in html:
            err("公开页结构", "占位符未替换：" + ph)
    m = re.search(r'<script id="LIBRARY_DATA"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        err("公开页结构", "找不到内嵌 LIBRARY_DATA")
    else:
        try:
            data = json.loads(m.group(1).replace("<\\/", "</"))
        except ValueError as e:
            err("公开页结构", "内嵌数据不是合法 JSON：" + str(e)[:80])
            data = None
        if data:
            books = data.get("books") or []
            scans = data.get("scansets") or []
            if data.get("kind") != "ebooklib_library_data":
                err("公开页结构", "kind 不是 ebooklib_library_data")
            if len(books) + len(scans) < 20:
                err("公开页结构", "示例条目不足 20 条")
            # 示例数据允许带真实豆瓣评分（用户选择「给示例书补真实评分」），
            # 但仍须满足：全部 __demo 标记、sk 无反斜杠（无本机路径）、
            # douban 只含公开白名单字段。三者任一不满足才视为真实数据泄漏。
            DOUBAN_PUBLIC = ("id", "url", "title", "author", "rating", "votes",
                             "year", "publisher", "pages", "intro", "cover",
                             "confidence", "matched_query")
            bad = []
            for b in books + scans:
                if not b.get("__demo"):
                    bad.append(b)
                    continue
                if "\\" in str(b.get("sk") or ""):
                    bad.append(b)
                    continue
                db = b.get("douban") or {}
                if isinstance(db, dict) and db and any(k not in DOUBAN_PUBLIC for k in db):
                    bad.append(b)
            if bad:
                err("公开页结构", "%d 条示例数据异常（非 demo / 含绝对路径 / douban 含私有字段）" % len(bad))
            sks = [b.get("sk") for b in books + scans]
            if len(set(sks)) != len(sks):
                err("公开页结构", "示例 sk 不唯一")
            notes.append("示例书单：%d 本 / %d 图册，全部 __demo、含示例评分" % (len(books), len(scans)))
    if "window.EbooklibScan" not in html and "EbooklibScan" not in html:
        err("公开页结构", "前端扫描模块未注入")
    # 静态外链 / 第三方请求
    for rx, label in [
        (re.compile(r'<script[^>]+src\s*=\s*["\']https?://', re.I), "外部脚本"),
        (re.compile(r'<link[^>]+href\s*=\s*["\']https?://', re.I), "外部样式/字体"),
        (re.compile(r'<img[^>]+src\s*=\s*["\']https?://', re.I), "外部图片"),
        (re.compile(r'@import\s+url\(\s*["\']?https?://', re.I), "CSS 外部导入"),
    ]:
        if rx.search(html):
            err("公开页结构", "页面含" + label + "（违反零上传 / 离线可用）")
    if not os.path.exists(os.path.join(ROOT, "docs", ".nojekyll")):
        err("公开页结构", "docs/.nojekyll 缺失")
    counts["公开页结构"] = 1


def check_docs():
    required = ["README.md", "LICENSE", ".gitignore", "config.example.json",
                "docs/index.html", "docs/troubleshooting.md", "docs/data-schema.md",
                "scripts/build_public.py", "scripts/prepublish_check.py",
                "scripts/scan_core.js", "scripts/demo_library.json",
                "scripts/app_template.html", "scripts/verify_readonly.py",
                "重新生成清单.bat"]
    missing = [p for p in required if not os.path.exists(os.path.join(ROOT, p))]
    if missing:
        err("文档与许可证", "发布必需文件缺失：" + ", ".join(missing))
    lic = os.path.join(ROOT, "LICENSE")
    if os.path.exists(lic):
        t = io.open(lic, "r", encoding="utf-8").read()
        if "PolyForm" not in t or "Noncommercial" not in t:
            err("文档与许可证", "LICENSE 不是 PolyForm Noncommercial 1.0.0")
        if re.search(r"\bMIT License\b", t):
            err("文档与许可证", "LICENSE 残留 MIT 条款")
        if "Commercial Licensing" not in t:
            warn("文档与许可证", "LICENSE 未附商业授权说明")
    with io.open(os.path.join(ROOT, "README.md"), "r", encoding="utf-8") as f:
        rd = f.read()
    if "Source Available" not in rd:
        warn("文档与许可证", "README 未标注 Source Available")
    if re.search(r"\bMIT\b|完全开源|开放源代码许可", rd):
        err("文档与许可证", "README 与「非 OSI 开源 / 不可商用」定位冲突")
    cfg = os.path.join(ROOT, "config.example.json")
    if os.path.exists(cfg):
        c = io.open(cfg, "r", encoding="utf-8").read()
        if re.search(r"[A-Za-z]:[\\/]", c):
            err("文档与许可证", "config.example.json 含本机绝对路径")
    # 占位符提醒（不算泄漏）
    ph = sum(io.open(os.path.join(ROOT, p), "r", encoding="utf-8").read().count("<YOUR_GITHUB_ID>")
             for p in ("README.md", "LICENSE", "docs/troubleshooting.md")
             if os.path.exists(os.path.join(ROOT, p)))
    if ph:
        warn("发布待办", "还有 %d 处 <YOUR_GITHUB_ID> 占位符待替换" % ph)
    counts["文档与许可证"] = len(required)
    return ph


def check_readonly():
    """只读铁律：接触书库的脚本不得出现删除 / 改名调用。

    common.py 的 dump_json() 用 os.replace 做原子写是允许的 —— 它把输出写到
    项目目录（data/、docs/），且必须先过 assert_not_in_source() 守卫。
    这里连守卫一起校验，防止以后有人把守卫删掉。
    """
    guards = ["scan_library.py", "common.py", "verify_readonly.py",
              "postprocess.py", "fetch_douban.py"]
    hard_forbidden = re.compile(
        r"\b(?:shutil\.rmtree|os\.remove|os\.unlink|os\.rename|Path\.unlink)\b")
    bad = []
    for g in guards:
        p = os.path.join(ROOT, "scripts", g)
        if not os.path.exists(p):
            err("只读铁律", "脚本缺失：" + g)
            continue
        t = io.open(p, "r", encoding="utf-8").read()
        m = hard_forbidden.search(t)
        if m:
            bad.append("%s 含 %s（禁止对书库做删除/改名）" % (g, m.group(0)))
        if g == "common.py":
            if "assert_readonly" not in t or "assert_not_in_source" not in t:
                bad.append("common.py 缺少 assert_readonly / assert_not_in_source 路径守卫")
            if "os.replace(" in t and not re.search(
                    r"def dump_json[\s\S]{0,300}?assert_not_in_source\(path\)[\s\S]{0,300}?os\.replace", t):
                bad.append("common.py 的 os.replace 未处于 assert_not_in_source 守卫内")
    for b in bad:
        err("只读铁律", b)
    if not bad:
        notes.append("只读铁律：%d 个脚本零删除/改名调用，原子写守卫完整" % len(guards))
    counts["只读铁律"] = len(guards)


# --------------------------------------------------------------------------
def main():
    rules = load_rules()
    tracked, ignored = simulate_add(rules)
    git_crosscheck(tracked)
    feats, feat_src = real_fingerprints()

    check_ignore_rules(ignored, rules)
    check_paths(tracked)
    check_content(tracked, feats)
    check_douban_pack()
    check_public_html()
    check_docs()
    check_readonly()

    print("=" * 62)
    print("发布前隐私自检 · 本地书库管理")
    print("  仓库      " + ROOT)
    print("  模式      " + ("strict" if STRICT else "normal"))
    print("  跟踪集合  %d 个文件（模拟 git add -A）／忽略 %d 项" % (len(tracked), len(ignored)))
    if feat_src:
        print("  指纹来源  " + "、".join(feat_src))
    print("=" * 62)
    for n in notes:
        print("  · " + n)
    if warns:
        print("-" * 62)
        for w in warns:
            print("  WARN  " + w)
    if errors:
        print("-" * 62)
        for e in errors[:60]:
            print("  ERROR " + e)
        if len(errors) > 60:
            print("  ERROR …另有 %d 条" % (len(errors) - 60))
    print("=" * 62)
    print("  ERROR %d · WARN %d" % (len(errors), len(warns)))
    if errors:
        print("  ❌ 不可发布：发现 %d 处潜在泄漏 / 结构问题" % len(errors))
    else:
        print("  ✅ 可发布：0 处泄漏")
    print("=" * 62)

    if SHOW_LIST:
        print("\n待提交清单（%d）:" % len(tracked))
        for rel in tracked:
            print("  " + rel)

    # 公开 clone 里没有 data/，交叉比对降级为 WARN，但仍可跑通自检。
    # 只有 ERROR 才阻断发布。
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
