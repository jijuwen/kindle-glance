/* Daily preferences share the app shell; first-run steps live in setup.js. */
(() => {
  'use strict';
  let dirty = new Set(), active = false, saving = false, mountVersion = 0;
  window.KindleSettings = {
    hasUnsavedChanges: () => active && (dirty.size > 0 || saving),
    dispose: () => { mountVersion++; active = false; dirty.clear(); },
    async mount(root, {api, toast, h}) {
      const version=++mountVersion;active = true; dirty.clear();
      root.innerHTML = '<section class="page-head"><h1>设置</h1></section><p role="status">正在读取设置…</p>';
      const state = await api('/admin/api/settings');
      if (!active || version!==mountVersion) return;
      let selected = state.location;
      const field = (id, label, value = '', type = 'text', extra = '') => `<div class="field"><label for="${id}">${label}</label><input id="${id}" type="${type}" value="${h(value)}" ${extra}></div>`;
      const prefs = state.display_preferences, loc = state.location || {};
      const saveButton = '<div class="settings-actions"><span class="save-state" role="status"></span><button class="primary-button" type="submit">保存修改</button></div>';
      root.innerHTML = `<section class="page-head settings-heading"><div><h1>设置</h1><p class="lead">调整看板与设备，保存后生效。</p></div></section>
      <div class="settings-stack">
        <section class="panel settings-panel"><div class="panel-head"><h2>地区与显示</h2><span class="tag">${h(loc.name || '未选择地点')}</span></div>
          <form id="region-settings">
            <div class="city-search">${field('city-query','搜索城市、区县','','search','placeholder="城市、拼音或英文" maxlength="100"')}<button type="button" id="city-search" class="secondary-button">搜索</button></div>
            <div id="city-results" class="city-results" aria-live="polite"></div>
            <p id="chosen-city" class="settings-note">${h(loc.name)} · ${h(state.timezone)}</p>
            <details class="settings-details"><summary>手动填写地点与时区</summary><div class="settings-grid">
              ${field('city-name','地点名称',loc.name || '', 'text', 'required maxlength="100"')}
              ${field('zone','IANA 时区',state.timezone,'text','required')}
              ${field('latitude','纬度',loc.latitude ?? '', 'number','required min="-90" max="90" step="any"')}
              ${field('longitude','经度',loc.longitude ?? '', 'number','required min="-180" max="180" step="any"')}
            </div></details>
            <div class="settings-grid">
              <div class="field"><label for="temperature">温度单位</label><select id="temperature"><option value="celsius">摄氏 °C</option><option value="fahrenheit">华氏 °F</option></select></div>
              <div class="field"><label for="week-start">一周起始日</label><select id="week-start"><option value="0">周一</option><option value="6">周日</option></select></div>
              <div class="field"><label for="hour-format">时间格式</label><select id="hour-format"><option value="24">24 小时制</option><option value="12">12 小时制</option></select></div>
              <label class="settings-check"><input id="email-mask" type="checkbox" ${prefs.mask_email?'checked':''}>遮罩用量看板中的邮箱</label>
            </div>${saveButton}
          </form>
        </section>
        <section class="panel settings-panel"><div class="panel-head"><h2>Kindle 连接</h2></div>
          <form id="device-settings">${field('device-url','Kindle 能访问的服务地址',state.external_base_url,'url','placeholder="https://kindle.example.com"')}<p class="settings-note" id="device-status">${state.device?'最近取图：'+h(new Date(state.device.at*1000).toLocaleString('zh-CN',{timeZone:state.timezone})):'等待 Kindle 连接'}</p>${saveButton}</form>
          <div class="button-row"><button type="button" class="secondary-button" data-setting-action="connection">显示连接信息</button><button type="button" class="quiet-button" data-setting-action="copy">复制连接信息</button><button type="button" class="quiet-button" data-setting-action="device">检查连接</button></div><pre id="connection-info" class="connection-info" hidden></pre>
        </section>
        <section class="panel settings-panel"><div class="panel-head"><h2>账号与安全</h2></div>
          <details class="settings-details"><summary>修改管理密码</summary><form id="password-settings"><div class="settings-grid">${field('old-password','当前密码','','password','required autocomplete="current-password"')}${field('new-password','新密码','','password','required minlength="6" autocomplete="new-password"')}</div><div class="settings-actions"><button class="secondary-button" type="submit">修改并重新登录</button></div></form></details>
          <details class="settings-details"><summary>设备令牌</summary><p class="settings-note">更换后需要在 Kindle 中更新连接信息。</p><button type="button" class="quiet-button" data-setting-action="rotate">更换设备令牌</button></details>
        </section>
        <details class="panel settings-panel"><summary>高级</summary><div class="advanced-content"><div class="button-row"><a class="secondary-button" href="/admin/api/settings/export" download>导出显示偏好</a><button class="quiet-button" type="button" data-setting-action="diagnostics">查看诊断</button></div><form id="import-settings">${field('preferences-file','导入显示偏好','','file','accept="application/json" required')}<p class="settings-note">仅导入显示偏好，保留地点、播放列表和连接信息。</p><button class="secondary-button" type="submit">导入</button></form><pre id="diagnostics" class="connection-info" hidden></pre></div></details>
      </div>`;
      const el = id => root.querySelector('#'+id), val = id => el(id).value;
      el('temperature').value=prefs.temperature_unit;el('week-start').value=prefs.week_start;el('hour-format').value=prefs.hour_format;
      const lockMap={location:['city-query','city-search','city-name','latitude','longitude'],timezone:['zone','city-query','city-search'],display_preferences:['temperature','week-start','hour-format','email-mask','preferences-file'],external_base_url:['device-url']};
      for(const key of state.locked_fields||[])for(const id of lockMap[key]||[])el(id).disabled=true;
      if(state.locked_fields?.length){const note=document.createElement('p');note.className='settings-note';note.textContent='部分选项由部署配置锁定。';root.querySelector('.settings-heading').append(note);}
      const mark = form => {dirty.add(form.id);const label=form.querySelector('.save-state');if(label)label.textContent='尚未保存';};
      root.oninput = e => {if(e.target.form && e.target.id!=='city-query')mark(e.target.form);};
      root.onchange = root.oninput;
      async function save(values, form){
        for(const key of state.locked_fields||[])delete values[key];
        const result=await api('/admin/api/settings',{method:'POST',body:{...values,revision:state.revision}});
        Object.assign(state,result);dirty.delete(form.id);const label=form.querySelector('.save-state');if(label)label.textContent='已保存';toast('已保存，相关预览会自动更新');
      }
      root.onsubmit = async e => {
        e.preventDefault();if(saving)return;const form=e.target;if(!form.reportValidity())return;
        saving=true;const controls=[...root.querySelectorAll('input,select,button')].filter(el=>!el.disabled);controls.forEach(el=>el.disabled=true);
        try{
          if(form.id==='region-settings'){
            const same=selected&&selected.name===val('city-name')&&selected.latitude===Number(val('latitude'))&&selected.longitude===Number(val('longitude'));
            await save({location:{id:same?selected.id:'manual',name:val('city-name'),latitude:Number(val('latitude')),longitude:Number(val('longitude'))},timezone:val('zone'),display_preferences:{temperature_unit:val('temperature'),week_start:Number(val('week-start')),hour_format:val('hour-format'),mask_email:el('email-mask').checked}},form);
            el('chosen-city').textContent=state.location.name+' · '+state.timezone;root.querySelector('.settings-panel .tag').textContent=state.location.name;
          } else if(form.id==='device-settings')await save({external_base_url:val('device-url')},form);
          else if(form.id==='password-settings'){
            await api('/admin/api/password',{method:'POST',body:{current:val('old-password'),password:val('new-password')}});dirty.clear();saving=false;location.href='/admin/login';
          } else if(form.id==='import-settings'){
            if(dirty.has('region-settings'))throw Error('请先保存地区与显示的修改，再导入偏好');
            const file=el('preferences-file').files[0];if(!file||file.size>16384)throw Error('请选择不超过 16 KB 的偏好文件');
            const imported=JSON.parse(await file.text());if(imported.schema_version!==1||!imported.display_preferences)throw Error('偏好文件格式不支持');
            await save({display_preferences:imported.display_preferences},form);
            el('temperature').value=state.display_preferences.temperature_unit;el('week-start').value=state.display_preferences.week_start;el('hour-format').value=state.display_preferences.hour_format;el('email-mask').checked=state.display_preferences.mask_email;
          }
        }catch(error){toast(error.message,true);}finally{saving=false;controls.forEach(el=>el.disabled=false);}
      };
      async function search(){
        if(el('city-search').disabled)return;
        const query=val('city-query').trim();if(query.length<2){toast('请输入至少 2 个字符',true);return;}
        const results=el('city-results');results.textContent='正在搜索…';el('city-search').disabled=true;
        try{
          const found=await api('/admin/api/locations?q='+encodeURIComponent(query));if(!active||val('city-query').trim()!==query)return;
          results.replaceChildren();
          const add=(item,parent)=>{const button=document.createElement('button');button.type='button';button.className='location-choice';button.textContent=item.label||item.name;button.onclick=()=>{selected=item;for(const [id,value] of Object.entries({'city-name':item.name,latitude:item.latitude,longitude:item.longitude,zone:item.timezone}))el(id).value=value;el('chosen-city').textContent=(item.label||item.name)+' · '+item.timezone;mark(el('region-settings'));results.replaceChildren();};parent.append(button);};
          (found.results||[]).forEach(item=>add(item,results));
          if(found.more_results?.length){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='更多地点';details.append(summary);found.more_results.forEach(item=>add(item,details));results.append(details);}
          if(!found.results?.length&&!found.more_results?.length)results.textContent='未找到地点，可手动填写；当前地点未改变。';
        }catch(error){results.textContent='搜索暂不可用，可重试或手动填写。';}finally{el('city-search').disabled=false;}
      }
      el('city-search').onclick=search;
      el('city-query').onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();search();}};
      root.onclick=async e=>{
        const button=e.target.closest('[data-setting-action]');if(!button)return;const action=button.dataset.settingAction;button.disabled=true;
        try{
          if(action==='connection'||action==='copy'||action==='rotate'){
            if(action==='copy'&&dirty.has('device-settings'))throw Error('请先保存服务地址');
            if(action==='rotate'&&!confirm('更换后旧设备令牌立即失效，需在 Kindle 更新。继续？'))return;
            const response=await api(action==='rotate'?'/admin/api/device/rotate':'/admin/api/device/token',action==='rotate'?{method:'POST'}:{});
            const text=state.external_base_url+'\n'+response.token;el('connection-info').textContent=text;el('connection-info').hidden=false;
            if(action==='copy'){try{await navigator.clipboard.writeText(text);toast('已复制');}catch{toast('复制未成功，请从连接信息中手动复制',true);}}
          }else if(action==='device'){
            const response=await api('/admin/api/settings');el('device-status').textContent=response.device?'最近取图：'+new Date(response.device.at*1000).toLocaleString('zh-CN',{timeZone:response.timezone}):'等待 Kindle 连接';
          }else if(action==='diagnostics'){
            const response=await api('/admin/api/diagnostics');el('diagnostics').textContent=JSON.stringify(response,null,2);el('diagnostics').hidden=false;
          }
        }catch(error){toast(error.message,true);}finally{button.disabled=false;}
      };
    }
  };
})();
