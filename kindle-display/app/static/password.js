(() => {
  'use strict';
  const eye = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/><path class="password-eye-slash" d="m3 3 18 18"/></svg>';
  function enhance() {
    document.querySelectorAll('input[type="password"]:not([data-password-field])').forEach(input => {
      // This marker survives revealing the value, so draft saving still excludes it.
      input.dataset.passwordField = 'true';
      const wrapper = document.createElement('div');
      wrapper.className = 'password-control';
      input.before(wrapper);
      wrapper.append(input);
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'password-toggle';
      toggle.setAttribute('aria-label', '显示密码');
      toggle.setAttribute('aria-pressed', 'false');
      toggle.setAttribute('aria-controls', input.id);
      toggle.title = '显示密码';
      toggle.innerHTML = eye;
      toggle.addEventListener('click', () => {
        const visible = input.type === 'password';
        input.type = visible ? 'text' : 'password';
        toggle.setAttribute('aria-pressed', String(visible));
        toggle.setAttribute('aria-label', visible ? '隐藏密码' : '显示密码');
        toggle.title = visible ? '隐藏密码' : '显示密码';
      });
      wrapper.append(toggle);
    });
  }
  enhance();
  new MutationObserver(enhance).observe(document.body, {childList: true, subtree: true});
})();
