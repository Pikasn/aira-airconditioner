  // 合并拖动产生的设置，串行下发；旧响应不能覆盖更新的手势。
  class DeviceBridge {
    constructor(app) {
      this.app = app;
      this.pending = {};
      this.revision = 0;
      this.busy = this.polling = this.disposed = false;
      this.retries = 0;
      this.timer = this.messageTimer = null;
      this.readyAt = 0;
      this.statusLink = requiredElement('deviceConnection');
      this.message = requiredElement('deviceMessage');
      requiredElement('deviceSettings').hidden = false;
      app.events.signal.addEventListener('abort', () => this.dispose(), { once: true });
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) this.poll();
      }, { signal: app.events.signal });
      this.pollTimer = setInterval(() => this.poll(), 3000);
      this.poll();
    }

    async request(url, options = {}) {
      const signal = AbortSignal.any([this.app.events.signal, AbortSignal.timeout(18000)]);
      const response = await fetch(url, {
        ...options, signal, cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Aira-Request': '1' }
      });
      const payload = await response.json();
      if (!response.ok) {
        const error = new Error(payload.error?.message || '设备操作未完成');
        error.code = payload.error?.code;
        error.snapshot = payload.snapshot;
        throw error;
      }
      return payload;
    }

    showStatus(snapshot) {
      this.statusLink.hidden = !!snapshot.connected;
      this.statusLink.textContent = snapshot.configured ? '设备离线 · 设置' : '连接空调';
      this.statusLink.title = snapshot.error?.message || '连接米家空调伴侣 2';
    }

    accept(snapshot, includeState = true) {
      if (this.disposed) return;
      this.showStatus(snapshot);
      this.app.acceptDevice(snapshot, includeState);
    }

    async poll() {
      if (this.disposed || document.hidden || this.polling || this.busy || Object.keys(this.pending).length) return;
      const revision = this.revision;
      this.polling = true;
      try {
        const snapshot = await this.request('/api/status');
        if (revision === this.revision && !this.busy && !Object.keys(this.pending).length) this.accept(snapshot);
      } catch {
        if (revision === this.revision && !this.disposed && !this.busy) this.accept({ connected: false, configured: true });
      } finally {
        this.polling = false;
      }
    }

    queue(patch) {
      if (this.disposed) return;
      this.revision++;
      if (patch.power === false) this.pending = { power: false };
      else Object.assign(this.pending, patch);
      this.readyAt = Date.now() + (patch.power === false ? 0 : 350);
      this.schedule();
    }

    schedule() {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.flush(), Math.max(0, this.readyAt - Date.now()));
    }

    async setTimer(action, due) {
      const snapshot = await this.request('/api/timer', { method: 'POST', body: JSON.stringify({ action, due }) });
      this.accept(snapshot);
      return snapshot;
    }

    async clearTimer() {
      const snapshot = await this.request('/api/timer', { method: 'DELETE', body: '{}' });
      this.accept(snapshot);
      return snapshot;
    }

    async flush() {
      if (this.disposed || this.busy || !Object.keys(this.pending).length) return;
      const patch = this.pending, revision = this.revision;
      this.pending = {};
      this.busy = true;
      this.app.elements.scene.setAttribute('aria-busy', 'true');
      try {
        const snapshot = await this.request('/api/state', { method: 'PATCH', body: JSON.stringify(patch) });
        this.retries = 0;
        this.accept(snapshot, revision === this.revision && !Object.keys(this.pending).length);
      } catch (error) {
        if (!this.disposed) {
          // 轮询正在读取设备时会短暂占锁并返回 device_busy；此时保留设置稍后重试，
          // 避免刚拖动的温度被直接丢弃。
          if (error.code === 'device_busy' && (this.retries = (this.retries || 0) + 1) <= 4) {
            this.pending = Object.assign(patch, this.pending);
            this.readyAt = Date.now() + 180 + this.retries * 140;
          } else {
            this.retries = 0;
            this.pending = {};
            clearTimeout(this.timer);
            this.accept(error.snapshot || { connected: false, configured: true });
            this.showMessage(error.message === 'Failed to fetch' ? '设备连接中断，请稍后重试' : error.message);
          }
        }
      } finally {
        this.busy = false;
        this.app.elements.scene.setAttribute('aria-busy', 'false');
        if (!this.disposed && Object.keys(this.pending).length) this.schedule();
      }
    }

    showMessage(text) {
      this.message.textContent = text;
      this.message.hidden = false;
      clearTimeout(this.messageTimer);
      this.messageTimer = setTimeout(() => { this.message.hidden = true; }, 4500);
    }

    dispose() {
      this.disposed = true;
      this.pending = {};
      this.retries = 0;
      clearInterval(this.pollTimer);
      clearTimeout(this.timer);
      clearTimeout(this.messageTimer);
    }
  }
