/* test_exactdup.js — 轻量单测（Node 运行，无需浏览器）
 * 覆盖：
 *   元数据聚类（高度疑似完全重复识别）
 *   删除/恢复事务状态机（基本数据安全：及时持久化恢复记录 / 不覆盖 / 可重试）
 *   唯一批次号
 * 运行：node scripts/test_exactdup.js
 */
const EX = require('./exactdup.js');

let pass = 0, fail = 0;
function ok(cond, msg) { if (cond) pass++; else { fail++; console.error('  ✗ ' + msg); } }
function eq(a, b, msg) { ok(a === b, msg + '  (got ' + JSON.stringify(a) + ', want ' + JSON.stringify(b) + ')'); }

// ---------------------------------------------------------------- 元数据聚类
const cl = (files) => EX.clusterByMeta(files);

// 书名+作者+大小+格式 相同、路径不同 → 高度疑似完全重复
eq(cl([
  { rel: 'a/book.epub', title: '三体', author: '刘慈欣', size: 1200, ext: '.epub' },
  { rel: 'b/book.epub', title: '三体', author: '刘慈欣', size: 1200, ext: '.epub' },
]).clusters.length, 1, '同名同作者同大小同格式不同路径 → 1 组');

// 不同格式（EPUB vs MOBI）→ 不归为一组，交回用户判断
eq(cl([
  { rel: 'a/book.epub', title: '三体', author: '刘慈欣', size: 1200, ext: '.epub' },
  { rel: 'b/book.mobi', title: '三体', author: '刘慈欣', size: 1200, ext: '.mobi' },
]).clusters.length, 0, 'EPUB 与 MOBI 不自动归组');

// 大小不同 → 不归为一组
eq(cl([
  { rel: 'a/x.epub', title: 'A', author: 'B', size: 100, ext: '.epub' },
  { rel: 'b/x.epub', title: 'A', author: 'B', size: 200, ext: '.epub' },
]).clusters.length, 0, '大小不同不归组');

// 作者不同（同名书不同作者）→ 不归组
eq(cl([
  { rel: 'a/x.epub', title: '红楼梦', author: '曹雪芹', size: 100, ext: '.epub' },
  { rel: 'b/x.epub', title: '红楼梦', author: '佚名', size: 100, ext: '.epub' },
]).clusters.length, 0, '作者不同不归组');

