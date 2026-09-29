# Changelog

## v0.2.0 — 正式版（2026-09-30）

- 服务端 0.2.0、插件 1.1.0、A/B 启动器 1.1.0；正式发布部署包、设备包与校验文件。
- 设备连接码在新装和主动轮换时自动生成 6 位大写字母数字；升级保留已有码，内部签名与会话密钥保持独立长随机值。
- 替换全部八张看板示例与管理页面截图，新增当前渲染拼图和可复现生成脚本。

- 初次设置独立到 `/admin/setup`；`/admin/settings` 改为日常设置，完成初始化后不再返回向导。
- 仪表盘、播放列表、设置共用 Dock，支持页内切换、浏览器前进后退和未保存修改提示。
- 保存初始内容后后台依次生成全部所选预览，已有列表自动补齐缺图；显示生成进度、失败和重试，单页失败不阻塞其他页面。
- 保存服务地址等非画面设置复用现有图片；修改地区、显示偏好只更新受影响画面。未收到 Kindle 取图时明确显示等待连接。

- 城市搜索支持中文简称、全称、简繁及拼音别名；城市/区县优先，其他地点可展开，按地点 ID 去重并清理别名标签。
- 明确显示当前已选地点，搜索无结果或失败不改变选择；经纬度/时区移入高级设置，支持回车搜索。

- 管理密码改为至少 6 个字符，不限制字符类型或要求字符组合，移除原 256 字符上限。
- 首次设置、登录和修改密码输入框增加显示／隐藏按钮；明文显示时仍不会写入表单草稿。

## 初始公开基线（2026-09-28）

- Server: persistent location/timezone, secure first-run setup, preference controls, migration and revision-aware cache; independent optional Codex collector.
- Plugin: explicit server configuration, verified TLS chain and SAN hostname, no redirects; existing RTC/power behavior retained.
- Launcher 1.1.0: preserve normal A and no-framework B arguments, present the KindleGlance name.
- Generic Compose, contribution/security/installation/upgrade documentation, automated tests and reproducible release archives.

The earlier local v1.0.2 label combined plugin 1.0.2, the then-current server and launcher 1.0. It was not a unified component version. Personal history is not part of the public baseline.

See docs/COMPATIBILITY.md for unverified physical-device and production-migration scenarios.
