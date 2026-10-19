(() => {
  'use strict';
  const form = document.getElementById('connectionForm');
  const ip = document.getElementById('deviceIp');
  const token = document.getElementById('deviceToken');
  const connect = document.getElementById('connect');
  const discover = document.getElementById('discover');
  const message = document.getElementById('setupMessage');
  const open = document.getElementById('openControl');
  const list = document.getElementById('deviceList');
  const discoveryMessage = document.getElementById('discoveryMessage');
  let working = false;

  async function request(url, options = {}) {
    const response = await fetch(url, {
      ...options, signal: AbortSignal.timeout(18000), cache: 'no-store', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Aira-Request': '1' }
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || '操作未完成，请重试');
    return data;
  }

  function show(text, kind = '') {
    message.textContent = text;
    message.className = 'result ' + kind;
  }

  function apply(snapshot) {
    if (snapshot.device?.ip && !ip.value) ip.value = snapshot.device.ip;
    token.required = !snapshot.tokenSaved;
    token.placeholder = snapshot.tokenSaved ? '已保存，留空继续使用' : '32 位设备 Token';
    open.hidden = !snapshot.connected;
    if (snapshot.connected) show('已连接', 'success');
    else if (snapshot.error) show(snapshot.error.message, 'error');
    else if (snapshot.configured) show('连接信息已保存，正在读取设备');
  }

  function busy(value, text) {
    working = value;
    connect.disabled = discover.disabled = value;
    ip.readOnly = token.readOnly = value;
    connect.textContent = text || '测试并连接';
    form.setAttribute('aria-busy', String(value));
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (working || !form.reportValidity()) return;
    busy(true, '连接中…');
    show('正在验证设备');
    try {
      const body = { ip: ip.value.trim() };
      if (token.value.trim()) body.token = token.value.trim();
      const snapshot = await request('/api/device', { method: 'POST', body: JSON.stringify(body) });
      token.value = '';
      apply(snapshot);
    } catch (error) {
      show(error.message === 'Failed to fetch' ? '本机服务无法连接，请重新启动空调程序' : error.message, 'error');
    } finally {
      busy(false);
    }
  });

  discover.addEventListener('click', async () => {
    if (working) return;
    busy(true);
    discover.textContent = '查找中';
    list.replaceChildren();
    list.hidden = true;
    discoveryMessage.hidden = false;
    discoveryMessage.textContent = '正在查找局域网中的米家设备…';
    try {
      const { devices } = await request('/api/discover', { method: 'POST', body: '{}' });
      if (!devices.length) discoveryMessage.textContent = '未找到设备，也可在路由器中查看 IP。';
      else {
        discoveryMessage.textContent = '选择伴侣的 IP，连接时会核对型号。';
        for (const device of devices) {
          const choice = document.createElement('button');
          choice.type = 'button';
          choice.textContent = device.ip;
          choice.addEventListener('click', () => { ip.value = device.ip; token.focus(); });
          list.append(choice);
        }
        list.hidden = false;
        if (devices.length === 1) ip.value = devices[0].ip;
      }
    } catch (error) {
      discoveryMessage.textContent = error.message;
    } finally {
      discover.textContent = '查找';
      busy(false);
    }
  });

  request('/api/status').then(apply).catch(() => show('本机服务无法连接，请重新启动空调程序', 'error'));
})();
