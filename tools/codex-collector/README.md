# 云端 Codex 用量采集器

独立可选的 `service.py`、`rpc.py` 和 `subscriptions.py` 负责账号授权、用量与订阅同步。服务端管理桥接在 `kindle-display/app/codex_bridge.py`，账号卡片在 `kindle-display/app/static/codex-accounts.js`。本目录不包含账号凭据、桥接密钥或生产环境配置。

## 数据与授权

- 使用已安装的官方 Codex CLI `app-server`，通过 `account/login/start` 的设备码流程授权，并由用户确认绑定邮箱。每个账号有独立的凭据目录。
- `account/read` 读取身份和套餐，`account/rateLimits/read` 读取额度窗口及重置券；不发起模型调用。
- 四个固定栏位，额度每 900 秒、订阅每 3600 秒自动采集；失败分别退避。管理员可立即同步、重新授权或解除绑定。
- 使用官方 CLI 已保存的 access token 查询 ChatGPT `/backend-api/subscriptions`，读取套餐、`active_until`、是否有效及自动续费状态；`/backend-api/accounts/check/v4-2023-04-27` 按所选 account ID 匹配补充或回退。此接口不是公开稳定 API，变化时保留自动缓存并标记待更新，不影响成功的额度查询。
- `active_until` 为本周期结束时间；开启自动续费时展示续费时间。`entitlement.expires_at` 单独保存，不代替周期结束时间；不会根据额度重置时间猜测订阅日期。旧 ID token 仅作明确标记的缓存，不冒充实时查询。
- 仅官方 CLI 刷新凭据；订阅请求在 CLI 关闭并保存凭据后读取同一授权文件，不自行交换或刷新 token。升级保留原授权，删除手工套餐和日期覆盖。原 metadata 接口已移除。
- 展示快照为严格白名单 schema v2；看板兼容 v1，部署先更新看板再更新采集器。额度与订阅分别保存更新时间；周期结束后显示待更新，不自行降级套餐。
- 只发布无凭据的展示 JSON；看板挂载公开快照目录，私有授权目录只由采集器使用。

## 运行契约

需要 Python 3.11+、官方 Codex CLI，以及可用的时区数据。Python 代码除标准库外不依赖应用服务的 FastAPI。

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `COLLECTOR_STATE_DIR` | `/state` | 私有状态及每个账号的授权目录 |
| `COLLECTOR_PUBLIC_DIR` | `/public` | 无凭据展示快照输出 |
| `COLLECTOR_SECRET_FILE` | `/run/secrets/codex-bridge` | 内部桥接鉴权密钥文件 |
| `CODEX_BINARY` | `/usr/local/bin/codex` | 已安装的官方 CLI |

启动 `python service.py`，内部监听 8091。除 `/health` 外均要求桥接鉴权；不直接发布到公网。使用非 root 用户运行，预先准备仅该用户可写的状态目录。通用安装使用根目录 compose.codex.yaml。Dockerfile 固定 CLI 0.158.0，协议由 CI 与替身测试验证；真实授权仍需管理员自己的账号。

应用侧通过 `CODEX_COLLECTOR_URL`、`CODEX_COLLECTOR_SECRET_FILE` 连接内部服务，并从 `CODEX_SNAPSHOT_PATH` 读取快照（默认 `/app/codex-data/ai-accounts.json`）。旧 Windows 快照仅作为官方快照尚不存在时的兼容路径。

完整部署发布包包含采集器、Dockerfile 和独立卷配置。

## 验证

从仓库根目录运行 `python -m unittest discover -s tools/codex-collector -v`，只使用临时目录和虚构账号，不读取或变更生产授权。验收边界见 [兼容矩阵](../../docs/COMPATIBILITY.md)。

旧 Windows / Cockpit 同步工具属于私有历史，不包含在公开发行包中。
