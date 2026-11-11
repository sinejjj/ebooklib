# -*- coding: utf-8 -*-
"""阶段1/2：抓取豆瓣评分 / 作者 / 简介。

关键设计（修复 id 串号）：
- 回填只按「相对路径 rel」，绝不按 id；enriched 文件内不出现任何 bNNNNN id。
- 缓存内容寻址（q: / id:），离线可完整重放。
- --offline 永不联网；--online 只补 needs_network 缺口。

用法：
    python scripts/fetch_douban.py --offline      # 只用缓存重算（不联网）
    python scripts/fetch_douban.py --online [--batch N]   # 补抓缺口
    python scripts/fetch_douban.py --retry        # 重试失败项
    python scripts/fetch_douban.py --fix          # 重抓未命中/低置信
    python scripts/fetch_douban.py --full         # 首次全量
"""
import os
import re
import sys
import json
import time
import random
import difflib
import urllib.parse
import urllib.request
import html as htmlmod

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import dump_json, load_json  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "books.raw.json")
ENRICHED = os.path.join(ROOT, "data", "douban_enriched.json")
CACHE = os.path.join(ROOT, "data", "douban_cache.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

SUGGEST_URL = "https://book.douban.com/j/subject_suggest?q="
DETAIL_URL = "https://book.douban.com/subject/{}/"

SUGGEST_DELAY = (0.6, 1.1)
DETAIL_DELAY = (1.2, 2.0)
LONG_SLEEP_EVERY = 200
LONG_SLEEP = 15
EMPTY_TTL = 7 * 86400

THRESHOLD = 0.60
SUSPECT_SIM = 0.50


class MissingQuery(Exception):
    pass


# ---------------------------------------------------------------- 网络

_nreq = 0


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def throttle(kind):
    global _nreq
    lo, hi = SUGGEST_DELAY if kind == "s" else DETAIL_DELAY
    time.sleep(random.uniform(lo, hi))
    _nreq += 1
    if _nreq % LONG_SLEEP_EVERY == 0:
        print(f"    [限速] 已请求 {_nreq} 次，休眠 {LONG_SLEEP}s", flush=True)
        time.sleep(LONG_SLEEP)


class CacheOnlyLookup:
    """离线查找：只读缓存，缺查询抛 MissingQuery，绝不联网。"""

    def __init__(self, cache):
        self.c = cache

    def suggest(self, q):
        v = self.c.get("q:" + q)
        if v is None:
            raise MissingQuery("q:" + q)
        if isinstance(v, dict) and v.get("__empty__"):
            return []
        return v

    def detail(self, sid):
        k = "id:" + str(sid)
        if k not in self.c:
            raise MissingQuery(k)
        return self.c[k]


class NetworkLookup(CacheOnlyLookup):
    """联网查找：缓存命中即用；未命中才请求并写回缓存。"""

    def suggest(self, q):
        v = self.c.get("q:" + q)
        if isinstance(v, list):
            return v
        if isinstance(v, dict) and v.get("__empty__"):
            if time.time() - v.get("ts", 0) < EMPTY_TTL:
                return []
        for attempt in range(2):
            try:
                throttle("s")
                txt = _get(SUGGEST_URL + urllib.parse.quote(q))
                data = [d for d in json.loads(txt) if d.get("type") == "b"]
                if data:
                    self.c["q:" + q] = data
                else:
                    self.c["q:" + q] = {"__empty__": True, "ts": int(time.time())}
                return data
            except Exception:
                time.sleep(4 * (attempt + 1))
        raise MissingQuery("q:" + q)

    def detail(self, sid):
        k = "id:" + str(sid)
        if k in self.c:
            return self.c[k]
        for attempt in range(3):
            try:
                throttle("d")
                h = _get(DETAIL_URL.format(sid))
                out = parse_detail(h)
                self.c[k] = out
                return out
            except Exception:
                if attempt == 2:
                    self.c[k] = None
                    return None
                time.sleep(5 * (attempt + 1))
        return None


def info_field(h, label):
    """读豆瓣 infobox 的一行：<span class="pl">标签:</span> 值（值可能被 <a> 包裹）<br>。

    豆瓣真实结构示例（出版社被 <a> 包裹，所以旧的 [^<]+ 必然失败）：
        <span class="pl">出版社:</span>
              <a href="https://book.douban.com/press/2287">人民文学出版社</a>
            <br>
        <span class="pl">页数:</span> 990<br/>
    """
    pat = (r'<span class="pl">\s*' + re.escape(label) + r'\s*[:：]\s*</span>'
           r'(.*?)(?:<br\s*/?>|</div>)')
    m = re.search(pat, h, re.S)
    if not m:
        # 兜底：老写法（值紧跟 span、无 <a>）
        m = re.search(r'class="pl">\s*' + re.escape(label) + r'\s*[:：]\s*</span>\s*([^<\n]+)', h)
    if not m:
        return None
    s = re.sub(r"<[^>]+>", " ", m.group(1))       # 剥标签，多个 <a> 用空格分隔
    s = htmlmod.unescape(s).replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s).strip(" :：、/")
    return s or None


