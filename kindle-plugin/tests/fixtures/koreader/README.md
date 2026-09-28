# KOReader 测试夹具

从原始 KOReader v2026.07.1 设备快照提取五个上游 Lua 源文件：唤醒管理器、模拟 RTC、菜单排序器和两份菜单顺序。版本见 `git-rev`，授权见 `COPYING`，`SHA256SUMS` 校验上述五个文件及版本/授权文件。

仅用于 1.0.2 测试，不进入插件安装包。保留上游源码字节，不做格式化；设备、网络、UI 和电源行为的其他部分由测试替身提供。

刷新研究新增的 UIManager、屏保、设备和控件夹具随 rc1/rc2 归档，不属于当前五组测试依赖。需要恢复研究时从完整归档取回源码及其原校验清单。

上游参考：[KOReader v2026.07.1](https://github.com/koreader/koreader/tree/v2026.07.1/frontend)，沿用 AGPL-3.0 授权。
