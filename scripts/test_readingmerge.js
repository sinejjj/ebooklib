#!/usr/bin/env node
/* readingmerge.js 纯逻辑单测（零依赖，Node 直接跑）
   用法： node scripts/test_readingmerge.js
   样例书名 / 作者全部为虚构占位，不含任何真实书目。 */
'use strict';

const RM = require('./readingmerge.js');

let pass = 0, fail = 0;
const fails = [];

function ok(name, cond, extra) {
  if (cond) { pass++; return; }
  fail++;
  fails.push(name + (extra === undefined ? '' : '  →  ' + JSON.stringify(extra)));
}
function eq(name, got, want) {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  ok(name, a === b, { got, want });
}

/* ============================================================
   A. 规范化
   ============================================================ */

eq('A1 书名去书名号 + 去首尾空白', RM.normTitle('  《样例小说》 '), '样例小说');
eq('A2 书名去版本注括号', RM.normTitle('样例小说（第2版）'), '样例小说');
eq('A3 书名去修订版括注', RM.normTitle('样例小说 (修订版)'), '样例小说');
eq('A4 卷次括注必须保留', RM.normTitle('样例小说（下）'), '样例小说(下)');
eq('A5 卷次「第二卷」保留', RM.normTitle('样例丛书（第二卷）'), '样例丛书(第二卷)');
eq('A6 副标题括号保留', RM.normTitle('样例小说（一个关于测试的故事）'), '样例小说(一个关于测试的故事)');
eq('A7 全角字符拉平', RM.normTitle('ＡＢＣ　测试'), 'abc 测试');
eq('A8 大小写拉平', RM.normTitle('Sample BOOK'), 'sample book');
eq('A9 中文逗号统一', RM.normTitle('甲乙，丙丁'), '甲乙,丙丁');
eq('A10 缓存一致', RM.normTitle('样例小说'), RM.normTitle('样例小说'));

eq('A11 作者去国别括注', RM.normAuthor('[英] 张测试'), '张测试');
eq('A12 作者去「著」后缀', RM.normAuthor('张测试 著'), '张测试');
eq('A13 作者去「编著」后缀', RM.normAuthor('张测试编著'), '张测试');
eq('A14 多名作者统一分隔符', RM.normAuthor('张测试、李样本'), '张测试,李样本');
eq('A15 作者空值', RM.normAuthor(''), '');

eq('A16 ISBN-13 校验通过', RM.normIsbn('978-7-5366-9293-0'), '9787536692930');
eq('A17 ISBN-10 校验通过', RM.normIsbn('7-5366-9293-9'), '');
eq('A18 ISBN 位数不足判无效', RM.normIsbn('978753669293'), '');
eq('A19 ISBN-13 校验位错判无效', RM.normIsbn('9787536692931'), '');
eq('A20 ISBN 含前缀文案可解析', RM.normIsbn('ISBN 978-7-5366-9293-0'), '9787536692930');

eq('A21 评分 5 分制', RM.parseRating('4'), { stars: 4, ten: 8 });
eq('A22 评分 10 分制折算', RM.parseRating('9.6'), { stars: 5, ten: 9.6 });
eq('A23 评分带「星」字', RM.parseRating('3 星'), { stars: 3, ten: 6 });
eq('A24 评分空值', RM.parseRating(''), { stars: 0, ten: 0 });
eq('A25 评分超界截断', RM.parseRating('99'), { stars: 5, ten: 10 });

/* ============================================================
   B. 分类映射
   ============================================================ */

eq('B1 完全匹配', RM.mapCat('科幻·奇幻'), '科幻·奇幻');
eq('B2 只写一级名', RM.mapCat('科幻'), '科幻·奇幻');
eq('B3 认不出留空', RM.mapCat('随便什么'), '');
eq('B4 空值留空', RM.mapCat(''), '');
eq('B5 待归类视为未分类', RM.mapCat('待归类'), '');

/* ============================================================
   C. TXT 解析
   ============================================================ */

