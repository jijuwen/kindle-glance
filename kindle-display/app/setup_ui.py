"""Quiet, responsive setup shell. All draft state is persisted on the server."""
import html


def shell(csrf, claimed):
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf-token" content="''' + html.escape(csrf, quote=True) + '''">
<title>初次设置 · KindleGlance</title><link rel="stylesheet" href="/admin/static/setup.css?v=locations1"><link rel="stylesheet" href="/admin/static/password.css?v=1"></head>
<body data-claimed="''' + str(claimed).lower() + '''"><header><a href="/admin">KindleGlance <span>Kindle 看板</span></a><a href="/admin">返回看板</a></header>
<main><div class="intro"><p class="eyebrow">一块墨水屏，你的日常</p><h1>让看板融入你的生活</h1><p>选择所在地和想看的内容，把当地的天气与时间带到 Kindle。</p></div>
<ol id="steps" aria-label="设置进度"></ol><div class="workspace"><section id="form-area" aria-label="看板设置"></section>
<aside><div class="paper"><img id="preview" alt="当前设置的看板预览" hidden><div id="preview-empty"><span class="ink-mark">日</span><h2>你的第一张看板</h2><p>保存地区并选择内容后，会自动生成所有已选页面。</p></div></div><p id="preview-progress" role="status"></p><button id="retry-previews" type="button" hidden>重试失败页面</button><p id="preview-note">画面按 Kindle 的灰阶显示。</p></aside></div>
<p id="feedback" role="status" aria-live="polite"></p></main><footer>自托管 · 地区和内容随时可改 · 天气数据来自 Open-Meteo</footer>
<script src="/admin/static/password.js?v=1" defer></script><script src="/admin/static/setup.js?v=previews1" defer></script></body></html>'''
