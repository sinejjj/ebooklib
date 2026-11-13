/* EbooklibReading —— 「我的阅读清单」纯逻辑模块（零依赖 UMD）
   浏览器挂 window.EbooklibReading；Node 可 require 直接单测。

   职责：
     1) 文本解码（BOM / UTF-8 / UTF-16 / GBK 兜底）
     2) TXT / CSV / TSV / JSON 解析成统一行
     3) 字段归一（中英文常见别名 → 中性字段名）
     4) 书名 / 作者 / ISBN 规范化
     5) 跨来源同一本书的判定与合并（三级优先级，不确定不合并）
     6) 批次指纹（重复导入同一份文件不产生重复书籍）

   约定：本文件所有字段名与提示文案一律中性，不含任何第三方平台名称。
   作者仅用于本人本地管理，不上传。 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.EbooklibReading = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /* ============================================================
     1. 基础文本工具
     ============================================================ */

  /* 全角 ASCII → 半角；统一空白 */
  function toHalf(s) {
    return String(s == null ? '' : s)
      .replace(/[\uFF01-\uFF5E]/g, function (c) {
        return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
      })
      .replace(/\u3000/g, ' ');
  }

  /* 单行化：把换行/制表压成空格，去首尾空白 */
  function cleanInline(s) {
    return String(s == null ? '' : s).replace(/[\r\n\t]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  /* 评价正文：保留换行（便于 AI 读），但压缩多余空白 */
  function cleanComment(s) {
    return String(s == null ? '' : s)
      .replace(/\r\n?/g, '\n')
      .replace(/[ \t]+/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  /* 只放行 http/https 链接，长度截断，避免把奇怪协议或超长串塞进数据 */
  function safeUrl(u) {
    var s = cleanInline(u);
    if (!s) return '';
    if (!/^https?:\/\//i.test(s)) return '';
    return s.slice(0, 600);
  }

  /* 统一标点：书名/作者比较前把所有「看起来一样但字符不同」的写法拉平 */
  function baseNorm(s) {
    var t = toHalf(s);
    t = t.replace(/\s+/g, ' ').trim();
    t = t.replace(/[《》〈〉「」『』“”‘’"']/g, '');
    t = t.replace(/[，、；：]/g, function (c) {
      return { '，': ',', '、': ',', '；': ';', '：': ':' }[c];
    });
    t = t.replace(/[（]/g, '(').replace(/[）]/g, ')')
         .replace(/[【\[]/g, '[').replace(/[】\]]/g, ']');
    return t;
  }

  /* ============================================================
     2. 书名 / 作者 / ISBN 规范化
     ============================================================ */

  var TITLE_CACHE = Object.create(null);
  var AU_CACHE = Object.create(null);

  /* 版本/影视改编注关键词：出现在括号里就整段删掉（它描述的是「同一本书的哪一版 / 哪次改编」）。
     跨平台合并（豆瓣 / 微信读书 / 本地书库各一份）时，丛书名、出版社 imprint 也是同一本书的
     非区分性后缀，必须一并剥掉，否则「血殇（译文纪实）」和「血殇」会被当成两本书。
     只在括号内部触发（normTitle 的括号剥离循环保证了这一点），不会误伤真书名。 */
  var VER_RE = /(版|修订|新版|典藏|精装|平装|插图|彩图|全译|译本|译注|校注|注释|增订|纪念|出版|印刷|套装|全集|文库|原著|电视剧|影视|改编|电影|剧集|剧照|同名|热播|网剧|精校|校订|校勘|汇校|增补|补遗|珍藏|限定|签名|毛边|特装|函套|线装|影印|繁体|简体|横排|竖排|足本|全本|未删节|节选|删节|白话|文言|今译|注音|彩印|图文|缩印|大字|袖珍|口袋|普及|导读|译文纪实|译文经典|世纪文景|文景|甲骨文|汗青堂|理想国|读库|后浪|果麦|新经典|三辉|新民说|汉唐阳光|野草|鹿书|贝贝特|青马|湖岸|雅众|大方|未读|磨铁|紫图|博集天卷|读客|知微|华章|图灵|异步|湛庐|99读书人|译林|知日|知中|蓝狮子|白马时光|记忆坊|酷威|中信|三部曲|四部曲|系列|地球往事|文集|选集|作品集|精选|名家|名著|插图本|彩图本|青少版|少年版|学生版|简写|缩写|节本|藏书|精装版|平装版|大字版|注音版|双语|中英对照|商务印书馆|三联|中华书局|人民文学|上海译文|社会科学文献|广西师大|湖南文艺|十月文艺|南海|新世界|江苏文艺|浙江文艺|北京联合|出版社|出版集团|书局|印社|传媒|文化|书店|丛书|书系|译丛|译库|汉译)/;
  /* 卷次：括号里只有「上/中/下/一/二/…/册/第X卷」这类，属于不同册，必须保留 */
  var VOL_RE = /^(第)?[上中下五六七八九十百千\d]+\s*(册|卷|部|篇|集)?$/;

  /* 纯汉字数字的整标题归一成阿拉伯数字（「一九八四」→「1984」）；
     只处理整串都是数字的情况，不会动到「三体」「一百年的孤独」这类正常书名。 */
  var CN_DIGIT = { '〇': '0', '零': '0', '一': '1', '二': '2', '三': '3',
                   '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9' };
  function cnDigitsOnly(t) {
    if (/^[〇零一二三四五六七八九]+$/.test(t)) {
      return t.split('').map(function (c) { return CN_DIGIT[c]; }).join('');
    }
    return t;
  }

  function normTitle(s) {
    var key = String(s == null ? '' : s);
    var hit = TITLE_CACHE[key];
    if (hit !== undefined) return hit;
    var t = baseNorm(key);
    /* 括号内的版本注 → 删；卷次或其他说明 → 保留 */
    t = t.replace(/\(([^()]{0,30})\)/g, function (m, inner) {
      var v = inner.trim();
      if (VOL_RE.test(v)) return m;
      if (VER_RE.test(v)) return '';
      return m;
    });
    t = t.replace(/\[([^\[\]]{0,30})\]/g, function (m, inner) {
      if (VOL_RE.test(inner.trim())) return m;
      if (VER_RE.test(inner.trim())) return '';
      return m;
    });
    /* 尾部「（全三册）」这类已被上面处理，这里再兜一层空的括号 */
    t = t.replace(/\(\s*\)/g, '').replace(/\[\s*\]/g, '');
    t = t.replace(/\s+/g, ' ').trim().toLowerCase();
    t = cnDigitsOnly(t);
    TITLE_CACHE[key] = t;
    return t;
  }

  /* 作者尾部角色词，出现在末尾就删（「刘慈欣 著」→「刘慈欣」） */
  var AU_TAIL = /[\s]*(著|编著|主编|编|译|绘|等|撰|口述|整理|校注|注|文|图)$/;

  function normAuthor(s) {
    var key = String(s == null ? '' : s);
    var hit = AU_CACHE[key];
    if (hit !== undefined) return hit;
    var t = baseNorm(key);
    /* 开头的国别/朝代括注：[英] （美） ［法］ */
    t = t.replace(/^\s*[\[(]\s*[^\[\]()]{1,8}\s*[\])]\s*/, '');
    /* 拆多名作者后逐个去角色词，再拼回 */
    var parts = t.split(/[,;/]/).map(function (x) {
      return x.replace(AU_TAIL, '').trim();
    }).filter(Boolean);
    t = parts.join(',');
    /* 作者比较时彻底去掉空白（「理查德 ·普雷斯顿」与「理查德·普雷斯顿」、「J. K. 罗琳」与「J.K.罗琳」应视为同一人） */
    t = t.replace(/\s+/g, '').toLowerCase();
    AU_CACHE[key] = t;
    return t;
  }

  function normIsbn(s) {
    var t = toHalf(s).replace(/[^0-9Xx]/g, '').toUpperCase();
    if (t.length === 10) {
      var sum = 0;
      for (var i = 0; i < 10; i++) {
        var d = t.charAt(i) === 'X' ? 10 : parseInt(t.charAt(i), 10);
        if (isNaN(d)) return '';
        sum += d * (10 - i);
      }
      return (sum % 11 === 0) ? t : '';
    }
    if (t.length === 13) {
      if (!/^\d{13}$/.test(t)) return '';
      var s13 = 0;
      for (var j = 0; j < 13; j++) s13 += parseInt(t.charAt(j), 10) * (j % 2 === 0 ? 1 : 3);
      return (s13 % 10 === 0) ? t : '';
    }
    return '';
  }

  /* 评分归一：≤5 视为 5 星制，>5 视为 10 分制折算。返回 {stars, ten} */
  function parseRating(v) {
    var s = cleanInline(v);
    if (!s) return { stars: 0, ten: 0 };
    var m = s.match(/[0-9]+(?:\.[0-9]+)?/);
    if (!m) return { stars: 0, ten: 0 };
    var n = parseFloat(m[0]);
    if (!isFinite(n) || n <= 0) return { stars: 0, ten: 0 };
    if (n > 10) n = 10;
    var stars, ten;
    if (n > 5) {
      ten = Math.round(n * 10) / 10;
      stars = Math.round((n / 2) * 2) / 2;   /* 保留 .5 精度 */
    } else {
      stars = Math.round(n * 2) / 2;
      ten = Math.round(n * 20) / 10;
    }
    if (stars > 5) stars = 5;
    return { stars: stars, ten: ten };
  }

  /* ============================================================
     3. 分类映射：13 类题材，认不出就留空（归「未分类」）
     与 bookclassify.js 保持同一套分类名；那边可用时优先交给它判。
     ============================================================ */

  var CAT_LIST = [
    '文学·小说', '科幻·奇幻', '推理·悬疑',
    '历史·纪实', '地理·旅行', '社会·文化',
    '政治·军事', '哲学·宗教', '心理·认知',
    '商业·经济·管理', '科学·技术·自然', '设计·艺术·摄影',
    '个人成长·方法论'
  ];

  function classifier() {
    if (typeof require === 'function') {
      try { return require('./bookclassify.js'); } catch (e) { /* 浏览器无 require */ }
    }
    var g = (typeof globalThis !== 'undefined') ? globalThis
          : (typeof window !== 'undefined' ? window : null);
    return (g && g.EbooklibClassify) || null;
  }

  function mapCat(raw) {
    var s = cleanInline(raw);
    if (!s || s.length > 24) return '';
    if (CAT_LIST.indexOf(s) >= 0) return s;
    var BC = classifier();
    if (BC) {
      var hit = BC.mapRaw(s);
      if (hit) return hit;
    }
    for (var i = 0; i < CAT_LIST.length; i++) {
      var c = CAT_LIST[i];
      if (c.indexOf(s) >= 0 || s.indexOf(c) >= 0) return c;
      if (s === c.split('·')[0]) return c;
    }
    return '';
  }

  /* ============================================================
     4. 字段别名（全部中性名，中英兼容）
     ============================================================ */

  var ALIAS = Object.create(null);
  function reg(field, list) {
    for (var i = 0; i < list.length; i++) ALIAS[normKey(list[i])] = field;
  }
  function normKey(k) {
    return String(k == null ? '' : k).toLowerCase()
      .replace(/[\s_\-·．.（）()【】\[\]]/g, '');
  }

  reg('title', ['title', 'bookname', 'book_name', 'name', 'book', 'booktitle',
    '书名', '标题', '名称', '图书名称', '书籍名称', '题名', '作品名']);
  reg('author', ['author', 'authors', 'writer', 'creator', 'by',
    '作者', '著者', '作者名', '编写者']);
  reg('isbn', ['isbn', 'isbn13', 'isbn10', 'isbn-13', 'isbn-10', '书号', 'isbn号', 'isbn编码']);
  reg('rate', ['rating', 'rate', 'score', 'stars', 'star', 'myrating',
    '评分', '我的评分', '打分', '星级', '分数', '推荐指数']);
  reg('comment', ['comment', 'comments', 'review', 'note', 'notes', 'remark',
    'summary', 'content', '评价', '短评', '书评', '读后感', '备注', '想法', '摘录', '评论']);
  reg('id', ['id', 'bookid', 'book_id', 'uid', 'sid', '书籍id', '书籍编号', '编号', '标识', '记录id']);
  reg('url', ['url', 'link', 'href', '链接', '地址', '详情页', '详情链接']);
  reg('cat', ['cat', 'category', 'genre', 'tag', 'tags', 'class', 'subject', 'subjects',
    '分类', '类别', '标签', '题材', '图书分类', '书籍分类', '图书类别', '书籍类别',
    '分类名称', '类别名称', '题材分类', '标签列表', '豆瓣分类', '书单分类']);
  reg('read', ['read', 'finished', 'done', 'status', 'isread', '已读', '状态', '读完', '阅读状态']);

  function fieldVal(norm, field) {
    var keys = Object.keys(norm);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (ALIAS[k] === field) {
        var v = norm[k];
        if (v != null && String(v).trim() !== '') return v;
      }
    }
    return '';
  }

  /* ============================================================
     5. 单行 → 记录（含「书名 · 作者」的保守拆分）
     ============================================================ */

  function looksLikeAuthor(s) {
    if (!s) return false;
    if (s.length < 2) return false;                  /* 单字几乎不可能是作者，「达」不该被当成作者 */
    if (s.length > 14) return false;
    if (/[，。：；！？,.:;!?]/.test(s)) return false;
    if (/\s/.test(s) && s.length > 8) return false;
    return true;
  }

  /* hint: 可选函数，判断某段是否是「已知作者」（由调用方用本地书库作者集提供）。
     命中 hint 时拆分最可靠；无 hint 时用保守启发式，宁可整行当书名也不乱拆。 */
  /* 去掉行首编号：「1.书名」「10、书名」「100)书名」。
     只认 1-4 位数字 + 分隔符，1984 / 1Q84 / 三体2 保持原样。 */
  var LEAD_INDEX_RE = /^\d{1,4}\s*[.、．)）]\s*(\S[\s\S]*)$/;
  function stripIndex(s) {
    var t = String(s == null ? '' : s).trim();
    var m = t.match(LEAD_INDEX_RE);
    return m ? m[1].trim() : t;
  }

  function splitName(s, hint) {
    var rawStr = String(s == null ? '' : s).replace(/^[\s\-*•·]+/, '');
    if (!cleanInline(rawStr)) return { title: '', author: '' };
    /* 显式分隔符优先，且必须在压缩空白之前判断（制表符会被压成空格） */
    if (rawStr.indexOf('\t') >= 0) {
      var p = rawStr.split('\t');
      return { title: cleanInline(p[0]), author: cleanInline(p.slice(1).join(' ')) };
    }
    var t = cleanInline(rawStr);
    if (/\s\|\s/.test(t)) {
      var q = t.split(/\s\|\s/);
      return { title: cleanInline(q[0]), author: cleanInline(q.slice(1).join(' ')) };
    }

    /* 「·」只有在旁边带空格时才当分隔符。
       译名本身就用间隔号（达·芬奇密码 / 安娜·卡列尼娜），没有空格时整行按书名处理，
       否则会把「达·芬奇密码」拆成书名「达」+ 作者「芬奇密码」。 */
    var parts = t.split(/(?:\s+·\s*|\s*·\s+)/).map(cleanInline).filter(Boolean);
    if (parts.length < 2) return { title: t, author: '' };

    /* 「作者 · 书名」→ 前 n-1 段是作者；「书名 · 作者」→ 后 n-1 段是作者。
       两位译名内部也含「·」，所以按整段拼接后再判断，而不是只看第一段。 */
    var head = parts.slice(0, -1).join('·');
    var last = parts[parts.length - 1];
    var first = parts[0];
    var rest = parts.slice(1).join('·');

    if (typeof hint === 'function') {
      var hHead = false, hRest = false;
      var hitHint = function (h) {
        if (!h || h.length < 2) return false;        /* 单字段不当作作者 */
        try { return !!hint(h); } catch (e) { return false; }
      };
      hHead = hitHint(head) || hitHint(first);
      hRest = hitHint(rest) || hitHint(last);
      if (hHead && !hRest) return { title: last, author: head };
      if (hRest && !hHead) return { title: first, author: rest };
    }

    /* 无 hint：含「·」的一方是多段人名（译名/合著），更像作者 */
    var headMulti = head.indexOf('·') >= 0, restMulti = rest.indexOf('·') >= 0;
    if (restMulti && !headMulti) return { title: first, author: rest };
    if (headMulti && !restMulti) return { title: last, author: head };

    /* 中文书名与中文人名长度区间重叠，无法可靠区分 →
       只有「一侧短得像人名、另一侧明显不像」时才拆，否则整行当书名，交给 hint 兜底 */
    var headLike = looksLikeAuthor(head), restLike = looksLikeAuthor(rest);
    if (headLike && !restLike) return { title: rest, author: head };
    if (restLike && !headLike && head.length >= 2) return { title: head, author: rest };
    return { title: t, author: '' };
  }

  /* ============================================================
     6. 解析器：TXT / 清单格式 / CSV / JSON
     ============================================================ */

  /* 我们自己导出的清单：## 分组 · N 本 / [0001] 名字 / 评分 X | 我的评分：Y 星 | 我的评价：… */
  function parseListText(text, opts) {
    var hint = opts && opts.authorHint;
    var lines = String(text == null ? '' : text).replace(/^\uFEFF/, '').split(/\r\n|\n|\r/);
    var out = [], curCat = '', last = null, seenItem = false;

    for (var i = 0; i < lines.length; i++) {
      /* 只去首尾空白，保留行内制表符（它是「书名<TAB>作者」的显式分隔符） */
      var raw = lines[i], ln = String(raw).trim();
      if (!ln) continue;

      /* 分组表头 */
      var mCat = ln.match(/^#{1,4}\s*(.+)$/);
      if (mCat) {
        seenItem = true;
        var c = mCat[1].replace(/^已阅\s*·\s*/, '').replace(/\s*·\s*\d+\s*本\s*$/, '').trim();
        curCat = mapCat(c) || '';
        last = null;
        continue;
      }
      if (/^={5,}$/.test(ln)) continue;
      if (/^(生成时间|共\s*\d+|我的阅读|本地书库管理|全渠道)/.test(ln)) continue;

      /* 书条 */
      var mItem = ln.match(/^\[(\d{1,5})\]\s*(.+)$/);
      if (mItem) {
        seenItem = true;
        var rec = splitName(mItem[2], hint);
        if (rec.title) {
          rec.catRaw = curCat;
          out.push(rec);
          last = rec;
        }
        continue;
      }

      /* 书条：纯序号前缀「1.书名」「10、书名」「100)书名」
         只认 1-4 位数字 + 分隔符，1984 / 1Q84 / 三体2 这类真书名不会被切。 */
      var mNum = ln.match(/^(\d{1,4})\s*[.、．)）]\s*(\S[\s\S]*)$/);
      if (mNum) {
        seenItem = true;
        var rec2 = splitName(mNum[2], hint);
        if (rec2.title) {
          rec2.catRaw = curCat;
          rec2.srcId = rec2.srcId || mNum[1];
          out.push(rec2);
          last = rec2;
        }
        continue;
      }

      /* 评分 / 评价行（紧跟在书条后） */
      if (last && /^(评分|Rating|我的评分)/.test(ln)) {
        var rateM = ln.match(/(?:评分|Rating)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)/);
        if (rateM) last.rateRaw = rateM[1];
        var myM = ln.match(/我的评分\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)/);
        if (myM) last.myRateRaw = myM[1];
        var cm = ln.match(/我的评价\s*[:：]\s*([\s\S]*)$/);
        if (cm && cm[1].trim()) last.comment = cm[1].trim();
        /* 评价换行后缩进的续行 */
        var j = i + 1, cont = [];
        while (j < lines.length && /^\s{2,}\S/.test(lines[j]) && !/^\s*\[/.test(lines[j])) {
          cont.push(String(lines[j]).trim());
          j++;
        }
        if (cont.length) {
          last.comment = (last.comment ? last.comment + '\n' : '') + cont.join('\n');
          i = j - 1;
        }
        continue;
      }

      /* 清单格式之外的缩进行，视为上一段说明文字，忽略 */
      if (seenItem && /^\s{2,}/.test(raw)) continue;

      /* 普通一行一本 */
      var r2 = splitName(ln, hint);
      if (r2.title) out.push(r2);
    }
    return out;
  }

  function countDelim(line, d) {
    var n = 0, inQ = false;
    for (var i = 0; i < line.length; i++) {
      var c = line.charAt(i);
      if (c === '"') { inQ = !inQ; continue; }
      if (!inQ && c === d) n++;
    }
    return n;
  }

  function detectDelim(lines) {
    var cands = [',', '\t', ';', '|'], best = ',', bestScore = 0;
    for (var i = 0; i < cands.length; i++) {
      var d = cands[i], counts = [];
      for (var j = 0; j < lines.length; j++) counts.push(countDelim(lines[j], d));
      if (!counts.length) continue;
      var mn = counts[0], mx = counts[0];
      for (var k = 1; k < counts.length; k++) { if (counts[k] < mn) mn = counts[k]; if (counts[k] > mx) mx = counts[k]; }
      if (mn > 0 && mn === mx && mn > bestScore) { bestScore = mn; best = d; }
    }
    return best;
  }

  /* RFC4180 子集：支持引号包裹、"" 转义、\r\n 换行 */
  function parseDelimited(text, delim) {
    var s = String(text == null ? '' : text).replace(/^\uFEFF/, '');
    var out = [], row = [], cur = '', inQ = false, i = 0, n = s.length;
    while (i < n) {
      var c = s.charAt(i);
      if (inQ) {
        if (c === '"') {
          if (s.charAt(i + 1) === '"') { cur += '"'; i += 2; continue; }
          inQ = false; i++; continue;
        }
        cur += c; i++; continue;
      }
      if (c === '"') { inQ = true; i++; continue; }
      if (c === delim) { row.push(cur); cur = ''; i++; continue; }
      if (c === '\r') {
        if (s.charAt(i + 1) === '\n') i++;
        row.push(cur); cur = ''; out.push(row); row = []; i++; continue;
      }
      if (c === '\n') { row.push(cur); cur = ''; out.push(row); row = []; i++; continue; }
      cur += c; i++;
    }
    if (cur !== '' || row.length) { row.push(cur); out.push(row); }
    return out.filter(function (r) {
      for (var k = 0; k < r.length; k++) if (String(r[k]).trim() !== '') return true;
      return false;
    });
  }

  function parseCsv(text) {
    var head0 = String(text == null ? '' : text).replace(/^\uFEFF/, '').split(/\r\n|\n|\r/).slice(0, 5);
    var lines = [];
    for (var i = 0; i < head0.length; i++) if (head0[i].trim()) lines.push(head0[i]);
    var rows = parseDelimited(text, detectDelim(lines));
    if (!rows.length) return [];

    var first = rows[0].map(normKey);
    var hit = 0;
    for (var j = 0; j < first.length; j++) if (first[j] && ALIAS[first[j]]) hit++;

    var out = [];
    if (hit >= 1) {
      for (var r = 1; r < rows.length; r++) {
        var o = {};
        for (var c = 0; c < first.length; c++) {
          if (first[c]) o[first[c]] = rows[r][c];
        }
        out.push(o);
      }
    } else {
      /* 没有表头：退化为「第一列书名，第二列作者」 */
      for (var q = 0; q < rows.length; q++) {
        out.push({ title: rows[q][0], author: rows[q][1] || '' });
      }
    }
    return out;
  }

  function parseJsonText(text) {
    var d = JSON.parse(text);
    var arr = null;
    if (Array.isArray(d)) arr = d;
    else if (d && typeof d === 'object') {
      var keys = ['books', 'items', 'records', 'list', 'data', 'rows', 'result', 'results'];
      for (var i = 0; i < keys.length; i++) {
        if (Array.isArray(d[keys[i]])) { arr = d[keys[i]]; break; }
      }
      if (!arr) arr = [d];
    }
    if (!arr) return [];
    return arr.filter(function (x) { return x && typeof x === 'object'; });
  }

  function mapRow(raw) {
    if (!raw) return null;
    if (typeof raw === 'string') raw = { title: raw };
    var norm = Object.create(null);
    var keys = Object.keys(raw);
    for (var i = 0; i < keys.length; i++) norm[normKey(keys[i])] = raw[keys[i]];

    var title = cleanInline(fieldVal(norm, 'title'));
    if (!title) return null;

    var readRaw = fieldVal(norm, 'read');
    if (readRaw && /想读|未读|在读|unread|todo|wish|plan/i.test(String(readRaw))) return null;

    return {
      title: title,
      author: cleanInline(fieldVal(norm, 'author')),
      isbn: cleanInline(fieldVal(norm, 'isbn')),
      rateRaw: fieldVal(norm, 'rate'),
      myRateRaw: '',
      comment: cleanComment(fieldVal(norm, 'comment')),
      srcId: cleanInline(fieldVal(norm, 'id')),
      url: cleanInline(fieldVal(norm, 'url')),
      catRaw: cleanInline(fieldVal(norm, 'cat'))
    };
  }

  /* 统一入口：按扩展名/内容判格式，返回归一后的行数组 */
  function parseAny(name, text, opts) {
    var body = String(text == null ? '' : text).replace(/^\uFEFF/, '');
    var ext = (String(name || '').split('.').pop() || '').toLowerCase();
    var kind;
    if (ext === 'json') kind = 'json';
    else if (ext === 'csv' || ext === 'tsv') kind = 'csv';
    else if (ext === 'txt' || ext === 'text' || ext === 'md') kind = 'txt';
    else {
      var head = body.replace(/^\s+/, '').slice(0, 1);
      if (head === '{' || head === '[') kind = 'json';
      else {
        var firstLine = body.split(/\r\n|\n|\r/)[0] || '';
        if (countDelim(firstLine, '\t') > 0 || countDelim(firstLine, ',') >= 2) kind = 'csv';
        else kind = 'txt';
      }
    }

    var rows;
    if (kind === 'json') rows = parseJsonText(body);
    else if (kind === 'csv') rows = parseCsv(body);
    else rows = parseListText(body, opts);

    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var r = mapRow(rows[i]);
      if (r && r.title) out.push(r);
    }
    return out;
  }

  /* ============================================================
     7. 记录构造 / 同书判定 / 合并
     ============================================================ */

  function fnv1a(str) {
    var h = 0x811c9dc5;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return ('0000000' + h.toString(16)).slice(-8);
  }

  function fingerprint(text) {
    var s = String(text == null ? '' : text);
    return fnv1a(s) + '-' + s.length.toString(36);
  }

  function newRid(seed) {
    return 'r' + fnv1a(String(seed || '') + ':' + Math.random()) + '-' + Date.now().toString(36);
  }

  /* 行 → 可持久化记录。sid = 本批导入的来源 id */
  function toRecords(rows, sid) {
    var out = [], skipped = 0, now = Date.now();
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      var title = cleanInline(r.title);
      if (!title) { skipped++; continue; }
      var rt = parseRating(r.rateRaw);
      var mine = parseRating(r.myRateRaw);
      var rate = mine.stars || rt.stars;
      var ten = mine.ten || rt.ten;
      out.push({
        rid: newRid(title + '|' + (r.author || '') + '|' + i),
        title: title,
        author: cleanInline(r.author),
        isbn: normIsbn(r.isbn),
        origin: sid || '',
        originUrl: safeUrl(r.url),
        rate: rate,
        rating10: ten,
        comment: cleanComment(r.comment),
        cat: mapCat(r.catRaw),
        sources: sid ? [sid] : [],
        srcIds: (r.srcId && sid) ? [sid + ':' + cleanInline(r.srcId)] : [],
        createdAt: now,
        updatedAt: now
      });
    }
    return { records: out, skipped: skipped };
  }

  function uniq(arr) {
    var out = [], seen = Object.create(null);
    for (var i = 0; i < arr.length; i++) {
      var v = arr[i];
      if (v == null || v === '') continue;
      var k = String(v);
      if (seen[k]) continue;
      seen[k] = 1;
      out.push(v);
    }
    return out;
  }

  /* 卷次标记：括号里只有「上/中/下/数字+册卷」这类不同册，绝不能并入同一本 */
  var _VOL_RE = /(第?\s*[一二三四五六七八九十百千\d]+\s*(册|卷|部|篇|辑)?)|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|(^|[^一-龥])(上|中|下)(卷|册|部|集)?($|[^一-龥])/;
  function hasVolume(t) {
    return _VOL_RE.test(String(t == null ? '' : t));
  }
  /* 宽松匹配的标题核心：在 normTitle 基础上再剥掉所有残留括号（卷次除外，已在 normTitle 保留） */
  function coreTitle(t) {
    return normTitle(t)
      .replace(/[\(\[][^()\[\]]{0,30}[\)\]]/g, '')
      .replace(/\s+/g, ' ').trim();
  }
  var _SUB_SEP = '：:—\-－,，. 。. ';

  /* 宽松键（只用于最后兜底，不用于显示/索引）：
     1) 括注里若正好是该作者名（「超新星纪元（刘慈欣）」）→ 视作作者注记剥掉；
        括注是卷次（上/中/下/第X册）→ 保留，绝不能并不同册；
        其它括注（如「人类简史(知识漫画)」）→ 保留内容，避免误并衍生本。
     2) 去掉所有分隔符（空格/：·—_,，、.()[]），把「银河帝国 基地七部曲」
        「银河帝国：基地七部曲」「银河帝国(基地七部曲)」归一到同一键。
     3) 标题尾部若就是作者名（「超新星纪元·刘慈欣」）→ 剥掉。 */
  function looseKey(t, author) {
    var au = normAuthor(author);
    var s = normTitle(t);
    s = s.replace(/[\(\[]([^()\[\]]{1,30})[\)\]]/g, function (m, inner) {
      if (VOL_RE.test(inner.trim())) return m;            /* 卷次保留 */
      var ni = normAuthor(inner);
      if (au && ni && (ni === au || au.indexOf(ni) >= 0 || ni.indexOf(au) >= 0)) return ''; /* 作者注记 */
      return m;                                           /* 其它括注保留内容 */
    });
    s = s.replace(/[\s:：·・—–－_\-_,，、.。()\[\]]/g, '');
    if (au && s.length > au.length && s.slice(-au.length) === au) s = s.slice(0, -au.length);
    return s;
  }

  /* 作者是否相容：相等，或「较短的是较长的尾段」且较长一方原串含姓名分隔符
     （「普雷斯顿」⊂「理查德·普雷斯顿」、「奥威尔」⊂「乔治·奥威尔」、「罗琳」⊂「J.K. 罗琳」）。
     尾段匹配只对「译名/西文名」（带 · . 空格）启用，避免「春树」误并「村上春树」这类本土名。 */
  function hasNameSep(s) {
    return /[·・.\s]/.test(String(s == null ? '' : s));
  }
  function authorCompatible(aOrig, bOrig) {
    var x = normAuthor(aOrig), y = normAuthor(bOrig);
    if (!x || !y) return true;                       /* 任一方缺作者 → 视为相容 */
    if (x === y) return true;
    var s = x.length <= y.length ? x : y;
    var l = x.length <= y.length ? y : x;
    var lOrig = (x.length <= y.length) ? String(bOrig == null ? '' : bOrig)
                                       : String(aOrig == null ? '' : aOrig);
    if (s.length >= 2 && l.length > s.length && l.slice(-s.length) === s && hasNameSep(lOrig)) return true;
    return false;
  }

  /* 判定「同一本书」，跨平台（本地书库 / 豆瓣 / 微信读书…）都靠它合并：
     1) 双方都有 ISBN 且相同 → 同一本（不同版次不再因为 ISBN 不同就拆成两卡）
     2) 同一来源的同一条目 id → 同一本
     3) 规范化书名一致：双方作者都有则必须相容；任一方缺作者（甚至两边都缺）
        也按同一本处理——跨平台导出经常只有书名没有作者，
        不合并就会出现「豆瓣 1984」「微信读书 1984」两张卡。
     4) 宽松档：短书名是长书名的「主标题 + 副标题」关系（如本地「血殇」与导入
        「血殇:埃博拉的过去、现在和未来」），且两边都没有卷次标记、作者相容 → 合并。
        以分隔符「:：—,，.」判定副标题起点，避免「中国」误并「中国哲学史」这类。 */
  function sameBook(a, b) {
    if (!a || !b) return false;
    var ia = a.isbn ? normIsbn(a.isbn) : '';
    var ib = b.isbn ? normIsbn(b.isbn) : '';
    if (ia && ib && ia === ib) return true;

    var sa = a.srcIds || [], sb = b.srcIds || [];
    for (var i = 0; i < sa.length; i++) {
      if (sb.indexOf(sa[i]) >= 0) return true;
    }

    var ta = normTitle(a.title), tb = normTitle(b.title);
    if (ta && ta === tb) {
      var aa = normAuthor(a.author), ab = normAuthor(b.author);
      if (aa && ab) return authorCompatible(a.author, b.author);   /* 都有作者：必须相容 */
      return true;                                   /* 缺作者：书名一致即视为同一本 */
    }

    /* 宽松档：主标题 + 副标题（如「血殇」与「血殇:埃博拉的过去…」） */
    var ca = coreTitle(a.title), cb = coreTitle(b.title);
    if (ca && cb && ca !== cb && ca.length >= 2) {
      var short = ca.length <= cb.length ? ca : cb;
      var long = ca.length <= cb.length ? cb : ca;
      var sep = long.charAt(short.length);
      if (long.indexOf(short) === 0 && _SUB_SEP.indexOf(sep) >= 0
          && !hasVolume(a.title) && !hasVolume(b.title)) {
        var ra = normAuthor(a.author), rb = normAuthor(b.author);
        if (ra && rb) return authorCompatible(a.author, b.author);
        return true;                                 /* 任一方缺作者：主副标题关系即合并 */
      }
    }
    /* 最后兜底：宽松键完全相同（分隔符/作者括注/尾部作者名差异都抹掉），且作者相容 */
    var la = looseKey(a.title, a.author), lb = looseKey(b.title, b.author);
    if (la && la === lb) return authorCompatible(a.author, b.author);
    return false;
  }

  function mergeRecords(a, b) {
    var out = {};
    var keys = Object.keys(a || {});
    for (var i = 0; i < keys.length; i++) out[keys[i]] = a[keys[i]];
    out.title = a.title || b.title || '';
    out.author = a.author || b.author || '';
    out.isbn = a.isbn || b.isbn || '';
    out.origin = a.origin || b.origin || '';
    out.originUrl = a.originUrl || b.originUrl || '';
    out.rate = (a.rate || 0) || (b.rate || 0);
    out.rating10 = (a.rating10 || 0) || (b.rating10 || 0);
    out.comment = a.comment || b.comment || '';
    out.cat = a.cat || b.cat || '';
    out.sources = uniq((a.sources || []).concat(b.sources || []));
    out.srcIds = uniq((a.srcIds || []).concat(b.srcIds || []));
    out.createdAt = a.createdAt || b.createdAt || Date.now();
    out.updatedAt = Date.now();
    if (!out.rid) out.rid = b.rid || newRid(out.title);
    return out;
  }

  /* 索引：ISBN / 书名 key / 来源 id，避免两两全比 */
  function idxAdd(rec, i, byIsbn, byKey, bySid) {
    if (!rec) return;
    var isbn = rec.isbn ? normIsbn(rec.isbn) : '';
    if (isbn && byIsbn[isbn] == null) byIsbn[isbn] = i;
    var tk = normTitle(rec.title);
    if (tk) (byKey[tk] || (byKey[tk] = [])).push(i);
    var ids = rec.srcIds || [];
    for (var k = 0; k < ids.length; k++) {
      if (bySid[ids[k]] == null) bySid[ids[k]] = i;
    }
  }

  function candidatesOf(rec, byIsbn, byKey, bySid) {
    var out = [], seen = Object.create(null);
    function push(i) {
      if (i == null || i < 0) return;
      if (seen[i]) return;
      seen[i] = 1; out.push(i);
    }
    var isbn = rec.isbn ? normIsbn(rec.isbn) : '';
    if (isbn) push(byIsbn[isbn]);
    var tk = normTitle(rec.title);
    if (tk && byKey[tk]) for (var i = 0; i < byKey[tk].length; i++) push(byKey[tk][i]);
    var ids = rec.srcIds || [];
    for (var j = 0; j < ids.length; j++) push(bySid[ids[j]]);
    return out;
  }

  /* 把 incoming 合并进 existing 的副本里。返回 {records, added, merged, skipped} */
  function ingest(existing, incoming) {
    var recs = (existing || []).slice();
    var byIsbn = Object.create(null), byKey = Object.create(null), bySid = Object.create(null);
    for (var i = 0; i < recs.length; i++) idxAdd(recs[i], i, byIsbn, byKey, bySid);

    var added = 0, merged = 0, skipped = 0;
    var list = incoming || [];
    for (var n = 0; n < list.length; n++) {
      var nr = list[n];
      if (!nr || !cleanInline(nr.title)) { skipped++; continue; }
      var cands = candidatesOf(nr, byIsbn, byKey, bySid);
      var hit = -1;
      for (var c = 0; c < cands.length; c++) {
        var idx = cands[c];
        if (idx < recs.length && sameBook(recs[idx], nr)) { hit = idx; break; }
      }
      if (hit >= 0) {
        var m = mergeRecords(recs[hit], nr);
        m.rid = recs[hit].rid;
        recs[hit] = m;
        idxAdd(m, hit, byIsbn, byKey, bySid);
        merged++;
      } else {
        recs.push(nr);
        idxAdd(nr, recs.length - 1, byIsbn, byKey, bySid);
        added++;
      }
    }
    return { records: recs, added: added, merged: merged, skipped: skipped };
  }

  /* 批内自我去重（同一份文件里出现两次同一本书） */
  function dedupeBatch(recs) {
    var r = ingest([], recs);
    return { records: r.records, merged: r.merged, skipped: r.skipped };
  }

  /* ============================================================
     8. 解码：BOM / UTF-8 / UTF-16 / GBK 兜底
     ============================================================ */

  function decodeText(buf) {
    var u8 = (buf instanceof Uint8Array) ? buf : new Uint8Array(buf);
    function dec(enc, slice) {
      var view = slice ? u8.subarray(slice) : u8;
      return new TextDecoder(enc).decode(view);
    }
    try {
      if (u8.length >= 3 && u8[0] === 0xEF && u8[1] === 0xBB && u8[2] === 0xBF) {
        return { text: dec('utf-8', 3), enc: 'utf-8' };
      }
      if (u8.length >= 2 && u8[0] === 0xFF && u8[1] === 0xFE) {
        return { text: dec('utf-16le', 2), enc: 'utf-16le' };
      }
      if (u8.length >= 2 && u8[0] === 0xFE && u8[1] === 0xFF) {
        return { text: dec('utf-16be', 2), enc: 'utf-16be' };
      }
    } catch (e) { /* 继续往下试 */ }
    try {
      return { text: new TextDecoder('utf-8', { fatal: true }).decode(u8), enc: 'utf-8' };
    } catch (e) { /* 不是合法 UTF-8 */ }
    try {
      return { text: new TextDecoder('gbk').decode(u8), enc: 'gbk' };
    } catch (e) { /* 环境不支持 gbk */ }
    try {
      return { text: new TextDecoder('utf-8').decode(u8), enc: 'utf-8(loose)' };
    } catch (e) {
      return { text: '', enc: 'unknown' };
    }
  }

  /* ============================================================
     9. 对外 API
     ============================================================ */

  return {
    /* 文本工具 */
    cleanInline: cleanInline,
    cleanComment: cleanComment,
    toHalf: toHalf,
    /* 规范化 */
    normTitle: normTitle,
    normAuthor: normAuthor,
    normIsbn: normIsbn,
    normKey: normKey,
    mapCat: mapCat,
    parseRating: parseRating,
    splitName: splitName,
    /* 解析 */
    parseListText: parseListText,
    parseCsv: parseCsv,
    parseDelimited: parseDelimited,
    parseJsonText: parseJsonText,
    parseAny: parseAny,
    mapRow: mapRow,
    /* 记录与合并 */
    toRecords: toRecords,
    sameBook: sameBook,
    mergeRecords: mergeRecords,
    ingest: ingest,
    dedupeBatch: dedupeBatch,
    fingerprint: fingerprint,
    newRid: newRid,
    /* 其他 */
    decodeText: decodeText,
    safeUrl: safeUrl,
    CAT_LIST: CAT_LIST,
    stripIndex: stripIndex
  };
});
