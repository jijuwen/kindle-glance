# KindleGlance 插件 1.1.0-rc.1

安装、运行、退出与恢复见 [安装指南](../docs/INSTALL.md) 和 [故障处理](../docs/TROUBLESHOOTING.md)。保留 `trmnl.koplugin` 目录、设置键及设备 API。

基于 TRMNL KOReader 提交 `3dc7ff6c73b289dd2d5919f54f979e85d4f3a422`，保留 [MIT 许可](LICENSE)。源码包含 13 个 Lua 模块；新增 transport 模块验证 HTTPS 证书链、SAN 主机名并禁止重定向。CA 路径可通过设置文件里的 `ca_file` 指定。不要禁用验证。

首次设置自己的地址和令牌。刷新支持 1、5、15、30、60 分钟及 12、24 小时；1 分钟使用常驻，其他默认 RTC。设备端间隔独立于服务器建议。省电退出需电源键唤醒后在 30 秒内点按；真正休眠时触摸不能唤醒。

停止看板返回 KOReader，正常退出 KOReader 恢复原生界面。电源恢复记录不可随意删除。新 TLS、深睡、长期续航待真机验证，见 [兼容矩阵](../docs/COMPATIBILITY.md)。

构建：`python tools/build_public_release.py` 或本目录 `build.ps1`。测试：根目录 `python tools/test_plugin.py`。
