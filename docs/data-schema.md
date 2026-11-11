# 数据文件契约

私有运行时数据一律放 `data/`（已被 `.gitignore` 排除），**永远不会进公开仓库**。
发布前跑 `python scripts/prepublish_check.py --strict`，它会模拟 `git add -A`
得到待提交清单，并用本地真实书单作为指纹库逐字反查，0 处泄漏才放行。

## 三类书单数据

| 文件 | 谁生成 | 是否公开 | 用途 |
|---|---|---|---|
| `data/books.merged.json` | `postprocess.py` | 否 | 本机完整书单（含豆瓣评分/简介/出版社） |
| `data/library_final.json` | `build_html.py` | 否 | 「恢复」载入用的脱敏导出契约 |
| `scripts/demo_library.json` | 手工编造 | **是** | GitHub Pages 开屏示例数据 |

---

## books.raw.json（扫描产物，未污染）
- `books[]`：每个**文件**一条（扫描后按书名合并前）。字段：`kind/path/rel/name/ext/size/mtime/title/author/category/read/files[]`
- `files[]`：`{path, rel, size, ext, mtime, read}`
- `scansets[]`：`{kind:"scanset", dir, rel, title, pages, total_size, category, locked_keep}`
- `source_root` / `source_root_name`：书库根（绝对路径仅私有数据内）。

## douban_enriched.json（豆瓣产物，键=rel，零 id）
```json
{
  "schema": 2,
  "entries": {
    "<相对路径>": {
      "douban": {"id":"...","title":"...","author":"...","rating":8.4,"votes":6030,
                 "year":"1998-05","publisher":"人民文学出版社","pages":990,
                 "intro":"...","url":"..."},
      "douban_status": "ok|partial|notfound|lowconf|skipped",
      "confidence": 1.0,
      "matched_query": "...",
      "needs_network": false,
      "suspect": false
    }
  }
}
```
**不变量**：文件内不得出现 `b\d{5}` 形式的 id。

### douban_cache.json（内容寻址缓存）
- `q:<关键词>` → suggest 结果数组（空结果存 `{"__empty__":true,"ts":...}`，7 天后可重试）
- `id:<豆瓣id>` → 详情解析后的 dict（**不是 HTML**）：
  `{rating, votes, intro, year, publisher, pages, author, cover}`
- **重要**：因为存的是解析结果，改了 `parse_detail()` 的正则后，旧缓存不会自动变好，
  必须跑 `--refresh-detail` 重新抓详情页。判据 = 「该条 dict 缺 `pages` 键」。

## books.merged.json（合并产物，稳定 id）
- `books[]`：唯一条目。`id = sha1(kind:rel)[:8]`，永不重排。
- `files[]`：全部副本。
- `douban_status` / `suspect` / `confidence`。
- `douban.publisher` / `douban.pages` 随 douban dict 整体透传（postprocess 不做白名单）。
- `source_root_name`。

---

## library_final.json ·「恢复」载入契约

页面工具栏「**恢复**」接受三种 JSON，按内容自动识别，不需要用户先分辨：

| 文件里有什么 | 判成什么 | 效果 |
|---|---|---|
| `library.books`（完整备份 v4） | 完整备份 | 书单 + 豆瓣评分 + 我的评分 + 进度 + 笔记，一次全还原 |
| 顶层 `books` 数组 | 书库数据 | 只换书单（带评分/简介/出版社），个人评分按 sk 保留 |
| 只有 `state` | 个人标记备份 | 只合并评分/进度/笔记，书单不动 |

下面这种是「书库数据」格式（完整备份里的 `library` 字段是同一个对象）。
`build_html.py` 与单文件 HTML 的内嵌 `__LIBRARY_DATA__` 用的是同一份对象。

```json
{
  "kind": "ebooklib_library_data",
  "meta":  { "root_name": "我的书库", "source": "local" },
  "books": [ { "sk": "path:文学/示例书名.epub", "id": "a1b2c3d4", "title": "…" } ],
  "scansets": [],
  "rmap": { "<旧sk>": "<新sk>" }
}
```

