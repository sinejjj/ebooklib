# 常见问题

## 豆瓣抓不到 / 全是 notfound
- 先确认 `python scripts/fetch_douban.py --offline` 能命中缓存。
- 联网抓取内置限速与封禁探测，遇封禁会提前退出；稍后重跑 `--online` 可续。
- 匹配不上的书不会伪造数据，界面归入「未匹配豆瓣」。

## 页面「选择文件夹」不可用
- File System Access API 仅 Chromium 类浏览器（Chrome / Edge）支持。
- 必须在**安全上下文**下打开：`https://` 或 `http://localhost`。`file://` 下部分浏览器会拒绝。
- **内置预览面板 / iframe 里会被拦截**。点开屏提示里的「在新标签打开」，用独立标签页访问。
- 不支持时按钮会降级为「选择文件夹」（webkitdirectory），功能相同但每次都要重选。
- 本地起服务：
  ```bash
  python -m http.server 5175
  ```
  然后访问 `http://localhost:5175/docs/index.html`。

## 在线版没有豆瓣评分
豆瓣不提供 CORS 接口，页面内不发起任何第三方请求。在线版是纯前端扫描，书卡如实显示「未匹配」。
想要评分 / 简介 / 出版社，用本地 Python 链路生成 `data/library_final.json`，再点工具栏「恢复」载入。

## 评分 / 笔记「不见了」
浏览器存储按 **origin（协议 + 域名 + 端口）** 隔离。换端口、换浏览器、换设备都会看到另一套数据，
不是被删了。点「数据体检」看当前地址与各字段条数；用「完整备份」导出 JSON，在新地址点「恢复」导入，
或直接用 `#recover=<恢复码>` 跨地址搬回。

## 重扫后备注错位
- 老版本用 `b.id` 存状态，重扫会错位。新版已迁移到稳定键 `sk`（`path:<相对路径>`，统一用 `/`）。
- 首次打开会自动把历史反斜杠键迁移到新键，幂等且只搬「旧键存在、新键不存在」的条目。

## 发布前自检
```bash
python scripts/prepublish_check.py --strict     # 模拟 git add -A，0 处泄漏才通过
python scripts/audit.py --strict                # 数据结构与隐私护栏
python scripts/verify_readonly.py --diff        # 书库 0 改动
git status --porcelain                          # 目检待提交清单
```
