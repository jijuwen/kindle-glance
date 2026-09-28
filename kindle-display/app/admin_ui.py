"""Server-rendered shell for the Kindle dashboard application."""

from __future__ import annotations

import html
import json
from typing import Any


ICONS = {
    "dashboard": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1Z"/></svg>',
    "playlist": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3Z"/></svg>',
}


def admin_shell(view: str, title: str, bootstrap: dict[str, Any], csrf: str) -> str:
    payload = json.dumps(bootstrap, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    dashboard_active = " active" if view == "dashboard" else ""
    playlist_active = " active" if view == "playlist" else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="csrf-token" content="{html.escape(csrf, quote=True)}">
  <meta name="color-scheme" content="dark">
  <title>{html.escape(title)} · KindleGlance</title>
  <link rel="stylesheet" href="/admin/static/admin.css?v=40">
</head>
<body data-view="{html.escape(view, quote=True)}">
  <div class="ambient ambient-a"></div><div class="ambient ambient-b"></div>
  <header class="topbar">
    <a class="brand" href="/admin" aria-label="KindleGlance 仪表盘">
      <span class="brand-mark">K</span><span><b>KindleGlance</b><small>个人信息看板</small></span>
    </a>
    <form action="/admin/logout" method="post"><button class="quiet-button" type="submit">退出</button></form>
  </header>
  <main id="app" class="app-shell" aria-live="polite"></main>
  <nav class="dock" aria-label="主导航">
    <a class="dock-item{dashboard_active}" href="/admin">{ICONS['dashboard']}<span>仪表盘</span></a>
    <a class="dock-item{playlist_active}" href="/admin/playlist">{ICONS['playlist']}<span>播放列表</span></a>
    <a class="dock-item" href="/admin/settings"><span>设置</span></a>
  </nav>
  <div id="toast-region" class="toast-region" aria-live="assertive"></div>
  <div id="overlay-root"></div>
  <script id="bootstrap" type="application/json">{payload}</script>
  <script src="/admin/static/admin.js?v=38" defer></script>
  <script src="/admin/static/codex-accounts.js?v=40" defer></script>
</body>
</html>"""
