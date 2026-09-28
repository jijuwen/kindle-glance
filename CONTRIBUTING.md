# Contributing

Use Python 3.12+ and one application worker. Install `requirements-dev.txt` in a virtual environment.

```text
python -m unittest discover -s kindle-display
python -m unittest discover -s tools/codex-collector
python tools/test_plugin.py
python tools/build_release.py
python kindle-launcher-ab/build.py
```

Changes to settings need migration, concurrent-save, cache and DST coverage. Device changes need the Lua suites and a separately recorded physical-device test. Never use production credentials in tests or attach signed image URLs, cookies, tokens or account snapshots to issues. Use reserved example domains and synthetic accounts.

Keep `trmnl.koplugin`, existing settings and official launcher arguments compatible. Retain third-party notices. Avoid committing generated distributions, runtime data or personal deployment files. Public release assets are built from an audited source allowlist.
