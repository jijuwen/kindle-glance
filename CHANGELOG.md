# Changelog

## Unreleased

- 管理密码改为至少 6 个字符，不限制字符类型或要求字符组合，移除原 256 字符上限。
- 首次设置、登录和修改密码输入框增加显示／隐藏按钮；明文显示时仍不会写入表单草稿。

## v0.2.0-rc.1 — first public candidate

- Server 0.2.0-rc.1: persistent location/timezone, secure first-run setup, preference controls, migration and revision-aware cache; independent optional Codex collector.
- Plugin 1.1.0-rc.1: explicit server configuration, verified TLS chain and SAN hostname, no redirects; existing RTC/power behavior retained.
- Launcher 1.1.0: preserve normal A and no-framework B arguments, present the KindleGlance name.
- Generic Compose, contribution/security/installation/upgrade documentation, automated tests and reproducible release archives.

The earlier local v1.0.2 label combined plugin 1.0.2, the then-current server and launcher 1.0. It was not a unified component version. Personal history is not part of the public baseline.

See docs/COMPATIBILITY.md for unverified physical-device and production-migration scenarios.