def info_pages(h):
    """页数取整数：支持「990」「1,024页」「990 页」，无意义值返回 None。"""
    v = info_field(h, "页数")
    if not v:
        return None
    digits = re.sub(r"[^\d]", "", v)
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    return n if 0 < n <= 100000 else None


def parse_detail(h):
    rating = None
    m = re.search(r'class="ll rating_num"[^>]*>\s*([0-9.]+)\s*<', h)
    if m:
        try:
            rating = float(m.group(1))
        except ValueError:
            rating = None
    votes = None
    m = re.search(r'property="v:votes">\s*(\d+)', h)
    if m:
        votes = int(m.group(1))
    intro = None
    m = re.search(r'<div class="intro">(.*?)</div>', h, re.S)
    if m:
        intro = re.sub(r"<[^>]+>", "", m.group(1))
        intro = htmlmod.unescape(intro)
        intro = re.sub(r"\s+", " ", intro).strip()
    year = info_field(h, "出版年")
    publisher = info_field(h, "出版社") or info_field(h, "出品方")
    if publisher and len(publisher) > 60:
        publisher = publisher[:60]
    pages = info_pages(h)
    author = None
    m = re.search(r"作者</span>:?\s*<a[^>]*>([^<]+)</a>", h)
    if m:
        author = m.group(1).strip()
    cover = None
    m = re.search(r'property="og:image" content="([^"]+)"', h)
    if m:
        cover = m.group(1).strip()
    return {"rating": rating, "votes": votes, "intro": intro,
            "year": year, "publisher": publisher, "pages": pages,
            "author": author, "cover": cover}


def sentinel_blocked():
    try:
        txt = _get(SUGGEST_URL + urllib.parse.quote("活着"))
        data = [d for d in json.loads(txt) if d.get("type") == "b"]
        return len(data) == 0
    except Exception:
        return True


# ---------------------------------------------------------------- 匹配

def clean_author(a):
    if not a:
        return a
    s = str(a).strip()
    s = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", s)
    s = re.sub(r"^\s*[\[（(【][^\]）)】]{1,10}[\]）)】]\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,，")
    return s


def core(t):
    if not t:
        return ""
    s = str(t)
    s = re.split(r"[（(]", s)[0]
    s = re.split(r"[_]", s)[0]
    s = re.split(r"[：:]", s)[0]
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s).lower()
    return s


