# -*- coding: utf-8 -*-
"""阶段4：把数据内嵌进 app_template.html → 我的书库.html

载荷脱敏：只输出相对路径 rel，绝不包含本地绝对路径。
"""
import os
import re
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, dump_json, human_size, source_root, load_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPL = os.path.join(ROOT, "scripts", "app_template.html")
def out_path():
    """延迟读配置：公开仓库 clone 后没有 config.local.json，import 本模块不能崩。"""
    return os.path.join(ROOT, load_config().get("out_html") or "我的书库.html")


def norm_rel(r):
    """稳定键统一用正斜杠，与前端 walk() 的 rel 口径一致。"""
    return str(r or "").replace("\\", "/")


FAMOUS = os.path.join(ROOT, "data", "famous_authors.txt")
OVR = os.path.join(ROOT, "data", "overrides.json")
MERGED = os.path.join(ROOT, "data", "books.merged.json")
RAW = os.path.join(ROOT, "data", "books.raw.json")
BACKUP = os.path.join(ROOT, "data", "_backup_20261027", "library_final.json")
VOTES_THRESHOLD = 1000
BOOK_EXT = [".mobi", ".epub", ".pdf", ".azw3", ".azw", ".kfx", ".txt", ".doc", ".docx"]


def load_famous():
    names = []
    if not os.path.exists(FAMOUS):
        return names
    with open(FAMOUS, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            names.append(s)
    return names


def norm(s):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", s or "").lower()


def is_famous(author, famous):
    a = norm(author)
    if not author or not a:
        return False
    for n in famous:
        nn = norm(n)
        if not nn:
            continue
        if len(nn) <= 3:
            if a == nn:
                return True
        elif nn in a or a in nn:
            return True
    return False


MARKETING = re.compile(r"^(【[^】]{0,10}】|\[[^\]]{0,10}\]|◎|★|※|☆|▲|\||-|\s)+")


def short_intro(intro, n=400):
    if not intro:
        return ""
    s = re.sub(r"\s+", " ", intro).strip()
    s = re.sub(r"^《[^》]{1,30}》\s*", "", s)
    s = MARKETING.sub("", s).strip()
    for sep in ("。", "！", "？"):
        i = s.find(sep)
        if 12 <= i <= n:
            return s[: i + 1]
    if len(s) <= n:
        return s
    cut = s[:n]
    for sep in ("。", "！", "？", "；", ". "):
        i = cut.rfind(sep)
        if i >= n * 0.35:
            return cut[: i + 1]
    return cut + "…"


def build_idmap():
    """旧顺序 b-id → 稳定 sk，用于前端 localStorage 精确迁移。"""
    old = load_json(BACKUP) or {}
    idmap = {}
    sr = source_root()
    for b in old.get("books", []) + old.get("scansets", []):
        oid = b.get("id")
        if not oid:
            continue
        rel = b.get("rel")
        if not rel:
            p = b.get("path") or (b.get("files") or [{}])[0].get("path") or b.get("dir")
            if p:
                try:
                    rel = os.path.relpath(p, sr)
                except Exception:
                    rel = None
        if rel:
            idmap[oid] = ("dir:" if b.get("kind") == "scanset" else "path:") + rel
    return idmap


SKMAP = os.path.join(ROOT, "data", "skmap.json")


def _ident(b):
    """跨重建的稳定身份：优先豆瓣 id，否则「文件名#体积」。"""
    db = b.get("douban") or {}
    if b.get("douban_status") == "ok" and db.get("id"):
        return "db:" + str(db["id"])
    rel = b.get("rel") or ""
    name = os.path.basename(rel.replace("\\", "/"))
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name
    files = b.get("files") or []
    size = (files[0].get("size") if files else None)
    if size is None:
        size = b.get("size") or b.get("total_size") or 0
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", stem).lower()
    return "f:%s#%s" % (stem, size)


def build_rmap(entries, cur_sks):
    """上次 sk → 本次 sk。只搬 1:1 且旧键已不存在的，避免误并/抢数据。"""
    cur = {}
    dup = set()
    for b in entries:
        sk = b.get("sk")
        if not sk:
            continue
        i = _ident(b)
        if i in cur and cur[i] != sk:
            dup.add(i)
        cur[i] = sk
    for i in dup:
        cur.pop(i, None)          # 一个身份对应多本书 → 不存、不迁，防同名误并

    prev = load_json(SKMAP) or {}
    if not isinstance(prev, dict):
        prev = {}
    rmap = {}
    for i, newsk in cur.items():
        oldsk = prev.get(i)
        if not oldsk or oldsk == newsk:
            continue
        if oldsk in cur_sks:      # 旧键现在是另一本书的身份 → 跳过，绝不能抢它的数据
            continue
        rmap[oldsk] = newsk

    # 链式合成：a→b、b→c 合并成 a→c
    for _ in range(5):
        changed = False
        for k, v in list(rmap.items()):
            if v in rmap and rmap[v] != v:
                rmap[k] = rmap[v]
                changed = True
        if not changed:
            break

    dump_json(SKMAP, cur)
    return rmap, len(dup)


def main():
    if "--public" in sys.argv:
        # 公开版完全不读 data/ 与 config，避免真实书单泄漏
        import build_public
        build_public.main()
        return
    public = False
    src = load_json(MERGED)
    if not src or not src.get("books"):
        src = load_json(RAW)
    if not src:
        print("缺少数据，先运行 scan_library.py / postprocess.py")
        return

    famous = load_famous()
    ovr = load_json(OVR) or {}

    def skey(b):
        return ("dir:" if b.get("kind") == "scanset" else "path:") + norm_rel(b.get("rel"))

    def dbkey(b):
        db = b.get("douban") or {}
        if b.get("douban_status") == "ok" and db.get("id"):
            return "db:" + str(db["id"])
        return None

    def apply(b):
        b["sk"] = skey(b)
        o = ovr.get(b["sk"]) or {}
        if not o:
            dk = dbkey(b)
            if dk:
                o = ovr.get(dk) or {}
        db = b.get("douban") or {}
        author = o.get("author") or b.get("author") or db.get("author") or ""
        votes = db.get("votes") or 0
        fl = is_famous(author, famous)
        by_votes = votes >= VOTES_THRESHOLD
        b["author"] = author
        b["author_famous"] = bool(o.get("author_famous", fl or by_votes))
        b["fame_reason"] = ("both" if (fl and by_votes) else
                            "list" if fl else "votes" if by_votes else "none")
        rating = db.get("rating")
        b["rating"] = rating
        b["votes"] = votes
        b["oneline"] = o.get("oneline") or b.get("oneline") or ""
        b["intro_short"] = short_intro(o.get("oneline") or db.get("intro"))
        if o.get("category"):
            b["category"] = o["category"]
        if o.get("title"):
            b["title"] = o["title"]
        return b

    books = [apply(b) for b in src.get("books", [])]
    scans = [apply(b) for b in src.get("scansets", [])]

    # ---- 脱敏：douban 用白名单，避免私有字段随新增字段裸奔进 payload ----
    DOUBAN_PUBLIC = ("id", "url", "title", "author", "rating", "votes", "year",
                     "publisher", "pages", "intro", "cover", "confidence", "matched_query")

    def clean_douban(db):
        if not isinstance(db, dict):
            return {}
        out = {}
        for k in DOUBAN_PUBLIC:
            v = db.get(k)
            if isinstance(v, str):
                v = v.strip() or None
            out[k] = v
        return out

    out_books = []
    for b in books:
        nb = dict(b)
        for k in ("path", "dir"):
            nb.pop(k, None)
        nb["rel"] = norm_rel(nb.get("rel"))
        nb["sk"] = skey(b)
        nb["douban"] = clean_douban(b.get("douban"))
        nb["files"] = [{"rel": norm_rel(f.get("rel")), "size": f.get("size"),
                        "ext": f.get("ext"), "mtime": f.get("mtime")}
                       for f in (b.get("files") or []) if f.get("rel")]
        out_books.append(nb)
    out_scans = []
    for s in scans:
        ns = {k: v for k, v in s.items() if k not in ("dir", "path")}
        ns["rel"] = norm_rel(ns.get("rel"))
        ns["sk"] = skey(s)
        if ns.get("files"):
            ns["files"] = [dict(f, rel=norm_rel(f.get("rel"))) for f in ns["files"]]
        out_scans.append(ns)

    stats = dict(src.get("stats") or {})
    stats.update({
        "entries": len(out_books) + len(out_scans),
        "rated": sum(1 for b in out_books if b.get("rating")),
        "famous": sum(1 for b in out_books + out_scans if b.get("author_famous")),
        "pending": sum(1 for b in out_books + out_scans if b.get("category") == "待归类·资料杂项"),
        "suspect": sum(1 for b in out_books if b.get("suspect")),
        "no_douban": sum(1 for b in out_books if not b.get("rating")),
    })

    data = {
        "kind": "ebooklib_library_data",
        "schema": 2,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stats": stats,
        "meta": {
            "root_name": None if public else (load_config().get("source_name") or ""),
            "book_ext": BOOK_EXT,
            "counts": {"books": len(out_books), "scansets": len(out_scans)},
        },
        "books": out_books,
        "scansets": out_scans,
    }
    if not public:
        im = build_idmap()
        if im:
            data["idmap"] = im
        # 重扫/重建后 sk 会变（sk 就是相对路径）→ 生成 old_sk→new_sk 迁移表，
        # 让浏览器里的已读/我的评分/进度/笔记跟着搬，不丢
        cur_sks = set(x.get("sk") for x in out_books + out_scans)
        rmap, skipped = build_rmap(out_books + out_scans, cur_sks)
        # 人工补的迁移：标题修正后并入真重名组等 case，自动 ident 比对会因冲突跳过。
        # 只接受「旧键已不存在、新键确实存在」的单向映射，避免抢别本书的数据。
        extra = load_json(os.path.join(ROOT, "data", "rmap_extra.json")) or {}
        for oldsk, newsk in (extra.items() if isinstance(extra, dict) else []):
            if newsk in cur_sks and oldsk not in cur_sks:
                rmap[oldsk] = newsk
        if rmap:
            data["rmap"] = rmap
        print(f"  状态迁移表    {len(rmap)} 条（冲突跳过 {skipped} 条）")

    dump_json(os.path.join(ROOT, "data", "library_final.json"), data)

    with open(TMPL, "r", encoding="utf-8") as f:
        tpl = f.read()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # 私有字段绝不允许进公开载荷（用户评分/进度/笔记/链接只存在浏览器本地）
    for bad in ('"my_rating"', '"noteIndex"', '"noteIndex":', '"ebooklib_library_state',
                '"mubu.com/doc', '"page_read"', '"my_rate"', '"mine_rating"'):
        assert bad not in payload, f"私有字段泄漏到公开载荷: {bad}"
    payload = payload.replace("</", "<\\/")
    scan_path = os.path.join(ROOT, "scripts", "scan_core.js")
    scan_js = ""
    if os.path.exists(scan_path):
        with open(scan_path, "r", encoding="utf-8") as f:
            scan_js = f.read().replace("</", "<\\/")
    exactdup_path = os.path.join(ROOT, "scripts", "exactdup.js")
    exactdup_js = ""
    if os.path.exists(exactdup_path):
        with open(exactdup_path, "r", encoding="utf-8") as f:
            exactdup_js = f.read().replace("</", "<\\/")
    readingmerge_path = os.path.join(ROOT, "scripts", "readingmerge.js")
    readingmerge_js = ""
    if os.path.exists(readingmerge_path):
        with open(readingmerge_path, "r", encoding="utf-8") as f:
            readingmerge_js = f.read().replace("</", "<\\/")
    pack_path = os.path.join(ROOT, "scripts", "douban_pack.json")
    pack_js = '{"items":[]}'
    pack_n = 0
    if os.path.exists(pack_path):
        with open(pack_path, "r", encoding="utf-8") as f:
            pack_js = f.read().replace("</", "<\\/")
        try:
            pack_n = len(json.loads(pack_js).get("items") or [])
        except Exception:
            pack_n = 0
    html = (tpl.replace("__LIBRARY_DATA__", payload)
               .replace("__DOUBAN_PACK__", pack_js)
               .replace("__SCAN_JS__", scan_js)
               .replace("__EXACTDUP_JS__", exactdup_js)
               .replace("__READINGMERGE_JS__", readingmerge_js))
    out = out_path()
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize(out)
    print("=" * 62)
    print("已生成单文件网页图书馆")
    print("=" * 62)
    print(f"  条目        {len(out_books)+len(out_scans)}  (书 {len(out_books)} / 扫描图册 {len(out_scans)})")
    print(f"  有评分      {stats['rated']}")
    print(f"  评分包      {pack_n} 本（供无豆瓣数据的用户自动补分）")
    print(f"  知名作者    {stats['famous']}")
    print(f"  待归类      {stats['pending']}")
    print(f"  存疑        {stats['suspect']}")
    n_pub = sum(1 for b in out_books if (b.get("douban") or {}).get("publisher"))
    n_pg = sum(1 for b in out_books if (b.get("douban") or {}).get("pages"))
    print(f"  出版社      {n_pub} / {len(out_books)}")
    print(f"  页数        {n_pg} / {len(out_books)}")
    print(f"  文件体积    {human_size(size)}")
    print(f"  输出        {out}")


if __name__ == "__main__":
    main()
