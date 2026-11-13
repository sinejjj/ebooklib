# -*- coding: utf-8 -*-
"""阶段2.5：数据清洗（确定性重放）

raw（只读扫描）⋈ enriched（按 rel 的豆瓣数据）→ books.merged.json

关键修复：
- 不再从旧 books.json 继承任何字段（旧继承是 id 串号/title 污染的通路）。
- 豆瓣数据只按 rel 挂载，结构上不可能串号。
- suspect 条目清空 rating/votes。
- id = sha1(kind:rel)[:8]，永不重排。
"""
import os
import sys
import re
import json
import hashlib
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, dump_json, norm_key, classify, human_size, source_root  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "books.raw.json")
ENRICHED = os.path.join(ROOT, "data", "douban_enriched.json")
OUT = os.path.join(ROOT, "data", "books.merged.json")

PENDING = "未分类"

JUNK_TOKEN = re.compile(
    r"(kindle电子书|kindle正版|kindle版|电子书|说明书|样章|试读|"
    r"扫描版|高清扫描|\d{4}-\d{1,2}|\[\d寸\]|【\d寸】|_sample)", re.I)


def core(t):
    if not t:
        return ""
    s = str(t)
    s = re.split(r"[（(_：:]", s)[0]
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


def clean_title(t):
    if not t:
        return t
    s = JUNK_TOKEN.sub("", t)
    s = re.sub(r"\s{2,}", " ", s).strip(" -_·、,，")
    return s or t


def stable_id(rel, kind):
    h = hashlib.sha1((("dir:" if kind == "scanset" else "file:") + rel).encode("utf-8")).hexdigest()[:8]
    return ("s" if kind == "scanset" else "b") + h


def is_ok(b):
    return (b.get("douban_status") == "ok"
            and not b.get("suspect")
            and (b.get("confidence") or 0) >= 0.8)


