# KindleGlance KUAL 入口 1.1.0

同一安装包内保留两种方式：

| 入口 | 参数 | 用途 |
|---|---|---|
| A - Reading (normal) | `--kual` | 普通阅读 |
| B - Dashboard (no framework) | `--kual --framework_stop` | 看板推荐入口 |

两者均调用设备已有 `/mnt/us/koreader/koreader.sh`。原生 framework 的停止与恢复由官方脚本负责，不修改 KOReader 核心。B 启动后仍需手动进入看板；停止看板返回 KOReader，正常退出 KOReader 后恢复原生界面。切换 A/B 必须完整退出再启动。

目录继续为 `extensions/kindle-board-ab`，旧 A/B Test 名称仅改为 KindleGlance。历史 B 不显示飞机图标有用户验证，新候选版需要真机回归。

`python kindle-launcher-ab/build.py` 生成两文件 ZIP 和 SHA256，检查参数、路径、CRC 和源码一致性。安装见 [安装指南](../docs/INSTALL.md)。

发行 ZIP 另附根 LICENSE；实际复制到设备的菜单配置仍为两个文件。
