(() => {
  "use strict";

  const data = JSON.parse(document.getElementById("bootstrap").textContent);
  const app = document.getElementById("app");
  const overlay = document.getElementById("overlay-root");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const colors = ["#4fa57b", "#c58627", "#7b72d8", "#d85f50", "#4b94ba", "#ab6fa7", "#78923f", "#bd7552"];
  const weekday = ["一", "二", "三", "四", "五", "六", "日"];

  const h = (value) => String(value ?? "").replace(/[&<>'"]/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[character]);
  const formatTime = (seconds, short = false) => {
    if (!seconds) return "尚无记录";
    const date = new Date(seconds * 1000);
    return new Intl.DateTimeFormat("zh-CN", short
      ? {hour:"2-digit", minute:"2-digit", hour12:data.settings?.display_preferences?.hour_format === "12", timeZone:data.settings?.timezone || "UTC"}
      : {month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:data.settings?.display_preferences?.hour_format === "12", timeZone:data.settings?.timezone || "UTC"}
    ).format(date);
  };
  const orientationLabel = item => item.rotation === 90 ? "横屏 · 向右转" : item.rotation === 270 ? "横屏 · 向左转" : "竖屏";
  const iconFor = page => ({"simple-calendar":"日", "weather-glance":"☀", "hourly-weather":"时", "year-progress":"年", "time-scales":"刻", "daily-overview":"▤", "shan-shui":"山"})[page] || "◇";
  const renderModeLabel = item => item.page_id === "shan-shui"
    ? (item.config?.render_mode === "kindle_gray" ? "Kindle 优化灰阶" : "原版灰阶")
    : "";

  function toast(message, error = false) {
    const node = document.createElement("div");
    node.className = `toast${error ? " error" : ""}`;
    node.textContent = message;
    document.getElementById("toast-region").appendChild(node);
    setTimeout(() => node.remove(), 3200);
  }

  async function api(url, options = {}) {
    const headers = {"X-CSRF-Token": csrf, ...(options.headers || {})};
    if (options.body && typeof options.body !== "string") {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    const response = await fetch(url, {...options, headers});
    if (!response.ok) {
      let detail = "操作失败";
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return response.json();
  }

  function screenPicture(item, className = "") {
    if (!item?.preview_url) return '<div class="screen-empty">尚未生成预览</div>';
    return `<img class="${className}" src="${h(item.preview_url)}" alt="${h(item.name)}预览">`;
  }

  function renderDashboard() {
    const current = data.current;
    const upNext = data.up_next.map((item, index) => `
      <article class="mini-card">
        <div class="mini-thumb">${screenPicture(item)}</div>
        <strong>${h(item.name)}</strong>
        <small>${index === 0 ? "正在显示" : formatTime(item.at, true)} · ${h(orientationLabel(item))}</small>
      </article>`).join("");
    const events = data.events.length ? data.events.map(event => `
      <li><time>${h(event.time)}</time><span>${h(event.message)}</span></li>`).join("") : '<li><span>暂无事件</span></li>';
    app.innerHTML = `
      <section class="page-head">
        <div><p class="eyebrow">Overview</p><h1>${h(data.greeting)}</h1><p class="lead">Kindle 看板${data.metrics.service_ok ? "运行正常" : "需要检查"}，所有时间使用上海时区。</p></div>
        <a class="primary-button" href="/admin/playlist">编辑播放列表 ›</a>
      </section>
      <section class="hero-grid">
        <article class="panel current-panel">
          <div class="panel-head"><div><h2>当前画面</h2><p>Kindle 实际收到的 1236 × 1648 图片</p></div></div>
          <div class="screen-stage">${screenPicture(current, "screen-image")}<span class="screen-badge">${h(orientationLabel(current))}</span></div>
          <div class="current-meta"><div><h2>${h(current?.name || "尚未生成")}</h2><p>${h(current?.page_title || "等待首次渲染")} · 更新于 ${formatTime(current?.rendered_at)}</p></div></div>
          <div class="button-row"><button id="render-current" class="primary-button">立即重新渲染</button><button id="preview-current" class="secondary-button">大图预览</button></div>
        </article>
        <div>
          <article class="panel summary-panel">
            <div class="panel-head"><div><h2>播放列表</h2><p>${data.playlist_count} 个项目 · 每 ${data.metrics.refresh_minutes} 分钟切换</p></div><a class="quiet-button" href="/admin/playlist">修改 ›</a></div>
            <div class="up-next">${upNext}</div>
            <div class="metric-grid">
              <div class="metric"><span>Kindle 最近取图</span><strong>${h(data.metrics.last_fetch)}</strong></div>
              <div class="metric"><span>下一次切换</span><strong>${h(data.metrics.next_switch)}</strong></div>
              <div class="metric"><span>天气数据</span><strong class="${data.metrics.weather_ok ? "good" : "warn"}">${data.metrics.weather_ok ? "正常" : "使用缓存或降级"}</strong></div>
              <div class="metric"><span>Smart Skip</span><strong>${data.metrics.smart_skip ? "已开启" : "已关闭"}</strong></div>
            </div>
          </article>
          <article class="panel activity-panel"><div class="panel-head"><h2>最近活动</h2></div><ul class="activity-list">${events}</ul></article>
        </div>
      </section>`;
    document.getElementById("render-current").addEventListener("click", async event => {
      const button = event.currentTarget; button.disabled = true; button.textContent = "正在渲染…";
      try { await api("/admin/api/actions/render", {method:"POST"}); location.reload(); }
      catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "立即重新渲染"; }
    });
    document.getElementById("preview-current").addEventListener("click", () => showPreview(current));
  }

  function timelineMarkup() {
    const counts = new Map();
    data.timeline.forEach(segment => counts.set(segment.item_id, (counts.get(segment.item_id) || 0) + 1));
    const itemIndex = new Map(data.items.map((item, index) => [item.id, index]));
    const segments = data.timeline.map(segment => {
      const index = itemIndex.get(segment.item_id) ?? 0;
      return `<button class="timeline-segment" data-jump="${h(segment.item_id)}" style="background:${colors[index % colors.length]}" title="${h(segment.name)} · ${formatTime(segment.at, true)}"></button>`;
    }).join("");
    const legends = data.items.filter(item => counts.has(item.id)).map((item, index) => `<span class="legend"><i style="background:${colors[index % colors.length]}"></i>${h(item.name)} ${counts.get(item.id)}×</span>`).join("");
    return `<article class="panel timeline-panel"><div class="panel-head"><div><h2>接下来 24 小时</h2><p>时间轴与 Kindle 实际调度使用同一套计算</p></div><span class="tag">next 24 hours</span></div><div class="timeline">${segments}</div><div class="timeline-labels"><span>现在</span><span>6 小时</span><span>12 小时</span><span>18 小时</span><span>24 小时</span></div><div class="timeline-legend">${legends}</div></article>`;
  }

  function dayDots(days) {
    return `<span class="days">${weekday.map((label, index) => `<i class="${days.includes(index + 1) ? "" : "off"}">${label}</i>`).join("")}</span>`;
  }

  function slotMeter(count) {
    return `<span class="slot-meter" title="连续展示 ${count} 个时间片">${Array.from({length:4}, (_, index) => `<i class="${index < Math.min(count,4) ? "on" : ""}"></i>`).join("")}</span>`;
  }

  function playlistRow(item) {
    return `<li class="playlist-row${item.enabled ? "" : " disabled"}" data-item-id="${h(item.id)}">
      <div class="page-icon">${h(iconFor(item.page_id))}</div>
      <div class="row-thumb">${screenPicture(item)}</div>
      <div class="row-main"><div class="row-title"><strong>${h(item.name)}</strong><span class="tag">${h(item.page_title)}</span></div><div class="row-sub">${h(orientationLabel(item))}${renderModeLabel(item) ? ` · ${h(renderModeLabel(item))}` : ""} · ${h(item.schedule.start)}–${h(item.schedule.end)}</div></div>
      ${slotMeter(item.duration_slots)}${dayDots(item.schedule.days)}
      <div class="row-status">${item.is_current ? '<span class="now-pill">⚡ 正在显示</span>' : ""}<button class="icon-button menu-trigger" aria-label="${h(item.name)}菜单">•••</button></div>
      <button class="icon-button drag-handle" aria-label="拖动排序">≡</button>
    </li>`;
  }

  function renderPlaylist() {
    app.innerHTML = `
      <section class="page-head"><div><p class="eyebrow">Schedule</p><h1>播放列表</h1><p class="lead">横竖页面共用一个队列；横屏项目会在服务端旋转后发送给 Kindle。</p></div>
        <div class="playlist-toolbar"><button id="smart-skip" class="toolbar-button toggle-button" aria-pressed="${data.playlist.smart_skip}">Smart Skip</button><button id="add-page" class="primary-button">添加页面 ＋</button></div>
      </section>
      ${timelineMarkup()}
      <section class="panel playlist-panel"><ul id="playlist-list" class="playlist-list">${data.items.map(playlistRow).join("")}</ul></section>`;
    document.getElementById("smart-skip").addEventListener("click", async event => {
      const button = event.currentTarget;
      try { await api("/admin/api/playlist/settings", {method:"POST", body:{smart_skip: button.getAttribute("aria-pressed") !== "true"}}); location.reload(); }
      catch (error) { toast(error.message, true); }
    });
    document.getElementById("add-page").addEventListener("click", showAddSheet);
    app.addEventListener("click", playlistClick);
    enablePointerReorder();
  }

  function playlistClick(event) {
    const jump = event.target.closest("[data-jump]");
    if (jump) document.querySelector(`[data-item-id="${CSS.escape(jump.dataset.jump)}"]`)?.scrollIntoView({behavior:"smooth", block:"center"});
    const trigger = event.target.closest(".menu-trigger");
    if (!trigger) return;
    document.querySelectorAll(".row-menu").forEach(menu => menu.remove());
    const row = trigger.closest(".playlist-row");
    const item = data.items.find(value => value.id === row.dataset.itemId);
    const menu = document.createElement("div");
    menu.className = "row-menu";
    menu.innerHTML = `<button data-action="preview">预览</button><button data-action="settings">设置</button><button data-action="duplicate">复制</button><button data-action="render">立即重新渲染</button>${item.page_id === "shan-shui" ? '<button data-action="new-scene">换一幅山水</button>' : ""}<button data-action="toggle">${item.enabled ? "临时隐藏" : "重新启用"}</button><button class="danger" data-action="delete">从播放列表删除</button>`;
    row.appendChild(menu);
    menu.addEventListener("click", async menuEvent => {
      const action = menuEvent.target.dataset.action;
      if (!action) return;
      menu.remove();
      if (action === "preview") return showPreview(item);
      if (action === "settings") return showSettings(item);
      if (action === "delete" && !confirm(`从播放列表删除“${item.name}”？页面类型和历史图片不会被删除。`)) return;
      try { await api(`/admin/api/playlist/items/${encodeURIComponent(item.id)}/${action}`, {method:"POST"}); location.reload(); }
      catch (error) { toast(error.message, true); }
    });
    setTimeout(() => document.addEventListener("pointerdown", function close(outside) {
      if (!menu.contains(outside.target) && outside.target !== trigger) { menu.remove(); document.removeEventListener("pointerdown", close); }
    }), 0);
  }

  function showPreview(item) {
    overlay.innerHTML = `<div class="sheet-backdrop"><section class="sheet preview-dialog" role="dialog" aria-modal="true"><div class="panel-head"><div><h2>${h(item?.name || "图片预览")}</h2><p>${h(orientationLabel(item || {rotation:0}))}</p></div><button class="icon-button close-sheet">×</button></div>${item?.display_preview_url || item?.preview_url ? `<img src="${h(item.display_preview_url || item.preview_url)}" alt="${h(item.name)}大图预览">` : '<div class="empty-state">暂无图片</div>'}</section></div>`;
    bindSheetClose();
  }

  function bindSheetClose() {
    const backdrop = overlay.querySelector(".sheet-backdrop");
    overlay.querySelector(".close-sheet")?.addEventListener("click", () => overlay.replaceChildren());
    backdrop?.addEventListener("pointerdown", event => { if (event.target === backdrop) overlay.replaceChildren(); });
  }

  function showAddSheet() {
    overlay.innerHTML = `<div class="sheet-backdrop"><section class="sheet" role="dialog" aria-modal="true"><div class="panel-head"><div><h2>添加页面</h2><p>可以重复添加同一种页面并独立设置</p></div><button class="icon-button close-sheet">×</button></div><div class="metric-grid">${data.page_types.map(page => `<button class="metric add-type" data-page="${h(page.id)}"><span>${h(page.orientation_label)}</span><strong>${h(page.title)}</strong></button>`).join("")}</div></section></div>`;
    bindSheetClose();
    overlay.querySelectorAll(".add-type").forEach(button => button.addEventListener("click", async () => {
      button.disabled = true;
      try { await api("/admin/api/playlist/items", {method:"POST", body:{page_id:button.dataset.page}}); location.reload(); }
      catch (error) { toast(error.message, true); button.disabled = false; }
    }));
  }

  function showSettings(item) {
    overlay.innerHTML = `<div class="sheet-backdrop"><form id="item-settings" class="sheet" role="dialog" aria-modal="true"><div class="panel-head"><div><h2>项目设置</h2><p>${h(item.page_title)}</p></div><button class="icon-button close-sheet" type="button">×</button></div>
      <div class="form-grid">
        <div class="field full"><label>显示名称</label><input name="name" maxlength="80" value="${h(item.name)}"></div>
        <div class="field"><label>展示时长</label><select name="duration_slots">${[1,2,3,4,6,8,12].map(value => `<option value="${value}"${value === item.duration_slots ? " selected" : ""}>${value} 个时间片</option>`).join("")}</select></div>
        <div class="field"><label>展示方向</label><select name="rotation"><option value="0"${item.rotation === 0 ? " selected" : ""}>竖屏</option><option value="90"${item.rotation === 90 ? " selected" : ""}>横屏 · 向右转</option><option value="270"${item.rotation === 270 ? " selected" : ""}>横屏 · 向左转</option></select></div>
        <div class="field"><label>开始时间</label><input name="start" type="time" value="${item.schedule.start === "24:00" ? "00:00" : h(item.schedule.start)}"></div>
        <div class="field"><label>结束时间</label><input name="end" type="time" value="${item.schedule.end === "24:00" ? "00:00" : h(item.schedule.end)}"></div>
        ${item.page_id === "shan-shui" ? `<div class="field full"><label>渲染风格</label><select name="render_mode"><option value="original_gray"${item.config?.render_mode !== "kindle_gray" ? " selected" : ""}>原版灰阶（默认）</option><option value="kindle_gray"${item.config?.render_mode === "kindle_gray" ? " selected" : ""}>Kindle 优化灰阶</option></select><small>切换模式会保留同一幅山水，只改变灰阶处理。</small></div>` : ""}
        <div class="field full"><label>生效星期</label><div class="check-days">${weekday.map((label,index) => `<label><input type="checkbox" name="day" value="${index+1}"${item.schedule.days.includes(index+1) ? " checked" : ""}><span>${label}</span></label>`).join("")}</div></div>
      </div>${item.page_id === "ai-accounts" ? '<section id="codex-account-settings" class="codex-settings" aria-label="Codex 账号管理"></section>' : ''}<div class="sheet-actions"><button class="secondary-button close-sheet" type="button">取消</button><button class="primary-button" type="submit">保存设置</button></div></form></div>`;
    if (item.page_id === "ai-accounts") window.mountCodexAccounts?.(document.getElementById("codex-account-settings"), {api, toast, h, formatTime});
    overlay.querySelectorAll(".close-sheet").forEach(button => button.addEventListener("click", () => overlay.replaceChildren()));
    document.getElementById("item-settings").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const body = {name: form.get("name"), duration_slots:Number(form.get("duration_slots")), rotation:Number(form.get("rotation")), schedule:{start:form.get("start"), end:form.get("end") === "00:00" ? "24:00" : form.get("end"), days:form.getAll("day").map(Number)}};
      if (item.page_id === "shan-shui") body.config = {render_mode:form.get("render_mode") || "original_gray"};
      try { await api(`/admin/api/playlist/items/${encodeURIComponent(item.id)}`, {method:"POST", body}); location.reload(); }
      catch (error) { toast(error.message, true); }
    });
  }

  function enablePointerReorder() {
    const list = document.getElementById("playlist-list");
    let active = null;
    list.querySelectorAll(".drag-handle").forEach(handle => handle.addEventListener("pointerdown", event => {
      if (event.button !== 0) return;
      const row = handle.closest(".playlist-row");
      handle.setPointerCapture(event.pointerId);
      active = {row, handle, pointerId:event.pointerId, startY:event.clientY, moved:false};
      row.classList.add("dragging");
    }));
    list.addEventListener("pointermove", event => {
      if (!active || event.pointerId !== active.pointerId) return;
      const delta = event.clientY - active.startY;
      if (Math.abs(delta) > 8) active.moved = true;
      active.row.style.transform = `translateY(${delta}px) scale(1.01)`;
      const candidate = document.elementFromPoint(event.clientX, event.clientY)?.closest(".playlist-row");
      if (candidate && candidate !== active.row && candidate.parentElement === list) {
        const box = candidate.getBoundingClientRect();
        list.insertBefore(active.row, event.clientY < box.top + box.height / 2 ? candidate : candidate.nextSibling);
        active.startY = event.clientY;
        active.row.style.transform = "translateY(0) scale(1.01)";
      }
    });
    list.addEventListener("pointerup", async event => {
      if (!active || event.pointerId !== active.pointerId) return;
      active.row.classList.remove("dragging"); active.row.style.transform = "";
      const moved = active.moved; active = null;
      if (!moved) return;
      const item_ids = [...list.querySelectorAll(".playlist-row")].map(row => row.dataset.itemId);
      try { await api("/admin/api/playlist/reorder", {method:"POST", body:{item_ids}}); toast("播放顺序已保存"); }
      catch (error) { toast(error.message, true); setTimeout(() => location.reload(), 500); }
    });
    list.addEventListener("pointercancel", () => { if (active) { active.row.classList.remove("dragging"); active.row.style.transform = ""; active = null; location.reload(); } });
  }

  if (document.body.dataset.view === "playlist") renderPlaylist(); else renderDashboard();
})();