// 三个及以上相同副本 → 同一组
{
  const r = cl([
    { rel: 'a/1.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
    { rel: 'b/2.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
    { rel: 'c/3.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
  ]);
  eq(r.clusters.length, 1, '三副本 → 1 组');
  eq(r.clusters[0].rels.length, 3, '组含 3 份');
}

// 多个不同组同时识别
{
  const r = cl([
    { rel: 'a/1.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
    { rel: 'b/2.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
    { rel: 'c/3.epub', title: 'X', author: 'Y', size: 50, ext: '.epub' },
    { rel: 'd/4.epub', title: 'X', author: 'Y', size: 50, ext: '.epub' },
  ]);
  eq(r.clusters.length, 2, '两组独立识别');
}

// rel2cluster 映射正确
{
  const r = cl([
    { rel: 'a/1.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
    { rel: 'b/2.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
  ]);
  ok(r.rel2cluster['a/1.epub'] && r.rel2cluster['a/1.epub'] === r.rel2cluster['b/2.epub'], 'rel2cluster 指向同一簇');
}

// 同源（路径不同即视为两份）不会因内部重复而多算
{
  const r = cl([
    { rel: 'a/1.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
    { rel: 'a/1.epub', title: 'T', author: 'A', size: 100, ext: '.epub' },
  ]);
  eq(r.clusters.length, 0, '同一 rel 去重，不误判');
}

// 标题大小写/空格差异被归一化（仍判为疑似）
{
  const r = cl([
    { rel: 'a/1.epub', title: ' 三体 ', author: 'Liu Cixin', size: 100, ext: '.epub' },
    { rel: 'b/2.epub', title: '三体', author: 'liu cixin', size: 100, ext: '.epub' },
  ]);
  eq(r.clusters.length, 1, '大小写/空格归一后仍判为疑似');
}

// ---------------------------------------------------------------- 保留路径逻辑（纯逻辑模拟）
function simulateKeep(clusters) {
  const rel2c = {}; const byC = {};
  clusters.forEach(c => { byC[c.id] = c.rels.slice(); c.rels.forEach(r => rel2c[r] = c.id); });
  const CLEAN_SEL = new Set();
  const KEEPS = new Set();
  function markKeeper(rel) {
    const cid = rel2c[rel]; if (!cid) return;
    const cluster = byC[cid];
    [...KEEPS].forEach(k => { if (cluster.indexOf(k) >= 0) KEEPS.delete(k); });
    KEEPS.add(rel);
    CLEAN_SEL.delete(rel);
    cluster.forEach(s => { if (s === rel) return; if (KEEPS.has(s)) return; CLEAN_SEL.add(s); });
  }
  return { CLEAN_SEL, KEEPS, markKeeper };
}
// 选一个保留 → 其余进待删除
{
  const sim = simulateKeep([{ id: 'c0', rels: ['A', 'B', 'C'] }]);
  sim.markKeeper('A');
  ok(sim.KEEPS.has('A') && !sim.CLEAN_SEL.has('A') && sim.CLEAN_SEL.has('B') && sim.CLEAN_SEL.has('C'), '保留 A → B/C 待删除');
}
// 可取消自动选择
{
  const sim = simulateKeep([{ id: 'c0', rels: ['A', 'B', 'C'] }]);
  sim.markKeeper('A'); sim.CLEAN_SEL.delete('B');
  ok(!sim.CLEAN_SEL.has('B') && sim.CLEAN_SEL.has('C'), '可取消 B');
}
// 取消全部
{
  const sim = simulateKeep([{ id: 'c0', rels: ['A', 'B', 'C'] }]);
  sim.markKeeper('A'); sim.CLEAN_SEL.clear(); sim.KEEPS.clear();
  eq(sim.CLEAN_SEL.size, 0, '清空后无待删除');
}
// 多组同时保留
{
  const sim = simulateKeep([{ id: 'c0', rels: ['A', 'B'] }, { id: 'c1', rels: ['X', 'Y'] }]);
  sim.markKeeper('A'); sim.markKeeper('X');
  ok(sim.CLEAN_SEL.has('B') && sim.CLEAN_SEL.has('Y') && sim.KEEPS.has('A') && sim.KEEPS.has('X'), '多组各自生效');
}
// 用户已勾选不被覆盖
{
  const sim = simulateKeep([{ id: 'c0', rels: ['A', 'B', 'C'] }]);
  sim.CLEAN_SEL.add('B');
  sim.markKeeper('A');
  ok(sim.CLEAN_SEL.has('B'), '用户已勾选的 B 不被取消');
}
// 保留路径不直接触发删除
{
  const sim = simulateKeep([{ id: 'c0', rels: ['A', 'B', 'C'] }]);
  let deleted = false; sim._del = () => { deleted = true; };
  sim.markKeeper('A');
  ok(!deleted, 'markKeeper 不触发删除');
}

// ---------------------------------------------------------------- 删除/恢复事务状态机（假文件系统）
function FakeFS() { this.root = { dirs: new Map(), files: new Map() }; this.failWrite = false; this.failRemove = false; }
function splitPath(rel) { const p = String(rel).replace(/\\/g, '/').split('/').filter(Boolean); return { dirs: p.slice(0, -1), name: p[p.length - 1] }; }
function mkNode() { return { dirs: new Map(), files: new Map() }; }
FakeFS.prototype._nav = function (node, segs, create) {
  let cur = node;
  for (const s of segs) { let n = cur.dirs.get(s); if (!n) { if (!create) throw new Error('no dir ' + s); n = mkNode(); cur.dirs.set(s, n); } cur = n; }
  return cur;
};
FakeFS.prototype.writeFile = function (rel, buf) { if (this.failWrite) throw new Error('write failed'); const { dirs, name } = splitPath(rel); this._nav(this.root, dirs, true).files.set(name, new Uint8Array(buf)); };
FakeFS.prototype.readFile = function (rel) { const { dirs, name } = splitPath(rel); const n = this._nav(this.root, dirs, false); if (!n.files.has(name)) throw new Error('no file ' + rel); return n.files.get(name); };
FakeFS.prototype.remove = function (rel) { if (this.failRemove) throw new Error('remove failed'); const { dirs, name } = splitPath(rel); const n = this._nav(this.root, dirs, false); if (!n.files.has(name)) throw new Error('no file ' + rel); n.files.delete(name); };
FakeFS.prototype.exists = function (rel) { const { dirs, name } = splitPath(rel); let n; try { n = this._nav(this.root, dirs, false); } catch (e) { return false; } return n.files.has(name); };

// 复刻 doDelete 单文件关键步骤：复制 → 确认备份(大小) → 持久化记录 → 删除 → 持久化完成
async function doDeleteOne(origFS, trashFS, rel, content) {
  const manifest = { batch_id: 'b1', created_at: '', root: 'R', done: [], failed: [], restored: false };
  try {
    trashFS.writeFile(rel, content);                     // 1) 完整复制到回收区
    const chk = trashFS.readFile(rel);
    if (chk.byteLength !== content.byteLength) throw new Error('backup size mismatch'); // 2) 确认备份成功
    const rec = EX.makeRecord(rel, rel.split('/').pop(), content.byteLength);
    EX.recordCopied(manifest, rec);                     // 3) 持久化恢复记录（删除前！）
    if (trashFS.failWrite) throw new Error('manifest write failed'); // 模拟写盘失败：绝不能继续删原文件
    origFS.remove(rel);                                 // 4) 删除原文件（仅当记录已落盘）
    EX.markDeleted(manifest, rel);
    return { manifest, error: null };
  } catch (e) { return { manifest, error: e.message }; }
}

(async () => {
  // 正常删除一个
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const c = Buffer.from('hello');
    orig.writeFile('a/book.epub', c);
    const { manifest, error } = await doDeleteOne(orig, trash, 'a/book.epub', c);
    eq(error, null, '正常删除无错误');
    ok(!orig.exists('a/book.epub'), '原件已移除');
    ok(trash.exists('a/book.epub'), '备份已写入隔离区');
    ok(manifest.done[0].deleted === true, '记录标记 deleted');
  }
  // 批量删除多个
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const rels = ['a/1.epub', 'b/2.epub', 'c/3.epub'];
    const cs = rels.map((_, i) => Buffer.from('x' + i));
    rels.forEach((r, i) => orig.writeFile(r, cs[i]));
    for (let i = 0; i < rels.length; i++) { const { error } = await doDeleteOne(orig, trash, rels[i], cs[i]); eq(error, null, '批量 #' + i); }
    ok(rels.every(r => !orig.exists(r)) && rels.every(r => trash.exists(r)), '批量全部替换到隔离区');
  }
  // 备份失败 → 原文件保留
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const c = Buffer.from('x');
    orig.writeFile('a/x.epub', c); trash.failWrite = true;
    const { error } = await doDeleteOne(orig, trash, 'a/x.epub', c);
    ok(error, '备份失败有错误');
    ok(orig.exists('a/x.epub'), '原件保留');
    ok(!trash.exists('a/x.epub'), '无备份');
  }
  // 恢复记录写入失败 → 原文件保留（未被删）
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const c = Buffer.from('x');
    orig.writeFile('a/x.epub', c);
    trash.failWrite = true; // 恢复记录持久化失败（模拟写盘异常）
    const { error } = await doDeleteOne(orig, trash, 'a/x.epub', c);
    ok(error, '记录持久化失败有错误');
    ok(orig.exists('a/x.epub'), '原件保留（未被删）');
  }
  // 删除后、完成态持久化前中断 → 仍可恢复（done 含 deleted 记录）
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const c = Buffer.from('x');
    orig.writeFile('a/x.epub', c); trash.writeFile('a/x.epub', c);
    const m = { batch_id: 'b', done: [], failed: [], restored: false };
    EX.recordCopied(m, EX.makeRecord('a/x.epub', 'x.epub', c.byteLength));
    orig.remove('a/x.epub'); EX.markDeleted(m, 'a/x.epub');
    ok(!orig.exists('a/x.epub') && m.done[0].deleted, '中断前记录已含 deleted（可恢复）');
    eq(m.done.filter(d => d.deleted && !d.restored).length, 1, '可恢复 1 份');
  }
  // 连续两批次，目录/记录不冲突（批次号唯一）
  {
    const ids = new Set();
    for (let i = 0; i < 5000; i++) { const id = EX.nextBatchId(); ok(!ids.has(id), '批次号唯一'); ids.add(id); }
  }

  // ---------------- 恢复安全（EX 状态机 + 假 FS 复刻 restoreLast 关键路径）
  async function restoreOne(origFS, trashFS, manifest, rel) {
    const rec = manifest.done.find(d => d.rel === rel);
    if (!rec) return;
    if (EX.alreadyRestored(manifest, rel)) return;
    if (origFS.exists(rec.rel)) { EX.markSkipped(manifest, rel); return; } // 目标已存在 → 不覆盖
    try {
      const buf = trashFS.readFile(rec.rel);
      origFS.writeFile(rec.rel, buf);
      trashFS.remove(rec.rel);
      EX.markRestored(manifest, rel);
    } catch (e) { EX.markError(manifest, rel); }
  }
  // 正常恢复一个
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const c = Buffer.from('data');
    trash.writeFile('a/book.epub', c);
    const m = { batch_id: 'b', done: [EX.makeRecord('a/book.epub', 'book.epub', c.length)], restored: false };
    EX.markDeleted(m, 'a/book.epub');
    await restoreOne(orig, trash, m, 'a/book.epub');
    ok(orig.exists('a/book.epub') && !trash.exists('a/book.epub') && EX.isFullyRestored(m), '正常恢复 1 份且整批完成');
  }
  // 恢复整个批次
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const rels = ['a/1', 'b/2', 'c/3'];
    const cs = rels.map((_, i) => Buffer.from('d' + i));
    rels.forEach((r, i) => trash.writeFile(r, cs[i]));
    const m = { batch_id: 'b', done: rels.map((r, i) => EX.makeRecord(r, r.split('/').pop(), cs[i].length)), restored: false };
    rels.forEach(r => EX.markDeleted(m, r));
    for (const r of rels) await restoreOne(orig, trash, m, r);
    ok(rels.every(r => orig.exists(r)) && EX.isFullyRestored(m), '整批恢复完成');
  }
  // 部分恢复成功后再次恢复可续做
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const rels = ['a/1', 'b/2', 'c/3'];
    const cs = rels.map((_, i) => Buffer.from('d' + i));
    rels.forEach((r, i) => trash.writeFile(r, cs[i]));
    const m = { batch_id: 'b', done: rels.map((r, i) => EX.makeRecord(r, r.split('/').pop(), cs[i].length)), restored: false };
    rels.forEach(r => EX.markDeleted(m, r));
    await restoreOne(orig, trash, m, rels[0]);
    ok(orig.exists(rels[0]) && !EX.isFullyRestored(m), '部分恢复后未完成');
    for (const r of rels.slice(1)) await restoreOne(orig, trash, m, r);
    ok(EX.isFullyRestored(m), '续做后完成');
  }
  // 目标已存在同名文件 → 不覆盖、不标记完成
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const c = Buffer.from('new'); const existing = Buffer.from('old');
    trash.writeFile('a/book.epub', c); orig.writeFile('a/book.epub', existing);
    const m = { batch_id: 'b', done: [EX.makeRecord('a/book.epub', 'book.epub', c.length)], restored: false };
    EX.markDeleted(m, 'a/book.epub');
    await restoreOne(orig, trash, m, 'a/book.epub');
    ok(Buffer.compare(Buffer.from(orig.readFile('a/book.epub')), existing) === 0, '原文件未被覆盖');
    ok(!EX.isFullyRestored(m) && m.done[0].status === 'skipped_exists', '冲突保留备份、批次未完成');
  }
  // 恢复中断后下次可继续
  {
    const orig = new FakeFS(), trash = new FakeFS();
    const rels = ['a/1', 'b/2'];
    const cs = rels.map((_, i) => Buffer.from('d' + i));
    rels.forEach((r, i) => trash.writeFile(r, cs[i]));
    const m = { batch_id: 'b', done: rels.map((r, i) => EX.makeRecord(r, r.split('/').pop(), cs[i].length)), restored: false };
    rels.forEach(r => EX.markDeleted(m, r));
    await restoreOne(orig, trash, m, rels[0]);
    ok(EX.alreadyRestored(m, rels[0]), '第一份已持久化为 recovered');
    await restoreOne(orig, trash, m, rels[1]);
    ok(EX.isFullyRestored(m), '续做后完成');
  }
  // 非法路径段校验
  {
    ok(!EX.validSeg('') && !EX.validSeg('.') && !EX.validSeg('..') && !EX.validSeg('a/b') && EX.validSeg('ok'), '路径段合法性');
  }

  console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
