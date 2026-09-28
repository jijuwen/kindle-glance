# 云端 Codex 用量采集器

独立可选的 `service.py` 和 `rpc.py` 负责账号授权与用量同步。服务端管理桥接在 `kindle-display/app/codex_bridge.py`，账号卡片在 `kindle-display/app/static/codex-accounts.js`。本目录不包含账号凭据、桥接密钥或生产环境配置。

## 数据与授权

- 使用已安装的官方 Codex CLI `app-server`，通过 `account/login/start` 的设备码流程授权，并由用户确认绑定邮箱。每个账号有独立的凭据目录。
- `account/read` 读取身份和套餐，`account/rateLimits/read` 读取额度窗口及重置券；不发起模型调用。
- 四个固定栏位，每 900 秒串行采集；失败退避，登录失效时等待重新授权。管理员可同步、补录订阅信息或解除绑定。
- 到期时间通过 metadata 接口人工填写。自动采集的 `expires_at` 为空，发布展示快照时使用各栏位保存的手工值；不会用额度重置时间推算。
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

`tools/cockpit-sync` 保留旧 Windows 同步方式，当前 VPS 自动采集不依赖它。
