/* exactdup.js — 「高度疑似完全重复」识别与删除/恢复安全底层（轻量、零依赖）
 *
 * 设计原则（按用户要求简化）：
 *   - 不做内容哈希（SHA-256）。同一本电子书在 Kindle / 磁盘 / 移动硬盘 / 多台电脑间反复复制后，
 *     复本通常「书名 + 作者 + 文件大小 + 格式」完全一致、只是路径不同 → 标记为「高度疑似完全重复」。
 *   - 文件名解析、作者清洗等复杂活交给 scan_core.js；这里只做轻量元数据聚类与删除/恢复事务状态机。
 *
 * 浏览器端（app_template.html）与 Node 单测共用同一份实现，避免逻辑分叉。
 * UMD：浏览器挂 window.EbooklibExactdup；Node 可 require。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.EbooklibExactdup = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // ---------------------------------------------------------- 轻量元数据归一化
  function normMeta(s) {
    return String(s || '').replace(/\s+/g, '').toLowerCase();
  }

  // ---------------------------------------------------------- 元数据聚类
  // files: [{rel, title, author, size, ext}]  ext 应为小写
  // 判定「高度疑似完全重复」：书名 + 作者 + 大小 + 格式 全部相同、但路径(rel)不同。
  // 不同格式（EPUB / MOBI / PDF）因 ext 不同不会被归为一组，交回用户自行判断。
  // 返回 { rel2cluster:{rel:clusterId}, clusters:[{id,key,rels:[...]}] }
  function clusterByMeta(files) {
    var byKey = {};
    (files || []).forEach(function (f) {
      var k = normMeta(f.title) + '|' + normMeta(f.author) + '|' + (f.size || 0) + '|' + (f.ext || '').toLowerCase();
      (byKey[k] || (byKey[k] = [])).push(f.rel);
    });
    var clusters = [], rel2 = {}, idx = 0;
    Object.keys(byKey).forEach(function (key) {
      var rels = [];
      byKey[key].forEach(function (r) { if (rels.indexOf(r) < 0) rels.push(r); }); // 去重
      if (rels.length >= 2) {
        var id = 'c' + (idx++);
        clusters.push({ id: id, key: key, rels: rels });
        rels.forEach(function (r) { rel2[r] = id; });
      }
    });
    return { rel2cluster: rel2, clusters: clusters };
  }

  // ---------------------------------------------------------- 唯一批次 ID
  // 毫秒时间戳 + 随机串，避免同秒两次删除目录冲突（原秒级时间戳可能重复）
  function nextBatchId() {
    return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
  }

  // ---------------------------------------------------------- 删除 / 恢复 事务 manifest
  // 关键不变量：原文件被 remove 之前，对应的恢复记录必须已经持久化（status='copied' 且 deleted=false）。
  // 每份记录字段：rel / name / size / status / deleted / restored
  function makeRecord(rel, name, size) {
    return { rel: rel, name: name, size: size || 0, status: 'copied', deleted: false, restored: false };
  }
  function recordCopied(manifest, rec) {
    manifest.done = manifest.done || [];
    manifest.done.push(rec);
    return manifest;
  }
  function markDeleted(manifest, rel) {
    (manifest.done || []).forEach(function (d) { if (d.rel === rel) d.deleted = true; });
    return manifest;
  }
  // 整批是否「完全恢复」：仅当所有 done 都已 restored 才算完成
  function isFullyRestored(manifest) {
    var done = manifest && manifest.done;
    return !!(done && done.length && done.every(function (d) { return d.restored === true; }));
  }
  function alreadyRestored(manifest, rel) {
    var d = findRec(manifest, rel);
    return !!(d && d.restored === true);
  }
  // 目标路径已存在同名文件 → 不覆盖、不标记恢复、保留备份
  function markSkipped(manifest, rel) {
    var d = findRec(manifest, rel);
    if (d) d.status = 'skipped_exists';
    return manifest;
  }
  function markRestored(manifest, rel) {
    var d = findRec(manifest, rel);
    if (d) { d.restored = true; d.status = 'restored'; }
    return manifest;
  }
  function markError(manifest, rel) {
    var d = findRec(manifest, rel);
    if (d) d.status = 'error';
    return manifest;
  }
  function findRec(manifest, rel) {
    var done = manifest && manifest.done;
    if (!done) return null;
    for (var i = 0; i < done.length; i++) if (done[i].rel === rel) return done[i];
    return null;
  }
  // 已成功恢复（restored）的 rel 列表，供上层从 state.deletedRels 里摘掉
  function restoredRels(manifest) {
    return (manifest && manifest.done || []).filter(function (d) { return d.restored === true; })
      .map(function (d) { return d.rel; });
  }

  function validSeg(s) {
    return !!s && s !== '.' && s !== '..' && s.indexOf('/') < 0 && s.indexOf('\\') < 0;
  }

  return {
    normMeta: normMeta,
    clusterByMeta: clusterByMeta,
    nextBatchId: nextBatchId,
    makeRecord: makeRecord,
    recordCopied: recordCopied,
    markDeleted: markDeleted,
    isFullyRestored: isFullyRestored,
    alreadyRestored: alreadyRestored,
    markSkipped: markSkipped,
    markRestored: markRestored,
    markError: markError,
    restoredRels: restoredRels,
    validSeg: validSeg
  };
});
