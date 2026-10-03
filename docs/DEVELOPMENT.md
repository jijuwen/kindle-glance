# 开发、测试与构建

## 环境

本地验证环境为 Windows x64、Python 3.12、Git；插件测试使用 Lupa 2.8 的 LuaJIT 2.1，管理端导航测试使用 Node.js 22。Linux 环境由 GitHub Actions 验证。运行库通过依赖安装，不提交平台运行时。

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

下文使用虚拟环境解释器，无需激活脚本。服务端新容器环境见 `kindle-display/README.md`；需要完整浏览器渲染时另安装 Playwright Chromium 和适用中文字体。

## 测试

```powershell
.\.venv\Scripts\python.exe tools/test_plugin.py
.\.venv\Scripts\python.exe -m unittest discover -s kindle-display
.\.venv\Scripts\python.exe -m unittest discover -s tools/codex-collector
node kindle-display/test_admin_navigation.cjs
```

插件依次运行 stage1、stage2、loop、board、sleep_display、transport 六组，并校验 13 个 Lua 模块语法及上游夹具 SHA256。支持指定组，例如 `tools/test_plugin.py board sleep_display`，`--verbose` 显示完整输出。部分组会复用前面的回归用例，检查数量不要直接相加作为独立测试总数。

采集器测试只用临时目录、虚构账号和 HTTP / CLI 替身，不登录官方服务。VPS 候选测试应限制 CPU、内存与运行时间，不能复用生产账号目录。旧 NAS / Cockpit 运维工具不属于公开清单。

设备/网络/屏幕替身只验证软件路径；实际闪动、耗电、RTC 长间隔和深睡必须在 Kindle 上验证。服务端测试也不代表 NAS 已部署。

## 生成发布包

```powershell
.\.venv\Scripts\python.exe tools/check_public.py
.\.venv\Scripts\python.exe tools/build_public_release.py
```

根目录 `dist/` 被忽略；构建生成部署 ZIP、插件 ZIP、A/B 启动器 ZIP 及 SHA256SUMS，逐项核对白名单和源码字节。部署包包含公开文档、采集器、完整花园素材和字体；插件包包含 13 个 Lua 模块和 LICENSE。归档使用固定条目时间戳，不打包运行数据。

实际发布的包和校验清单另存发布附件或私有恢复档案，不用重新打包的哈希替换历史发布记录。

## 预览

```powershell
.\.venv\Scripts\python.exe tools/render_public_previews.py --at 2026-10-02T12:00:00+08:00 --images-only --pages annual-garden year-progress
```

脚本默认写入 `previews/`，使用临时数据目录、演示天气和固定公开花园种子，不读取实际授权或实例种子。`--images-only` 跳过管理端和拼图浏览器截图；`--pages` 只生成指定看板并写入独立 `selected-render-manifest.json`，不改写完整画廊的历史清单。不加参数时生成完整画廊及设置截图，需要 Chromium。Windows 上可用 `FONT_PATH` / `FONT_BOLD_PATH` 指定中文字体，花园字体已内置。生成图片不能冒充设备实拍。

重新生成素材使用 `tools/build_annual_garden_assets.py`；它会覆盖基础 SVG、PNG 和清单，修改前先保留版本。字体不由生成器下载，许可证与来源随素材目录保存。修改素材或构图后递增渲染修订并运行花园测试，见 [年度花园](ANNUAL_GARDEN.md)。

## Git 和版本边界

- 公开仓库主分支为 `main`，当前正式标签为 `v0.2.0`，组件版本与未发布源码更新见 [CHANGELOG](../CHANGELOG.md)。早期本地 `v1.0.2` 不属于公开仓库的统一发行版。
- 提交源码、依赖声明、测试、夹具及许可证、构建脚本和当前文档。
- 排除 `.venv/`、`.local/`、`.cloudflare/`、`backups/`、`dist/`、缓存、日志、设备数据和机器配置；`.env.example` 保留可提交。公开导出以 `tools/public_files.py` 为准，不复制私人 Git 历史或运维档案。
- 自有文本默认 LF；上游资源、许可证、测试夹具及已有服务端静态文件保留原字节，以便核对部署基线。插件清单记录换行标准化后的 1.0.2 文件哈希。旧版及第三方源码原有行尾空格保留，避免为了格式检查改写基线。
- 先跑适合改动的测试、构建并检查暂存内容，再提交；不将未经实机验证的功能写成已验收。
- 公开发布前检查导出目录、文档链接、许可证、凭据排除和 CI；不改写历史发行附件。

第三方字体、地图、山水资源、KOReader 测试夹具保留各自授权文件；仓库不是一份统一 MIT 授权。见 `THIRD_PARTY_NOTICES.md`。
