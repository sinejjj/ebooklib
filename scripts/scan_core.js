/* scan_core.js — 前端从零扫描：文件名解析 / 分类 / 分卷 / 查重
 *
 * 与 scripts/common.py + scan_library.py 的算法对齐，纯 JS、无依赖。
 * 用途：GitHub Pages 在线版选一个本地文件夹，不经过 Python 也能生成书卡。
 *
 * 注意：目录映射使用【通用词表】，不包含任何真实书库的目录命名。
 * 在线版不提供豆瓣评分 / 简介 / 出版社（浏览器受 CORS 与反爬限制），
 * 书卡一律 rating:0 / douban:{}，如实显示「未匹配」。
 *
 * UMD：浏览器挂 window.EbooklibScan，Node 可 require 用于夹具测试。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.EbooklibScan = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // ---------------------------------------------------------------- 正则
  var BOOK_EXT_DEFAULT = ['.mobi', '.epub', '.pdf', '.azw3', '.azw', '.kfx',
                          '.txt', '.doc', '.docx', '.prc', '.chm', '.rtf'];

  var NON_BOOK_RE = /(^My Clippings|^已阅书籍|^经典书籍清单|^kindle阅读榜单|^IMG_|^DSC|^IMAG|^\d{3,6}$|^CR!|^EBOK|^B[A-Z0-9]{9,}$)/i;
  var ASIN_RE = /[_\-\s]?B0[A-Z0-9]{8}\S*$/i;
  var SUFFIX_RE = /(_sample|_copy|_sample\d*|\(\d+\)|（\d+）|kindle正版|kindle版|升级版|珍藏版|典藏版|完整图文版|精编图文版|图文版|v\d+\.\d+|第\d+版|修订版|白金版|纪念版)$/i;
  var NOISE_RE = /(【中亚】|\[中亚\]|通俗说\S*|tongsushuo\.com|www\.\S+|\.com)/gi;
  var VOL_RE = /[（(]\s*([一二三四五六七八九十\d]+)\s*[）)]\s*$/;
  var VOL_BRACKET_RE = /^[\d一二三四五六七八九十]{1,3}$/;
  var COLLECTION_RE = /(套装|全集|全[一二三四五六七八九十\d]+册|合集|合订|三部曲|四部曲|系列|共\d+册)/;
  var EDITION_BRACKET_RE = /\s*[（(](?:[^（）()]*?(?:文库|出版社|出版|插图|精装|平装|修订|校注|注译|全\d|上下|典藏|珍藏|完整|图文|双语?|英文|中文)[^（）()]*?)[）)]\s*$/i;
  var AUTHOR_MARK_RE = /(\[|\(|（|【)(?![\d一二三四五六七八九十]{1,3}\s*[\]\)）】])[^\]\)）】]{1,10}(\]|\)|）|】)|(?:,|，|\s)*(?:著|译|编|绘|整理|主编|原著|撰|口述|选编|编译)$|作者[:：]|译者[:：]/;
  var PUNCT_RE = /[《》〈〉「」『』【】\[\]()（）·、，,。．.：:；;！!？?~～\-－_—"'’“”]/g;
  var DOUBLE_EXT_RE = /\.(mobi|epub|azw3?|prc|pdf|txt|docx?|chm|rtf|html?)$/i;
  var PAREN_RE = /（[^（）]*）|\([^()]*\)/g;
  var PAREN_ONCE_RE = /（[^（）]*）|\([^()]*\)/;
  var BOOK_MARK_A = /^(.*?)《(.+?)》(.*)$/;
  var BOOK_MARK_B = /^《(.+?)》\s*(.*)$/;
  var HYPHEN_RE = /^(.+?)\s*[-－—]\s*(.+)$/;
  var MULTISPACE_RE = /\s{2,}|\u3000+/;
  var BULLET_RE = /[·‧•]/;

  var CN_DIGIT = { '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
                   '五': 5, '六': 6, '七': 7, '八': 8, '九': 9 };

  // ---------------------------------------------------------------- 基础工具
  function normRel(rel) {
    return String(rel || '').replace(/\\/g, '/');
  }

  function makeSk(kind, rel) {
    return (kind === 'scanset' ? 'dir:' : 'path:') + normRel(rel);
  }

  function stripExt(name) {
    var s = String(name || '');
    var i = s.lastIndexOf('.');
    return i < 0 ? s : s.slice(0, i);
  }

  function stripChars(s, chars) {
    s = String(s || '');
    var a = 0, b = s.length;
    while (a < b && chars.indexOf(s[a]) >= 0) a++;
    while (b > a && chars.indexOf(s[b - 1]) >= 0) b--;
    return s.slice(a, b);
  }

  function shortest(list) {
    return list.reduce(function (a, b) { return b.length < a.length ? b : a; });
  }

  function hash8(s) {
    var h = 2166136261 >>> 0;
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return ('00000000' + h.toString(16)).slice(-8);
  }

  function cn2int(s) {
    if (/^\d+$/.test(s)) return parseInt(s, 10);
    if (s === '十') return 10;
    var p = s.indexOf('十');
    if (p >= 0) {
      var a = s.slice(0, p), b = s.slice(p + 1);
      return (a in CN_DIGIT ? CN_DIGIT[a] : 1) * 10 + (b && (b in CN_DIGIT) ? CN_DIGIT[b] : 0);
    }
    var n = 0;
    for (var i = 0; i < s.length; i++) {
      if (!(s[i] in CN_DIGIT)) return null;
      n = n * 10 + CN_DIGIT[s[i]];
    }
    return n;
  }

  // ---------------------------------------------------------------- 作者清洗
  function normalizeAuthor(a) {
    if (!a) return a;
    a = a.replace(/^(作者|译者)\s*[:：]\s*/, '');
    a = a.replace(/^\s*[\[（(【]\s*[^\[\]（）()【】]{1,10}\s*[\]）)】]\s*[.:：\-]?\s*/, '');
    a = a.replace(/[\(（][^)）]*[\)）]/g, '');
    a = a.replace(/\s+\S{1,10}(?:译|编译|选编|译著)$/, '');
    a = a.replace(/(?:,|，|\s)*(?:著|译|编|绘|整理|主编|原著|撰|选编|编译).*$/, '');
    a = a.replace(/·/g, ' ');
    a = a.replace(/\s{2,}/g, ' ');
    a = stripChars(a, ' -_,');
    var halves = a.split(/\s{2,}/);
    if (halves.length === 2 && halves[0].trim() === halves[1].trim()) a = halves[0].trim();
    return a;
  }

  function pickFromCandidates(cand) {
    if (!cand) return null;
    var halves = String(cand).split(/\s+[-－—]\s+/).filter(function (x) { return x.trim(); })
      .map(function (x) { return x.trim(); });
    if (halves.length === 2) {
      var a = normalizeAuthor(halves[0]), b = normalizeAuthor(halves[1]);
      if (a && a === b) cand = halves[0];
      else cand = AUTHOR_MARK_RE.test(halves[0]) ? halves[0] : shortest(halves);
    }
    var segs = String(cand).split(MULTISPACE_RE).filter(function (x) { return x.trim(); })
      .map(function (x) { return x.trim(); });
    if (segs.length >= 2) cand = shortest(segs);
    return cand ? String(cand).trim() : null;
  }

  function pickAuthorSide(x, y) {
    var mx = AUTHOR_MARK_RE.test(x), my = AUTHOR_MARK_RE.test(y);
    if (mx && !my) return x;
    if (my && !mx) return y;
    if (x.length <= y.length && x.length <= 14) return x;
    return y;
  }

  // ---------------------------------------------------------------- 文件名解析
  function parseFilename(name) {
    var raw = String(name || '');
    var s = stripExt(raw);
    for (var k = 0; k < 2; k++) {
      var t2 = s.replace(DOUBLE_EXT_RE, '');
      if (t2 === s) break;
      s = t2;
    }

    var asin = null;
    var m = ASIN_RE.exec(s);
    if (m) {
      asin = stripChars(m[0], '_- ');
      s = s.slice(0, m.index);
    }

    for (var i = 0; i < 3; i++) {
      var m2 = SUFFIX_RE.exec(s);
      if (!m2) break;
      s = s.slice(0, m2.index);
    }
    s = s.replace(NOISE_RE, '');

    for (var j = 0; j < 3; j++) {
      var me = EDITION_BRACKET_RE.exec(s);
      if (!me) break;
      s = s.slice(0, me.index);
    }

    var volume = null;
    var mv = VOL_RE.exec(s);
    if (mv) {
      volume = mv[1];
      s = s.slice(0, mv.index);
    }
    s = stripChars(s, ' -_·');

    // 《书名》只出现在括号注解内时，取括号外主干当书名
    var parenTitle = null, authorCand = null;
    if (s.indexOf('《') >= 0) {
      var masked = s.replace(PAREN_RE, function (mm) { return '\u0000'.repeat(mm.length); });
      if (masked.indexOf('《') < 0) {
        var opens = [s.indexOf('（'), s.indexOf('(')].filter(function (v) { return v >= 0; });
        var iOpen = opens.length ? Math.min.apply(null, opens) : -1;
        var iClose = Math.max(s.lastIndexOf('）'), s.lastIndexOf(')'));
        var head = iOpen >= 0 ? stripChars(s.slice(0, iOpen), ' -_·') : '';
        var tail = iClose > iOpen ? stripChars(s.slice(iClose + 1), ' -_·') : '';
        if (head) {
          parenTitle = head;
          authorCand = pickFromCandidates(tail);
          if (authorCand && authorCand.length > 24) authorCand = null;
        } else {
          s = s.replace(PAREN_RE, ' ').replace(/\s{2,}/g, ' ');
          s = stripChars(s, ' -_·');
        }
      }
    }

    // 丛书前缀：示例丛书·第08卷·示例分册…
    var series = null;
    var parts = s.split(BULLET_RE);
    if (parts.length >= 3 && /\d/.test(parts[1])) {
      series = parts[0].trim() + '·' + parts[1].trim();
      s = stripChars(parts.slice(2).join('·'), ' ·');
    } else if (parts.length === 2 && /\d/.test(parts[0]) && parts[0].length < 20) {
      series = parts[0].trim();
      s = stripChars(parts[1], ' ·');
    }

    var author = null, authorFrom = 'unknown', title;

    var mA = BOOK_MARK_A.exec(s);
    if (mA) {
      var pre = mA[1].trim(), book = mA[2].trim(), post = mA[3].trim();
      title = book;
      var cand = pickFromCandidates(pre || post);
      if (cand && cand.length <= 24) { author = cand; authorFrom = 'filename'; }
    } else {
      var mB = BOOK_MARK_B.exec(s);
      if (mB) {
        title = mB[1].trim();
        var candB = pickFromCandidates(mB[2].trim());
        if (candB && candB.length <= 24) { author = candB; authorFrom = 'filename'; }
      } else {
        var mH = HYPHEN_RE.exec(s);
        if (mH) {
          var x = mH[1].trim(), y = mH[2].trim();
          author = pickAuthorSide(x, y);
          title = (author === y ? x : y);
          authorFrom = 'filename';
        } else {
          var segs = s.split(MULTISPACE_RE).filter(Boolean);
          if (segs.length >= 2) {
            author = shortest(segs);
            title = segs.reduce(function (a, b) { return b.length > a.length ? b : a; });
            authorFrom = 'filename';
          } else {
            title = s;
          }
        }
        title = stripExt(title).trim();
      }
    }

    if (parenTitle !== null) {
      title = parenTitle;
      if (authorCand) { author = authorCand; authorFrom = 'filename'; }
      else author = null;
    }

    if (author) {
      ['：', ':'].some(function (sep) {
        if (title.indexOf(author + sep) === 0) {
          title = title.slice(author.length + sep.length).trim();
          return true;
        }
        return false;
      });
    }

    var mv2 = VOL_RE.exec(title);
    if (mv2) {
      volume = volume || mv2[1];
      title = title.slice(0, mv2.index);
    }

    var isCollection = COLLECTION_RE.test(title) || title.indexOf('+') >= 0;
    if (author) author = normalizeAuthor(author);

    return {
      title: String(title).trim(),
      author: author || null,
      author_from: authorFrom,
      volume: volume || null,
      series: series || null,
      is_collection: !!isCollection,
      asin: asin || null,
      raw: raw
    };
  }

  // ---------------------------------------------------------------- 分卷
  function volumeLabel(name) {
    var s = stripExt(name);
    s = s.replace(/[上中下]{2,}\s*[册卷部]?|套装|全[一二三四五六七八九十\d]*[册卷]|共\s*\d+\s*[册卷]/g, '');

    var m = /第\s*(\d+|[一二三四五六七八九十百]+)\s*([卷册部辑篇集])(?![\u4e00-\u9fff])/.exec(s);
    if (m) {
      var n = cn2int(m[1]);
      if (n !== null) return [m[2] + n, m[0].replace(/ /g, '')];
    }

    m = /[（(]\s*([上中下])\s*[）)]|([上中下])\s*[卷册]/.exec(s);
    if (m) return [m[1] || m[2], m[0].replace(/ /g, '')];

    m = /[（(]\s*([一二三四五六七八九十]{1,3})\s*[）)]/.exec(s);
    if (m) {
      var n2 = cn2int(m[1]);
      if (n2 !== null) return ['卷' + n2, m[0].replace(/ /g, '')];
    }

    m = /\b(?:Vol|VOL|vol)\.?\s*(\d+)\b/.exec(s);
    if (m) return ['卷' + parseInt(m[1], 10), m[0]];
    return null;
  }

  // ---------------------------------------------------------------- 重名键
  function normKey(title) {
    if (!title) return '';
    var s = String(title).replace(/[_\-\s]?B0[A-Z0-9]{8}\S*$/i, '');
    s = s.replace(PUNCT_RE, '').replace(/\s+/g, '');
    return s.toLowerCase();
  }

  // ---------------------------------------------------------------- 分类规则
  var CATEGORIES = [
    '文学·小说', '历史·地理', '商业·经济·管理', '心理·认知·思维',
    '设计·艺术·摄影', '传记·回忆录·口述', '政治·哲学·军事', '社会·纪实·新闻',
    '个人成长·方法论', '科学·技术·自然', '科幻·奇幻', '推理·悬疑',
    '待归类·资料杂项'
  ];

  // 通用目录词表（不含任何真实书库的目录命名）
  var DIR_CATEGORY = {
    '文学': '文学·小说', '小说': '文学·小说', '小说其他': '文学·小说',
    '推理': '推理·悬疑', '悬疑': '推理·悬疑', '侦探': '推理·悬疑',
    '科幻': '科幻·奇幻', '奇幻': '科幻·奇幻',
    '历史': '历史·地理', '地理': '历史·地理', '轻历史': '历史·地理',
    '心理': '心理·认知·思维', '认知': '心理·认知·思维',
    '经管': '商业·经济·管理', '商业': '商业·经济·管理', '经济': '商业·经济·管理',
    '管理': '商业·经济·管理', '商业管理': '商业·经济·管理',
    '科技': '科学·技术·自然', '科学': '科学·技术·自然', '自然': '科学·技术·自然',
    '医学': '科学·技术·自然',
    '艺术': '设计·艺术·摄影', '设计': '设计·艺术·摄影', '摄影': '设计·艺术·摄影',
    '成长': '个人成长·方法论', '自我提升': '个人成长·方法论', '励志': '个人成长·方法论',
    '传记': '传记·回忆录·口述', '人物传记': '传记·回忆录·口述',
    '哲学': '政治·哲学·军事', '政治': '政治·哲学·军事', '军事': '政治·哲学·军事',
    '社会': '社会·纪实·新闻', '社会科学': '社会·纪实·新闻', '纪实': '社会·纪实·新闻',
    '杂项': '待归类·资料杂项', '图册': '设计·艺术·摄影'
  };
  var SUBDIR_CATEGORY = {
    '人物传记': '传记·回忆录·口述', '经管': '商业·经济·管理',
    '轻历史': '历史·地理', '历史': '历史·地理', '心理': '心理·认知·思维',
    '励志': '个人成长·方法论', '军事': '政治·哲学·军事',
    '医学': '科学·技术·自然', '社会科学': '社会·纪实·新闻'
  };

  var LOCK_RULES = [
    ['社会·纪实·新闻', /女性主义|女权|性别研究|社会学|妇女运动/i],
    ['心理·认知·思维', /男女交往|亲密关系|两性关系|恋爱心理|婚姻心理学/i],
    ['文学·小说', /词话|词集|诗集|散文集|小说集/i]
  ];

  var TITLE_STRONG = [
    ['推理·悬疑', /推理|侦探|悬疑|奇案|密室|刑警|法医|犯罪心理|命案|破案|福尔摩斯|阿加莎|东野圭吾|岛田庄司|松本清张|江户川乱步|柯南.?道尔|京极夏彦|占星术杀人|谋杀案/i],
    ['科幻·奇幻', /科幻|奇幻小说|星际|银河帝国|银河英雄|银河系|三体|沙丘|魔戒|霍比特人|哈利.?波特|赛博朋克|时间机器|星舰|异星|流浪地球|太空漫游|火星救援|火星任务|火星孤儿|反乌托邦|外星文明|克隆人|时空穿越/i],
    ['传记·回忆录·口述', /自传|回忆录|口述史|传记|生平|年谱|别传|忏悔录|亲历|牛棚|文革|右派|日记/i],
    ['设计·艺术·摄影', /设计|摄影|绘画|平面|工业设计|建筑|园林|景观|配色|字体|版式|素描|手绘|插画|图案|艺术史|书法|篆刻|rhino|vray|3ds|photoshop|illustrator|indesign|cad/i],
    ['心理·认知·思维', /心理学|心理|认知|思维|大脑|潜意识|情绪|记忆术|专注力|意志力|行为经济学|人格|梦的解析|精神分析|智商|情商/i],
    ['商业·经济·管理', /管理|营销|品牌|战略|金融|投资|股权|创业|谈判|财务|会计|经济学|资本|股市|商业模式|领导力|供应链|销售|广告|货币|债务|房地产|沃尔玛|麦肯锡|公司|企业/i],
    ['科学·技术·自然', /物理学|生物学|数学|化学|医学|海洋|植物|动物|天文|编程|算法|人工智能|基因|量子|生态|解剖|宇宙学|科学史/i],
    ['政治·哲学·军事', /政治|哲学|思想史|军事|战役|武器|军队|马克思|自由主义|民主|宗教|文明冲突|国际关系|外交|孙子兵法|兵法/i],
    ['历史·地理', /通史|断代|王朝|朝代|考古|简史|史话|演义|史纲|历史|地理|地图|丝绸之路|抗日战争|世界大战|近代史|古代史/i],
    ['个人成长·方法论', /成长|方法论|时间管理|学习方法|职场|效率|演讲|整理术|断舍离|拖延|习惯|沟通|读书|笔记|写作|自我提升/i],
    ['社会·纪实·新闻', /社会|纪实|调查|田野|报告文学|新闻|民族|乡土|阶层|城市化|教育|贫困|女性|劳工|监狱|医疗/i],
    ['文学·小说', /小说|文集|全集|选集|散文|随笔|诗词|词话|词集|戏剧|诗集|短篇|长篇|三部曲|言情|武侠|剧本|文选|童话|寓言|诗歌|文学/i]
  ];

  var AUTHOR_RULES = [
    ['推理·悬疑', /阿加莎|东野圭吾|岛田庄司|松本清张|江户川乱步|柯南.?道尔|京极夏彦|绫辻行人|钱德勒|埃勒里.?奎因/i],
    ['科幻·奇幻', /刘慈欣|阿西莫夫|托尔金|J\.?K\.?罗琳|阿瑟.?克拉克|弗兰克.?赫伯特|菲利普.?迪克|特德.?姜|道格拉斯.?亚当斯|莱姆|弗诺.?文奇|丹.?西蒙斯|田中芳树/i],
    ['文学·小说', /王小波|余华|莫言|村上春树|马尔克斯|博尔赫斯|卡尔维诺|鲁迅|张爱玲|金庸|古龙|亦舒|琼瑶|三毛|王国维/i]
  ];

  var TITLE_WEAK = [
    ['科幻·奇幻', /宇宙飞船|外星人|时空|飞船|星球/],
    ['历史·地理', /帝国|古代|近代|世纪|王朝|皇帝|民国/],
    ['个人成长·方法论', /人生|自我|修行|激励|励志|成功|改变自己/],
    ['科学·技术·自然', /自然|技术|科学|药|工程/],
    ['政治·哲学·军事', /战争|制度|国家|政府|权力|革命/],
    ['设计·艺术·摄影', /艺术|创意|视觉|美学|色彩|展示/],
    ['社会·纪实·新闻', /医疗|教育|城市|乡村|人口/],
    ['商业·经济·管理', /经济|财富|生意/],
    ['心理·认知·思维', /记忆|专注|意识|性格/],
    ['文学·小说', /传奇|史诗|叙事|读物/],
    ['传记·回忆录·口述', /杂忆|往事|岁月/],
    ['推理·悬疑', /犯罪|谜案|凶案/]
  ];

  // 前端无豆瓣简介，保留常量以对齐 Python，但不参与投票
  var INTRO_RULES = [
    ['科幻·奇幻', /科幻小说|科幻作品|奇幻小说|赛博朋克|反乌托邦|外星文明|星际旅行/i, /未来世界|宇宙飞船|魔法/i],
    ['推理·悬疑', /推理小说|侦探小说|悬疑小说|本格推理|密室/i, /凶手|案件|谋杀|悬疑/i],
    ['文学·小说', /小说|散文集|诗集|文学批评|文学史|词话|长篇|短篇/i, /散文|诗歌|主人公/i]
  ];

  var TIE_ORDER = CATEGORIES.filter(function (c) { return c !== '文学·小说'; }).concat(['文学·小说']);
  var PENDING = '待归类·资料杂项';

  function bump(sc, cat, n) { sc[cat] = (sc[cat] || 0) + n; }

  function classify(title, author, dirHint, subdirHint, intro, pathParts) {
    var t = title || '', a = author || '';
    for (var i = 0; i < LOCK_RULES.length; i++) {
      if (LOCK_RULES[i][1].test(t)) return [LOCK_RULES[i][0], 'lock'];
    }

    var sc = {}, hasDir = false, hasStrong = false, hasIntro = false;
    var pp = pathParts || [];
    for (var p = 0; p < pp.length; p++) {
      if (SUBDIR_CATEGORY[pp[p]]) { bump(sc, SUBDIR_CATEGORY[pp[p]], 6); hasDir = true; }
    }
    if (subdirHint && SUBDIR_CATEGORY[subdirHint]) { bump(sc, SUBDIR_CATEGORY[subdirHint], 6); hasDir = true; }
    if (dirHint && DIR_CATEGORY[dirHint]) { bump(sc, DIR_CATEGORY[dirHint], 5); hasDir = true; }

    for (var s = 0; s < TITLE_STRONG.length; s++) {
      var pat = TITLE_STRONG[s][1];
      var g = new RegExp(pat.source, 'gi');
      var hits = (t.match(g) || []).length;
      if (hits) { bump(sc, TITLE_STRONG[s][0], 4 * Math.min(hits, 2)); hasStrong = true; }
    }
    for (var ar = 0; ar < AUTHOR_RULES.length; ar++) {
      if (AUTHOR_RULES[ar][1].test(a)) bump(sc, AUTHOR_RULES[ar][0], 2);
    }
    for (var w = 0; w < TITLE_WEAK.length; w++) {
      if (TITLE_WEAK[w][1].test(t)) bump(sc, TITLE_WEAK[w][0], 2);
    }

    var snippet = intro ? String(intro).slice(0, 400) : '';
    if (snippet) {
      for (var ir = 0; ir < INTRO_RULES.length; ir++) {
        if (INTRO_RULES[ir][1].test(snippet)) { bump(sc, INTRO_RULES[ir][0], 3); hasIntro = true; }
        else if (INTRO_RULES[ir][2].test(snippet)) { bump(sc, INTRO_RULES[ir][0], 1); hasIntro = true; }
      }
    }

    var keys = Object.keys(sc);
    if (!keys.length) return [PENDING, 'pending'];
    var best = Math.max.apply(null, keys.map(function (k) { return sc[k]; }));
    if (best < 2) return [PENDING, 'pending'];
    var win = null;
    for (var o = 0; o < TIE_ORDER.length; o++) {
      if (sc[TIE_ORDER[o]] === best) { win = TIE_ORDER[o]; break; }
    }
    if (!win) return [PENDING, 'pending'];
    var src = (hasDir && sc[win] >= 5) ? 'dir'
            : (hasStrong && sc[win] >= 4) ? 'keyword'
            : hasIntro ? 'intro' : 'vote';
    return [win, src];
  }

  // ---------------------------------------------------------------- 生成书卡
  function buildCards(fileList) {
    var groups = new Map();
    (fileList || []).forEach(function (f) {
      var rel = normRel(f.rel);
      var name = f.name || rel.split('/').pop() || '';
      if (!name || NON_BOOK_RE.test(name)) return;
      var parsed = parseFilename(name);
      if (!parsed.title) return;
      var tag = volumeLabel(name);
      var parts = rel.split('/').filter(Boolean);
      var dirHint = parts[0] || '';
      var subdirHint = parts[1] || '';
      var cat = classify(parsed.title, parsed.author || '', dirHint, subdirHint, '', parts.slice(0, -1));
      var key = normKey(parsed.title) + '|' + (tag ? tag[0] : '');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({ f: f, rel: rel, name: name, parsed: parsed, tag: tag, cat: cat });
    });

    var cards = [];
    groups.forEach(function (members, key) {
      members.sort(function (a, b) {
        return (b.f.size || 0) - (a.f.size || 0) || a.rel.localeCompare(b.rel);
      });
      var head = members[0];
      var files = members.map(function (m) {
        return { rel: m.rel, size: m.f.size || 0, ext: m.f.ext || '', mtime: m.f.mtime || 0 };
      });
      var totalSize = files.reduce(function (n, f) { return n + f.size; }, 0);
      var title = head.parsed.title;
      var volLabel = null;
      if (head.tag) {
        volLabel = head.tag[1];
        var short = volLabel.replace(/[（()）]/g, '');
        if (title.indexOf(short) < 0) title = title + ' · ' + short;
      }
      var sk = makeSk('file', head.rel);
      cards.push({
        sk: sk,
        id: 'f:' + hash8(sk + '|' + files.length),
        kind: 'file',
        rel: head.rel,
        name: head.name,
        title: title,
        author: head.parsed.author || '',
        author_from: head.parsed.author_from || 'scan',
        ext: head.f.ext || '',
        size: head.f.size || 0,
        total_size: totalSize,
        mtime: head.f.mtime || 0,
        volume: head.parsed.volume || null,
        series: head.parsed.series || null,
        volume_label: volLabel,
        category: head.cat[0],
        category_src: 'scan',
        dup_count: files.length,
        files: files,
        rating: 0,
        votes: 0,
        douban: {},
        oneline: '',
        intro_short: '',
        author_famous: false,
        suspect: false,
        read: false,
        locked_keep: false,
        __src: 'scan'
      });
    });
    cards.sort(function (a, b) { return a.title.localeCompare(b.title, 'zh'); });
    return cards;
  }

  // ---------------------------------------------------------------- 目录遍历
  // File System Access API：只读遍历，返回 [{rel,name,ext,size,mtime}]
  async function collectFromHandle(dirHandle, opts) {
    opts = opts || {};
    var extSet = new Set(opts.bookExt || BOOK_EXT_DEFAULT);
    var cap = opts.sizeCap || 20000;
    var out = [];
    async function rec(handle, prefix) {
      for await (var entry of handle.values()) {
        if (out.length >= cap) return;
        if (entry.name.endsWith('.sdr')) continue;
        var rel = prefix + entry.name;
        if (entry.kind === 'directory') { await rec(entry, rel + '/'); continue; }
        var dot = entry.name.lastIndexOf('.');
        if (dot < 0) continue;
        var ext = entry.name.slice(dot).toLowerCase();
        if (!extSet.has(ext)) continue;
        var size = 0, mtime = 0;
        try {
          var file = await entry.getFile();
          size = file.size || 0;
          mtime = Math.floor((file.lastModified || 0) / 1000);
        } catch (e) { /* 取不到体积仍记录文件 */ }
        out.push({ rel: normRel(rel), name: entry.name, ext: ext, size: size, mtime: mtime });
      }
    }
    await rec(dirHandle, '');
    return out;
  }

  return {
    BOOK_EXT_DEFAULT: BOOK_EXT_DEFAULT,
    CATEGORIES: CATEGORIES,
    normRel: normRel,
    makeSk: makeSk,
    stripExt: stripExt,
    parseFilename: parseFilename,
    volumeLabel: volumeLabel,
    normKey: normKey,
    classify: classify,
    buildCards: buildCards,
    collectFromHandle: collectFromHandle,
    hash8: hash8
  };
});
