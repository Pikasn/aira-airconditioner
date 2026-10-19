  // 主界面下方的定时抽屉：设置/取消定时，倒计时由本机服务执行。
  // 指定时刻使用自绘双滚轮，并明确显示“今天/明天”，跨天顺延不再悄悄发生。
  const TIMER_WHEEL_ITEM = 32;

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
      this.popoverTitle = requiredElement('timerPopoverTitle');
      this.actionButtons = [...this.root.querySelectorAll('[data-action]')];
      this.modeButtons = [...this.root.querySelectorAll('[data-mode]')];
      this.chips = [...this.durations.querySelectorAll('.timer-chip[data-minutes]')];
      this.customChip = this.durations.querySelector('[data-custom]');
      this.action = 'off';
      this.mode = 'after';
      this.minutes = 60;
      this.custom = false;
      this.customMinutes = 60;
      this.picker = 'clock';
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
      this.buildWheels();
      this.bind();
      this.tick = setInterval(() => {
        this.renderState();
        if (this.mode === 'at' && !this.timer) this.updateTimeDisplay();
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
      // 点击某一行时先立即提交，再平滑滚动；避免点完马上“完成”导致选择丢失。
      if (this.picker === 'duration') {
        const hours = wheel === this.hourWheel ? value : Math.floor(this.minutes / 60);
        const minutes = wheel === this.minuteWheel ? value : this.minutes % 60;
        this.customMinutes = hours * 60 + minutes;
        this.minutes = this.customMinutes;
        this.custom = true;
        this.updateDurationDisplay();
        this.paintDuration();
      } else if (wheel === this.hourWheel) {
        this.atHour = value;
        this.updateTimeDisplay();
      } else {
        this.atMinute = value;
        this.updateTimeDisplay();
      }
      this.paintWheelSelection();
      wheel.scrollTo({ top: value * TIMER_WHEEL_ITEM, behavior: 'smooth' });
      clearTimeout(this.wheelTimer);
      this.wheelTimer = setTimeout(() => this.updateFromWheels(), 140);
    }

    updateFromWheels() {
      if (this.popover.hidden) return;
      const hour = clamp(Math.round(this.hourWheel.scrollTop / TIMER_WHEEL_ITEM), 0, 23);
      const minute = clamp(Math.round(this.minuteWheel.scrollTop / TIMER_WHEEL_ITEM), 0, 59);
      if (this.picker === 'duration') {
        this.customMinutes = hour * 60 + minute;
        this.minutes = this.customMinutes;
        this.custom = true;
        this.paintWheelSelection();
        this.updateDurationDisplay();
        this.paintDuration();
        return;
      }
      this.atHour = hour;
      this.atMinute = minute;
      this.paintWheelSelection();
      this.updateTimeDisplay();
    }

    paintWheelSelection() {
      const [hour, minute] = this.picker === 'duration'
        ? [Math.floor(this.minutes / 60), this.minutes % 60]
        : [this.atHour, this.atMinute];
      const groups = [[this.hourWheel, hour], [this.minuteWheel, minute]];
      for (const [wheel, value] of groups) {
        for (const item of wheel.querySelectorAll('.timer-wheel-item')) {
          const selected = Number(item.dataset.value) === value;
          item.classList.toggle('is-selected', selected);
          item.setAttribute('aria-selected', String(selected));
        }
      }
    }

    syncWheels() {
      const [hour, minute] = this.picker === 'duration'
        ? [Math.floor(this.minutes / 60), this.minutes % 60]
        : [this.atHour, this.atMinute];
      this.hourWheel.scrollTop = hour * TIMER_WHEEL_ITEM;
      this.minuteWheel.scrollTop = minute * TIMER_WHEEL_ITEM;
      this.paintWheelSelection();
    }

    openPopover(picker = 'clock') {
      if (picker === 'clock' && this.timeButton.disabled) return;
      if (picker === 'duration' && !this.available()) return;
      this.picker = picker;
      this.popoverTitle.textContent = picker === 'duration' ? `多久后 · ${this.durationLabel(this.minutes)}` : '到点时刻';
      this.popoverDay.hidden = picker === 'duration';
      this.popover.hidden = false;
      this.timeButton.setAttribute('aria-expanded', String(picker === 'clock'));
      if (this.customChip) this.customChip.setAttribute('aria-expanded', String(picker === 'duration'));
      this.syncWheels();
      if (picker === 'duration') this.updateDurationDisplay();
      else this.updateTimeDisplay();
    }

    closePopover() {
      if (this.popover.hidden) return;
      // 关闭前提交当前滚轮位置，避免滚动事件还没结束就关闭。
      this.updateFromWheels();
      this.popover.hidden = true;
      this.timeButton.setAttribute('aria-expanded', 'false');
      if (this.customChip) this.customChip.setAttribute('aria-expanded', 'false');
    }

    togglePopover() {
      if (this.popover.hidden === false && this.picker === 'clock') this.closePopover();
      else this.openPopover('clock');
    }

    // ---------------------------------------------------------------- 跨天计算
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

    durationLabel(minutes) {
      const total = Math.max(0, Math.round(minutes));
      if (total % 60 === 0) return `${total / 60} 小时`;
      const hours = Math.floor(total / 60);
      const rest = total % 60;
      return hours ? `${hours} 小时 ${rest} 分` : `${rest} 分钟`;
    }

    afterInfo() {
      const due = new Date(Date.now() + this.minutes * 60000);
      const now = new Date();
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

    updateDurationDisplay() {
      this.popoverTitle.textContent = `多久后 · ${this.durationLabel(this.minutes)}`;
      this.popoverDay.hidden = true;
      this.applyHint();
    }

    paintDuration() {
      for (const chip of this.chips) {
        chip.classList.toggle('is-active', !this.custom && Number(chip.dataset.minutes) === this.minutes);
      }
      if (this.customChip) {
        this.customChip.classList.toggle('is-active', this.custom);
        this.customChip.textContent = this.custom ? this.durationLabel(this.minutes) : '自定义';
      }
      const tooShort = this.mode === 'after' && this.custom && this.minutes < 1;
      this.startButton.disabled = !this.available() || this.busy || tooShort;
    }

    chooseCustom() {
      if (!this.available()) return;
      const initial = this.custom ? this.customMinutes : this.minutes;
      this.custom = true;
      this.customMinutes = initial;
      this.minutes = initial;
      this.openPopover('duration');
      this.paintDuration();
    }

    syncTimeInput() {
      const date = new Date(Date.now() + this.minutes * 60000);
      this.atHour = date.getHours();
      this.atMinute = date.getMinutes();
      if (!this.popover.hidden) this.syncWheels();
      this.updateTimeDisplay();
    }

    updateTimeDisplay() {
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
      if (open && this.mode === 'at') this.updateTimeDisplay();
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
      this.custom = false;
      this.customMinutes = null;
      this.minutes = minutes;
      this.render();
    }

    async submit() {
      if (!this.available() || this.busy || !this.bridge) return;
      const info = this.targetInfo();
      const after = this.mode === 'after';
      const afterInfo = after ? this.afterInfo() : null;
      const due = afterInfo ? afterInfo.due : info.due;
      const label = after
        ? `${this.durationLabel(this.minutes)}后${this.actionLabel(this.action)}`
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
        if (this.custom && this.minutes < 1) {
          this.hint.textContent = '自定义时长至少 1 分钟。';
          return;
        }
        const after = this.afterInfo();
        this.hint.textContent = `将在 ${this.durationLabel(after.minutes)}后（${after.dayLabel} ${after.clock}）执行，程序保持运行即可。`;
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
      for (const chip of this.chips) chip.classList.toggle('is-active', !this.custom && Number(chip.dataset.minutes) === this.minutes);
      if (this.customChip) {
        this.customChip.classList.toggle('is-active', this.custom);
        this.customChip.textContent = this.custom ? this.durationLabel(this.minutes) : '自定义';
      }
      this.durations.hidden = this.mode !== 'after';
      this.clockRow.hidden = this.mode !== 'at';
      const available = this.available();
      const tooShort = this.mode === 'after' && this.custom && this.minutes < 1;
      this.startButton.disabled = !available || this.busy || tooShort;
      if (this.customChip) this.customChip.disabled = !available;
      this.timeButton.disabled = !available;
      this.cancelButton.hidden = !this.timer;
      this.cancelButton.disabled = this.busy;
      if (this.timeButton.disabled) this.closePopover();
      this.applyHint();
      if (this.mode === 'at') this.updateTimeDisplay();
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
      if (this.customChip) listen(this.customChip, 'click', () => this.chooseCustom());
      listen(this.startButton, 'click', () => this.submit());
      listen(this.cancelButton, 'click', () => this.cancel());
    }

    dispose() {
      clearInterval(this.tick);
      clearTimeout(this.wheelTimer);
    }
  }
