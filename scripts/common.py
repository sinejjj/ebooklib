# -*- coding: utf-8 -*-
"""
书库盘点公共模块：只读守卫 + 文件名解析 + 分类规则.

铁律：本模块及所有调用方，禁止对书库根目录做任何写操作。
"""
import os
import re
import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- 只读守卫

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_CANDIDATES = (
    os.environ.get("EBOOKLIB_CONFIG"),
    os.path.join(ROOT, "config.local.json"),
    os.path.join(ROOT, "config.json"),
    os.path.join(ROOT, "config.example.json"),
)

_cfg = None


def out_html_name(default="我的书库.html"):
    """本机成品页面文件名：只读配置，不校验书库目录。

    公开仓库 clone 后没有 config.local.json 也能安全调用（返回中性默认名）；
    本机有私有配置时返回用户实际在用的文件名，保证「固定入口 / 一键恢复」不失效。
    """
    import json
    for p in CONFIG_CANDIDATES[1:]:
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    return json.load(f).get("out_html") or default
            except (OSError, ValueError):
                pass
    return default


def load_config():
    """加载配置（优先本地私有配置）。只允许读取 workspace 内的配置。"""
    global _cfg
    if _cfg is not None:
        return _cfg
    for p in CONFIG_CANDIDATES:
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
            break
    else:
        raise SystemExit(
            "缺少配置文件：请复制 config.example.json 为 config.local.json，"
            "并填写 source_root（你的书库绝对路径）。"
        )
    root = cfg.get("source_root") or ""
    if not root or not os.path.isdir(root):
        raise SystemExit(f"source_root 不存在或不是目录：{root!r}\n请检查 config.local.json")
    cfg["_root"] = os.path.abspath(root)
    cfg["_root_norm"] = os.path.normcase(cfg["_root"])
    _cfg = cfg
    return cfg


def source_root():
    return load_config()["_root"]


def to_rel(path):
    """绝对路径 → 相对书库根的路径（统一用系统分隔符）。"""
    return os.path.relpath(path, source_root())


def assert_readonly(path):
    """只允许访问书库根目录内的路径（只读语义）。"""
    p = os.path.normcase(os.path.abspath(path))
    rn = load_config()["_root_norm"]
    if not (p == rn or p.startswith(rn + os.sep)):
        raise SecurityError(f"拒绝访问库外路径: {path}")


def assert_not_in_source(dest):
    """反向守卫：任何输出文件都不允许落在书库内。"""
    d = os.path.normcase(os.path.abspath(dest))
    rn = load_config()["_root_norm"]
    if d == rn or d.startswith(rn + os.sep):
        raise SecurityError(f"输出路径落在书库内，已拒绝: {dest}")


class SecurityError(Exception):
    pass


def safe_stat(path):
    assert_readonly(path)
    return os.stat(path)


# ---------------------------------------------------------------- 常量

BOOK_EXT = {
    ".mobi", ".epub", ".pdf", ".azw3", ".azw", ".kfx",
    ".txt", ".doc", ".docx", ".rar", ".zip",
}

# 非书文件（笔记导出、清单、剪报、相机编号、裸序号）
NON_BOOK_RE = re.compile(
    r"(^My Clippings|^已阅书籍|^经典书籍清单|^kindle阅读榜单"
    r"|^IMG_|^DSC|^IMAG|^\d{3,6}$|^CR!|^EBOK|^B[A-Z0-9]{9,}$)",
    re.I,
)

ASIN_RE = re.compile(r"[_\-\s]?B0[A-Z0-9]{8}\S*$", re.I)

SUFFIX_RE = re.compile(
    r"(_sample|_copy|_sample\d*|\(\d+\)|（\d+）|kindle正版|kindle版|"
    r"升级版|珍藏版|典藏版|完整图文版|精编图文版|图文版|"
    r"v\d+\.\d+|第\d+版|修订版|白金版|纪念版)$",
    re.I,
)

NOISE_RE = re.compile(r"(【中亚】|\[中亚\]|通俗说\S*|tongsushuo\.com|www\.\S+|\.com)", re.I)

VOL_RE = re.compile(r"[（(]\s*([一二三四五六七八九十\d]+)\s*[）)]\s*$")

# 卷册样式的括号：内容仅为数字/中文数字，如 （三）(2)
VOL_BRACKET_RE = re.compile(r"^[\d一二三四五六七八九十]{1,3}$")

