# 配置与数据

`settings.json` 是全局地区、时区、服务地址和显示偏好的来源，由管理页修改，带 schema 与 revision。旧实例的 `WEATHER_*`、`TIMEZONE`、`EXTERNAL_BASE_URL` 只在首次迁移时导入；之后不覆盖管理页。`SETTINGS_LOCK_FIELDS` 可以用逗号列出禁止 UI 修改的字段。浏览器时区只影响浏览器自身，不能更改看板时区。

| 部署变量 | 默认 / 用途 |
|---|---|
| DATA_DIR | `/app/data`，私有持久目录 |
| DEVICE_TOKEN / IMAGE_SIGNING_KEY / ADMIN_SESSION_KEY | 新安装自动独立生成；兼容旧环境配置 |
| ADMIN_PASSWORD | 兼容旧管理员；新管理员用 scrypt 哈希单独保存 |
| ADMIN_COOKIE_SECURE | HTTPS 反代设为 `1` |
| RENDER_INTERVAL_SECONDS | 1800，后台渲染检查间隔，最少 300 |
| KINDLE_REFRESH_SECONDS | 3600，向设备建议的间隔，最少 900 |
| ALLOWED_DEVICE_ID | 可选设备标识限制 |
| FONT_PATH / FONT_BOLD_PATH | Noto CJK；本地预览可指定中文字体 |
| CODEX_COLLECTOR_URL / CODEX_COLLECTOR_SECRET_FILE / CODEX_SNAPSHOT_PATH | 可选组件内部地址、密钥文件、只读快照 |

`credentials.json` 包含设备令牌、签名和会话密钥及管理员哈希。设备令牌轮换后保存值优先于旧环境值；旧令牌立即失效，需要重新配置 Kindle。更改管理密码使全部旧会话失效。密钥不进入可分享偏好导出。

时间戳存储绝对 UTC 时刻，展示与排期使用所选 IANA 时区。夏令时缺失时间拒绝保存；重复时间必须指定第一次或第二次。改变时区不会移动既有订阅到期时间。排期按当前当地墙上时间匹配，跳过时段不补播，回拨时重新匹配。

显示偏好包括摄氏/华氏、周一/周日起始、12/24 小时制及邮箱遮罩。天气服务接收坐标、时区和单位；城市搜索接收查询字符串。数据源为 [Open-Meteo](https://open-meteo.com/)，部署者需遵守其 [使用条件](https://open-meteo.com/en/terms)。地图和昼夜计算无需外部 API。项目不添加遥测。

初始设置前 `/api/display` 返回 `503 setup_required`；`/api/health` 表示进程存活，不代表天气源或设备已连通。管理页分别显示预览和最近设备取图。单个全局配置对应固定 KPW11 画布；HTTP 请求中的尺寸不表示全机型适配。
