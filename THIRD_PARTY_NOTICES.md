# 第三方代码与资源

仓库包含不同来源和授权的代码、字体和资源，不能把全部内容视为统一 MIT 授权。保留以下原始许可、版本和来源说明：

| 内容 | 授权及来源文件 |
| --- | --- |
| TRMNL KOReader 插件及本地修改 | [kindle-plugin/LICENSE](kindle-plugin/LICENSE)，上游提交见插件 README |
| KOReader 测试夹具 | [COPYING](kindle-plugin/tests/fixtures/koreader/COPYING)、[来源](kindle-plugin/tests/fixtures/koreader/README.md)，AGPL-3.0 |
| 山水绘图资源 | [LICENSE](kindle-display/app/assets/shan-shui-inf/LICENSE)、[NOTICE](kindle-display/app/assets/shan-shui-inf/NOTICE.txt) |
| 天气字体 | [OFL](kindle-display/app/assets/weather-icons/OFL.txt)、[NOTICE](kindle-display/app/assets/weather-icons/NOTICE.txt)、上游 README |
| Natural Earth 地图 | [NOTICE](kindle-display/app/assets/natural-earth/NOTICE.md)，公有领域数据 |
| 年度花园中文手写字体 Yozai | [OFL](kindle-display/app/assets/annual-garden/fonts/Yozai-OFL.txt)，来源与校验见字体目录 sources.json |
| 年度花园数字手写字体 Shantell Sans | [OFL](kindle-display/app/assets/annual-garden/fonts/ShantellSans-OFL.txt)，来源与校验见字体目录 sources.json |

年度花园图案是根据用户提供的 One Year 花园截图重新绘制的矢量插画。图案主题和手绘视觉参考 One Year: Daily Journal（Wind Down Studio，原画 Sam Peitz），不代表获取到了原应用的素材源文件。365 幅基础图案与闰日补充图案的清单、文件校验保存在年度花园素材目录 manifest.json。

Lupa 等 Python 依赖按 requirements 安装至本地虚拟环境，其发行包保留各自授权，不随 Git 提交平台二进制。插件发布包只携带插件代码及其 LICENSE，不包含 KOReader 测试夹具。

城市搜索使用 Open-Meteo 地名服务（数据来源 GeoNames），见 [接口与数据来源](https://open-meteo.com/en/docs/geocoding-api)。简繁转换使用 [opencc-python-reimplemented](https://pypi.org/project/opencc-python-reimplemented/)（Apache-2.0），拼音别名使用 [pypinyin](https://pypi.org/project/pypinyin/)（MIT）；版本固定在服务端 requirements，安装包保留原许可。