COLLECTION_RE = re.compile(
    r"(套装|全集|全[一二三四五六七八九十\d]+册|合集|合订|三部曲|四部曲|系列|共\d+册)"
)

# 尾随的出版信息括号：（古典名著普及文库）（插图本）（精装版）
EDITION_BRACKET_RE = re.compile(
    r"\s*[（(](?:[^（）()]*?(?:文库|出版社|出版|插图|精装|平装|修订|校注|注译|"
    r"全\d|上下|典藏|珍藏|完整|图文|双语?|英文|中文)[^（）()]*?)[）)]\s*$"
)

# 判定作者侧的标记：国籍括号 / 角色词 / 作者前缀
# 注意：纯数字/中文数字的括号（卷册号）不算国籍标记
AUTHOR_MARK_RE = re.compile(
    r"(\[|\(|（|【)(?![\d一二三四五六七八九十]{1,3}\s*[\]\)）】])[^\]\)）】]{1,10}(\]|\)|）|】)"
    r"|(?:,|，|\s)*(?:著|译|编|绘|整理|主编|原著|撰|口述|选编|编译)$"
    r"|作者[:：]|译者[:：]"
)

# 全角/半角标点与书名号
PUNCT_RE = re.compile(r"[《》〈〉「」『』【】\[\]()（）·、，,。．.：:；;！!？?~～\-－_—\"'’“”]")


# ---------------------------------------------------------------- 解析


def strip_ext(name):
    return os.path.splitext(name)[0]


def parse_filename(name):
    """把文件名解析成结构化字段。

    返回 dict: title / author / author_from / volume / series /
               is_collection / asin / raw
    """
    raw = name
    s = strip_ext(name)
    # 双扩展名兜底：xxx.mobi.mobi —— 只剥真实电子书扩展名，
    # 不用 strip_ext 盲拆（否则 Example.Effect.2007 / 示例书名.J.K.示例作者 会被拆烂）
    for _ in range(2):
        t2 = re.sub(r"\.(mobi|epub|azw3?|prc|pdf|txt|docx?|chm|rtf|html?)$", "", s, flags=re.I)
        if t2 == s:
            break
        s = t2

    asin = None
    m = ASIN_RE.search(s)
    if m:
        asin = m.group(0).strip("_- ")
        s = s[: m.start()]

    # 版本后缀（仅尾部，反复剥离）
    for _ in range(3):
        m2 = SUFFIX_RE.search(s)
        if not m2:
            break
        s = s[: m2.start()]
    s = NOISE_RE.sub("", s)

    # 尾随出版信息括号：（古典名著普及文库）（插图本）
    for _ in range(3):
        me = EDITION_BRACKET_RE.search(s)
        if not me:
            break
        s = s[: me.start()]

    # 卷册号
    volume = None
    mv = VOL_RE.search(s)
    if mv:
        volume = mv.group(1)
        s = s[: mv.start()]

    s = s.strip(" -_·")

    # 《书名》只出现在括号注解内时，不能拿注解里的书名当主书名
    # （「冯唐：小通鉴（…一堂《资治通鉴》的管理课）」≠《资治通鉴》）。
    # 真书名通常是括号外主干：取第一个（之前的主干 + 最后一个）之后的残余。
    paren_title = None
    author_cand = None
    if "《" in s:
        masked = re.sub(
            r"（[^（）]*）|\([^()]*\)",
            lambda m: "\x00" * len(m.group(0)),
            s,
        )
        if "《" not in masked:
            i_open = min([i for i in (s.find("（"), s.find("(")) if i >= 0], default=-1)
            i_close = max(s.rfind("）"), s.rfind(")"))
            head = s[:i_open].strip(" -_·") if i_open >= 0 else ""
            tail = s[i_close + 1:].strip(" -_·") if i_close > i_open else ""
            if head:
                paren_title = head
                author_cand = pick_from_candidates(tail)
                if author_cand and len(author_cand) > 24:
                    author_cand = None
            else:
                # 括号打头（书名号全在括号内且没有主干）：剥括号后按普通规则解析
                s = re.sub(r"（[^（）]*）|\([^()]*\)", " ", s)
                s = re.sub(r"\s{2,}", " ", s).strip(" -_·")

    # 丛书前缀：示例丛书·第08卷·示例分册…
    series = None
    parts = re.split(r"[·‧•]", s)
    if len(parts) >= 3 and re.search(r"\d", parts[1]):
        series = f"{parts[0].strip()}·{parts[1].strip()}"
        s = "·".join(parts[2:]).strip(" ·")
    elif len(parts) == 2 and re.search(r"\d", parts[0]) and len(parts[0]) < 20:
        series = parts[0].strip()
        s = parts[1].strip(" ·")

    author = None
    author_from = "unknown"

    # A: 前缀《书名》后缀  —— 示例作者《示例大典2》
    m = re.match(r"^(.*?)《(.+?)》(.*)$", s)
    if m:
        pre, book, post = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        title = book
        cand = pre or post
        cand = pick_from_candidates(cand)
        if cand and len(cand) <= 24:
            author = cand
            author_from = "filename"
    else:
        # B: 《书名》  郑念
        m2 = re.match(r"^《(.+?)》\s*(.*)$", s)
        if m2:
            title = m2.group(1).strip()
            cand = pick_from_candidates(m2.group(2).strip())
            if cand and len(cand) <= 24:
                author = cand
                author_from = "filename"
        else:
            # C: 单连字符分隔
            mh = re.match(r"^(.+?)\s*[-－—]\s*(.+)$", s)
            if mh:
                x, y = mh.group(1).strip(), mh.group(2).strip()
                author = pick_author_side(x, y)
                title = (x if author == y else y)
                author_from = "filename"
            else:
                # D: 2+ 空格分隔
                segs = [x for x in re.split(r"\s{2,}|\u3000+", s) if x]
                if len(segs) >= 2:
                    author = min(segs, key=len)
                    title = max(segs, key=len)
                    author_from = "filename"
                else:
                    title = s
            title = strip_ext(title).strip()

    # 括号注解型文件名：用括号外主干覆盖链式解析结果
    if paren_title is not None:
        title = paren_title
        if author_cand:
            author = author_cand
            author_from = "filename"
        else:
            author = None

    # 「作者：书名」前缀去重（C 路径会把「冯唐：小通鉴」整体当书名）
    if author:
        for _sep in ("：", ":"):
            if title.startswith(author + _sep):
                title = title[len(author) + len(_sep):].strip()
                break

    # 标题尾部的卷册号：七侠五义（三） → 七侠五义 + 卷=三
    mv2 = VOL_RE.search(title)
    if mv2:
        volume = volume or mv2.group(1)
        title = title[: mv2.start()]

    is_collection = bool(COLLECTION_RE.search(title)) or ("+" in title)

    if author:
        author = normalize_author(author)

    return {
        "title": title.strip(),
        "author": author,
        "author_from": author_from,
        "volume": volume,
        "series": series,
        "is_collection": is_collection,
        "asin": asin,
        "raw": raw,
    }


