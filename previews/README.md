# 看板示例

下方拼图保留正式版 v0.2.0 的八种看板（其中年度进度、时间刻度和山水长卷已在之后的 main 中移除），示例日期为 2026-09-30，地区为厦门市，时区为 Asia/Shanghai。天气使用固定演示数据，不是实时预报；图片为原生渲染，不是真机实拍。不发布个人账号用量截图。

![八种看板组合展示](showcase.png)

| 看板 | 原图 |
|---|---|
| 世界昼夜 | [day-night.png](day-night.png) |
| 天气一览 | [weather-glance.png](weather-glance.png) |
| 简约月历 | [simple-calendar.png](simple-calendar.png) |
| 逐时天气 | [hourly-weather.png](hourly-weather.png) |
| 年度花园（2026-10-18 每天现画） | [annual-garden.png](annual-garden.png) |
| 每日概览 | [daily-overview.png](daily-overview.png) |

年度花园于 2026-10-18 更新为 R10：每天的图案在服务端用同一支笔现画，同题材细看各不相同，灰度与比例受检查约束；顶部以日期为主，右上角展示今日图案，每行 24 或 25 株铺满画面，题材按年度配额与季节安排，种子灰度 80。原生横屏 1648×1236；花园使用固定公开示例种子，与私人安装实例无关。最新花园参数见 [selected-render-manifest.json](selected-render-manifest.json)。上方历史拼图不包含年度花园。

`setup-desktop.png` 来自 v0.2.0 隔离测试实例的日常设置，使用保留示例域名，没有显示设备码或账号资料。

安装开发依赖、中文字体与 Chromium 后，在项目根目录运行：

```sh
python tools/render_public_previews.py --at 2026-09-30T00:05:00+08:00
```

当前脚本使用临时数据目录、当前渲染函数与真实管理页面生成六种公开看板（另有可选 Codex 用量页），以 HTML 网格组合原图。运行会更新完整画廊和 [render-manifest.json](render-manifest.json)；仓库现有完整清单仍对应 v0.2.0 的历史生成结果。Windows 可用 FONT_PATH、FONT_BOLD_PATH 指定中文字体。

只重现当前年度花园示例、不启动管理端或拼图浏览器：

```sh
python tools/render_public_previews.py --at 2026-10-18T12:00:00+08:00 --images-only --pages annual-garden
```