def main():
    raw = load_json(RAW)
    if not raw:
        print("缺少 books.raw.json")
        return
    en = load_json(ENRICHED) or {}
    entries = en.get("entries") or {}
    books = raw.get("books") or []
    scans = raw.get("scansets") or []

    # ---------- 1. 按 rel 挂载豆瓣数据 ----------
    n_attach = 0
    for b in books:
        rel = b.get("rel") or (b.get("files") or [{}])[0].get("rel") or ""
        b["rel"] = rel
        e = entries.get(rel) or {}
        db = dict(e.get("douban") or {})
        status = e.get("douban_status") or "pending"
        suspect = bool(e.get("suspect"))
        if suspect:
            db["rating"] = None
            db["votes"] = None
        b["douban"] = db
        b["douban_status"] = status
        b["suspect"] = suspect
        b["confidence"] = e.get("confidence") or 0
        b["needs_network"] = bool(e.get("needs_network"))
        if e:
            n_attach += 1

    # ---------- 2. 采用豆瓣规范名（仅高置信且非存疑） ----------
    n_canon = 0
    for b in books:
        db = b.get("douban") or {}
        if is_ok(b) and db.get("title"):
            if db["title"] != b.get("title"):
                b["title_raw2"] = b.get("title")
                b["title"] = db["title"]
                n_canon += 1
            if db.get("author"):
                b["author"] = db["author"]
                b["author_from"] = "douban"
        else:
            ct = clean_title(b.get("title"))
            if ct != b.get("title"):
                b["title_raw2"] = b.get("title")
                b["title"] = ct
                n_canon += 1

    # ---------- 3. 全量重算分类（确定性可重放） ----------
    # 用豆瓣规范名 + 简介 + 完整路径重跑每一条。规则升级后历史误判会自愈，
    # 不再只修「待归类」——旧版只重算 PENDING，导致 keyword 误判永久固化。
    n_reclass = 0
    for b in books + scans:
        old = b.get("category")
        intro = ((b.get("douban") or {}).get("intro") or "")
        parts = [p for p in (b.get("rel") or "").split(os.sep) if p]
        cat, src = classify(b.get("title"), b.get("author"), b.get("dir_hint"),
                            b.get("subdir_hint"), intro, parts)
        # 扫描图册的设计目录是硬信号，与 scan_library.py 保持一致
        if b.get("kind") == "scanset" and (
                b.get("dir_hint") == "7 设计、艺术、创意"
                or any(x in (b.get("rel") or "") for x in ("设计", "艺术"))):
            cat, src = "设计·艺术·摄影", "dir"
        b["category"] = cat
        b["category_src"] = src
        if cat != old:
            n_reclass += 1

    # ---------- 4. 分组（db:id 或 书名归一），冲突降级 ----------
    groups = defaultdict(list)
    for b in books:
        db = b.get("douban") or {}
        # 不同卷在豆瓣常共用同一个 id（如《他方世界》上下册），
        # 必须把卷标记并入分组键，否则分卷又被判成重名。
        vk = "|v:" + str(b["volume"]) if b.get("volume") else ""
        if is_ok(b) and db.get("id"):
            b["_gk"] = "db:" + str(db["id"]) + vk
        else:
            b["_gk"] = "nk:" + norm_key(b.get("title")) + vk
        b["_vk"] = vk
        groups[b["_gk"]].append(b)

    pairs = []
    n_conflict = 0
    for key, members in groups.items():
        if key.startswith("db:") and len(members) > 1:
            members.sort(key=lambda x: -(x.get("total_size") or 0))
            dom = members[0]
            keep = [dom]
            for m in members[1:]:
                if title_sim(m.get("title"), dom.get("title")) >= 0.5 or \
                   norm_key(m.get("title")) == norm_key(dom.get("title")):
                    keep.append(m)
                else:
                    m["suspect"] = True
                    db = dict(m.get("douban") or {})
                    db["rating"] = None
                    db["votes"] = None
                    m["douban"] = db
                    n_conflict += 1
                    pairs.append(("nk:" + norm_key(m.get("title")) + (m.get("_vk") or ""), [m]))
            pairs.append((key, keep))
        else:
            pairs.append((key, members))

    # ---------- 5. 合并 ----------
    merged = []
    for key, members in pairs:
        members.sort(key=lambda x: (-(x.get("total_size") or 0), x.get("rel") or ""))
        head = dict(members[0])
        files = []
        seen = set()
        for m in members:
            src = m.get("files") or [{
                "path": m.get("path"), "rel": m.get("rel"), "size": m.get("size"),
                "ext": m.get("ext"), "mtime": m.get("mtime"), "read": m.get("read"),
            }]
            for f in src:
                r = f.get("rel")
                if not r and f.get("path"):
                    try:
                        r = os.path.relpath(f["path"], source_root())
                    except Exception:
                        r = None
                if r and r not in seen:
                    seen.add(r)
                    f["rel"] = r
                    files.append(f)
        head["files"] = files
        head["total_size"] = sum(f.get("size") or 0 for f in files)
        head["dup_count"] = len(files)
        head["read"] = any(m.get("read") for m in members)
        head["dir_hints"] = sorted({m.get("dir_hint") for m in members if m.get("dir_hint")})
        head.pop("_gk", None)
        head.pop("_vk", None)
        merged.append(head)

    # ---------- 6. 稳定 id ----------
    merged.sort(key=lambda x: x.get("rel") or "")
    used = set()
    for b in merged:
        sid = stable_id(b.get("rel") or "", "file")
        while sid in used:
            sid += "x"
        used.add(sid)
        b["id"] = sid
    scans.sort(key=lambda x: x.get("rel") or "")
    for s in scans:
        sid = stable_id(s.get("rel") or "", "scanset")
        while sid in used:
            sid += "x"
        used.add(sid)
        s["id"] = sid

    # ---------- 7. 统计 + 输出 ----------
    dup_groups = [b for b in merged if b["dup_count"] > 1]
    stats = dict(raw.get("stats") or {})
    stats.update({
        "unique_entries": len(merged),
        "dup_groups": len(dup_groups),
        "dup_files": sum(b["dup_count"] for b in dup_groups),
        "dup_redundant": sum(b["dup_count"] - 1 for b in dup_groups),
        "read_marked": sum(1 for b in merged if b.get("read")),
        "pending": sum(1 for b in merged + scans if b.get("category") == PENDING),
        "rated": sum(1 for b in merged if (b.get("douban") or {}).get("rating")),
        "suspect": sum(1 for b in merged if b.get("suspect")),
        "no_douban": sum(1 for b in merged if not (b.get("douban") or {}).get("rating")),
        "attach": n_attach,
    })

    d = {
        "schema": 2,
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "source_root_name": raw.get("source_root_name"),
        "stats": stats,
        "books": merged,
        "scansets": scans,
    }
    dump_json(OUT, d)

    print("=" * 62)
    print("清洗完成（确定性重放，无旧数据继承）")
    print("=" * 62)
    print(f"  挂载豆瓣       {n_attach}/{len(books)}")
    print(f"  规范化书名     {n_canon}")
    print(f"  分类重算变更   {n_reclass}")
    print(f"  唯一条目       {len(merged)}")
    print(f"  重名组         {len(dup_groups)}  (涉及 {stats['dup_files']} 份)")
    print(f"  待归类         {stats['pending']}")
    print(f"  有评分         {stats['rated']}")
    print(f"  存疑           {stats['suspect']}  (冲突降级 {n_conflict})")
    print(f"  已读           {stats['read_marked']}")
    print(f"  总体积         {human_size(sum(b['total_size'] for b in merged + scans))}")
    print(f"  输出           {OUT}")


if __name__ == "__main__":
    main()