def pick_from_candidates(cand):
    """候选作者串清洗：拆 ' - ' 去重、拆多空格取最短。"""
    if not cand:
        return None
    # 《示例书名》[某] 示例作者 - [某] 示例作者
    halves = [h.strip() for h in re.split(r"\s+[-－—]\s+", cand) if h.strip()]
    if len(halves) == 2:
        a, b = normalize_author(halves[0]), normalize_author(halves[1])
        if a and a == b:
            cand = halves[0]
        else:
            # 两段不同：取更像作者的（有国籍标记或更短）
            cand = halves[0] if AUTHOR_MARK_RE.search(halves[0]) else min(halves, key=len)
    segs = [x.strip() for x in re.split(r"\s{2,}|\u3000+", cand) if x.strip()]
    if len(segs) >= 2:
        cand = min(segs, key=len)
    return cand.strip() if cand else None


def pick_author_side(x, y):
    """单连字符分隔时判定哪一侧是作者。"""
    mx = AUTHOR_MARK_RE.search(x)
    my = AUTHOR_MARK_RE.search(y)
    if mx and not my:
        return x
    if my and not mx:
        return y
    # 回退：短者为作者
    if len(x) <= len(y) and len(x) <= 14:
        return x
    return y


def normalize_author(a):
    """作者归一化：去国籍括号、去音译括号、去角色词。"""
    if not a:
        return a
    # 去前缀 作者:/译者:
    a = re.sub(r"^(作者|译者)\s*[:：]\s*", "", a)
    # 去开头的 [中] / (法) / 【苏】
    a = re.sub(r"^\s*[\[（(【]\s*[^\[\]（）()【】]{1,10}\s*[\]）)】]\s*[.:：\-]?\s*", "", a)
    # 去尾部括号（音译名）
    a = re.sub(r"[\(（][^)）]*[\)）]", "", a)
    # 去译者名（岛田庄司 郭清华译 → 岛田庄司）
    a = re.sub(r"\s+\S{1,10}(?:译|编译|选编|译著)$", "", a)
    # 去角色词及其后内容（大仲马著,李玉民译 → 大仲马）
    a = re.sub(r"(?:,|，|\s)*(?:著|译|编|绘|整理|主编|原著|撰|选编|编译).*$", "", a)
    a = a.replace("·", " ")
    a = re.sub(r"\s{2,}", " ", a).strip(" -_,")
    # 作者重复：康斯坦丁 西蒙诺夫 康斯坦丁 西蒙诺夫
    halves = re.split(r"\s{2,}", a)
    if len(halves) == 2 and halves[0].strip() == halves[1].strip():
        a = halves[0].strip()
    return a


CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn2int(s):
    """中文数字转 int，仅支持 0-99 的常见写法。"""
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        return CN_DIGIT.get(a, 1) * 10 + (CN_DIGIT.get(b, 0) if b else 0)
    n = 0
    for ch in s:
        if ch not in CN_DIGIT:
            return None
        n = n * 10 + CN_DIGIT[ch]
    return n


def volume_label(name):
    """从文件名识别分卷标识，返回 (归一化键, 可读标签) 或 None。

    「上下册」「套装」「共N册」是整套描述，不算分卷标记。
    用于把《XX全集 第3卷》与《XX全集 第7卷》拆成不同条目。
    """
    s = os.path.splitext(name)[0]
    # 先剔除整套描述，避免「（上下册）」被当作「上」卷
    s = re.sub(r"[上中下]{2,}\s*[册卷部]?|套装|全[一二三四五六七八九十\d]*[册卷]|共\s*\d+\s*[册卷]", "", s)

    # 卷标记后面不能再跟汉字，否则「第五部队」会被当成「第五部」
    m = re.search(r"第\s*(\d+|[一二三四五六七八九十百]+)\s*([卷册部辑篇集])(?![\u4e00-\u9fff])", s)
    if m:
        n = _cn2int(m.group(1))
        if n is not None:
            return f"{m.group(2)}{n}", m.group(0).replace(" ", "")

    m = re.search(r"[（(]\s*([上中下])\s*[）)]|([上中下])\s*[卷册]", s)
    if m:
        u = m.group(1) or m.group(2)
        return u, m.group(0).replace(" ", "")

    # 中文数字括号卷号：七侠五义（二）/（三）。阿拉伯数字 (1)(2) 多为副本编号，不动。
    m = re.search(r"[（(]\s*([一二三四五六七八九十]{1,3})\s*[）)]", s)
    if m:
        n = _cn2int(m.group(1))
        if n is not None:
            return f"卷{n}", m.group(0).replace(" ", "")

    m = re.search(r"\b(?:Vol|VOL|vol)\.?\s*(\d+)\b", s)
    if m:
        return f"卷{int(m.group(1))}", m.group(0)
    return None