def title_sim(a, b):
    """书名主干相似度。

    关键修复（2026-11-09）：短书名完整嵌在长书名**结尾**时，
    是「重返X / 重新发现X / 美国X」这类另一部作品，不是同一本书。
    旧版用字符集合相似度给到 0.71，再叠加作者加成 0.35 被截断成 1.0，
    导致《美丽新世界》挂到《重返美丽新世界》上。
    """
    ca, cb = core(a), core(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    lo, hi = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if lo in hi and len(lo) >= 3:
        if hi.startswith(lo):
            # 主干在前、后面是副标题/版本说明（括号已被 core 去掉）→ 同一作品
            return round(0.78 + 0.2 * len(lo) / len(hi), 3)
        # 主干在后、前面多出实词 → 另一部作品，压到阈值以下
        return round(min(0.5, 0.15 + 0.45 * len(lo) / len(hi)), 3)
    sa, sb = set(ca), set(cb)
    return round(len(sa & sb) / max(len(sa | sb), 1), 3)


def author_sim(a, b):
    if not a or not b:
        return None
    na = re.sub(r"[^\w\u4e00-\u9fff]", "", str(a)).lower()
    nb = re.sub(r"[^\w\u4e00-\u9fff]", "", str(b)).lower()
    if not na or not nb:
        return None
    if na in nb or nb in na:
        return 1.0
    return round(difflib.SequenceMatcher(None, na, nb).ratio(), 3)


def pick_best(results, title, author_hint):
    if not results:
        return None, 0.0
    best, best_score = None, -1
    for r in results:
        s = title_sim(title, r.get("title", ""))
        # 作者只能佐证「已经很像」的候选，绝不能把书名不一致的候选救活。
        if author_hint and s >= 0.7:
            ra = re.sub(r"[^\w\u4e00-\u9fff]", "", (r.get("author_name") or "")).lower()
            ha = re.sub(r"[^\w\u4e00-\u9fff]", "", author_hint).lower()
            if ra and ha and (ra in ha or ha in ra):
                s += 0.12
        if r.get("votes"):
            s += 0.02
        if s > best_score:
            best, best_score = r, s
    return best, min(best_score, 1.0)


def queries_for(b):
    t = (b.get("title") or "").strip()
    # 纯书名优先：带作者的查询在豆瓣 suggest 里召回极差，
    # 「美丽新世界 赫胥黎」只会返回《重返美丽新世界》一个候选。
    qs = [t]
    if b.get("author"):
        qs.append(f"{t} {b['author']}")
    main = str(t)
    for pat in (r"[（(]", r"[_]", r"[：:]"):
        main = re.split(pat, main)[0].strip()
    if main and main != t:
        qs.append(main)
        if b.get("author"):
            qs.append(f"{main} {b['author']}")
    if "+" in t:
        qs.append(t.split("+")[0].strip())
    nb = re.sub(r"[（(][^）)]*[）)]", "", t).strip()
    if nb and nb != t:
        qs.append(nb)
    if b.get("series"):
        qs.append(b["series"])
    seen, out = set(), []
    for q in qs:
        q = q.strip()
        if q and len(q) >= 2 and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def judge_suspect(b, info):
    """存疑判定：名称相似度过低且作者也不匹配。"""
    db = info.get("douban") or {}
    if info.get("douban_status") != "ok" or not db.get("title"):
        return False
    sim = title_sim(b.get("title") or "", db.get("title") or "")
    asim = author_sim(b.get("author"), db.get("author"))
    if sim < SUSPECT_SIM and (asim is None or asim < 0.5):
        return True
    return False


def enrich_one(b, lookup):
    info = {
        "id": None, "url": None, "title": None, "author": None,
        "rating": None, "votes": None, "year": None,
        "publisher": None, "pages": None, "intro": None, "cover": None,
        "matched_query": None, "confidence": 0.0,
    }
    fallback = None
    misses = []
    tried = 0
    for q in queries_for(b)[:4]:
        try:
            results = lookup.suggest(q)
        except MissingQuery:
            misses.append("q:" + q)
            continue
        tried += 1
        best, score = pick_best(results, b.get("title") or q, b.get("author"))
        if not best:
            continue
        if score >= THRESHOLD:
            info["id"] = best.get("id")
            info["url"] = best.get("url")
            info["title"] = best.get("title")
            info["author"] = clean_author(best.get("author_name"))
            info["year"] = best.get("year")
            info["matched_query"] = q
            info["confidence"] = round(score, 2)
            try:
                d = lookup.detail(best.get("id"))
            except MissingQuery:
                misses.append("id:" + str(best.get("id")))
                return info, "partial", misses
            if d:
                info["rating"] = d.get("rating")
                info["votes"] = d.get("votes")
                info["intro"] = d.get("intro")
                info["publisher"] = d.get("publisher")
                info["pages"] = d.get("pages")
                info["cover"] = d.get("cover")
                if d.get("author"):
                    info["author"] = clean_author(d["author"])
                if d.get("year"):
                    info["year"] = d["year"]
                return info, "ok", misses
            return info, "partial", misses
        if score >= 0.45 and (fallback is None or score > fallback[1]):
            fallback = (best, score, q)

    if fallback:
        best, score, q = fallback
        info.update({"id": best.get("id"), "url": best.get("url"),
                     "title": best.get("title"),
                     "author": clean_author(best.get("author_name")),
                     "year": best.get("year"),
                     "matched_query": q, "confidence": round(score, 2)})
        return info, "lowconf", misses
    if tried == 0 and misses:
        return info, "pending", misses
    return info, "notfound", misses


# ---------------------------------------------------------------- 主流程

def book_rel(b):
    return b.get("rel") or ""


def refresh_details(cache, batch=None, dry=False, force=False,
                    delay=None, block_sleep=120, max_blocks=10):
    """只重抓缓存里已有的 id: 详情页，把出版社/页数补齐。**只写 cache，不碰 enriched。**

    断点续跑判据 = 「该条详情缺 pages 键」，天然幂等，可任意分批。
    遇到 403/429 视为限流：长睡后重试同一本，不是在条目上记失败。
    """
    import urllib.error
    ids = [k[3:] for k in cache if k.startswith("id:") and isinstance(cache.get(k), dict)]
    todo = []
    for sid in ids:
        d = cache.get("id:" + sid) or {}
        if force or ("pages" not in d) or not d.get("publisher"):
            todo.append(sid)
    todo.sort()
    if batch:
        todo = todo[:batch]

    step = delay if delay else 1.7
    print(f"待刷新详情 {len(todo)} 条   单条约 {step:.1f}s   "
          f"预计 {len(todo) * (step + 1.0) / 60:.0f} 分钟")
    if dry or not todo:
        return

    t0 = time.time()
    ok = fail = 0
    streak = 0
    blocks = 0
    for i, sid in enumerate(todo, 1):
        out = None
        for attempt in range(3):
            try:
                time.sleep(random.uniform(step * 0.8, step * 1.3))
                h = _get(DETAIL_URL.format(sid))
                out = parse_detail(h)
                streak = 0
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    blocks += 1
                    print(f"    [限流 {e.code}] 第 {blocks} 次，休眠 {block_sleep}s", flush=True)
                    time.sleep(block_sleep)
                    if blocks >= max_blocks:
                        print("    [中止] 限流次数过多，已抓到的已落盘，稍后重跑可续。", flush=True)
                        dump_json(CACHE, cache)
                        return
                    continue
                print(f"    [失败] {sid}: HTTP {e.code}", flush=True)
                fail += 1
                streak += 1
                break
            except Exception as e:
                print(f"    [失败] {sid}: {type(e).__name__}", flush=True)
                fail += 1
                streak += 1
                time.sleep(3 * min(streak, 3))
                break

        if out:
            cache["id:" + sid] = out
            ok += 1
        elif out is None and streak == 0:
            fail += 1

        if streak >= 8:
            print("    [中止] 连续失败过多，已抓到的已落盘，稍后重跑可续。", flush=True)
            break

        if i % 20 == 0:
            el = time.time() - t0
            eta = (len(todo) - i) * el / i / 60
            print(f"  [{i}/{len(todo)}] ok {ok} fail {fail}  "
                  f"{el / 60:.1f}min  剩余约 {eta:.0f}min", flush=True)
        if i % 30 == 0:
            dump_json(CACHE, cache)        # 只落 cache

    dump_json(CACHE, cache)
    left = sum(1 for k in cache if k.startswith("id:")
               and isinstance(cache.get(k), dict) and "pages" not in cache[k])
    print("=" * 62)
    print(f"详情刷新完成  耗时 {(time.time() - t0) / 60:.1f} 分钟")
    print(f"  成功 {ok}  失败 {fail}  剩余待刷 {left}")
    print("  下一步：python scripts/fetch_douban.py --offline 把 pages 搬进 enriched")
    print("=" * 62)


def main():
    mode = ("--refresh-detail" if "--refresh-detail" in sys.argv else
            "--refix" if "--refix" in sys.argv else
            "--offline" if "--offline" in sys.argv else
            "--online" if "--online" in sys.argv else
            "--retry" if "--retry" in sys.argv else
            "--fix" if "--fix" in sys.argv else
            "--full" if "--full" in sys.argv else "--offline")
    batch = None
    for i, a in enumerate(sys.argv):
        if a == "--batch" and i + 1 < len(sys.argv):
            batch = int(sys.argv[i + 1])

    raw = load_json(RAW)
    if not raw:
        print("缺少 books.raw.json，先运行 scan_library.py")
        return
    cache = load_json(CACHE, {}) or {}

    if mode == "--refresh-detail":
        delay = None
        block_sleep = 120
        max_blocks = 10
        for i, a in enumerate(sys.argv):
            if i + 1 >= len(sys.argv):
                continue
            if a == "--delay":
                delay = float(sys.argv[i + 1])
            elif a == "--block-sleep":
                block_sleep = int(sys.argv[i + 1])
            elif a == "--max-blocks":
                max_blocks = int(sys.argv[i + 1])
        refresh_details(cache, batch=batch,
                        dry="--dry-run" in sys.argv,
                        force="--force" in sys.argv,
                        delay=delay, block_sleep=block_sleep, max_blocks=max_blocks)
        return

    prev = load_json(ENRICHED) or {}
    entries = dict(prev.get("entries") or {})

    lookup = CacheOnlyLookup(cache) if mode == "--offline" else NetworkLookup(cache)

    books = [b for b in raw.get("books", []) if b.get("kind") != "scanset" and book_rel(b)]

    if mode in ("--offline", "--full"):
        targets = books                      # 全量重算
    elif mode == "--online":
        targets = [b for b in books
                   if (entries.get(book_rel(b)) or {}).get("needs_network")]
    elif mode == "--retry":
        targets = [b for b in books
                   if (entries.get(book_rel(b)) or {}).get("douban_status") in ("failed", "partial", None)
                   or (entries.get(book_rel(b)) or {}).get("needs_network")]
    elif mode == "--refix":
        # 定向重修「本地书名主干 ⊂ 豆瓣书名主干且不在开头」的错配
        targets = []
        for b in books:
            db = ((entries.get(book_rel(b)) or {}).get("douban") or {})
            ca, cb = core(b.get("title") or ""), core(db.get("title") or "")
            if not ca or not cb or ca == cb:
                continue
            lo, hi = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
            if len(lo) >= 3 and lo in hi and not hi.startswith(lo):
                targets.append(b)
    else:  # --fix
        targets = [b for b in books
                   if (entries.get(book_rel(b)) or {}).get("douban_status") in ("notfound", "lowconf")]

    if batch:
        targets = targets[:batch]

    print(f"模式 {mode}：{len(targets)} 条")
    if mode == "--fix":
        n0 = len(cache)
        for k in [k for k, v in list(cache.items())
                  if k.startswith("q:") and (v == [] or (isinstance(v, dict) and v.get("__empty__")))]:
            del cache[k]
        print(f"  已清除空缓存 {n0 - len(cache)} 条")
    if mode == "--refix":
        keys = set()
        for b in targets:
            for q in queries_for(b):
                keys.add("q:" + q)
            if b.get("author"):
                keys.add("q:" + f"{(b.get('title') or '').strip()} {b['author']}")
        n0 = len(cache)
        for k in keys:
            cache.pop(k, None)
        print(f"  清除 {n0 - len(cache)} 条旧查询缓存，强制用新匹配规则重查")

    t0 = time.time()
    block_streak = 0
    for i, b in enumerate(targets, 1):
        rel = book_rel(b)
        if mode != "--offline" and i % 40 == 0:
            if sentinel_blocked():
                block_streak += 1
                print(f"    [封禁探测] 哨兵也空（第 {block_streak} 次），休眠 90s", flush=True)
                time.sleep(90)
                if block_streak >= 3:
                    print(f"    [已封禁] 提前结束，已处理 {i}/{len(targets)}。稍后重跑 --online 可续。", flush=True)
                    save(raw, cache, entries)
                    report(targets, entries, time.time() - t0, mode)
                    return
            else:
                block_streak = 0

        info, status, misses = enrich_one(b, lookup)
        # 离线全量重放：单调改进，绝不因为规则升级把已有匹配洗掉
        if mode in ("--offline", "--full") and rel in entries:
            old = entries[rel]
            if old.get("douban_status") == "mismatch":
                continue
            old_db = old.get("douban") or {}
            if old.get("douban_status") == "ok" and old_db.get("title"):
                osim = title_sim(b.get("title") or "", old_db.get("title"))
                nsim = title_sim(b.get("title") or "", info.get("title") or "")
                if status != "ok" or nsim < osim - 0.01:
                    continue
        if mode == "--refix":
            # 保守采纳：只有「抓到详情」且「书名主干比原来更像」才替换，
            # 否则保留原匹配，绝不因为重修把已有评分弄丢。
            old_db = ((entries.get(rel) or {}).get("douban") or {})
            old_sim = title_sim(b.get("title") or "", old_db.get("title") or "")
            new_sim = title_sim(b.get("title") or "", info.get("title") or "")
            if status != "ok" or new_sim < old_sim:
                # 前缀是作者名/丛书名 → 同一部作品，保留；
                # 否则是「重返 / 重新 / 美国 / 克林索尔的」这类另一部作品 → 断开，
                # 宁可显示本地书名 + 无评分，也不挂别书的评分和简介。
                ca, cb = core(b.get("title") or ""), core(old_db.get("title") or "")
                lo, hi = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
                prefix = hi[:hi.index(lo)] if lo and lo in hi else ""
                an = re.sub(r"[^\w\u4e00-\u9fff]", "", (b.get("author") or "")).lower()
                keep = ((an and (an in prefix or prefix in an))
                        or any(x in prefix for x in ("讲史", "文集", "文库", "系列", "丛书")))
                if old_sim < 0.5 and prefix and not keep:
                    entries[rel] = {
                        "douban": {}, "douban_status": "mismatch",
                        "confidence": 0.0, "matched_query": None,
                        "needs_network": False, "suspect": False,
                        "updated_at": int(time.time()),
                    }
                    print(f"  [{i}/{len(targets)}] 断开错配  "
                          f"《{b.get('title')}》 ← 《{old_db.get('title')}》", flush=True)
                else:
                    print(f"  [{i}/{len(targets)}] 保留原匹配  "
                          f"{(b.get('title') or '')[:30]}  (旧 {old_sim:.2f} / 新 {new_sim:.2f})",
                          flush=True)
                continue
        suspects = judge_suspect(b, info)
        if status == "ok":
            needs_net = False
        elif status == "partial":
            needs_net = True
        else:
            needs_net = bool(misses) or status == "pending"
        entries[rel] = {
            "douban": info,
            "douban_status": status,
            "confidence": info.get("confidence") or 0,
            "matched_query": info.get("matched_query"),
            "needs_network": needs_net,
            "suspect": suspects,
            "updated_at": int(time.time()),
        }
        tag = info.get("rating")
        flag = "  [存疑]" if suspects else ""
        print(f"  [{i}/{len(targets)}] {status:9} "
              f"{str(tag) if tag else '-':>4}  {(b.get('title') or '')[:30]}{flag}", flush=True)
        if mode != "--offline" and i % 20 == 0:
            save(raw, cache, entries)

    save(raw, cache, entries)
    report(targets, entries, time.time() - t0, mode)


def save(raw, cache, entries):
    dump_json(CACHE, cache)
    dump_json(ENRICHED, {
        "schema": 2,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_root_name": raw.get("source_root_name"),
        "entries": entries,
    })


def report(targets, entries, elapsed, mode):
    from collections import Counter
    c = Counter((entries.get(book_rel(b)) or {}).get("douban_status", "pending") for b in targets)
    rated = sum(1 for b in targets
                if ((entries.get(book_rel(b)) or {}).get("douban") or {}).get("rating")
                and not (entries.get(book_rel(b)) or {}).get("suspect"))
    sus = sum(1 for b in targets if (entries.get(book_rel(b)) or {}).get("suspect"))
    nn = sum(1 for b in targets if (entries.get(book_rel(b)) or {}).get("needs_network"))
    print("=" * 62)
    print(f"抓取完成  耗时 {elapsed/60:.1f} 分钟  （模式 {mode}）")
    print("=" * 62)
    for k, v in c.most_common():
        print(f"  {k:10} {v}")
    print(f"  有评分     {rated} / {len(targets)}  "
          f"({rated / max(len(targets), 1) * 100:.0f}%)")
    print(f"  存疑       {sus}")
    print(f"  待联网     {nn}")
    print(f"  输出       {ENRICHED}")


if __name__ == "__main__":
    main()
