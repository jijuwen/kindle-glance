# 安装 KindleGlance

当前发布为候选版。服务端支持单管理员、单进程、一个全局地区；设备基线为 KPW11 和 KOReader v2026.07.1。先阅读 [兼容与验收](COMPATIBILITY.md)。

## 服务端

安装 Docker Engine / Docker Desktop 及 Compose v2，下载源码或部署包，在根目录运行：

```sh
docker compose up -d --build
docker compose exec board python -m app.manage setup-code
```

打开 `http://localhost:3001/admin`，使用本机输出的一次性码设置至少 12 字符的管理密码。初始化码一小时过期；若未建立管理员，可运行 `docker compose exec board python -m app.manage renew-setup-code` 重发。内部密钥自动生成，只有管理员建立后初始化入口才关闭。

向导依次设置地区、IANA 时区、显示偏好、内容和 Kindle 连接。未选地点前不会请求天气。搜索不可用时手动填写经纬度和时区。无设备也可以完成服务器设置。

## 局域网

将根目录 `.env.example` 复制为 `.env`，设置 `BIND_ADDRESS=0.0.0.0`，再运行 `docker compose up -d`。在管理页面填服务器的局域网地址，例如 `http://192.168.1.20:3001`；不要填写浏览器自己的 localhost。局域网 HTTP 不加密，只用于受信任网络。

## VPS / HTTPS

保留绑定 `127.0.0.1:3001`，通过你自己的反向代理终止 HTTPS，设置 `.env` 的 `ADMIN_COOKIE_SECURE=1` 并重建容器。向导中的设备服务地址填写证书覆盖的 HTTPS 域名，例如 `https://board.example.com`。反向代理转发原 Host，应用不会根据未信任的 Host 自动生成设备地址。代理与应用在不同主机时应明确配置网络和受信任代理，不能使用任意转发头作为信任依据。

## Kindle

先自行准备支持 KUAL 和 KOReader 的设备环境；项目不分发破解工具或 KOReader 本体。

1. 退出 KOReader，备份插件与 `koreader/settings/`。
2. 解压插件 ZIP，把 `koreader/` 合并到设备根目录；保留原 `apikey.txt` 和设置。
3. 解压启动器 ZIP，把 `extensions/` 合并到设备根目录。
4. KUAL → KindleGlance：A 普通阅读；B 看板推荐模式（停止原生 framework）。
5. KOReader → 工具 → Kindle 看板 → 服务器与设备：填写服务地址和管理端显示的设备令牌。
6. 手动开始看板。停止看板返回 KOReader；正常退出 KOReader 才恢复原生界面。

HTTPS 需要设备时钟正确、完整证书链及可信 CA bundle。插件检查 KOReader 的 `common/turbo/ca-certificates.crt` 或系统 `/etc/ssl/certs/ca-certificates.crt`；也可在插件设置中指定 `ca_file`。自签证书需显式导入 CA；不提供关闭证书验证选项。首次候选版 TLS 尚需真机回归。

## 可选 Codex 采集器

```sh
docker compose -f compose.yaml -f compose.codex.yaml up -d --build
```

进入播放列表，添加用量提示并打开项目设置。完成官方设备码授权、确认绑定并启用自动同步。支持四个账号，每 15 分钟采集；不会发送模型请求。凭据保存在采集器私有卷，展示快照只读挂载给服务端。快照仍可能包含邮箱和额度，不可公开。

首次构建固定安装 `@openai/codex@0.158.0`。协议变更需重新验证，授权失效时在原账号栏重新授权。订阅到期时间由管理员维护，按看板时区输入，不能由额度重置时间推算。卸载此可选组件时保留其数据卷以便恢复；需要彻底删除时再按升级文档操作。