def norm_key(title):
    """重名分组键：去标点书名号间隔号空白后小写。"""
    if not title:
        return ""
    s = ASIN_RE.sub("", title)
    s = PUNCT_RE.sub("", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()


# ---------------------------------------------------------------- 分类

CATEGORIES = [
    "文学·小说",
    "历史·地理",
    "商业·经济·管理",
    "心理·认知·思维",
    "设计·艺术·摄影",
    "传记·回忆录·口述",
    "政治·哲学·军事",
    "社会·纪实·新闻",
    "个人成长·方法论",
    "科学·技术·自然",
    "科幻·奇幻",
    "推理·悬疑",
    "待归类·资料杂项",
]

# 目录 -> 分类 映射
DIR_CATEGORY = {
    "1 文学": "文学·小说",
    "1 文学、小说": "文学·小说",
    "小说其他": "文学·小说",
    "2 推理": "推理·悬疑",
    "2 推理、悬疑": "推理·悬疑",
    "3 科幻": "科幻·奇幻",
    "3 科幻、奇幻": "科幻·奇幻",
    "4 历史、社会、纪实": "历史·地理",
    "地理": "历史·地理",
    "5 心理、认知、思维": "心理·认知·思维",
    "6 商业、经济、管理": "商业·经济·管理",
    "商业管理": "商业·经济·管理",
    "互联网思维": "商业·经济·管理",
    "7 设计、艺术、创意": "设计·艺术·摄影",
    "8 科学、技术、自然": "科学·技术·自然",
    "9 个人成长、方法论": "个人成长·方法论",
    "自我提升": "个人成长·方法论",
    "军事": "政治·哲学·军事",
}

# 二级目录（用户导出目录的子目录）信号；词表均为通用分类词，不含任何真实目录名
SUBDIR_CATEGORY = {
    "人物传记": "传记·回忆录·口述",
    "经管": "商业·经济·管理",
    "营销金融": "商业·经济·管理",
    "轻历史": "历史·地理",
    "历史": "历史·地理",
    "政治哲学经典": "政治·哲学·军事",
    "社会科学": "社会·纪实·新闻",
    "心理": "心理·认知·思维",
    "励志": "个人成长·方法论",
    "军事": "政治·哲学·军事",
    "医学": "科学·技术·自然",
}

# ---------------------------------------------------------------- 分类规则
#
# 设计要点（2026-11-09 重构，修掉「李银河 → 科幻」这类误判）：
# 1. 题材关键词只跑【标题】。作者名里的字（李银河/王小波）绝不当题材词。
#    作者单独走「类型作家白名单」，只给 2 分。
# 2. 删掉所有过宽裸词：银河 / 火星 / 宇宙 / 魔法 / 未来世界 / 帝国 / 艺术 / 科学。
#    银河帝国、银河系、银河英雄、火星救援……这类完整词才保留。
# 3. 不再「首个命中即返回」，改为加权投票；目录信号权重最高（用户手工整理可信）。
# 4. 少数极确定主题走 LOCK，直接否决一切泛化词。

# L0：标题命中即锁定（否决其他所有信号）
LOCK_RULES = [
    ("社会·纪实·新闻", r"女性主义|女权|性别研究|社会学|妇女运动"),
    ("心理·认知·思维", r"男女交往|亲密关系|两性关系|恋爱心理|婚姻心理学"),
    ("文学·小说", r"词话|词集|诗集|散文集|小说集"),
]

# L2：标题强关键词（每个命中 4 分，同类最多算 2 次）
TITLE_STRONG = [
    ("推理·悬疑", r"推理|侦探|悬疑|奇案|密室|刑警|法医|犯罪心理|命案|破案|"
                  r"福尔摩斯|阿加莎|东野圭吾|岛田庄司|松本清张|江户川乱步|柯南.?道尔|"
                  r"京极夏彦|占星术杀人|谋杀案"),
    ("科幻·奇幻", r"科幻|奇幻小说|星际|银河帝国|银河英雄|银河系|三体|沙丘|魔戒|"
                  r"霍比特人|哈利.?波特|赛博朋克|时间机器|星舰|异星|流浪地球|太空漫游|"
                  r"火星救援|火星任务|火星孤儿|反乌托邦|外星文明|克隆人|时空穿越"),
    ("传记·回忆录·口述", r"自传|回忆录|口述史|传记|生平|年谱|别传|忏悔录|"
                        r"亲历|牛棚|文革|右派|日记"),
    ("设计·艺术·摄影", r"设计|摄影|绘画|平面|工业设计|建筑|园林|景观|配色|字体|版式|"
                      r"素描|手绘|插画|图案|艺术史|书法|篆刻|"
                      r"rhino|vray|3ds|photoshop|illustrator|indesign|cad"),
    ("心理·认知·思维", r"心理学|心理|认知|思维|大脑|潜意识|情绪|记忆术|专注力|"
                      r"意志力|行为经济学|人格|梦的解析|精神分析|智商|情商"),
    ("商业·经济·管理", r"管理|营销|品牌|战略|金融|投资|股权|创业|谈判|财务|会计|"
                      r"经济学|资本|股市|商业模式|领导力|供应链|销售|广告|货币|债务|"
                      r"房地产|沃尔玛|麦肯锡|公司|企业"),
    ("科学·技术·自然", r"物理学|生物学|数学|化学|医学|海洋|植物|动物|天文|编程|"
                      r"算法|人工智能|基因|量子|生态|解剖|宇宙学|科学史"),
    ("政治·哲学·军事", r"政治|哲学|思想史|军事|战役|武器|军队|马克思|自由主义|"
                      r"民主|宗教|文明冲突|国际关系|外交|孙子兵法|兵法"),
    ("历史·地理", r"通史|断代|王朝|朝代|考古|简史|史话|演义|史纲|历史|地理|地图|"
                  r"丝绸之路|抗日战争|世界大战|近代史|古代史"),
    ("个人成长·方法论", r"成长|方法论|时间管理|学习方法|职场|效率|演讲|整理术|"
                      r"断舍离|拖延|习惯|沟通|读书|笔记|写作|自我提升"),
    ("社会·纪实·新闻", r"社会|纪实|调查|田野|报告文学|新闻|民族|乡土|阶层|城市化|"
                      r"教育|贫困|女性|劳工|监狱|医疗"),
    ("文学·小说", r"小说|文集|全集|选集|散文|随笔|诗词|词话|词集|戏剧|诗集|短篇|"
                  r"长篇|三部曲|言情|武侠|剧本|文选|童话|寓言|诗歌|文学"),
]

# L2b：类型作家白名单（只跑作者字段，2 分）
AUTHOR_RULES = [
    ("推理·悬疑", r"阿加莎|东野圭吾|岛田庄司|松本清张|江户川乱步|柯南.?道尔|"
                  r"京极夏彦|绫辻行人|钱德勒|埃勒里.?奎因"),
    ("科幻·奇幻", r"刘慈欣|阿西莫夫|托尔金|J\.?K\.?罗琳|阿瑟.?克拉克|弗兰克.?赫伯特|"
                  r"菲利普.?迪克|特德.?姜|道格拉斯.?亚当斯|莱姆|弗诺.?文奇|"
                  r"丹.?西蒙斯|田中芳树"),
    ("文学·小说", r"王小波|余华|莫言|村上春树|马尔克斯|博尔赫斯|卡尔维诺|鲁迅|"
                  r"张爱玲|金庸|古龙|亦舒|琼瑶|三毛|王国维"),
]

# L3：弱词（同类固定 2 分，只算一次）。保证覆盖面，但压不过目录(5/6)与强词(4)。
# 不含「银河 / 火星 / 女性 / 心理」这类高危裸词。
TITLE_WEAK = [
    ("科幻·奇幻", r"宇宙飞船|外星人|时空|飞船|星球"),
    ("历史·地理", r"帝国|古代|近代|世纪|王朝|皇帝|民国"),
    ("个人成长·方法论", r"人生|自我|修行|激励|励志|成功|改变自己"),
    ("科学·技术·自然", r"自然|技术|科学|药|工程"),
    ("政治·哲学·军事", r"战争|制度|国家|政府|权力|革命"),
    ("设计·艺术·摄影", r"艺术|创意|视觉|美学|色彩|展示"),
    ("社会·纪实·新闻", r"医疗|教育|城市|乡村|人口"),
    ("商业·经济·管理", r"经济|财富|生意"),
    ("心理·认知·思维", r"记忆|专注|意识|性格"),
    ("文学·小说", r"传奇|史诗|叙事|读物"),
    ("传记·回忆录·口述", r"杂忆|往事|岁月"),
    ("推理·悬疑", r"犯罪|谜案|凶案"),
]

# L4：豆瓣简介投票 (分类, 强词 3 分, 弱词 1 分)；同类只取最高档一次。
# 泛词（历史/故事/制度/市场/公司…）只能当佐证，绝不能单独定类。
INTRO_RULES = [
    ("科幻·奇幻", r"科幻小说|科幻作品|奇幻小说|赛博朋克|反乌托邦|外星文明|星际旅行",
     r"未来世界|宇宙飞船|魔法"),
    ("推理·悬疑", r"推理小说|侦探小说|悬疑小说|本格推理|密室",
     r"凶手|案件|谋杀|悬疑"),
    ("传记·回忆录·口述", r"自传|回忆录|口述史|人物传记",
     r"生平|亲历|年谱"),
    ("心理·认知·思维", r"心理学|认知科学|精神分析|行为经济学",
     r"大脑|思维|行为|情绪"),
    ("商业·经济·管理", r"商业模式|经济学|管理学|营销学",
     r"企业|公司|市场|竞争|管理|营销|金融|投资|商业"),
    ("政治·哲学·军事", r"政治学|哲学史|战争史|国际关系",
     r"政治|哲学|战争|军事|制度|国家"),
    ("科学·技术·自然", r"物理学|生物学|宇宙学|自然科学|科学史",
     r"科学|技术|医学|自然"),
    ("历史·地理", r"通史|断代史|文明史|历史著作|考古",
     r"历史|王朝|世纪|地理"),
    ("社会·纪实·新闻", r"社会学|报告文学|田野调查|纪实文学",
     r"社会|纪实|调查|阶层|乡土"),
    ("个人成长·方法论", r"时间管理|方法论|自我成长",
     r"效率|职场|习惯|沟通|成长"),
    ("设计·艺术·摄影", r"设计史|艺术史|摄影集|建筑史",
     r"设计|艺术|摄影|绘画|视觉"),
    ("文学·小说", r"小说|散文集|诗集|文学批评|文学史|词话|长篇|短篇",
     r"散文|诗歌|主人公"),
]

# 兼容旧引用（内容已换成收紧后的强词表）
P1_RULES = TITLE_STRONG

# 平票裁决：文学·小说是兜底大类，排最后，避免通吃
TIE_ORDER = [c for c in CATEGORIES if c != "文学·小说"] + ["文学·小说"]


def _bump(scores, cat, n):
    scores[cat] = scores.get(cat, 0) + n


def classify(title, author, dir_hint, subdir_hint, intro="", path_parts=None):
    """加权投票分类（确定性、可重放）。

    权重：LOCK 直接返回 > 目录 6/5 > 标题强词 4~8 > 作者白名单 2
          > 标题弱词 1~2 > 简介 2。总分需 >= 2 才定类，否则待归类。
    题材关键词只看标题；作者只看类型作家白名单。平票按 CATEGORIES 顺序。
    """
    t = title or ""
    a = author or ""

    # L0 显式锁定：否决一切泛化词
    for cat, pat in LOCK_RULES:
        if re.search(pat, t, re.I):
            return cat, "lock"

    sc = {}
    has_dir = False
    has_strong = False
    has_intro = False

    # L1 目录信号（用户手工整理，权重最高）
    for p in (path_parts or []):
        if p in SUBDIR_CATEGORY:
            _bump(sc, SUBDIR_CATEGORY[p], 6)
            has_dir = True
    if subdir_hint and subdir_hint in SUBDIR_CATEGORY:
        _bump(sc, SUBDIR_CATEGORY[subdir_hint], 6)
        has_dir = True
    if dir_hint and dir_hint in DIR_CATEGORY:
        _bump(sc, DIR_CATEGORY[dir_hint], 5)
        has_dir = True

    # L2 标题强词：绝不把作者名拼进来
    for cat, pat in TITLE_STRONG:
        hits = len(re.findall(pat, t, re.I))
        if hits:
            _bump(sc, cat, 4 * min(hits, 2))
            has_strong = True

    # L2b 类型作家白名单
    for cat, pat in AUTHOR_RULES:
        if re.search(pat, a, re.I):
            _bump(sc, cat, 2)

    # L3 弱词：同类只算一次
    for cat, pat in TITLE_WEAK:
        if re.search(pat, t, re.I):
            _bump(sc, cat, 2)

    # L4 简介：强词 3 分 / 弱词 1 分，同类只取最高档
    snippet = intro[:400] if intro else ""
    if snippet:
        for cat, strong, weak in INTRO_RULES:
            if re.search(strong, snippet, re.I):
                _bump(sc, cat, 3)
                has_intro = True
            elif re.search(weak, snippet, re.I):
                _bump(sc, cat, 1)
                has_intro = True

    if not sc:
        return "待归类·资料杂项", "pending"
    best = max(sc.values())
    # 阈值 2：简介泛词只有 1 分，单独不足以定类；作者白名单/强词/目录才够。
    if best < 2:
        return "待归类·资料杂项", "pending"
    win = next((c for c in TIE_ORDER if sc.get(c) == best), None)
    if not win:
        return "待归类·资料杂项", "pending"

    src = ("dir" if has_dir and sc.get(win, 0) >= 5 else
           "keyword" if has_strong and sc.get(win, 0) >= 4 else
           "intro" if has_intro else "vote")
    return win, src


# ---------------------------------------------------------------- 工具


def human_size(n):
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path, obj):
    """原子写：临时文件 + os.replace。断言输出绝不落在书库内。"""
    assert_not_in_source(path)
    tmp = path + ".tmp"
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


import json  # noqa: E402  (放在此处避免影响上方默认值可读性)
