  // 主界面下方的定时抽屉：设置/取消定时，倒计时由本机服务执行。
  class TimerPanel {
    constructor({ signal, getBridge, isLive }) {
      this.getBridge = getBridge;
      this.isLive = isLive;
      this.root = requiredElement('timerDrawer');
      this.handle = requiredElement('timerHandle');
      this.panel = requiredElement('timerPanel');
      this.summary = requiredElement('timerSummary');
      this.state = requiredElement('timerState');
      this.announce = requiredElement('timerAnnounce');
      this.hint = requiredElement('timerHint');
      this.startButton = requiredElement('timerStart');
      this.cancelButton = requiredElement('timerCancel');
      this.durations = requiredElement('timerDurations');
      this.clockRow = requiredElement('timerClock');
      this.timeInput = requiredElement('timerTime');
      this.actionButtons = [...this.root.querySelectorAll('[data-action]')];
      this.modeButtons = [...this.root.querySelectorAll('[data-mode]')];
      this.chips = [...this.durations.querySelectorAll('.timer-chip')];
      this.action = 'off';
      this.mode = 'after';
      this.minutes = 60;
      this.timer = null;
      this.configured = false;
      this.connected = false;
      this.open = false;
      this.cancelling = false;
      this.busy = false;
      this.notice = null;
      this.bind(signal);
      this.tick = setInterval(() => this.renderState(), 1000);
      this.render();
    }

    bind(signal) {
      const listen = (element, type, handler) => element.addEventListener(type, handler, { signal });
      listen(this.handle, 'click', () => this.setOpen(!this.open));
      listen(this.root, 'keydown', event => {
        if (event.key === 'Escape' && this.open) {
          this.setOpen(false);
          this.handle.focus();
        }
      });
      for (const button of this.actionButtons) listen(button, 'click', () => this.chooseAction(button.dataset.action));
      for (const button of this.modeButtons) listen(button, 'click', () => this.chooseMode(button.dataset.mode));
      for (const chip of this.chips) listen(chip, 'click', () => this.chooseMinutes(Number(chip.dataset.minutes)));
      listen(this.startButton, 'click', () => this.submit());
      listen(this.cancelButton, 'click', () => this.cancel());
    }

    get bridge() {
      return this.getBridge ? this.getBridge() : null;
    }

    accept(snapshot) {
      const previous = this.timer;
      this.configured = !!snapshot.configured;
      this.connected = !!(snapshot.connected && snapshot.state);
      this.timer = snapshot.timer || null;
      if (previous && !this.timer && !this.cancelling && this.connected) {
        this.notice = { text: '定时已执行', until: Date.now() + 8000 };
        this.say('定时已执行');
      }
      if (this.timer) this.notice = null;
      this.render();
    }

    available() {
      return this.isLive && this.configured && this.connected;
    }

    setOpen(open) {
      this.open = open;
      this.root.classList.toggle('is-open', open);
      this.handle.setAttribute('aria-expanded', String(open));
      this.panel.hidden = !open;
      if (open && !this.timer) this.syncTimeInput();
    }

    chooseAction(action) {
      if (action !== 'off' && action !== 'on') return;
      this.action = action;
      this.render();
    }

    chooseMode(mode) {
      if (mode !== 'after' && mode !== 'at') return;
      this.mode = mode;
      if (mode === 'at' && !this.timer) this.syncTimeInput();
      this.render();
    }

    chooseMinutes(minutes) {
      if (!Number.isFinite(minutes)) return;
      this.minutes = minutes;
      this.render();
    }

    syncTimeInput() {
      const date = new Date(Date.now() + this.minutes * 60000);
      date.setSeconds(0, 0);
      this.timeInput.value = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
    }

    targetDue() {
      if (this.mode === 'after') return Math.floor(Date.now() / 1000) + this.minutes * 60;
      const [hours, minutes] = (this.timeInput.value || '').split(':').map(Number);
      if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null;
      const target = new Date();
      target.setHours(hours, minutes, 0, 0);
      if (target.getTime() <= Date.now() + 30000) target.setDate(target.getDate() + 1);
      return Math.floor(target.getTime() / 1000);
    }

    async submit() {
      if (!this.available() || this.busy || !this.bridge) return;
      const due = this.targetDue();
      if (!due) {
        this.notice = { text: '请选择有效的到点时刻', until: Date.now() + 5000, error: true };
        this.render();
        return;
      }
      this.busy = true;
      this.render();
      try {
        await this.bridge.setTimer(this.action, due);
        this.notice = null;
        this.say(`已设置 ${this.format(due - Date.now() / 1000)} 后${this.actionLabel(this.action)}`);
      } catch (error) {
        this.notice = { text: error.message || '定时设置失败', until: Date.now() + 6000, error: true };
        this.say(this.notice.text);
      } finally {
        this.busy = false;
        this.render();
      }
    }

    async cancel() {
      if (!this.timer || this.busy || !this.bridge) return;
      this.busy = true;
      this.cancelling = true;
      this.render();
      try {
        await this.bridge.clearTimer();
        this.notice = null;
        this.say('已取消定时');
      } catch (error) {
        this.notice = { text: error.message || '无法取消定时', until: Date.now() + 6000, error: true };
        this.say(this.notice.text);
      } finally {
        this.busy = false;
        this.cancelling = false;
        this.render();
      }
    }

    format(seconds) {
      const total = Math.max(0, Math.ceil(seconds));
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor(total % 3600 / 60);
      const rest = total % 60;
      if (hours >= 1) return `${hours}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
      return `${minutes}:${String(rest).padStart(2, '0')}`;
    }

    actionLabel(action) {
      return action === 'on' ? '开机' : '关机';
    }

    say(text) {
      // 只播报状态变化，不随每秒倒计时重复播报。
      this.announce.textContent = '';
      this.announce.textContent = text;
    }

    renderState() {
      if (this.notice && Date.now() > this.notice.until) this.notice = null;
      const remaining = this.timer ? this.timer.due - Date.now() / 1000 : 0;
      let summary = '未设置';
      let active = false;
      if (this.notice) {
        summary = this.notice.text;
        active = !this.notice.error;
      } else if (this.timer) {
        if (this.timer.failed) {
          summary = '定时执行失败';
        } else {
          summary = `${this.format(remaining)} 后${this.actionLabel(this.timer.action)}`;
          active = true;
        }
      } else if (!this.isLive) {
        summary = '预览模式';
      } else if (!this.configured) {
        summary = '未连接';
      } else if (!this.connected) {
        summary = '设备离线';
      }
      this.summary.textContent = summary;
      this.summary.classList.toggle('is-active', active);
      this.state.textContent = this.timer && this.timer.failed ? '定时执行失败' : summary;
      this.state.classList.toggle('is-error', !!(this.notice && this.notice.error) || !!(this.timer && this.timer.error));
      if (this.timer) this.cancelButton.hidden = false;
    }

    render() {
      for (const button of this.actionButtons) {
        const on = button.dataset.action === this.action;
        button.classList.toggle('is-active', on);
        button.setAttribute('aria-pressed', String(on));
      }
      for (const button of this.modeButtons) {
        const on = button.dataset.mode === this.mode;
        button.classList.toggle('is-active', on);
        button.setAttribute('aria-pressed', String(on));
      }
      for (const chip of this.chips) chip.classList.toggle('is-active', Number(chip.dataset.minutes) === this.minutes);
      this.durations.hidden = this.mode !== 'after';
      this.clockRow.hidden = this.mode !== 'at';
      const available = this.available();
      this.startButton.disabled = !available || this.busy;
      this.cancelButton.hidden = !this.timer;
      this.cancelButton.disabled = this.busy;
      this.hint.textContent = !this.isLive
        ? '连接空调后可设置定时。'
        : !this.configured
          ? '请先在设置中连接空调伴侣。'
          : !this.connected
            ? '设备离线，恢复连接后可设置定时。'
            : '到点由本机服务执行，程序保持运行即可（可最小化或悬浮）。';
      if (this.timer && this.timer.error) this.hint.textContent = this.timer.failed ? this.timer.error : `${this.timer.error}（将自动重试）`;
      this.renderState();
    }

    dispose() {
      clearInterval(this.tick);
    }
  }