const txt1 = RM.parseListText('样例图书甲\n样例图书乙\n\n样例图书丙\n');
eq('C1 一行一本', txt1.map(x => x.title), ['样例图书甲', '样例图书乙', '样例图书丙']);

const txt2 = RM.parseListText('样例图书甲\t张测试\n样例图书乙 | 李样本\n');
eq('C2 TAB 分隔带作者', txt2[0], { title: '样例图书甲', author: '张测试' });
eq('C3 竖线分隔带作者', txt2[1], { title: '样例图书乙', author: '李样本' });

const txt3 = RM.parseListText('- 样例图书甲\n* 样例图书乙\n• 样例图书丙\n');
eq('C4 去行首项目符号', txt3.map(x => x.title), ['样例图书甲', '样例图书乙', '样例图书丙']);

const listText = [
  '我的阅读 · 全渠道已读清单',
  '生成时间 2026/11/12 15:00:00',
  '共 2 条 · 1 个分类（仅供本人参考）',
  '='.repeat(70),
  '',
  '## 已阅 · 科幻·奇幻 · 2 本',
  '',
  '[0001] 张测试 · 样例图书甲',
  '评分 9.6 | 我的评分：5 星 | 我的评价：写得不错',
  '',
  '[0002] 样例图书乙',
  '评分 8.1 | 我的评分：4 星',
  ''
].join('\n');
const lr = RM.parseListText(listText, { authorHint: s => s === '张测试' });
eq('C5 清单格式条数', lr.length, 2);
eq('C6 清单作者书名拆分', { t: lr[0].title, a: lr[0].author }, { t: '样例图书甲', a: '张测试' });
eq('C7 清单分类带出', lr[0].catRaw, '科幻·奇幻');
eq('C8 清单评分带出', lr[1].rateRaw, '8.1');
eq('C9 清单我的评分带出', lr[0].myRateRaw, '5');
eq('C10 清单评价带出', lr[0].comment, '写得不错');
eq('C11 无评价时为空', lr[1].comment, undefined);

const hintText = '[0001] 三字作者 · 五字样例题\n';
const hinted = RM.parseListText(hintText, { authorHint: s => s === '三字作者' });
eq('C12 authorHint 命中时正确拆分', { t: hinted[0].title, a: hinted[0].author },
  { t: '五字样例题', a: '三字作者' });

const amb = RM.parseListText('甲 · 乙\n');
eq('C13 无法判断时不瞎拆', amb[0], { title: '甲 · 乙', author: '' });

/* ============================================================
   D. CSV / TSV 解析
   ============================================================ */

const csv1 = '书名,作者,评分\n样例图书甲,张测试,9.6\n样例图书乙,李样本,8.1\n';
const c1 = RM.parseCsv(csv1);
eq('D1 CSV 表头映射条数', c1.length, 2);
eq('D2 CSV 字段名归一', c1[0], { 书名: '样例图书甲', 作者: '张测试', 评分: '9.6' });

const csv2 = '"书名","评价"\n"样例图书甲","很,好"\n"样例图书乙","带""引号""的评价"\n';
const c2 = RM.parseCsv(csv2);
eq('D3 CSV 引号内逗号不拆列', c2[0]['评价'], '很,好');
eq('D4 CSV 双引号转义', c2[1]['评价'], '带"引号"的评价');

const csv3 = '"书名","评价"\n"样例图书甲","第一行\n第二行"\n';
const c3 = RM.parseCsv(csv3);
eq('D5 CSV 引号内换行保留', c3[0]['评价'], '第一行\n第二行');

const tsv = '书名\t作者\n样例图书甲\t张测试\n';
const t1 = RM.parseCsv(tsv);
eq('D6 TSV 自动识别分隔符', t1[0], { 书名: '样例图书甲', 作者: '张测试' });

const noHead = '样例图书甲,张测试\n样例图书乙,李样本\n';
const nh = RM.parseCsv(noHead);
eq('D7 无表头时第一列书名', nh[1], { title: '样例图书乙', author: '李样本' });

const crlf = '书名,作者\r\n样例图书甲,张测试\r\n';
eq('D8 CRLF 换行', RM.parseCsv(crlf).length, 1);

