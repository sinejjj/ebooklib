# -*- coding: utf-8 -*-
"""移植验收闸门：同一批文件名，逐字段比对 common.py 与 scan_core.js。

用法：
    python scripts/test_scan_port.py                # 找不到 node 时跳过
    NODE_EXE=/path/to/node python scripts/test_scan_port.py --strict
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from common import parse_filename, volume_label, norm_key, classify  # noqa: E402

REPORTS = os.path.join(ROOT, "reports")
CASES_PATH = os.path.join(REPORTS, "_scan_cases.json")
RUNNER_PATH = os.path.join(REPORTS, "_scan_runner.js")

# 全部为编造或公版书名，不含任何真实书库文件名与路径
CASES = [
    "示例·山居札记 - 示例作者.mobi",
    "《示例·纸上城市》 佚名.epub",
    "示例作者《示例·夜航手记》.mobi",
    "示例·短篇集.txt",
    "示例·江岸旧事.第1卷.epub",
    "示例·江岸旧事.第2卷.epub",
    "示例·江岸旧事.第9卷·书信.epub",
    "示例·七侠（三）-示例作者.epub",
    "示例·七侠（上）.epub",
    "示例·他方世界（下）.mobi",
    "示例作者：小札记（示例丛书·一堂《示例大典》的管理课）.mobi",
    "示例·导读《示例大典》：入门讲义.mobi",
    "示例·脱骨香（示例剧《示例花千骨》原著姐妹篇）.mobi",
    "示例·国富论（插图本） - 示例作者.epub",
    "示例·偶发空缺.J.K.示例.mobi",
    "Example.Effect.2007.The.Wal.mobi",
    "示例·美丽新世界_示例作者.azw3",
    "示例·百年孤独_B00ABC123456.mobi",
    "示例·编程入门(第2版).pdf",
    "示例·经济学原理_sample.epub",
    "讲谈社·示例的历史08·示例·疾驰的草原.mobi",
    "[英] 示例·克里斯蒂 - 示例·快车谋杀案.mobi",
    "示例作者  示例·白夜行  精装版.epub",
    "示例·女性主义 示例作者.pdf",
    "示例·男人来自火星 示例·女人来自金星.epub",
    "示例·人间词话 示例·词集.mobi",
    "示例·竞底：示例企业之殇.pdf",
    "示例·第五部队.mobi",
    "示例·罗斯柴尔德家族(套装上中下册).mobi",
    "Vol.3 示例·星际漫游.epub",
    "示例·诗经译注（上下册）.pdf",
    "示例·设计中的设计 - 示例·原研哉.pdf",
    "1984 - Example Author_B00TEST9999.mobi",
    "示例·霍比特人（插图本）.epub",
    "示例·如何阅读一本书（精装版）.mobi",
    "示例·某朝那些事儿 第1部.pdf",
    "示例·三体 - 示例·刘慈欣.mobi",
    "示例·活着 示例·余华.epub",
    "示例·算法散步.pdf",
    "示例·宇宙简图（上卷）.pdf",
]

FIELDS = ("title", "author", "volume", "norm_key", "category", "volume_label")


def expected(name):
    p = parse_filename(name)
    v = volume_label(name)
    cat, _ = classify(p["title"], p["author"], "", "", "", [])
    return {
        "name": name,
        "title": p["title"],
        "author": p["author"] or None,
        "volume": p["volume"] or None,
        "norm_key": norm_key(p["title"]),
        "category": cat,
        "volume_label": list(v) if v else None,
    }


RUNNER = r"""
const fs = require('fs');
const path = require('path');
const D = require(path.join(__dirname, '..', 'scripts', 'scan_core.js'));
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, '_scan_cases.json'), 'utf8'));
const out = cases.map(function (name) {
  const p = D.parseFilename(name);
  const v = D.volumeLabel(name);
  const c = D.classify(p.title, p.author || '', '', '', '', []);
  return {
    name: name,
    title: p.title,
    author: p.author || null,
    volume: p.volume || null,
    norm_key: D.normKey(p.title),
    category: c[0],
    volume_label: v || null
  };
});
process.stdout.write(JSON.stringify(out));
"""


def main():
    strict = "--strict" in sys.argv
    node = os.environ.get("NODE_EXE") or shutil.which("node")
    if not node:
        print("未找到 node，跳过移植比对（设置 NODE_EXE 后再跑）")
        return 1 if strict else 0

    os.makedirs(REPORTS, exist_ok=True)
    with open(CASES_PATH, "w", encoding="utf-8") as f:
        json.dump(CASES, f, ensure_ascii=False)
    with open(RUNNER_PATH, "w", encoding="utf-8") as f:
        f.write(RUNNER)

    try:
        r = subprocess.run([node, RUNNER_PATH], capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            print("Node 执行失败:", (r.stderr or "")[:800])
            return 1
        got = json.loads(r.stdout)
    finally:
        for p in (CASES_PATH, RUNNER_PATH):
            try:
                os.remove(p)
            except OSError:
                pass

    exp = [expected(n) for n in CASES]
    diffs = []
    for e, g in zip(exp, got):
        for k in FIELDS:
            if e[k] != g.get(k):
                diffs.append((e["name"], k, e[k], g.get(k)))

    print(f"夹具 {len(CASES)} 条 · 字段 {len(FIELDS)} 个 · 差异 {len(diffs)} 处")
    for name, k, a, b in diffs[:40]:
        print(f"  [{k}] {name}")
        print(f"      Python: {a!r}")
        print(f"      Node  : {b!r}")
    if len(diffs) > 40:
        print(f"  ... 还有 {len(diffs) - 40} 处")
    if diffs:
        return 1
    print("✅ 移植比对全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
