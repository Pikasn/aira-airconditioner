(() => {
  'use strict';
  let installed = false;
  let dragCounter = 0;
  window.__bindDesktopDrag = (element, shouldStart, doubleClick = false) => {
    let start = null, moved = false, previous = {time:0,x:0,y:0}, frame = null, delta = [0,0];
    const send = finished => {
      if (!start || !moved) return;
      window.pywebview?.api?.drag_window?.(start.token,delta[0],delta[1],finished,Date.now()*1000+(dragCounter++%1000));
    };
    element.addEventListener('pointerdown', event => {
      if (event.button!==0 || !shouldStart(event)) return;
      if (doubleClick && event.timeStamp-previous.time<450 && Math.hypot(event.screenX-previous.x,event.screenY-previous.y)<5) {
        previous.time=0;window.pywebview?.api?.window_action('maximize');return;
      }
      previous={time:event.timeStamp,x:event.screenX,y:event.screenY};
      start={token:Date.now()*1000+(dragCounter++%1000),x:event.screenX,y:event.screenY};moved=false;delta=[0,0];
      element.setPointerCapture(event.pointerId);
    });
    element.addEventListener('pointermove', event => {
      if (!start) return;
      delta=[event.screenX-start.x,event.screenY-start.y];
      if (!moved && Math.hypot(...delta)<4) return;
      moved=true;previous.time=0;
      if(frame===null)frame=requestAnimationFrame(()=>{frame=null;send(false)});
    });
    const finish = () => {
      if(frame!==null){cancelAnimationFrame(frame);frame=null}
      send(true);start=null;
    };
    element.addEventListener('pointerup',finish);
    element.addEventListener('pointercancel',finish);
    return {wasDragged:()=>moved};
  };
  const icons = {
    minimize: '<path d="M3 8h10"/>',
    maximize: '<rect class="maximize-icon" x="3.5" y="3.5" width="9" height="9" rx="1"/><g class="restore-icon"><path d="M6 3.5h6.5V10"/><rect x="3.5" y="6" width="6.5" height="6.5" rx=".8"/></g>',
    close: '<path d="m4 4 8 8m0-8-8 8"/>'
  };
  function install() {
    const api = window.pywebview?.api;
    if (installed || !api?.window_action || !api?.window_state) return;
    installed = true;
    document.documentElement.classList.add('desktop');
    const bar = document.createElement('div');
    bar.className = 'window-chrome';
    bar.setAttribute('role', 'toolbar');
    bar.setAttribute('aria-label', '窗口');
    for (const [action, label] of [['minimize', '最小化'], ['maximize', '最大化'], ['close', '关闭']]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.action = action;
      button.setAttribute('aria-label', label);
      button.title = label;
      button.innerHTML = `<svg viewBox="0 0 16 16" aria-hidden="true">${icons[action]}</svg>`;
      button.addEventListener('click', () => api.window_action(action === 'close' ? 'dismiss' : action));
      bar.append(button);
    }
    const refresh = () => api.window_state().then(state => {
      window.__desktopState = state;
      document.documentElement.classList.toggle('native-floating', !!state.nativeFloating);
      document.documentElement.classList.toggle('is-maximized', state.maximized);
      document.documentElement.classList.toggle('has-native-glass', state.glass);
      for (const view of ['standard', 'compact', 'bubble', 'settings']) document.documentElement.classList.toggle(`presentation-${view}`, (state.view || 'standard') === view);
      document.documentElement.classList.toggle('edge-hidden', !!state.edgeHidden);
      document.documentElement.dataset.edge = state.edge || '';
      const label = state.maximized ? '还原' : '最大化';
      const button = bar.querySelector('[data-action=maximize]');
      button.title = label;
      button.setAttribute('aria-label', label);
      const close = bar.querySelector('[data-action=close]');
      close.title = '关闭';
      close.setAttribute('aria-label', close.title);
      for (const choice of document.querySelectorAll('[data-presentation]')) choice.setAttribute('aria-pressed', String(choice.dataset.presentation === state.presentation));
      const topmost = document.getElementById('floatingTopmost');
      if (topmost) topmost.checked = state.floatingTopmost === true;
      window.dispatchEvent(new CustomEvent('presentationchange', { detail: state }));
    }).catch(() => {});
    window.__bindDesktopDrag(bar,event=>!event.target.closest('button'),true);
    document.body.prepend(bar);
    for (const edge of ['left', 'right', 'top', 'bottom', 'top-left', 'top-right', 'bottom-left', 'bottom-right']) {
      const handle = document.createElement('div');
      handle.className = `window-resize resize-${edge}`;
      handle.setAttribute('aria-hidden', 'true');
      handle.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        event.preventDefault();
        api.window_action(`resize-${edge}`);
      });
      document.body.append(handle);
    }
    window.addEventListener('resize', refresh);
    window.addEventListener('nativewindowchange', refresh);
    const settings = document.getElementById('windowSettings');
    if (settings && api.set_presentation) {
      settings.hidden = false;
      for (const button of settings.querySelectorAll('[data-presentation]')) button.addEventListener('click', () => api.set_presentation(button.dataset.presentation));
      const topmost = document.getElementById('floatingTopmost');
      if (topmost && api.set_floating_topmost) topmost.addEventListener('change', () => api.set_floating_topmost(topmost.checked));
    }
    api.page_ready?.(location.pathname === '/setup');
    refresh();
  }
  window.addEventListener('pywebviewready', install, { once: true });
  install();
})();
