# -*- coding: utf-8 -*-
"""结构与数据一致性审计。可作为发布前/每次重建后的护栏。

用法：
    python scripts/audit.py            # 全部检查
    python scripts/audit.py --strict   # 任一失败 exit 1
    python scripts/audit.py --only A3
"""
import os
import re
import sys
import json
import difflib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, out_html_name, parse_filename  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERGED = os.path.join(ROOT, "data", "books.merged.json")
ENRICHED = os.path.join(ROOT, "data", "douban_enriched.json")
HTML = os.path.join(ROOT, out_html_name())


def core(t):
    if not t:
        return ""
    s = re.split(r"[（(_：:]", str(t))[0]
    return re.sub(r"[^\w\u4e00-\u9fff]", "", s).lower()


def title_sim(a, b):
    ca, cb = core(a), core(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    if len(ca) >= 4 and len(cb) >= 4 and (ca.startswith(cb) or cb.startswith(ca)):
        return 1.0
    sa, sb = set(ca), set(cb)
    return len(sa & sb) / max(len(sa | sb), 1)


def author_sim(a, b):
    if not a or not b:
        return None
    na = re.sub(r"[^\w\u4e00-\u9fff]", "", str(a)).lower()
    nb = re.sub(r"[^\w\u4e00-\u9fff]", "", str(b)).lower()
    if not na or not nb:
        return None
    if na in nb or nb in na:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def head_rel(b):
    fs = b.get("files") or []
    return (fs[0].get("rel") if fs else None) or b.get("rel") or ""


def main():
    strict = "--strict" in sys.argv
    only = None
    for i, a in enumerate(sys.argv):
        if a == "--only" and i + 1 < len(sys.argv):
            only = sys.argv[i + 1]

    mg = load_json(MERGED) or {}
    en = load_json(ENRICHED) or {}
    books = mg.get("books") or []
    scans = mg.get("scansets") or []
    entries = en.get("entries") or {}

    results = {}

    def check(code, name, bad, detail=""):
        if only and only != code:
            return
        results[code] = (len(bad) == 0, name, bad, detail)

    # A1 结构
    bad = []
    ids = set()
    rels = set()
    for b in books + scans:
        bid = b.get("id")
        if not bid or bid in ids:
            bad.append(("dup_id", bid))
        ids.add(bid)
        rel = b.get("rel") or (head_rel(b) if b.get("kind") != "scanset" else "")
        if rel in rels:
            bad.append(("dup_rel", rel))
        rels.add(rel)
        if b.get("kind") != "scanset":
            fs = b.get("files") or []
            if not fs:
                bad.append(("no_files", bid))
            for f in fs:
                if not f.get("rel"):
                    bad.append(("file_no_rel", bid))
    check("A1", "结构完整性（id/rel 唯一、每条有文件）", bad)

    # A2 id 空间隔离
    bad = []
    try:
        txt = open(ENRICHED, encoding="utf-8").read()
        if re.search(r'"b\d{5}"', txt):
            bad.append(("enriched_has_bid", ""))
    except OSError:
        bad.append(("enriched_missing", ""))
    for b in books:
        if re.fullmatch(r"b\d{5}", b.get("id") or ""):
            bad.append(("legacy_id", b.get("id")))
    check("A2", "id 空间隔离（enriched 无 bNNNNN、无旧式 id）", bad)

    # A3 归属一致性
    bad = []
    n_ok = 0
    for b in books:
        if b.get("douban_status") != "ok" or b.get("suspect"):
            continue
        n_ok += 1
        db = b.get("douban") or {}
        pt = parse_filename(os.path.basename(head_rel(b))).get("title") or ""
        sim = title_sim(pt, db.get("title") or "")
        asim = author_sim(b.get("author"), db.get("author"))
        if sim < 0.5 and (asim is None or asim < 0.5):
            bad.append((b.get("id"), pt, db.get("title")))
    check("A3", f"归属一致性（ok={n_ok} 中名称+作者双不符）", bad)

    # A4 与 enriched 一致
    bad = []
    for b in books:
        rel = b.get("rel") or head_rel(b)
        e = entries.get(rel)
        if not e:
            bad.append(("no_entry", rel))
            continue
        if b.get("douban_status") == "ok":
            a = (b.get("douban") or {}).get("id")
            c = (e.get("douban") or {}).get("id")
            if str(a) != str(c):
                bad.append(("id_diff", rel, a, c))
    check("A4", "与 enriched 数据一致", bad)

    # A5 合并纯度（同一条目内文件书名应与头一致）
    bad = []
    for b in books:
        ht = parse_filename(os.path.basename(head_rel(b))).get("title") or b.get("title")
        for f in (b.get("files") or [])[1:]:
            ft = parse_filename(os.path.basename(f.get("rel") or "")).get("title") or ""
            if ft and title_sim(ht, ft) < 0.5:
                bad.append((b.get("id"), ht, ft))
    check("A5", "合并纯度（条目内异源文件）", bad)

    # A8 隐私泄露（rel 不得是绝对路径；成品 HTML 不得含绝对路径/私人目录名）
    bad = []
    for b in books + scans:
        v = b.get("rel")
        if v and (re.match(r"^[A-Za-z]:[\\/]", str(v)) or str(v).startswith("\\\\")):
            bad.append(("abs_rel", v))
    if os.path.exists(HTML):
        t = open(HTML, encoding="utf-8", errors="ignore").read()
        if re.search(r"[A-Za-z]:\\\\", t):
            bad.append(("html_abs_path", ""))
    check("A8", "隐私泄露（绝对路径 / 私人目录名）", bad)

    # 输出
    ok_all = True
    print("=" * 62)
    print("审计结果")
    print("=" * 62)
    for code in ["A1", "A2", "A3", "A4", "A5", "A8"]:
        if code not in results:
            continue
        ok, name, bad, detail = results[code]
        mark = "✅" if ok else "❌"
        print(f"  {mark} {code} {name}  （问题 {len(bad)}）")
        if not ok:
            ok_all = False
            for x in bad[:6]:
                print("       ", x)
    print("=" * 62)
    if ok_all:
        print("  ✅ 全部通过")
    else:
        print("  ❌ 存在问题")
    if strict and not ok_all:
        sys.exit(1)


if __name__ == "__main__":
    main()
