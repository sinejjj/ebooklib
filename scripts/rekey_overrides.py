# -*- coding: utf-8 -*-
"""重建 overrides.json 的稳定键（对齐 books.merged.json）。

策略（可靠度从高到低）：
1. 精确 path:<rel> 命中
2. 文件名（basename）唯一命中（书被移动目录后仍能找回）
3. db:<豆瓣id> 命中且未被其他条目占用
4. 都不中 → orphan:<旧键>（保留，不丢手写简介）

输出：每本书同时写 path:<rel> 与 db:<id> 双键，供 build_html 查找。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, dump_json  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVR = os.path.join(ROOT, "data", "overrides.json")
MERGED = os.path.join(ROOT, "data", "books.merged.json")


def norm(s):
    return (s or "").replace("\\", "/").strip().lower()


def basename(rel):
    return norm((rel or "").replace("\\", "/").rsplit("/", 1)[-1])


def main():
    old = load_json(OVR) or {}
    mg = load_json(MERGED) or {}
    if not old:
        print("没有 overrides.json，跳过")
        return
    if not mg.get("books"):
        print("缺少 books.merged.json，先运行 postprocess.py")
        return

    old_path, old_base, old_db = {}, {}, {}
    for k, v in old.items():
        if not isinstance(v, dict):
            continue
        if k.startswith("path:"):
            old_path[norm(k[5:])] = v
            old_base.setdefault(basename(k[5:]), []).append((k, v))
        elif k.startswith("db:"):
            old_db[k[3:]] = v

    used = set()
    new = {}
    hit_exact = hit_base = hit_db = 0
    for b in mg["books"]:
        rel = b.get("rel") or ""
        key = "path:" + rel
        val = None
        src = None
        if norm(rel) in old_path:
            val = old_path[norm(rel)]
            src = "exact"
            hit_exact += 1
        else:
            cands = old_base.get(basename(rel)) or []
            uniq = {id(v): v for _, v in cands}
            if len(cands) == 1:
                val = cands[0][1]
                src = "basename"
                hit_base += 1
        if val is None:
            db = b.get("douban") or {}
            did = str(db.get("id")) if (b.get("douban_status") == "ok" and db.get("id")) else None
            if did and did in old_db:
                val = old_db[did]
                src = "db"
                hit_db += 1
        if val is not None:
            new[key] = val
            db = b.get("douban") or {}
            if b.get("douban_status") == "ok" and db.get("id"):
                new["db:" + str(db["id"])] = val
            for k, v in old.items():
                if v is val:
                    used.add(k)

    orphan = {k: v for k, v in old.items() if k not in used and isinstance(v, dict)}
    for k, v in orphan.items():
        new["orphan:" + k] = v

    dump_json(OVR, new)
    print("=" * 62)
    print("overrides 重键完成")
    print("=" * 62)
    print(f"  旧键 {len(old)}  ->  新键 {len(new)}")
    print(f"  精确路径命中 {hit_exact} / 文件名命中 {hit_base} / 豆瓣id命中 {hit_db}")
    print(f"  孤立保留(orphan) {len(orphan)}")
    if orphan:
        for k in list(orphan)[:6]:
            print("    orphan:", k[:70])


if __name__ == "__main__":
    main()
