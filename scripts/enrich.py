# -*- coding: utf-8 -*-
"""阶段3：把「一句话介绍」等人工修正合并进 data/overrides.json

用法:
    python scripts/enrich.py data/onelines_001.json [data/onelines_002.json ...]

每个 oneline 文件格式： { "<book_id>": "一句话介绍", ... }
也支持列表形式： [ {"id": "b00001", "oneline": "…"}, ... ]
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, dump_json, norm_key  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVR = os.path.join(ROOT, "data", "overrides.json")
BOOKS = os.path.join(ROOT, "data", "books.json")


def stable_keys(b):
    db = b.get("douban") or {}
    keys = []
    if b.get("douban_status") == "ok" and db.get("id"):
        keys.append("db:" + str(db["id"]))
    rel = b.get("rel")
    if not rel and b.get("files"):
        try:
            from common import SOURCE_ROOT
            rel = os.path.relpath(b["files"][0]["path"], SOURCE_ROOT)
        except Exception:
            rel = None
    if not rel and b.get("dir"):
        rel = b["dir"]
    if rel:
        keys.append("path:" + rel)
    return keys or [b["id"]]


def main():
    paths = [a for a in sys.argv[1:] if a.endswith(".json")]
    if not paths:
        print("用法: python scripts/enrich.py data/onelines_001.json [...]")
        return
    ovr = load_json(OVR) or {}
    books = load_json(BOOKS) or {}
    bid2keys = {}
    for b in books.get("books", []) + books.get("scansets", []):
        bid2keys[b["id"]] = stable_keys(b)
    n = 0
    for p in paths:
        fp = p if os.path.isabs(p) else os.path.join(ROOT, p)
        d = load_json(fp)
        if not d:
            print(f"  跳过（读不到）: {p}")
            continue
        items = d.items() if isinstance(d, dict) else [
            (x["id"], x["oneline"]) for x in d if x.get("id")]
        for bid, line in items:
            if not line:
                continue
            for key in bid2keys.get(bid, [bid]):
                ovr.setdefault(key, {})["oneline"] = line
                n += 1
        print(f"  合并 {p}: {len(list(items))} 条")
    dump_json(OVR, ovr)
    print(f"overrides.json 现有 {len(ovr)} 条，本次写入 {n} 条")
    print(f"  {OVR}")


if __name__ == "__main__":
    main()
