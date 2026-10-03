/* Account management lives only in the existing AI board settings. */
(() => {
  "use strict";
  window.mountCodexAccounts = (root, {api, toast, h, formatTime}) => {
    let state, timer, busy = false, stopped = false, lastSignature = "";
    const dialog = root.closest('[role="dialog"]');
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.setAttribute("aria-label", "用量提示设置");
    const close = () => {
      stopped = true;
      clearTimeout(timer);
      observer.disconnect();
      document.removeEventListener("keydown", keyboard);
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
    const keyboard = event => {
      if (event.key === "Escape") { dialog.closest(".sheet-backdrop").remove(); return; }
      if (event.key !== "Tab") return;
      const focusable = [...dialog.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), summary, [tabindex="0"]')].filter(el => el.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", keyboard);
    const observer = new MutationObserver(() => { if (!root.isConnected) close(); });
    observer.observe(document.getElementById("overlay-root"), {childList:true, subtree:true});
    dialog.querySelector(".close-sheet")?.focus();

    const labels = {unbound:"未授权", ok:"同步正常", syncing:"正在同步", error:"同步异常", reauth_required:"需要重新授权"};
    const zone = JSON.parse(document.getElementById("bootstrap").textContent).settings?.timezone || "UTC";
    const subscriptionTime = seconds => seconds ? new Intl.DateTimeFormat("zh-CN", {timeZone:zone,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(seconds*1000)) : "尚未获取";
    const subscriptionMarkup = slot => {
      const sub = slot.subscription;
      if (!sub) return '<section class="codex-subscription"><p class="codex-hint">正在获取订阅信息…</p></section>';
      const renewable = sub.will_renew === true;
      const stale = sub.status !== "ok" || !sub.updated_at || Date.now()/1000 - sub.updated_at > 7200;
      const crossed = sub.cycle_ends_at && sub.cycle_ends_at <= Date.now()/1000 && sub.active !== false;
      const renewal = sub.active === false ? "订阅已结束" : sub.will_renew === true ? "自动续费已开启" : sub.will_renew === false ? "自动续费已关闭" : "续费状态尚未获取";
      const warning = slot.subscription_error || (crossed ? "已到周期结束时间，等待更新" : stale ? "订阅信息待更新" : sub.is_delinquent ? "订阅付款待处理" : "");
      const remaining = sub.active === false ? "已结束" : sub.cycle_ends_at > Date.now()/1000 ? `${Math.ceil((sub.cycle_ends_at - Date.now()/1000)/86400)} 天` : crossed ? "待更新" : "未知";
      return `<section class="codex-subscription" aria-label="自动订阅信息"><dl><div><dt>${renewable ? "续费时间" : "本周期结束"} <span>(${h(zone)})</span></dt><dd>${h(subscriptionTime(sub.cycle_ends_at))}</dd></div><div><dt>${renewable ? "距离续费" : "本周期剩余"}</dt><dd>${remaining}</dd></div></dl><p class="codex-hint">${renewal} · 自动获取${sub.updated_at ? " · 更新于 " + h(subscriptionTime(sub.updated_at)) : ""}</p>${warning ? `<p class="codex-hint warn" role="status">${h(warning)}${sub.source !== "none" ? "；当前显示上次获取的信息。" : ""}</p>` : ""}</section>`;
    };
    const button = (action, label, slot, style = "secondary-button") => `<button type="button" class="${style}" data-codex-action="${action}" data-slot="${slot}">${label}</button>`;
    const loginMarkup = slot => {
      const login = slot.login;
      if (!login) return "";
      if (login.state === "starting") return `<div class="codex-auth-box" role="status">正在准备官方授权… ${button("cancel", "取消", slot.slot)}</div>`;
      if (login.state === "waiting") return `<div class="codex-auth-box"><strong>在 OpenAI 官方页面完成登录</strong><p>选择要放在第 ${slot.slot} 栏的账号，输入下方一次性设备码。账号在其他浏览器资料中？复制授权链接，到对应窗口打开即可。</p><div class="codex-device-code"><code>${h(login.code)}</code>${button("copy", "复制设备码", slot.slot)}</div><div class="button-row"><a class="primary-button" href="${h(login.verification_url)}" target="_blank" rel="noopener noreferrer">打开官方授权页 ↗</a>${button("copy-link", "复制授权链接", slot.slot)}${button("cancel", "取消授权", slot.slot)}</div><p class="codex-hint" role="status">等待授权 · 本页会自动更新 · 最晚 ${formatTime(login.expires_at, true)} 结束<br>若官方提示未开启，请在 ChatGPT 安全设置中开启设备码登录。</p></div>`;
      if (login.state === "ready") return `<div class="codex-auth-box"><strong>请确认绑定的账号</strong><p class="codex-email">${h(login.email)} · ${h(login.plan)}</p><p>${login.error ? h(login.error) : "已成功读取额度，确认后保存到这个栏位。"}</p><div class="button-row">${button("confirm", "确认绑定到第 " + slot.slot + " 栏", slot.slot, "primary-button")}${button("cancel", "取消", slot.slot)}</div></div>`;
      if (login.state === "error") return `<p class="codex-hint warn" role="status">${h(login.error)}</p>`;
      if (login.state === "expired") return '<p class="codex-hint warn">授权已过期，请重新开始。</p>';
      return "";
    };
    const card = slot => {
      const active = ["starting","waiting","ready"].includes(slot.login?.state);
      const stale = slot.bound && slot.last_success && Date.now()/1000 - slot.last_success > 1800;
      return `<article class="codex-account" data-account-slot="${slot.slot}">
        <div class="codex-account-head"><span class="codex-slot-number">${slot.slot}</span><div class="codex-account-title"><strong class="codex-email">${h(slot.email || "账号 " + slot.slot)}</strong><small>${slot.bound ? h(slot.plan || "未知套餐") : "授权后显示在对应栏位"}</small></div><span class="codex-status ${slot.state === "ok" && !stale ? "good" : slot.state === "unbound" ? "" : "warn"}">${stale && slot.state === "ok" ? "数据已过期" : labels[slot.state] || "等待同步"}</span></div>
        ${slot.bound ? `<p class="codex-hint">最近成功同步 ${formatTime(slot.last_success)}${slot.error ? `<br><span class="warn">${h(slot.error)}</span>` : ""}</p><div class="codex-quota-summary">${slot.windows.map(w => `<span>${h(w.label)}剩余 <b>${w.remaining_percent === null ? "未知" : h(w.remaining_percent) + "%"}</b></span>`).join("")}${slot.reset_credits !== null ? `<span>可用重置券 <b>${h(slot.reset_credits)}</b></span>` : ""}</div>` : ""}
        ${!active ? `<div class="button-row">${button("login", slot.bound ? "重新授权" : "授权账号", slot.slot, slot.bound ? "secondary-button" : "primary-button")}${slot.bound ? button("sync", "立即同步", slot.slot) + button("unlink", "解除绑定", slot.slot, "quiet-button danger") : ""}</div>` : ""}
        ${loginMarkup(slot)}
        ${slot.bound ? subscriptionMarkup(slot) : ""}
      </article>`;
    };

    function render() {
      if (state.installed === false) { root.innerHTML = `<h2>Codex 用量未安装</h2><p>这是可选组件，基础看板可正常使用。请按安装文档启用采集器后再授权账号。</p>`; return; }
      const signature = JSON.stringify(state);
      if (signature === lastSignature) return;
      const focused = document.activeElement?.dataset?.codexAction;
      const focusedSlot = document.activeElement?.dataset?.slot;
      lastSignature = signature;
      root.innerHTML = `<div class="panel-head"><div><h2>Codex 账号</h2><p>四个固定栏位 · 额度每 15 分钟同步 · 订阅每小时更新</p></div></div><div class="codex-source ${state.enabled ? "good" : ""}">${state.enabled ? "已启用服务器自动同步，电脑关机也会更新。" : "采集器已安装，请完成账号授权后启用自动同步。"}</div><div class="codex-accounts">${state.slots.map(card).join("")}</div>${!state.enabled ? `<div class="codex-activate"><p>先核对已授权账号的额度，再切换看板。切换后只显示这些已绑定账号。</p><button type="button" class="primary-button" data-codex-action="enable" ${state.slots.some(s => s.bound && s.last_success) ? "" : "disabled"}>启用服务器自动同步</button></div>` : ""}`;
      if (focused) root.querySelector(`[data-codex-action="${focused}"][data-slot="${focusedSlot}"]`)?.focus();
    }

    async function refresh() {
      if (stopped || !root.isConnected) return;
      try {
        if (!busy) { state = await api("/admin/api/codex/accounts"); if (!root.isConnected) return; render(); }
      } catch (error) {
        if (!state) root.innerHTML = `<div class="panel-head"><h2>Codex 账号</h2></div><p class="warn" role="status">${h(error.message)}</p><button type="button" class="secondary-button" data-codex-action="retry">重试连接</button>`;
      } finally {
        if (!stopped && root.isConnected && state?.installed !== false) timer = setTimeout(refresh, state?.slots.some(s => ["starting","waiting","ready"].includes(s.login?.state)) ? 2000 : 10000);
      }
    }

    root.addEventListener("click", async event => {
      const target = event.target.closest("[data-codex-action]");
      if (!target || busy) return;
      const action = target.dataset.codexAction, slot = Number(target.dataset.slot);
      if (action === "retry") { clearTimeout(timer); refresh(); return; }
      if (action === "copy" || action === "copy-link") {
        const value = action === "copy-link" ? state.slots[slot - 1].login.verification_url : state.slots[slot - 1].login.code;
        try { await navigator.clipboard.writeText(value); toast(action === "copy-link" ? "授权链接已复制，可在其他浏览器资料中打开" : "设备码已复制"); }
        catch (_) { window.prompt(action === "copy-link" ? "复制此链接，到对应浏览器资料中打开：" : "复制此设备码：", value); }
        return;
      }
      if (action === "unlink" && !confirm("解除绑定后会删除服务器上的此账号登录凭据，并清空对应栏位。继续？")) return;
      if (action === "enable" && !confirm("切换后，看板只显示已在这里绑定的账号，历史快照不再参与显示。确认启用？")) return;
      busy = true; target.disabled = true;
      try {
        state = await api(action === "enable" ? "/admin/api/codex/enable" : `/admin/api/codex/accounts/${slot}/${action}`, {method:"POST", body:{}});
        if (root.isConnected) render();
        if (action === "confirm") toast("账号已绑定");
        if (action === "sync") toast("已安排同步");
        if (action === "enable") toast("已启用，Kindle 下次取图时显示新数据");
      } catch (error) { toast(error.message, true); }
      finally { busy = false; if (target.isConnected) target.disabled = false; clearTimeout(timer); if (!stopped) timer = setTimeout(refresh, 1000); }
    });
    root.innerHTML = '<div class="panel-head"><h2>Codex 账号</h2></div><p class="codex-hint" role="status">正在读取账号状态…</p>';
    refresh();
  };
})();
