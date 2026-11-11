# -*- coding: utf-8 -*-
"""生成试点复核页 reports/pilot_review.html

左右对照：原始文件名 → 解析结果 / 豆瓣匹配 / 命名格式 / 一句话
"""
import os
import sys
import json
import html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "books.json")
OUT = os.path.join(ROOT, "reports", "pilot_review.html")

CSS = """
body{font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:#f5f6f8;color:#1f2328;margin:0;padding:20px}
h1{font-size:18px;margin:0 0 4px}
.sub{color:#8b949e;font-size:12px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e6ea;border-radius:8px}
th{background:#f7f8fa;text-align:left;padding:8px 10px;font-size:12px;color:#5b6470;
border-bottom:1px solid #e3e6ea;position:sticky;top:0}
td{padding:7px 10px;border-bottom:1px solid #f0f2f5;font-size:12px;vertical-align:top}
tr:hover td{background:#fafcff}
.raw{font-family:ui-monospace,Consolas,monospace;color:#8b949e;font-size:11px;word-break:break-all}
.tt{font-weight:600}
.au{color:#2f6fd0}
.bad{color:#d93025;font-weight:700}
.ok{color:#1a7f45}
.dim{color:#b8bfc7}
.wrap{max-width:1500px;margin:0 auto}
.kpi{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:14px}
.kpi div{background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:8px 14px}
.kpi b{font-size:17px;display:block}
.kpi span{font-size:11px;color:#8b949e}
"""


def main():
    d = load_json(SRC)
    if not d:
        print("缺少 books.json")
        return
    rows = [b for b in (d.get("books", []) + d.get("scansets", []))
            if b.get("douban_status")]
    if not rows:
        rows = [b for b in (d.get("books", []) + d.get("scansets", []))
                if b.get("_layer")]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    n_ok = sum(1 for b in rows if b.get("douban_status") == "ok")
    n_rated = sum(1 for b in rows if (b.get("douban") or {}).get("rating"))
    n_author = sum(1 for b in rows if b.get("author"))
    n_pending = sum(1 for b in rows if b.get("category") == "待归类·资料杂项")
    n_low = sum(1 for b in rows if (b.get("douban") or {}).get("confidence", 1) < 0.8)

    tr = []
    for b in rows:
        db = b.get("douban") or {}
        st = b.get("douban_status", "")
        conf = db.get("confidence", 0)
        rt = db.get("rating")
        intro = (db.get("intro") or "")
        intro = intro[:90] + ("…" if len(intro) > 90 else "")
        disp = (b["author"] + " · " + b["title"]) if b.get("author") else b["title"]
        stc = "ok" if st == "ok" else ("dim" if st in ("notfound", "skipped") else "bad")
        confc = "bad" if conf < 0.8 else "ok"
        tr.append(
            f"<tr>"
            f"<td class='raw'>{html.escape(b.get('name') or b.get('dir',''))}</td>"
            f"<td class='tt'>{html.escape(b.get('title',''))}</td>"
            f"<td class='au'>{html.escape(b.get('author') or '')}</td>"
            f"<td>{html.escape(db.get('title') or '')}</td>"
            f"<td>{rt if rt else '<span class=dim>—</span>'}</td>"
            f"<td>{db.get('votes') or ''}</td>"
            f"<td class='{confc}'>{conf or ''}</td>"
            f"<td class='{stc}'>{st}</td>"
            f"<td>{html.escape(b.get('category',''))}</td>"
            f"<td class='tt'>{html.escape(disp)}</td>"
            f"<td style='color:#5b6470'>{html.escape(intro)}</td>"
            f"</tr>")

    html_out = f"""<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8>
<title>试点复核 · 本地书库管理</title><style>{CSS}</style></head><body><div class=wrap>
<h1>试点复核对照表</h1>
<div class=sub>原始文件名 → 解析结果 / 豆瓣匹配 / 命名格式。重点看：书名是否对、作者是否对、评分是否抓到。</div>
<div class=kpi>
<div><b>{len(rows)}</b><span>试点条目</span></div>
<div><b>{n_ok}</b><span>豆瓣命中 ok</span></div>
<div><b>{n_rated}</b><span>有评分</span></div>
<div><b>{n_author}</b><span>有作者</span></div>
<div><b>{n_low}</b><span>低置信(&lt;0.8)</span></div>
<div><b>{n_pending}</b><span>待归类</span></div>
</div>
<table><thead><tr>
<th>原始文件名</th><th>解析书名</th><th>作者</th><th>豆瓣标题</th><th>评分</th>
<th>评价数</th><th>置信</th><th>状态</th><th>分类</th><th>显示名</th><th>豆瓣简介(截)</th>
</tr></thead><tbody>{''.join(tr)}</tbody></table>
</div></body></html>"""

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"复核页已生成: {OUT}")
    print(f"  条目 {len(rows)} | ok {n_ok} | 有评分 {n_rated} | 有作者 {n_author} | 低置信 {n_low} | 待归类 {n_pending}")


if __name__ == "__main__":
    main()