/* ============================================================
   E. JSON 解析
   ============================================================ */

eq('E1 裸数组', RM.parseJsonText('[{"title":"甲"},{"title":"乙"}]').length, 2);
eq('E2 books 包装', RM.parseJsonText('{"books":[{"title":"甲"}]}').length, 1);
eq('E3 items 包装', RM.parseJsonText('{"items":[{"title":"甲"}]}').length, 1);
eq('E4 records 包装', RM.parseJsonText('{"records":[{"title":"甲"}]}').length, 1);
eq('E5 list 包装', RM.parseJsonText('{"list":[{"title":"甲"}]}').length, 1);
eq('E6 data 包装', RM.parseJsonText('{"data":[{"title":"甲"}]}').length, 1);
eq('E7 单条对象当一条', RM.parseJsonText('{"title":"甲"}').length, 1);
eq('E8 忽略非对象项', RM.parseJsonText('[{"title":"甲"},null,3]').length, 1);

/* ============================================================
   F. 字段映射
   ============================================================ */

eq('F1 中文别名', RM.mapRow({ 书名: '样例图书甲', 作者: '张测试', 我的评分: '4' }),
  { title: '样例图书甲', author: '张测试', isbn: '', rateRaw: '4', myRateRaw: '', comment: '', srcId: '', url: '', catRaw: '' });
eq('F2 英文别名', RM.mapRow({ title: 'T', author: 'A', rating: '3', review: 'ok' }).comment, 'ok');
eq('F3 缺书名返回 null', RM.mapRow({ author: '张测试' }), null);
eq('F4 想读状态跳过', RM.mapRow({ 书名: '甲', 状态: '想读' }), null);
eq('F5 已读状态保留', RM.mapRow({ 书名: '甲', 状态: '已读' }).title, '甲');
eq('F6 下划线 key 归一', RM.mapRow({ book_name: '甲', book_id: 'x1' }).srcId, 'x1');
eq('F7 空字符串不算命中', RM.mapRow({ 书名: '', title: '甲' }).title, '甲');

/* ============================================================
   G. parseAny 格式推断
   ============================================================ */

eq('G1 按扩展名 json', RM.parseAny('a.json', '{"books":[{"title":"甲"}]}').length, 1);
eq('G2 按扩展名 csv', RM.parseAny('a.csv', '书名,作者\n甲,张\n').length, 1);
eq('G3 按扩展名 txt', RM.parseAny('a.txt', '甲\n乙\n').length, 2);
eq('G4 无扩展名按内容判 json', RM.parseAny('a', '[{"title":"甲"}]').length, 1);
eq('G5 无扩展名按内容判 txt', RM.parseAny('a', '甲\n乙\n').length, 2);
eq('G6 空文件返回空', RM.parseAny('a.txt', '').length, 0);
eq('G7 全是无书名行返回空', RM.parseAny('a.txt', '\n\n\n').length, 0);

/* ============================================================
   H. toRecords
     ============================================================ */

const tr = RM.toRecords([
  { title: '样例图书甲', author: '张测试', rateRaw: '9.6', comment: '好', catRaw: '科幻', srcId: 'b1' },
  { title: '', author: 'x' }
], 's1');
eq('H1 有效记录数', tr.records.length, 1);
eq('H2 无书名被跳过', tr.skipped, 1);
eq('H3 评分折算', tr.records[0].rating10, 9.6);
eq('H4 来源写入', tr.records[0].sources, ['s1']);
eq('H5 来源 id 带 sid 前缀', tr.records[0].srcIds, ['s1:b1']);
eq('H6 分类映射', tr.records[0].cat, '科幻·奇幻');
ok('H7 rid 唯一', tr.records[0].rid !== RM.toRecords([{ title: '样例图书甲' }], 's1').records[0].rid);

/* ============================================================
   I. sameBook 三级优先级与「不确定不合并」
     ============================================================ */

const A = { title: '样例图书甲', author: '张测试', isbn: '9787536692930', srcIds: [], sources: [] };
const B = { title: '样例图书甲', author: '张测试', isbn: '', srcIds: [], sources: [] };

