"""把散落在多个浏览器 origin 的书库状态合并成一份可导入备份。

背景：内置预览面板每次可能用不同的本地端口，而 localStorage 按 origin
隔离，于是「我的评分 / 隐藏 / 进度」会散落在多个互不可见的存储里。
本脚本只做合并与键对齐，绝不修改书库，也绝不写浏览器原始存储。

用法：
  python scripts/recover_state.py                 # 读 reports/_probe_states.json
  python scripts/recover_state.py --states X.json --out Y.json

输入格式：{ "<origin>|<storage_key>": <state dict>, ... }
输出格式：书库页面「恢复」按钮可直接导入的标准备份（schema 3）。
"""
import argparse
import base64
import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from common import norm_key, out_html_name, parse_filename  # noqa: E402

FIELDS = ("read", "note", "tag", "fmt", "cat", "hidden", "autoHidden",
          "rating", "page", "link", "noteIndex")

# 合并优先级：低 → 高。按「后缀形态」识别状态键，新旧命名空间都能找回，
# 源码里不留任何历史前缀明文。
PRIORITY_SUFFIX = [
    "library_state_v1_backup",
    "library_state_v2_backup",
    "library_state_v2",
    "library_state_v3_preRmap",
    "library_state_v3",
]
def state_rank(key):
    for i, suf in enumerate(PRIORITY_SUFFIX):
        if key == suf or key.endswith("_" + suf):
            return i
    return 2
ORIGIN_RANK = {"http://127.0.0.1:5175": 10, "file://": 0}


def load_payload():
    p = os.path.join(ROOT, out_html_name())
    with open(p, "r", encoding="utf-8") as f:
        h = f.read()
    m = re.search(r'<script id="LIBRARY_DATA"[^>]*>(.*?)</script>', h, re.S)
    return json.loads(m.group(1))


def build_index(data):
    entries = data.get("books", []) + data.get("scansets", [])
    sks = {b["sk"] for b in entries}

    def base(rel):
        return os.path.basename((rel or "").replace("\\", "/")).lower()

    by_file = collections.defaultdict(set)
    by_title = collections.defaultdict(set)
    for b in entries:
        by_title[norm_key(b.get("title") or "")].add(b["sk"])
        rels = [f.get("rel") for f in (b.get("files") or [])] + [b.get("rel")]
        for r in rels:
            if not r:
                continue
            by_file[base(r)].add(b["sk"])
            by_file[os.path.splitext(base(r))[0]].add(b["sk"])
            try:
                p = parse_filename(os.path.basename(r))
                if p.get("title"):
                    by_title[norm_key(p["title"])].add(b["sk"])
            except Exception:
                pass
    return sks, by_file, by_title


