# -*- coding: utf-8 -*-
"""只读校验：导出书库快照 (path,size,mtime)，可与前次对比证明 0 改动。

用法:
  python scripts/verify_readonly.py           # 生成/更新快照
  python scripts/verify_readonly.py --diff    # 与上次快照对比
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import source_root, assert_readonly, dump_json  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "data", "snapshot.json")


def snapshot():
    items = {}
    for root, dirs, files in os.walk(source_root()):
        assert_readonly(root)
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            items[p] = [st.st_size, int(st.st_mtime)]
    return items


def main():
    diff = "--diff" in sys.argv
    cur = snapshot()
    if not diff:
        dump_json(SNAP, cur)
        print(f"快照已写入 {SNAP}")
        print(f"  文件数 {len(cur)}")
        return

    if not os.path.exists(SNAP):
        print("无历史快照，先运行不带 --diff 生成。")
        return
    with open(SNAP, "r", encoding="utf-8") as f:
        old = json.load(f)

    added = [p for p in cur if p not in old]
    removed = [p for p in old if p not in cur]
    changed = [p for p in cur if p in old and cur[p] != old[p]]

    print("=" * 62)
    print("只读校验结果")
    print("=" * 62)
    print(f"  基准文件数 {len(old)}   当前 {len(cur)}")
    print(f"  新增       {len(added)}")
    print(f"  删除       {len(removed)}")
    print(f"  内容/时间变化 {len(changed)}")
    for p in (added + removed + changed)[:20]:
        print("   !", p)
    if not (added or removed or changed):
        print("\n  ✅ 库内文件 0 改动 —— 全程只读已验证")
    else:
        print("\n  ❌ 检测到差异，请检查！")
    dump_json(SNAP, cur)


if __name__ == "__main__":
    main()