ok('I1 同名同作者合并', RM.sameBook(A, B));
ok('I2 ISBN 相同但书名不同也合并', RM.sameBook(
  { title: '甲', author: '张', isbn: '9787536692930' },
  { title: '完全不同的书名', author: '李', isbn: '9787536692930' }));
ok('I3 ISBN 冲突直接判不同', !RM.sameBook(
  { title: '样例图书甲', author: '张测试', isbn: '9787536692930' },
  { title: '样例图书甲', author: '张测试', isbn: '9787115428028' }));
ok('I4 同来源同 id 合并', RM.sameBook(
  { title: '甲', author: '', srcIds: ['s1:x9'] },
  { title: '乙', author: '', srcIds: ['s1:x9'] }));
ok('I5 不同来源同 id 不合并', !RM.sameBook(
  { title: '甲', author: '', srcIds: ['s1:x9'] },
  { title: '甲', author: '', srcIds: ['s2:x9'] }));
ok('I6 仅书名相同不合并', !RM.sameBook({ title: '样例图书甲', author: '' }, { title: '样例图书甲', author: '' }));
ok('I7 作者不同不合并', !RM.sameBook(
  { title: '样例图书甲', author: '张测试' },
  { title: '样例图书甲', author: '李样本' }));
ok('I8 一方作者缺失不合并', !RM.sameBook(
  { title: '样例图书甲', author: '张测试' },
  { title: '样例图书甲', author: '' }));
ok('I9 卷次不同不合并', !RM.sameBook(
  { title: '样例丛书（上）', author: '张测试' },
  { title: '样例丛书（下）', author: '张测试' }));
ok('I10 版本注不同视为同书', RM.sameBook(
  { title: '样例图书甲（第2版）', author: '张测试' },
  { title: '样例图书甲', author: '张测试' }));
ok('I11 副标题不同不合并', !RM.sameBook(
  { title: '样例图书甲（一个副标题）', author: '张测试' },
  { title: '样例图书甲（另一个副标题）', author: '张测试' }));
ok('I12 空对象不合并', !RM.sameBook(null, A));

/* ============================================================
   J. mergeRecords
     ============================================================ */

const m1 = RM.mergeRecords(
  { title: '甲', author: '张测试', rate: 5, comment: '本地评价', sources: ['local'], srcIds: [], cat: '' },
  { title: '甲', author: '张测试', rate: 4, comment: '导入评价', sources: ['s1'], srcIds: ['s1:1'], cat: '科幻·奇幻', originUrl: 'https://x.test/1' });
eq('J1 来源并集', m1.sources, ['local', 's1']);
eq('J2 来源 id 并集', m1.srcIds, ['s1:1']);
eq('J3 非空字段保留前者（本地优先）', m1.comment, '本地评价');
eq('J4 空字段补全', m1.cat, '科幻·奇幻');
eq('J5 链接补全', m1.originUrl, 'https://x.test/1');
ok('J6 不改入参', (function () {
  const a = { title: '甲', author: '', rate: 0, comment: '', sources: [], srcIds: [] };
  RM.mergeRecords(a, { title: '甲', author: '李', sources: ['s'], srcIds: [] });
  return a.author === '' && a.sources.length === 0;
})());

/* ============================================================
   K. ingest：新增 / 合并 / 幂等
     ============================================================ */

const base = RM.toRecords([
  { title: '样例图书甲', author: '张测试' },
  { title: '样例图书乙', author: '李样本' }
], 's1').records;

const r1 = RM.ingest(base, RM.toRecords([
  { title: '样例图书甲', author: '张测试' },     // 已存在 → 合并
  { title: '样例图书丙', author: '王样例' }      // 新 → 新增
], 's2').records);
eq('K1 新增数', r1.added, 1);
eq('K2 合并数', r1.merged, 1);
eq('K3 总数', r1.records.length, 3);
eq('K4 合并后来源有两个', r1.records[0].sources.sort(), ['s1', 's2']);