def align(sk, sks, by_file, by_title):
    """旧键 → 当前键。只接受唯一匹配，避免把评分挂到另一本书上。"""
    if sk in sks:
        return sk, "exact"
    rel = sk.split(":", 1)[-1]
    name = os.path.basename(rel.replace("\\", "/")).lower()
    for key in (name, os.path.splitext(name)[0]):
        c = by_file.get(key, set())
        if len(c) == 1:
            return next(iter(c)), "file"
    try:
        t = parse_filename(os.path.basename(rel)).get("title")
        c = by_title.get(norm_key(t or ""), set())
        if len(c) == 1:
            return next(iter(c)), "title"
    except Exception:
        pass
    return sk, "orphan"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", default=os.path.join(ROOT, "reports", "_probe_states.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "我的书库数据_找回备份.json"))
    ap.add_argument("--code", default=os.path.join(ROOT, "reports", "recover_code.txt"))
    ap.add_argument("--page", default=os.path.join(ROOT, "一键恢复.html"))
    args = ap.parse_args()

    states = json.load(open(args.states, encoding="utf-8"))
    data = load_payload()
    sks, by_file, by_title = build_index(data)

    sources = []
    for full, st in states.items():
        origin, _, key = full.partition("|")
        rank = (state_rank(key),
                ORIGIN_RANK.get(origin, 1))
        sources.append((rank, origin, key, st))
    sources.sort(key=lambda x: x[0])

    merged = {k: {} for k in FIELDS}
    stat = collections.Counter()
    for rank, origin, key, st in sources:
        for f in FIELDS:
            for sk, val in (st.get(f) or {}).items():
                nsk, how = align(sk, sks, by_file, by_title)
                if f == "rating":
                    stat[how] += 1
                # 优先级高的来源覆盖低的；孤儿键保留但不覆盖已对齐的值
                if nsk in merged[f] and how == "orphan":
                    continue
                merged[f][nsk] = val

    # autoHidden 是「上次同步判定本地已删」的临时标记，会随书库重扫过期。
    # 恢复它会让书卡莫名消失，因此不进备份（本机现有的也不动）。
    merged.pop("autoHidden", None)

    pack = {
        "kind": "ebooklib_library_backup",
        "schema": 3,
        "exported_at": data.get("generated_at", ""),
        "app": {"generated_at": data.get("generated_at", ""),
                "books": len(data.get("books", [])),
                "scansets": len(data.get("scansets", []))},
        "state": dict(merged, __v=3),
        "notes": {},
        "_recovered_from": [f"{o}|{k}" for _, o, k, _ in sources],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=1)

    # 恢复码：只含状态，不含书库数据，供任意 origin 的页面通过 #recover= 导入
    code = base64.urlsafe_b64encode(
        json.dumps({"state": pack["state"], "notes": {}}, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")).decode("ascii")
    with open(args.code, "w", encoding="utf-8") as f:
        f.write(code)

    # 一键恢复页：与书库页同目录、相对跳转，因此在任何 origin 下都能把数据
    # 写进「当前正在看的那个地址」，绕开预览面板随机端口的问题。
    page = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>恢复我的书库数据</title>
<style>body{font:15px/1.8 system-ui,-apple-system,"Microsoft YaHei",sans-serif;
background:#f7f8fa;color:#1f2328;display:flex;align-items:center;justify-content:center;
height:100vh;margin:0}.box{max-width:520px;background:#fff;border:1px solid #e5e7eb;
border-radius:12px;padding:26px 30px;box-shadow:0 8px 30px rgba(0,0,0,.06)}
h1{font-size:17px;margin:0 0 10px}p{margin:6px 0;color:#5c636e;font-size:13px}
b{color:#1f2328}</style></head><body><div class="box">
<h1>正在恢复我的评分与进度…</h1>
<p>马上会打开书库清单，并把找回的 <b>%d</b> 条评分等个人数据写入<b>当前地址</b>的浏览器存储。</p>
<p>若你刚才已经开着书库页面，恢复后请按 <b>Ctrl+F5</b> 刷新一下。</p>
<p style="margin-top:14px;color:#9aa1ab">本文件含你的个人数据，仅供本机使用，不要上传到 GitHub。</p>
</div><script>
var CODE=%s;
setTimeout(function(){ location.replace('MYLIB_HTML#recover='+CODE); }, 350);
</script></body></html>
""" % (len(merged["rating"]), json.dumps(code))
    with open(args.page, "w", encoding="utf-8") as f:
        f.write(page.replace("MYLIB_HTML", out_html_name()))

    print(f"来源 state      {len(sources)} 份")
    for f in FIELDS:
        if merged.get(f):
            print(f"  {f:12s} {len(merged[f]):4d} 条")
    print(f"评分键对齐     精确 {stat['exact']} / 文件名 {stat['file']} / "
          f"书名 {stat['title']} / 孤儿 {stat['orphan']}")
    print(f"备份文件       {args.out}")
    print(f"恢复码         {args.code}（{len(code)} 字符）")


if __name__ == "__main__":
    main()
