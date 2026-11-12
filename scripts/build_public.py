# -*- coding: utf-8 -*-
"""生成 GitHub Pages 公开版 docs/index.html。

刻意不 import common、不读 config、不碰 data/：
公开仓库 clone 后没有任何私有数据，本脚本也能直接跑。
真实书单、豆瓣缓存、本地路径一律不参与公开版构建。
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPL = os.path.join(ROOT, "scripts", "app_template.html")
SCAN = os.path.join(ROOT, "scripts", "scan_core.js")
EXACTDUP = os.path.join(ROOT, "scripts", "exactdup.js")
DEMO = os.path.join(ROOT, "scripts", "demo_library.json")
PACK = os.path.join(ROOT, "scripts", "douban_pack.json")
READINGMERGE = os.path.join(ROOT, "scripts", "readingmerge.js")
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "index.html")

# 用 Unicode 转义写，避免检查器自身被隐私扫描规则误判
BAD = ["\u2764", "13\u4e66\u5e93", "mobi\u7535\u5b50\u4e66", "\u5f85\u7406",
       '"my_rating"', '"noteIndex"', '"page_read"', '"my_rate"', '"mine_rating"']
PATH_RE = re.compile(r"[A-Za-z]:[\\/](?![\\/])")  # 盘符路径 C:\/，但放行 http(s):// 协议

END_PUNCT = "。！？…；”』」）)》"


def tidy_intro(s, limit=260):
    """收尾：简介不许停在半截句上（「…堪称中国古代小」这种像假数据）。

    优先切在标点；标点太靠前就补省略号。幂等：已合规的串原样返回。
    """
    if not isinstance(s, str) or not s.strip():
        return s
    t = re.sub(r"\s+", " ", s).strip()
    t = re.sub(r"[.·]{4,}", " ", t).strip()
    # 豆瓣简介末尾自带的「(展开全部)」「(收起)」不是正文，去掉
    t = re.sub(r"[（(]\s*(展开全部|收起)\s*[)）]", "", t).strip()
    if len(t) <= limit and t[-1] in END_PUNCT:
        return t
    head = t[:limit]
    for sep in ("。", "！", "？", "；"):
        i = head.rfind(sep)
        if i >= limit * 0.45:
            return head[: i + 1]
    return head.rstrip("，、；：,· ") + "…"


def main():
    for p in (TMPL, SCAN, EXACTDUP, READINGMERGE, DEMO):
        if not os.path.exists(p):
            raise SystemExit("缺少构建输入：" + p)

    with open(DEMO, "r", encoding="utf-8") as f:
        demo = json.load(f)
    books = demo.get("books") or []
    scans = demo.get("scansets") or []
    if not books:
        raise SystemExit("示例书单为空")
    for b in books + scans:
        if not b.get("sk"):
            raise SystemExit("示例条目缺少 sk：" + str(b.get("title")))
        if "\\" in b["sk"]:
            raise SystemExit("sk 含反斜杠：" + b["sk"])

    # 示例简介统一收尾，杜绝「句子断在半截」的假数据观感（幂等）
    for b in books + scans:
        full = re.sub(r"\s+", " ", ((b.get("douban") or {}).get("intro") or "")).strip()
        one = b.get("oneline") or ""
        # 源数据里的 oneline 是豆瓣简介硬切的前 120 字（结尾「…前沿进展」这种半截句）。
        # 能跟完整简介对上，就换成完整简介的截短版：卡片两行 clamp 自然收尾，点开再看全文。
        if full and one and len(one) >= 100 and full.startswith(one[:30].strip()):
            b["oneline"] = tidy_intro(full, 600)
        elif one:
            b["oneline"] = tidy_intro(one)
        if b.get("intro_short"):
            b["intro_short"] = tidy_intro(b["intro_short"], 600)

    payload = json.dumps(demo, ensure_ascii=False, separators=(",", ":"))
    for bad in BAD:
        assert bad not in payload, "示例数据含禁止特征：" + repr(bad)
    assert not PATH_RE.search(payload), "示例数据含绝对路径"
    payload = payload.replace("</", "<\\/")

    with open(TMPL, "r", encoding="utf-8") as f:
        html = f.read()
    with open(SCAN, "r", encoding="utf-8") as f:
        scan_js = f.read().replace("</", "<\\/")
    with open(EXACTDUP, "r", encoding="utf-8") as f:
        exactdup_js = f.read().replace("</", "<\\/")
    readingmerge_js = ""
    if os.path.exists(READINGMERGE):
        with open(READINGMERGE, "r", encoding="utf-8") as f:
            readingmerge_js = f.read().replace("</", "<\\/")
    assert readingmerge_js, "缺少 scripts/readingmerge.js：阅读清单解析模块未注入"
    pack_js, pack_n = '{"items":[]}', 0
    if os.path.exists(PACK):
        with open(PACK, "r", encoding="utf-8") as f:
            pack_js = f.read().replace("</", "<\\/")
        try:
            pack_n = len(json.loads(pack_js).get("items") or [])
        except Exception:
            pack_n = 0
    html = (html.replace("__LIBRARY_DATA__", payload)
                .replace("__DOUBAN_PACK__", pack_js)
                .replace("__SCAN_JS__", scan_js)
                .replace("__EXACTDUP_JS__", exactdup_js)
                .replace("__READINGMERGE_JS__", readingmerge_js))

    for bad in BAD[:4]:
        assert bad not in html, "成品页面含禁止特征：" + repr(bad)
    for ph in ("__LIBRARY_DATA__", "__DOUBAN_PACK__", "__SCAN_JS__",
               "__EXACTDUP_JS__", "__READINGMERGE_JS__"):
        assert ph not in html, "占位符未替换：" + ph

    os.makedirs(DOCS, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    nojekyll = os.path.join(DOCS, ".nojekyll")
    if not os.path.exists(nojekyll):
        with open(nojekyll, "w", encoding="utf-8"):
            pass

    print("=" * 56)
    print("公开版页面已生成")
    print(f"  示例条目    {len(books)} 本 / {len(scans)} 图册")
    print(f"  前端扫描    {'已注入' if scan_js else '未注入'}")
    print(f"  评分包      {pack_n} 本内嵌（无豆瓣数据时自动补分）")
    print("  隐私断言    0 处泄漏")
    print(f"  输出        {OUT}")
    print("=" * 56)


if __name__ == "__main__":
    main()
