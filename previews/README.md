# 当前版本示例

八种看板均由正式版 v0.2.0 当前代码重新生成，示例日期为 2026-09-30，地区为厦门市，时区为 Asia/Shanghai。天气使用固定演示数据，不是实时预报；图片为原生渲染，不是真机实拍。不发布个人账号用量截图。

![八种看板组合展示](showcase.png)

| 看板 | 原图 |
|---|---|
| 世界昼夜 | [day-night.png](day-night.png) |
| 天气一览 | [weather-glance.png](weather-glance.png) |
| 简约月历 | [simple-calendar.png](simple-calendar.png) |
| 逐时天气 | [hourly-weather.png](hourly-weather.png) |
| 山水长卷 | [shan-shui.png](shan-shui.png) |
| 年度进度 | [year-progress.png](year-progress.png) |
| 每日概览 | [daily-overview.png](daily-overview.png) |
| 时间刻度 | [time-scales.png](time-scales.png) |

`setup-desktop.png` 来自隔离测试实例的当前日常设置，使用保留示例域名，没有显示设备码或账号资料。

安装服务端依赖、中文字体与 Chromium 后，在项目根目录运行：

```sh
python tools/render_public_previews.py --at 2026-09-30T00:05:00+08:00
```

脚本使用临时数据目录、当前渲染函数与真实管理页面生成图片，以 HTML 网格组合原图。Windows 可用 FONT_PATH、FONT_BOLD_PATH 指定中文字体。参数见 [render-manifest.json](render-manifest.json)。