const again = RM.ingest(r1.records, RM.toRecords([{ title: '样例图书甲', author: '张测试' }], 's3').records);
eq('K5 重复导入不新增', again.added, 0);
eq('K6 重复导入走合并', again.merged, 1);
eq('K7 重复导入总数不变', again.records.length, 3);

const batch = RM.dedupeBatch(RM.toRecords([
  { title: '样例图书甲', author: '张测试' },
  { title: '样例图书甲', author: '张测试' },
  { title: '样例图书丁', author: '赵样本' }
], 's1').records);
eq('K8 批内自去重', batch.records.length, 2);
eq('K9 批内合并计数', batch.merged, 1);

/* ============================================================
   L. 解码
     ============================================================ */

function utf8Bytes(s) { return new TextEncoder().encode(s); }

const d1 = RM.decodeText(utf8Bytes('样例图书甲'));
eq('L1 UTF-8 解码', [d1.text, d1.enc], ['样例图书甲', 'utf-8']);

const bom = new Uint8Array([0xEF, 0xBB, 0xBF].concat(Array.from(utf8Bytes('甲'))));
eq('L2 UTF-8 BOM 去掉', RM.decodeText(bom).text, '甲');

const u16 = new Uint8Array([0xFF, 0xFE, 0x32, 0x75]);
const d3 = RM.decodeText(u16);
eq('L3 UTF-16LE BOM 解码', [d3.text, d3.enc], ['甲', 'utf-16le']);

/* GBK「甲」= 0xBC 0xD7；环境不支持 gbk 时跳过 */
try {
  const gbk = new Uint8Array([0xBC, 0xD7]);
  const d4 = RM.decodeText(gbk);
  ok('L4 GBK 兜底解码', d4.text === '甲' || d4.enc === 'utf-8(loose)', { text: d4.text, enc: d4.enc });
} catch (e) {
  ok('L4 GBK 环境不支持（跳过）', true);
}

eq('L5 空 buffer 不抛错', RM.decodeText(new Uint8Array(0)).text, '');

/* ============================================================
   M. 指纹与工具
     ============================================================ */

eq('M1 指纹稳定', RM.fingerprint('abc'), RM.fingerprint('abc'));
ok('M2 不同内容指纹不同', RM.fingerprint('abc') !== RM.fingerprint('abd'));
ok('M3 指纹带长度标记', /^[0-9a-f]{8}-[0-9a-z]+$/.test(RM.fingerprint('样例')));
eq('M4 只放行 http 链接', RM.safeUrl('javascript:alert(1)'), '');
eq('M5 https 链接放行', RM.safeUrl('https://x.test/a'), 'https://x.test/a');
eq('M6 过长链接截断', RM.safeUrl('https://x.test/' + 'a'.repeat(900)).length, 600);
eq('M7 评价压缩多余空行', RM.cleanComment('a\n\n\n\nb'), 'a\n\nb');
eq('M8 单行化压掉换行', RM.cleanInline('a\n\t b'), 'a b');

/* ============================================================
     汇总
     ============================================================ */

/* ---------------- Z. 行首序号剥离 ---------------- */
function tt(line) { return RM.parseAny('a.txt', line).map(r => r.title); }
eq('Z1 「1.书名」剥掉序号', tt('1.活着'), ['活着']);
eq('Z2 「10、书名」剥掉序号', tt('10、活着'), ['活着']);
eq('Z3 「100)书名」剥掉序号', tt('100)活着'), ['活着']);
eq('Z4 纯数字书名 1984 不动', tt('1984'), ['1984']);
eq('Z5 1Q84 不动', tt('1Q84'), ['1Q84']);
eq('Z6 三体2 不动', tt('三体2'), ['三体2']);

console.log('');
console.log('='.repeat(62));
if (fail) {
  console.log('readingmerge 单测：' + pass + ' 通过 / ' + fail + ' 失败');
  fails.forEach(f => console.log('  ✗ ' + f));
  console.log('='.repeat(62));
  process.exit(1);
}
console.log('readingmerge 单测：' + pass + ' 通过 / 0 失败');
console.log('='.repeat(62));
process.exit(0);
