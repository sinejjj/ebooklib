# -*- coding: utf-8 -*-
"""生成「内置豆瓣评分包」：让下载这个工具、但没有豆瓣数据的人也能看到评分。

抓豆瓣 Top250 + 若干高频标签的高分榜（每标签前 100 本），
按书名+作者去重，输出 scripts/douban_pack.json 供构建时内嵌进网页。

只读：不碰任何书库文件，只联网读豆瓣公开页面 + 写一个 json。
用法：python scripts/build_douban_pack.py [--limit-pages N]
"""
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "scripts", "douban_pack.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DELAY = (1.8, 2.8)
LONG_EVERY = 40
LONG_SLEEP = 20

TAGS = [
    "小说", "中国文学", "外国文学", "经典", "历史",
    "哲学", "心理学", "科普", "科学", "传记",
    "社会学", "经济学", "艺术", "计算机", "推理",
    "科幻", "随笔", "管理", "政治", "教育",
]

TAG_PAGES = 4      # 每标签 4 页 × 25 = 100 本
TOP_PAGES = 10     # Top250 共 10 页

_n = 0


def get(url):
    global _n
    _n += 1
    if _n % LONG_EVERY == 0:
        time.sleep(LONG_SLEEP)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def clean_author(raw):
    """'(清)曹雪芹 / 人民文学出版社 / ...' -> '曹雪芹'"""
    if not raw:
        return ""
    a = strip_tags(raw).split("/")[0].strip()
    a = re.sub(r"^[\[\(（【][^\]\)）】]*[\]\)）】]\s*", "", a)
    a = re.sub(r"^\[[^\]]*\]\s*", "", a)
    a = re.sub(r"[（(][^）)]*[）)]", "", a)   # 去掉外文原名括注
    a = a.replace("著", "").strip()
    # 多作者：取第一个（"余华 著" / "曹雪芹, 高鹗" / "王小波 等"）
    for sep in ("，", ",", "、", "等", "编", "译"):
        if sep in a:
            a = a.split(sep)[0].strip()
    return a[:24]


def norm_title(t):
    """书名归一化：去副标题、括号内容、标点、空白。"""
    if not t:
        return ""
    t = re.sub(r"\s*[:：]\s*.*$", "", t)
    t = re.sub(r"\s*[—\-]{1,2}\s*.*$", "", t)
    t = re.sub(r"[（(【\[].*?[）)】\]]", "", t)
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    return t.strip().lower()


def parse_list(html, kind):
    """从列表页提取条目。kind: 'top' | 'tag'"""
    out = []
    if kind == "top":
        blocks = re.split(r'<tr class="item">', html)[1:]
    else:
        blocks = re.split(r'<li class="subject-item">', html)[1:]

    for b in blocks:
        m = re.search(r'href="https://book\.douban\.com/subject/(\d+)/"', b)
        if not m:
            continue
        sid = m.group(1)
        mt = re.search(r'title="([^"]+)"', b)
        if not mt:
            continue
        title = strip_tags(mt.group(1))
        if not title:
            continue
        mp = re.search(r'<div class="pub">(.*?)</div>', b, re.S) or \
            re.search(r'<p class="pl">(.*?)</p>', b, re.S)
        author = clean_author(mp.group(1)) if mp else ""
        mr = re.search(r'class="rating_nums">\s*([0-9.]+)\s*<', b)
        rating = float(mr.group(1)) if mr else 0.0
        mv = re.search(r'\(\s*(\d+)\s*人评价', b)
        votes = int(mv.group(1)) if mv else 0
        if rating <= 0:
            continue
        out.append({
            "t": title,
            "a": author,
            "r": round(rating, 1),
            "v": votes,
            "i": sid,
            "nt": norm_title(title),
        })
    return out


def fetch_top():
    items = []
    for p in range(TOP_PAGES):
        url = "https://book.douban.com/top250?start=%d" % (p * 25)
        try:
            h = get(url)
            got = parse_list(h, "top")
            items += got
            print("  Top250 p%d -> %d 本" % (p + 1, len(got)), flush=True)
        except Exception as e:
            print("  Top250 p%d 失败: %s" % (p + 1, e), flush=True)
        time.sleep(random.uniform(*DELAY))
    return items


def fetch_tags():
    items = []
    for tag in TAGS:
        q = urllib.parse.quote(tag)
        n0 = len(items)
        for p in range(TAG_PAGES):
            url = "https://book.douban.com/tag/%s?start=%d&type=T" % (q, p * 25)
            try:
                h = get(url)
                items += parse_list(h, "tag")
            except Exception as e:
                print("  标签 %s p%d 失败: %s" % (tag, p + 1, e), flush=True)
            time.sleep(random.uniform(*DELAY))
        print("  标签 %s -> +%d 本（累计 %d）" % (tag, len(items) - n0, len(items)), flush=True)
    return items


def dedupe(items):
    """同 nt 保留评价人数最多的；作者信息补全。"""
    best = {}
    for it in items:
        k = it["nt"]
        if not k:
            continue
        cur = best.get(k)
        if cur is None or it["v"] > cur["v"]:
            best[k] = it
    return sorted(best.values(), key=lambda x: -x["v"])


def main():
    only = None
    if "--limit-pages" in sys.argv:
        global TAG_PAGES
        TAG_PAGES = int(sys.argv[sys.argv.index("--limit-pages") + 1])
        only = "small"

    print("抓取豆瓣 Top250 …", flush=True)
    items = fetch_top()
    if not only:
        print("抓取标签高分榜 …", flush=True)
        items += fetch_tags()

    pack = dedupe(items)
    data = {
        "generated_at": time.strftime("%Y-%m-%d"),
        "source": "douban.com Top250 + tag 高分榜",
        "count": len(pack),
        "items": [{"t": x["t"], "a": x["a"], "r": x["r"], "v": x["v"], "i": x["i"]} for x in pack],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT) / 1024
    print("\n已写入 %s\n  条目 %d 本 / %.1fKB / 请求 %d 次" % (OUT, len(pack), size, _n))


if __name__ == "__main__":
    main()
