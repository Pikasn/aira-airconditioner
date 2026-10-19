  // 主界面下方的定时抽屉：设置/取消定时，倒计时由本机服务执行。
  // 倒计时：预设档位 + “+30 分钟”点按/长按加速；指定时刻：自绘双滚轮并标注今天/明天。
  const TIMER_WHEEL_ITEM = 32;
  const TIMER_STEP_MINUTES = 30;
  const TIMER_MIN_MINUTES = 30;
  const TIMER_MAX_MINUTES = 23 * 60 + 30;

  class TimerPanel {
    constructor({ signal, getBridge, isLive }) {
      this.signal = signal;
      this.getBridge = getBridge;
      this.isLive = isLive;
      this.root = requiredElement('timerDrawer');
      this.handle = requiredElement('timerHandle');
      this.panel = requiredElement('timerPanel');
      this.summary = requiredElement('timerSummary');
      this.state = requiredElement('timerState');
      this.hint = requiredElement('timerHint');
      this.startButton = requiredElement('timerStart');
      this.cancelButton = requiredElement('timerCancel');
      this.durations = requiredElement('timerDurations');
      this.stepButton = requiredElement('timerStep');
      this.preview = requiredElement('timerPreview');
      this.previewWhen = requiredElement('timerPreviewWhen');
      this.clockRow = requiredElement('timerClock');
      this.timeButton = requiredElement('timerTimeButton');
      this.timeValue = requiredElement('timerTimeValue');
      this.dayLabel = requiredElement('timerDay');
      this.popover = requiredElement('timerTimePopover');
      this.popoverDay = requiredElement('timerPopoverDay');
      this.hourWheel = requiredElement('timerHourWheel');
      this.minuteWheel = requiredElement('timerMinuteWheel');
      this.timeDone = requiredElement('timerTimeDone');
      this.announce = requiredElement('timerAnnounce');
      this.actionButtons = [...this.root.querySelectorAll('[data-action]')];
      this.modeButtons = [...this.root.querySelectorAll('[data-mode]')];
      this.chips = [...this.durations.querySelectorAll('.timer-chip[data-minutes]')];
      this.action = 'off';
      this.mode = 'after';
      this.minutes = 60;
      const defaultTime = new Date(Date.now() + 60 * 60000);
      this.atHour = defaultTime.getHours();
      this.atMinute = defaultTime.getMinutes();
      this.timer = null;
      this.configured = false;
      this.connected = false;
      this.open = false;
      this.cancelling = false;
      this.busy = false;
      this.notice = null;
      this.wheelTimer = null;
      this.stepDelay = null;
      this.stepRepeat = null;
      this.stepAccel = null;
      this.stepStarted = false;
      this.buildWheels();
      this.bind();
      this.tick = setInterval(() => {
        this.renderState();
        this.renderPreview();
        if (this.mode === 'at') this.updateClockDisplay();
      }, 1000);
      this.render();
    }

    get bridge() {
      return this.getBridge ? this.getBridge() : null;
    }

    // ---------------------------------------------------------------- 时间滚轮
    buildWheels() {
      const fill = (wheel, count) => {
        wheel.innerHTML = '';
        const spacer = () => {
          const element = document.createElement('div');
          element.className = 'timer-wheel-spacer';
          return element;
        };
        wheel.append(spacer());
        for (let value = 0; value < count; value++) {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'timer-wheel-item';
          item.dataset.value = String(value);
          item.setAttribute('role', 'option');
          item.textContent = String(value).padStart(2, '0');
          item.addEventListener('click', () => this.scrollWheelTo(wheel, value), { signal: this.signal });
          wheel.append(item);
        }
        wheel.append(spacer());
        wheel.addEventListener('scroll', () => {
          clearTimeout(this.wheelTimer);
          this.wheelTimer = setTimeout(() => this.updateFromWheels(), 90);
        }, { signal: this.signal, passive: true });
        wheel.addEventListener('keydown', event => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
          event.preventDefault();
          const current = Math.round(wheel.scrollTop / TIMER_WHEEL_ITEM);
          const next = clamp(current + (event.key === 'ArrowDown' ? 1 : -1), 0, count - 1);
          this.scrollWheelTo(wheel, next);
        }, { signal: this.signal });
      };
      fill(this.hourWheel, 24);
      fill(this.minuteWheel, 60);
      this.paintWheelSelection();
    }

    scrollWheelTo(wheel, value) {
      // 先立即提交，再平滑滚动；避免点完马上“完成”时选择丢失。
      if (wheel === this.hourWheel) this.atHour = value;
      else this.atMinute = value;
      this.paintWheelSelection();
      this.updateClockDisplay();
      wheel.scrollTo({ top: value * TIMER_WHEEL_ITEM, behavior: 'smooth' });
      clearTimeout(this.wheelTimer);
      this.wheelTimer = setTimeout(() => this.updateFromWheels(), 140);
    }

    updateFromWheels() {
      if (this.popover.hidden) return;
      this.atHour = clamp(Math.round(this.hourWheel.scrollTop / TIMER_WHEEL_ITEM), 0, 23);
      this.atMinute = clamp(Math.round(this.minuteWheel.scrollTop / TIMER_WHEEL_ITEM), 0, 59);
      this.paintWheelSelection();
      this.updateClockDisplay();
    }

    paintWheelSelection() {
      const groups = [[this.hourWheel, this.atHour], [this.minuteWheel, this.atMinute]];
      for (const [wheel, value] of groups) {
        for (const item of wheel.querySelectorAll('.timer-wheel-item')) {
          const selected = Number(item.dataset.value) === value;
          item.classList.toggle('is-selected', selected);
          item.setAttribute('aria-selected', String(selected));
        }
      }
    }

    syncWheels() {
      this.hourWheel.scrollTop = this.atHour * TIMER_WHEEL_ITEM;
      this.minuteWheel.scrollTop = this.atMinute * TIMER_WHEEL_ITEM;
      this.paintWheelSelection();
    }

    openPopover() {
      if (this.popover.hidden === false || this.timeButton.disabled) return;
      this.popover.hidden = false;
      this.timeButton.setAttribute('aria-expanded', 'true');
      this.syncWheels();
      this.updateClockDisplay();
    }

    closePopover() {
      if (this.popover.hidden) return;
      this.updateFromWheels();
      this.popover.hidden = true;
      this.timeButton.setAttribute('aria-expanded', 'false');
    }

    togglePopover() {
      if (this.popover.hidden === false) this.closePopover();
      else this.openPopover();
    }

    // ---------------------------------------------------------------- 时间计算
    clockLabel(hour, minute) {
      return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    }

    targetInfo() {
      const now = new Date();
      const target = new Date(now);
      target.setHours(this.atHour, this.atMinute, 0, 0);
      const forced = target.getTime() <= now.getTime() + 30000;
      if (forced) target.setDate(target.getDate() + 1);
      const tomorrow = target.getFullYear() !== now.getFullYear()
        || target.getMonth() !== now.getMonth()
        || target.getDate() !== now.getDate();
      return {
        due: Math.floor(target.getTime() / 1000),
        timeLabel: this.clockLabel(this.atHour, this.atMinute),
        dayLabel: tomorrow ? '明天' : '今天',
        tomorrow,
        forced,
      };
    }

    afterInfo() {
      const now = new Date();
      const due = new Date(now.getTime() + this.minutes * 60000);
      const tomorrow = due.getFullYear() !== now.getFullYear()
        || due.getMonth() !== now.getMonth()
        || due.getDate() !== now.getDate();
      return {
        due: Math.floor(due.getTime() / 1000),
        minutes: this.minutes,
        dayLabel: tomorrow ? '明天' : '今天',
        clock: this.clockLabel(due.getHours(), due.getMinutes()),
      };
    }

    syncTimeInput() {
      const date = new Date(Date.now() + this.minutes * 60000);
      this.atHour = date.getHours();
      this.atMinute = date.getMinutes();
      if (!this.popover.hidden) this.syncWheels();
      this.updateClockDisplay();
    }

    updateClockDisplay() {
      const info = this.targetInfo();
      this.timeValue.textContent = info.timeLabel;
      this.dayLabel.textContent = info.dayLabel;
      this.popoverDay.textContent = info.dayLabel;
      this.timeButton.setAttribute('aria-label', `到点时刻，${info.dayLabel} ${info.timeLabel}`);
      this.applyHint(info);
    }

    describeTimer(timer) {
      const due = new Date(timer.due * 1000);
      const now = new Date();
      const sameDay = due.getFullYear() === now.getFullYear()
        && due.getMonth() === now.getMonth()
        && due.getDate() === now.getDate();
      return {
        sameDay,
        dayLabel: sameDay ? '今天' : '明天',
        clock: this.clockLabel(due.getHours(), due.getMinutes()),
        action: timer.action,
      };
    }

    formatDuration(minutes) {
      const total = Math.max(0, Math.round(minutes));
      const hours = Math.floor(total / 60);
      const rest = total % 60;
      if (hours && rest) return `${hours} 小时 ${rest} 分`;
      if (hours) return `${hours} 小时`;
      return `${rest} 分钟`;
    }

    // ---------------------------------------------------------------- 状态
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
      if (open && this.mode === 'at') this.updateClockDisplay();
      if (!open) this.closePopover();
    }

    chooseAction(action) {
      if (action !== 'off' && action !== 'on') return;
      this.action = action;
      this.render();
    }

    chooseMode(mode) {
      if (mode !== 'after' && mode !== 'at') return;
      this.closePopover();
      if (mode === 'at' && this.mode !== 'at') this.syncTimeInput();
      this.mode = mode;
      this.render();
    }

    chooseMinutes(minutes) {
      if (!Number.isFinite(minutes)) return;
      this.minutes = clamp(minutes, TIMER_MIN_MINUTES, TIMER_MAX_MINUTES);
      this.render();
    }

    increaseDuration() {
      if (!this.available() || this.mode !== 'after') return;
      const next = Math.min(TIMER_MAX_MINUTES, this.minutes + TIMER_STEP_MINUTES);
      if (next === this.minutes) return;
      this.minutes = next;
      this.render();
    }

    clearStepTimers() {
      clearTimeout(this.stepDelay);
      clearTimeout(this.stepAccel);
      clearInterval(this.stepRepeat);
      this.stepDelay = null;
      this.stepAccel = null;
      this.stepRepeat = null;
    }

    beginStepHold(event) {
      if (!this.available() || this.mode !== 'after') return;
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      this.clearStepTimers();
      this.stepStarted = true;
      this.increaseDuration();
      this.stepDelay = setTimeout(() => {
        this.stepRepeat = setInterval(() => this.increaseDuration(), 180);
        this.stepAccel = setTimeout(() => {
          clearInterval(this.stepRepeat);
          this.stepRepeat = setInterval(() => this.increaseDuration(), 80);
        }, 1200);
      }, 420);
    }

    stopStepHold() {
      this.clearStepTimers();
      if (!this.stepStarted) return;
      this.stepStarted = false;
      const info = this.afterInfo();
      this.say(`已设为 ${this.formatDuration(this.minutes)}，预计 ${info.dayLabel} ${info.clock} ${this.actionLabel(this.action)}`);
    }

    announceDuration() {
      const info = this.afterInfo();
      this.say(`已设为 ${this.formatDuration(this.minutes)}，预计 ${info.dayLabel} ${info.clock} ${this.actionLabel(this.action)}`);
    }

    async submit() {
      if (!this.available() || this.busy || !this.bridge) return;
      const info = this.targetInfo();
      const after = this.mode === 'after';
      const afterInfo = after ? this.afterInfo() : null;
      const due = afterInfo ? afterInfo.due : info.due;
      const label = after
        ? `${this.formatDuration(this.minutes)}后${this.actionLabel(this.action)}`
        : `${info.dayLabel} ${info.timeLabel} ${this.actionLabel(this.action)}`;
      this.busy = true;
      this.render();
      try {
        await this.bridge.setTimer(this.action, due);
        this.notice = null;
        this.closePopover();
        this.say(`已设置${label}`);
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

    previewText() {
      if (!this.available()) return '';
      if (this.mode === 'at') {
        const info = this.targetInfo();
        return `${info.dayLabel} ${info.timeLabel} ${this.actionLabel(this.action)}`;
      }
      const info = this.afterInfo();
      return `${this.formatDuration(this.minutes)}后 · ${info.dayLabel} ${info.clock} ${this.actionLabel(this.action)}`;
    }

    renderPreview() {
      const text = this.previewText();
      this.preview.hidden = !text;
      if (text) this.previewWhen.textContent = text;
    }

    applyHint(info = this.targetInfo()) {
      if (this.timer && this.timer.error) {
        this.hint.textContent = this.timer.failed ? this.timer.error : `${this.timer.error}（将自动重试）`;
        return;
      }
      if (!this.isLive) {
        this.hint.textContent = '连接空调后可设置定时。';
      } else if (!this.configured) {
        this.hint.textContent = '请先在设置中连接空调伴侣。';
      } else if (!this.connected) {
        this.hint.textContent = '设备离线，恢复连接后可设置定时。';
      } else if (this.mode === 'at') {
        this.hint.textContent = info.tomorrow
          ? (info.forced
            ? `今天 ${info.timeLabel} 已过，将安排在明天 ${info.timeLabel} 执行。`
            : `将在明天 ${info.timeLabel} 执行。`)
          : `将在今天 ${info.timeLabel} 执行。`;
      } else {
        this.hint.textContent = '点按「+30 分钟」延长，长按加速；重新选档位可重设。到点由本机服务执行，可最小化或悬浮。';
      }
    }

    renderState() {
      if (this.notice && Date.now() > this.notice.until) this.notice = null;
      const remaining = this.timer ? this.timer.due - Date.now() / 1000 : 0;
      const descriptor = this.timer ? this.describeTimer(this.timer) : null;
      let summary = '未设置';
      let active = false;
      if (this.notice) {
        summary = this.notice.text;
        active = !this.notice.error;
      } else if (this.timer) {
        if (this.timer.failed) {
          summary = '定时执行失败';
        } else {
          summary = descriptor.sameDay
            ? `${this.format(remaining)} 后${this.actionLabel(descriptor.action)}`
            : `${descriptor.dayLabel} ${descriptor.clock} 后${this.actionLabel(descriptor.action)}`;
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
      this.state.textContent = this.timer
        ? (this.timer.failed ? '定时执行失败' : `${descriptor.dayLabel} ${descriptor.clock} 后${this.actionLabel(descriptor.action)}`)
        : summary;
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
      this.timeButton.disabled = !available;
      this.stepButton.disabled = !available || this.mode !== 'after' || this.minutes >= TIMER_MAX_MINUTES;
      this.cancelButton.hidden = !this.timer;
      this.cancelButton.disabled = this.busy;
      if (this.timeButton.disabled) this.closePopover();
      this.applyHint();
      if (this.mode === 'at') this.updateClockDisplay();
      this.renderPreview();
      this.renderState();
    }

    bind() {
      const listen = (element, type, handler, options = {}) => element.addEventListener(type, handler, { signal: this.signal, ...options });
      listen(this.handle, 'click', () => this.setOpen(!this.open));
      listen(this.root, 'keydown', event => {
        if (event.key !== 'Escape') return;
        if (this.popover.hidden === false) {
          this.closePopover();
          this.timeButton.focus();
          event.stopPropagation();
          return;
        }
        if (this.open) {
          this.setOpen(false);
          this.handle.focus();
        }
      });
      listen(this.timeButton, 'click', () => this.togglePopover());
      listen(this.timeDone, 'click', () => {
        this.closePopover();
        this.timeButton.focus();
      });
      listen(document, 'pointerdown', event => {
        if (this.popover.hidden) return;
        if (this.popover.contains(event.target) || this.timeButton.contains(event.target)) return;
        this.closePopover();
      });
      for (const button of this.actionButtons) listen(button, 'click', () => this.chooseAction(button.dataset.action));
      for (const button of this.modeButtons) listen(button, 'click', () => this.chooseMode(button.dataset.mode));
      for (const chip of this.chips) listen(chip, 'click', () => this.chooseMinutes(Number(chip.dataset.minutes)));
      listen(this.stepButton, 'pointerdown', event => this.beginStepHold(event));
      listen(this.stepButton, 'pointerup', () => this.stopStepHold());
      listen(this.stepButton, 'pointerleave', () => this.stopStepHold());
      listen(this.stepButton, 'pointercancel', () => this.stopStepHold());
      listen(this.stepButton, 'contextmenu', event => event.preventDefault());
      listen(this.stepButton, 'click', event => {
        if (event.detail === 0) {
          this.increaseDuration();
          this.announceDuration();
        }
      });
      listen(document, 'pointerup', () => this.stopStepHold());
      listen(this.startButton, 'click', () => this.submit());
      listen(this.cancelButton, 'click', () => this.cancel());
    }

    dispose() {
      clearInterval(this.tick);
      clearTimeout(this.wheelTimer);
      this.clearStepTimers();
    }
  }
