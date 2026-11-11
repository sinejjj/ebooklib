# -*- coding: utf-8 -*-
"""阶段0：只读扫描书库 → data/books.raw.json

绝不写入/移动/重命名/删除库内任何内容。
"""
import os
import sys
import json
import time
import re
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    source_root, BOOK_EXT, NON_BOOK_RE, assert_readonly,
    parse_filename, norm_key, classify, dump_json, human_size, load_json,
    volume_label,
)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "books.raw.json")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
MIN_PAGES_FOR_SCANSET = 30      # 目录内图片数 >= 30 视为扫描图册
READ_DIR_MARK = "已阅"


def scan():
    src_root = source_root()
    books = []          # 文件型条目
    scansets = []       # 目录型（扫描图册）
    file_count = 0
    skipped_sdr = 0

    for root, dirs, files in os.walk(src_root):
        assert_readonly(root)
        dirs[:] = [d for d in dirs if not d.endswith(".sdr")]
        if root.endswith(".sdr"):
            skipped_sdr += 1
            continue

        rel = os.path.relpath(root, src_root)
        parts = [] if rel == "." else rel.split(os.sep)
        top = parts[0] if parts else ""
        sub = parts[1] if len(parts) > 1 else ""
        in_read_dir = any(READ_DIR_MARK in p for p in parts)

        imgs = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXT]

        # ---- 目录型：扫描图册
        if len(imgs) >= MIN_PAGES_FOR_SCANSET:
            total = 0
            for f in files:
                try:
                    total += os.stat(os.path.join(root, f)).st_size
                except OSError:
                    pass
            name = os.path.basename(root) or top
            cat, src = classify(name, None, top, sub, "", parts)
            if top == "7 设计、艺术、创意" or "设计" in rel or "艺术" in rel:
                cat = "设计·艺术·摄影"
                src = "dir"
            scansets.append({
                "kind": "scanset",
                "dir": root,
                "rel": os.path.relpath(root, src_root),
                "title": parse_filename(name)["title"] or name,
                "pages": len(imgs),
                "total_size": total,
                "dir_hint": top,
                "category": cat,
                "category_src": src,
                "read": False,
                "locked_keep": True,
            })
            continue

        # ---- 文件型：书
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in BOOK_EXT:
                continue
            if NON_BOOK_RE.search(os.path.splitext(f)[0]):
                continue
            full = os.path.join(root, f)
            assert_readonly(full)
            try:
                st = os.stat(full)
            except OSError:
                continue
            file_count += 1
            p = parse_filename(f)
            cat, src = classify(p["title"], p["author"], top, sub, "", parts)
            books.append({
                "kind": "file",
                "path": full,
                "rel": os.path.relpath(full, src_root),
                "name": f,
                "ext": ext.lstrip("."),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "title": p["title"],
                "title_raw": f,
                "author": p["author"],
                "author_from": p["author_from"],
                "volume": p["volume"],
                "series": p["series"],
                "is_collection": p["is_collection"],
                "asin": p["asin"],
                "dir_hint": top,
                "subdir_hint": sub,
                "category": cat,
                "category_src": src,
                "read": in_read_dir,
                "files": [{
                    "path": full, "rel": os.path.relpath(full, src_root),
                    "size": st.st_size, "ext": ext.lstrip("."),
                    "mtime": int(st.st_mtime), "read": in_read_dir,
                }],
                "total_size": st.st_size,
            })

    # ---- 重名分组（文件型）
    # 分组键 = 书名主干 + 卷标记。不同卷是不同书，不算重名；
    # 同卷的多个文件仍归为一组真重名。
    groups = defaultdict(list)
    for b in books:
        tag = volume_label(b["title_raw"])
        base = b["title"]
        if tag:
            short = re.sub(r"[（()）]", "", tag[1])
            base = base.replace(tag[1], "").replace(short, "")
            base = re.sub(r"[.·\s]+$", "", base).strip(" .·-_") or b["title"]
            b["volume"] = tag[0]
            b["volume_label"] = tag[1]
            b["_short"] = short
        b["_base"] = base
        groups[(norm_key(base), tag[0] if tag else "")].append(b)

    merged = []
    for (key, vkey), members in groups.items():
        members.sort(key=lambda x: (-x["size"], x["rel"]))
        head = dict(members[0])
        head["files"] = [{
            "path": m["path"], "rel": m["rel"], "size": m["size"], "ext": m["ext"],
            "mtime": m["mtime"], "read": m["read"],
        } for m in members]
        head["total_size"] = sum(m["size"] for m in members)
        head["dup_count"] = len(members)
        head["read"] = any(m["read"] for m in members)
        if vkey:
            short = head.get("_short", "")
            t = head["title"]
            # 卷标记在标题中间且带卷名（如「第一部：落日之巨龙」）时保持原名
            if short not in t or t.endswith(short):
                head["title"] = f"{head['_base']} · {short}"
        for k in ("_base", "_short"):
            head.pop(k, None)
        merged.append(head)

    merged.sort(key=lambda x: norm_key(x["title"]))

    for i, b in enumerate(merged + scansets):
        b["id"] = f"b{i+1:05d}"

    total_files = sum(b["dup_count"] for b in merged)
    dup_groups = [b for b in merged if b["dup_count"] > 1]
    total_bytes = sum(b["total_size"] for b in merged + scansets)

    data = {
        "schema": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_root": src_root,
        "source_root_name": os.path.basename(src_root),
        "stats": {
            "file_books": total_files,
            "unique_entries": len(merged),
            "scansets": len(scansets),
            "dup_groups": len(dup_groups),
            "dup_files": sum(b["dup_count"] for b in dup_groups),
            "dup_redundant": sum(b["dup_count"] - 1 for b in dup_groups),
            "volume_entries": sum(1 for b in merged if b.get("volume_label")),
            "read_marked": sum(1 for b in merged if b["read"]),
            "total_bytes": total_bytes,
            "book_bytes": sum(b["total_size"] for b in merged),
            "scanset_bytes": sum(s["total_size"] for s in scansets),
        },
        "books": merged,
        "scansets": scansets,
    }
    return data


