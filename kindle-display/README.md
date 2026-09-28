# KindleGlance 服务端

Python / FastAPI / Pillow 渲染九类看板，Chromium 用于山水资源。单进程逐页渲染锁、全局设置修订和图片缓存；传输画布为 1236×1648，当前为 KPW11 档案。

完整发行包的通用部署入口位于根 `compose.yaml`，包含 docs 和可选采集器。也可以在本目录执行 `docker compose up -d --build`，然后运行 `docker compose exec board python -m app.manage setup-code` 并访问 `http://localhost:3001/admin`。推荐使用完整发行包以便查阅安装与配置指南。

管理员初始化码和独立密钥自动创建于私有数据卷，地点留空。管理员建立后使用地区向导，配置热更新；旧运行状态迁移时保留地点、时区与播放列表。损坏配置不自动覆盖。

用量采集器是可选组件。未配置 `CODEX_COLLECTOR_URL` 时不连接采集器，不默认添加用量页。凭据只存采集器私有卷，应用仅读取展示快照。订阅到期时间需人工维护。

依赖见 requirements；测试 `python -m unittest discover -s kindle-display`（从仓库根目录）。字体和 Chromium 实际渲染需在 Linux 镜像中验收。`/api/health` 表示存活，内容和设备状态分别展示。更多说明见完整仓库 docs。