硬性约束：

1. `kind` 必须是 `ebooklib_library_data`，`books` 必须是数组；单文件上限 25MB。
2. **稳定键 `sk`**：`path:<相对路径>`（文件）或 `dir:<相对路径>`（扫描图册），
   分隔符统一正斜杠 `/`。评分 / 进度 / 笔记 / 隐藏全部以 `sk` 为键，
   换来源只替换书卡数组、**不动用户状态**，因此导入后评分不会丢。
3. **禁止出现绝对路径**：不含 `path` / `dir` 字段，不含盘符，不含书库根目录绝对路径。
   `build_html.py` 用白名单挑字段，页面 `normalizeCard()` 再做一次防御性裁剪。
4. **禁止出现个人状态**：不含我的评分、阅读页数、外部笔记链接、笔记正文、标签、已读、隐藏。
   `build_html.py` 有断言清单，命中即构建失败。
5. `rmap` 可选，是「上次 sk → 本次 sk」的 1:1 迁移表，冲突身份会被跳过以防误并；
   前端 `migrateLegacySk()` 先做反斜杠归一化，再套用 `rmap`，全程幂等。
6. 页面导入后会写入 IndexedDB `kv['userLibrary']`，刷新自动恢复。

## demo_library.json · 示例书单契约

这是**唯一允许进公开仓库的书单**。全部人工编造，不得从 `books.merged.json` 抽样。

```json
{
  "kind": "ebooklib_library_data",
  "meta":  { "root_name": "示例书库", "source": "demo" },
  "books": [ { "__demo": true, "rating": 0, "douban": {}, "sk": "path:示例书库/…" } ],
  "scansets": []
}
```

- 每条 `books` / `scansets` 必须有 `__demo: true`、`rating: 0`、`douban: {}`、`sk`。
- 书名 / 作者 / 目录一律带「示例」「Demo」「演示作者」「佚名」等标记。
- `sk` 必须正斜杠且全书单唯一。
- 不得含真实书名、真实目录名、绝对路径、豆瓣 id、评分、评价人数、出版社、简介。
- `build_public.py` 在生成 `docs/index.html` 前会逐条断言，`prepublish_check.py`
  再对成品页做一次独立校验。

## 浏览器侧持久化契约（不进任何文件）

| 内容 | 存储 |
|---|---|
| 书单本体（前端扫描 / 导入所得） | IndexedDB `ebooklib_sync_v1` · `kv['userLibrary']` = `{v:1, books, scans, meta, source, ts}` |
| 我的评分、进度、已读、标签、分类覆写、隐藏、链接 | `localStorage['ebooklib_library_state_v3']` |
| 笔记正文 | IndexedDB `ebooklib_sync_v1` · `notes` |
| 是否已有自有书单 | `localStorage['ebooklib_has_library_v1']` |
| 开屏引导已读 | `localStorage['ebooklib_welcome_seen_v1']` |

`?demo=1` 强制回到内嵌示例（只用于演示，不清除任何状态）。
数据按 origin 隔离，换域名 / 端口 / 浏览器请用「完整备份 / 恢复」或 `#recover=<恢复码>`。

---

## 关键不变量
1. `rel` 在全书库唯一。
2. 回填只按 `rel`，绝不按 `id`。
3. `suspect=true` 的条目 `rating/votes` 必须为 `null`（`publisher/pages` 保留）。
4. **用户个人信息永不出现在任何 `data/*.json` 或成品 HTML 的 payload 里**，只存浏览器本地。
5. 扫描链路全程只读：脚本只用 `os.scandir` / `os.stat`；`verify_readonly.py --diff` 校验 0 改动。
   网页「重复与可删除」是唯一例外：需用户逐份勾选 + 二次确认，且先隔离可恢复，详见 README。
6. 公开版构建链（`build_public.py`）**不读 `data/`、不读 `config*`、不 import `common`**，
   只依赖 `app_template.html` + `scan_core.js` + `demo_library.json`。