def main():
    t0 = time.time()
    data = scan()
    if "--check" in sys.argv:
        old = load_json(OUT) or {}

        def relset(d):
            s = set()
            sr = source_root()
            for b in d.get("books", []):
                for f in (b.get("files") or []):
                    r = f.get("rel")
                    if not r and f.get("path"):
                        r = os.path.relpath(f["path"], sr)
                    if r:
                        s.add(r)
            for x in d.get("scansets", []):
                r = x.get("rel")
                if not r and x.get("dir"):
                    r = os.path.relpath(x["dir"], sr)
                if r:
                    s.add(r)
            return s

        cur, prv = relset(data), relset(old)
        added, removed = cur - prv, prv - cur
        print("=" * 62)
        print("扫描一致性检查（不落盘）")
        print("=" * 62)
        print(f"  当前 {len(cur)}  历史 {len(prv)}  新增 {len(added)}  缺失 {len(removed)}")
        for p in list(added)[:8]:
            print("   + ", p)
        for p in list(removed)[:8]:
            print("   - ", p)
        if added or removed:
            print("\n  ❌ rel 集合有差异（书库有增删属正常）")
            sys.exit(1)
        print("\n  ✅ rel 集合完全一致")
        return

    dump_json(OUT, data)
    s = data["stats"]
    print("=" * 62)
    print("只读扫描完成（未对书库做任何修改）")
    print("=" * 62)
    print(f"  书籍文件        {s['file_books']}")
    print(f"  唯一条目        {s['unique_entries']}")
    print(f"  扫描图册目录    {s['scansets']}  ({human_size(s['scanset_bytes'])})")
    print(f"  重名组          {s['dup_groups']}  (涉及 {s['dup_files']} 份)")
    print(f"  已阅预标记      {s['read_marked']}")
    print(f"  电子书体积      {human_size(s['book_bytes'])}")
    print(f"  总体积          {human_size(s['total_bytes'])}")
    print(f"  耗时            {time.time()-t0:.1f}s")
    print(f"  输出            {OUT}")

    print("\n--- 分类分布 ---")
    cc = defaultdict(int)
    for b in data["books"] + data["scansets"]:
        cc[b["category"]] += 1
    for k, v in sorted(cc.items(), key=lambda x: -x[1]):
        print(f"  {v:5d}  {k}")

    print("\n--- 重名最多 top8 ---")
    for b in sorted(data["books"], key=lambda x: -x["dup_count"])[:8]:
        print(f"  x{b['dup_count']}  {b['title'][:30]}")


if __name__ == "__main__":
    main()
