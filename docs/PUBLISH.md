# 发布与更新指南

> 本项目**已上线**。本文件只讲"以后改了东西怎么发、发完怎么验"，
> 不再包含建仓库、替换占位符这类一次性步骤（那些都做完了）。
> 最后核实时间：2026-11-11。

---

## 0. 当前状态（已核实）

| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/sinejjj/ebooklib` · **Public** |
| 默认分支 | `main` |
| 在线演示 | `https://sinejjj.github.io/ebooklib/` |
| Pages 来源 | `main` 分支 / `docs` 目录（Deploy from a branch） |
| 仓库文件 | 29 个 |
| 线上页面 | 已验证与本仓库 `docs/index.html` 内容一致 |

以下操作**已经完成，不需要再做**：

- 建仓库、选可见性
- 用户名占位符已全部替换为 `sinejjj`（README / LICENSE 链接均已指向真实地址）
- Settings → Pages 绑定 `main` / `/docs`
- 首次推送与首次部署

> 仓库门面（About 里的简介、站点链接、Topics、是否开启 Discussions）
> 属于维护者的个人设置，不影响任何人使用本项目，因此**不在本文档维护**。
> 需要调整时直接去仓库页面改，不必回来同步文档。

---

## 1. 改了代码怎么发

### 1.1 重新生成公开演示页

只要改动了 `scripts/app_template.html`、`scripts/scan_core.js` 或
`scripts/demo_library.json` 中的任意一个，就要重新生成：

```bash
python scripts/build_public.py
```

输出 `docs/index.html`——单文件、自包含、无外部请求。
脚本是**幂等**的：数据和模板没变时，重复运行产出的文件完全一致。

### 1.2 发布前检查（推送前必跑）

公开仓库里**可以直接跑**的两条：

```bash
python scripts/prepublish_check.py --strict    # 期望：ERROR 0
python scripts/test_scan_port.py --strict      # 期望：差异 0 处
```

`prepublish_check.py` 会自动判断"当前是不是 git 仓库"：
是的话用 `git ls-files` 交叉核对跟踪集合（避免漏提交/多提交）。
在公开 clone 里没有 `data/`，真实书单指纹比对会跳过，
输出 `WARN 1` 属正常，只看 **ERROR 0**。

以下两条**只在本机源码目录**有意义（依赖私有数据，公开仓库里没有）：

```bash
python scripts/audit.py --strict          # 需要 data/books*.json
python scripts/verify_readonly.py --diff  # 需要 config.local.json + 书库路径
```

在 clone 里跑它们会提示缺少 `data/` 或 `config.local.json`，
这是设计如此，**不是报错**。

### 1.3 提交并推送

```bash
git add -A
git status --short                      # 目检：只应有预期内的文件
git commit -m "一句话说明这次改了什么"
git push origin main
```

`git status --short` 别跳过。若出现 `data/`、`reports/`、
`config.local.json`、或根目录的 `.html`，先检查 `.gitignore`，**不要** `git add -f`。

### 1.4 等自动部署

推送后 GitHub 会自动重新部署 Pages，通常 1–2 分钟。
浏览器打开站点时按 **Ctrl + F5** 强刷，否则可能看到旧缓存。

---

## 2. 怎么确认发布成功

按顺序看这四点：

1. **提交对上了**：仓库页顶部的 commit 号 = 本地 `git log -1` 的哈希
2. **Pages 在跑**：仓库 → **Settings → Pages**，顶部应显示
   `Your site is live at https://sinejjj.github.io/ebooklib/`
3. **站点能开**：打开上面的地址，页面标题为「本地书库管理 · 电子图书馆」
4. **内容是最新的**（可选，命令行验证）：

```bash
curl -s https://sinejjj.github.io/ebooklib/ | grep -c READ_DIR_MARK
```

返回大于 `0` 说明线上含当前版本的扫描器代码。

> 线上文件与本地文件的字节数可能不同（线上是 LF 换行、本地是 CRLF），
> 比对时请忽略换行符差异，内容本身应完全一致。

---

## 3. 绝对不要做的事

- 不要 `git add -f data/` / `reports/` / `_compare_tmp/` / `config.local.json`
- 不要把本地生成的成品页面、`一键恢复.html` 拖进仓库
- 不要把备份 JSON 或恢复码贴进 Issue / Discussion
- 不要为了"让大家看到真实效果"把真实书单做成线上演示数据

需要展示效果，只用 `docs/index.html` 里的脱敏示例书单。

若要展示自己的书库效果，请**截图**，并把书名/作者打码或只截局部。

---

## 4. 如果将来改了仓库名

三处要一起改，漏一处就会出现死链：

1. 本表格里的仓库地址与 Pages 地址
2. `README.md` 的在线体验链接、`LICENSE` 的 Discussions 链接
3. GitHub → Settings → Pages 重新保存一次（确认 `main` / `/docs` 仍正确）

---

## 许可与商业授权

PolyForm Noncommercial 1.0.0 · **Source Available（源码可用，非 OSI 开源）**。
允许非商业使用 / 修改 / 再分发，禁止任何商业用途；商业授权通过 GitHub Discussions 单独洽谈。
版权人自己不受 NC 条款限制，未来可另行发布商业版本或双许可。
