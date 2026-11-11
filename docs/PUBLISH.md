# 发布步骤（由你执行）

当前仓库已准备到**可发布状态**：代码、许可证、README、在线页面、脱敏示例数据、
发布前自检脚本都已就位。**助手没有执行任何 git 命令**，没有 `git init` / `commit` / `push`，
也不会替你创建远程仓库。下面每一步都由你自己操作。

---

## 0. 替换占位符

全仓库搜索 `<YOUR_GITHUB_ID>`，共 4 处，替换成你的 GitHub 用户名：

| 文件 | 位置 |
|---|---|
| `README.md` | 在线体验链接、商业授权 Discussions 链接 |
| `LICENSE` | 商业授权 Discussions 链接 |
| `docs/troubleshooting.md` | 如有残留 |

仓库名固定为 `ebooklib`。若你改了仓库名，Pages 地址和所有链接都要一起改。

## 1. 发布前自检（务必在推送前跑）

```bash
python scripts/prepublish_check.py --strict   # 模拟 git add -A，必须 ERROR 0
python scripts/audit.py --strict              # 数据结构 A1–A8
python scripts/verify_readonly.py --diff      # 书库 0 改动
python scripts/test_scan_port.py --strict     # Python ↔ 前端解析移植比对
python scripts/build_public.py                # 重新生成 docs/index.html
```

`prepublish_check.py` 会用本机真实书单作为指纹库，逐字反查所有待提交文件。
看到 `✅ 可发布：0 处泄漏` 才能继续。唯一允许的 WARN 是「占位符待替换」，
第 0 步做完后它会消失。

## 2. 建仓库并推送

在 GitHub 新建 **Public** 仓库 `ebooklib`，**不要**勾选初始化 README / LICENSE
（本地已有）。然后在本仓库根目录执行：

```bash
git init
git add -A
git status --porcelain        # 目检：应当只有约 28 个文件，且不含 data/、reports/、根目录 .html
git commit -m "Initial release: local-first ebook catalog"
git branch -M main
git remote add origin https://github.com/sinejjj/ebooklib.git
git push -u origin main
```

> `git status --porcelain` 这一步别跳过。若看到 `data/`、`reports/`、`_compare_tmp/`、
> `config.local.json`、`我的书库数据_*.json` 或任何根目录 `.html`，
> **立即停下**并检查 `.gitignore`，不要 `git add -f`。

## 3. 开启 GitHub Pages

仓库 → **Settings** → **Pages**：

- Source: **Deploy from a branch**
- Branch: `main` / **`docs`** → Save

约 1–2 分钟后访问 `https://sinejjj.github.io/ebooklib/`。
`docs/.nojekyll` 已就位，GitHub 不会用 Jekyll 处理页面。

## 4. 仓库门面（影响曝光，建议认真填）

**About → Description**（可直接用）：

```
Turn a local ebook folder into a searchable, deduplicated catalog — entirely in your browser. Nothing is uploaded.
```

**Topics**：`ebooks` `local-first` `privacy` `static-web` `no-backend`
`source-available` `catalog` `books` `offline-first`

**About → Website**：填 Pages 地址。

**Settings → General → Features**：勾选 **Discussions**。
`LICENSE` 的商业授权咨询指向 Discussions，不开启会让潜在商业用户找不到入口。

README 已引用两张截图（`docs/shot_welcome.png`、`docs/shot_library.png`），
推送后会自动显示在仓库首页。

## 5. 发布后验收

用 **Chrome / Edge 独立标签页**打开 Pages 地址（内置预览 iframe 会拦截目录选择）：

- [ ] 首次打开弹出开屏引导，背后主页面虚化
- [ ] 点「先看看示例」能看到 30 条脱敏书卡
- [ ] 点「选择文件夹」选一个本地电子书目录，能生成书卡（需 `https://` 安全上下文）
- [ ] 打 5 星后刷新，评分仍在（已修复 350ms 落盘延迟）
- [ ] 浏览器开发者工具 Network 面板：无任何第三方请求
- [ ] Pages 地址固定，不会再出现「换个端口评分就不见」
- [ ] 在仓库页面搜自己的书名，应当搜不到

## 6. 绝对不要做的事

- 不要 `git add -f data/` / `reports/` / `_compare_tmp/` / `config.local.json`
- 不要把本地生成的 `我的书库.html`、`一键恢复.html` 拖进仓库
- 不要把 `我的书库数据_找回备份.json` 或恢复码贴进 Issue / Discussion
- 不要为了「让大家看到真实效果」把真实书单做成线上演示数据

需要展示效果，只用 `docs/index.html` 里的脱敏示例书单。

---

## 许可与商业授权

PolyForm Noncommercial 1.0.0 · **Source Available（源码可用，非 OSI 开源）**。
允许非商业使用 / 修改 / 再分发，禁止任何商业用途；商业授权通过 GitHub Discussions 单独洽谈。
版权人自己不受 NC 条款限制，未来可另行发布商业版本或双许可。
