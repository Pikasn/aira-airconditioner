  // 所有输入都经过同一入口验证，再通知圆环、按钮和风场。
  class AirConditionerApp {
    constructor() {
      this.isLive = location.protocol === 'http:' || location.protocol === 'https:';
      this.online = !this.isLive;
      this.temperatureRange = this.isLive ? { min: 16, max: 30 } : TEMPERATURE;
      this.climate = this.isLive ? { temperature: null, humidity: null } : CLIMATE;
      this.controlOptions = Object.fromEntries(Object.entries(CONTROLS).map(([key, config]) => [key, config.order]));
      if (this.isLive) this.controlOptions.direction = ['fixed', 'swing'];
      this.state = Object.freeze({ ...DEFAULT_STATE, ...(this.isLive ? { power: false, direction: 'fixed' } : {}) });
      this.previousState = null;
      this.destroyed = false;
      this.events = new AbortController();
      this.motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
      this.freeze = new URLSearchParams(location.search).get('freeze') === '1';
      this.reduced = this.motionQuery.matches;
      document.body.classList.toggle('freeze', this.freeze);
      this.elements = {
        power: requiredElement('power'), scene: requiredElement('scene'),
        dial: requiredElement('dial'), progress: requiredElement('prog'),
        knob: requiredElement('knob'), readout: requiredElement('bigTemp'),
        canvas: requiredElement('airCanvas'), louver: requiredElement('louver'),
        mode: requiredElement('modeControl'), speed: requiredElement('speedControl'), direction: requiredElement('directionControl'),
        climate: requiredElement('climateReading'), room: requiredElement('roomTemperature'),
        moisture: requiredElement('roomHumidity'),
        machine: document.querySelector('.machine'), outlet: document.querySelector('.machine-bottom')
      };
      this.controls = Object.entries(CONTROLS).map(([key, config]) => {
        const button = requiredElement(config.id);
        const svg = button.querySelector('svg');
        return { key, config, button, svg, icon: svg.querySelector('use') };
      });
      this.dial = new TemperatureDial({
        element: this.elements.dial, progress: this.elements.progress,
        knob: this.elements.knob, readout: this.elements.readout,
        getState: () => ({ ...this.viewState(), power: this.online && this.state.power && Number.isFinite(this.state.temp) }), getLimits: () => this.temperatureRange,
        onChange: temp => this.update({ temp }), signal: this.events.signal
      });
      this.airflow = new AirflowEngine({
        ...this.elements, getState: () => this.viewState(), getClimate: () => this.climate,
        isStatic: () => this.freeze || this.reduced
      });
      this.timer = new TimerPanel({
        signal: this.events.signal, isLive: this.isLive, getBridge: () => this.bridge
      });
      this.bindEvents();
      this.render();
      if (this.isLive) this.bridge = new DeviceBridge(this);
    }

    viewState() {
      return { ...this.state, temp: Number.isFinite(this.state.temp) ? this.state.temp : DEFAULT_STATE.temp, power: this.online && this.state.power };
    }

    acceptDevice(snapshot, includeState = true) {
      if (this.destroyed) return;
      this.online = !!(snapshot.connected && snapshot.state);
      this.climate = {
        temperature: snapshot.telemetry?.temperature ?? null,
        humidity: snapshot.telemetry?.humidity ?? null
      };
      if (includeState && snapshot.state) this.update(snapshot.state, { device: true });
      this.timer.accept(snapshot);
      this.render();
    }

    bindEvents() {
      const signal = this.events.signal;
      this.elements.power.addEventListener('click', () => this.update({ power: !this.state.power }), { signal });
      for (const { key, config, button } of this.controls) {
        button.addEventListener('click', () => {
          const order = this.controlOptions[key];
          const next = order[(order.indexOf(this.state[key]) + 1) % order.length];
          this.update({ [key]: next, power: true });
        }, { signal });
      }
      this.motionQuery.addEventListener('change', event => {
        this.reduced = event.matches;
        this.airflow.sync();
      }, { signal });
      document.addEventListener('visibilitychange', () => {
        document.body.classList.toggle('page-hidden',document.hidden);
        if (document.hidden) this.airflow.stop();
        else this.airflow.sync();
      }, { signal });
      window.addEventListener('pagehide', event => {
        if (event.persisted) this.airflow.stop();
        else this.destroy();
      }, { signal });
      window.addEventListener('pageshow', () => this.airflow.sync(), { signal });
      window.addEventListener('presentationchange', event => {
        this.airflow.setVisible(!['bubble','compact'].includes(event.detail.view) && !event.detail.edgeHidden);
      }, { signal });
    }

    update(patch, { device = false } = {}) {
      if (this.destroyed) return;
      if (this.isLive && !this.online && !device) return;
      const checked = {};
      for (const [key, value] of Object.entries(patch)) {
        if (key === 'temp') {
          if (device && value === null) { checked.temp = null; continue; }
          if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError('Temperature must be a finite number');
          checked.temp = clamp(Math.round(value), this.temperatureRange.min, this.temperatureRange.max);
        } else if (key === 'power') {
          if (typeof value !== 'boolean') throw new TypeError('Power must be a boolean');
          checked.power = value;
        } else if (Object.hasOwn(CONTROLS, key)) {
          if (!this.controlOptions[key].includes(value)) throw new RangeError(`Invalid ${key}: ${value}`);
          checked[key] = value;
        } else {
          throw new TypeError(`Unknown setting: ${key}`);
        }
      }
      if (!Object.entries(checked).some(([key, value]) => value !== this.state[key])) return;
      this.state = Object.freeze({ ...this.state, ...checked });
      this.render();
      if (this.isLive && !device) this.bridge.queue(checked);
    }

    render() {
      const state = this.viewState(), previous = this.previousState;
      if (!previous || state.mode !== previous.mode) {
        if (previous) document.body.classList.remove(`mode-${previous.mode}`);
        document.body.classList.add(`mode-${state.mode}`);
      }
      if (!previous || state.power !== previous.power) {
        document.body.classList.toggle('is-off', !state.power);
        this.elements.scene.classList.toggle('is-off', !state.power);
        this.elements.power.classList.toggle('off', !state.power);
        const label = state.power ? '关机' : '开机';
        this.elements.power.setAttribute('aria-label', label);
        this.elements.power.title = label;
      }
      document.body.dataset.speed = state.speed;
      const thermal=state.mode==='heat'?(state.temp-16)/14:(30-state.temp)/14;
      document.body.style.setProperty('--thermal-level',clamp(thermal,0,1).toFixed(3));
      for (const { key, config, button, icon, svg } of this.controls) {
        if (!previous || state[key] !== previous[key]) {
          const value = state[key], label = config.labels[value];
          icon.setAttribute('href', `#icon-${key}-${value}`);
          button.dataset[key] = value;
          button.title = label;
          button.setAttribute('aria-label', `${label}，点击切换`);
          svg.classList.toggle('speed-bars', key === 'speed' && value !== 'auto');
        }
      }
      this.elements.mode.classList.toggle('active', state.power);
      this.elements.speed.classList.toggle('active', state.power);
      this.elements.direction.classList.toggle('active', state.power && state.direction === 'swing');
      this.elements.direction.setAttribute('aria-pressed', String(state.power && state.direction === 'swing'));
      const unknownTarget = this.isLive && (!this.online || !Number.isFinite(this.state.temp));
      this.dial.render({ ...state, power: state.power && !unknownTarget });
      this.elements.power.disabled = this.isLive && !this.online;
      for (const { button } of this.controls) button.disabled = this.isLive && !this.online;
      this.elements.readout.textContent = unknownTarget ? '—' : state.temp;
      this.elements.progress.style.visibility = unknownTarget ? 'hidden' : '';
      this.elements.knob.style.visibility = unknownTarget ? 'hidden' : '';
      this.elements.dial.setAttribute('aria-valuemin', String(this.temperatureRange.min));
      this.elements.dial.setAttribute('aria-valuemax', String(this.temperatureRange.max));
      if (unknownTarget) this.elements.dial.removeAttribute('aria-valuenow');
      else this.elements.dial.setAttribute('aria-valuenow', String(state.temp));
      this.elements.dial.setAttribute('aria-valuetext', this.isLive && !this.online ? '设备未连接' : unknownTarget ? '当前模式没有设定温度' : `${state.temp} 摄氏度`);
      this.renderClimate();
      this.airflow.sync();
      this.previousState = state;
    }

    renderClimate() {
      const { temperature, humidity } = this.climate;
      const { room, moisture, climate: reading } = this.elements;
      room.textContent = `${temperature}°`;
      moisture.textContent = `${humidity}%`;
      room.parentElement.hidden = !Number.isFinite(temperature);
      moisture.parentElement.hidden = !Number.isFinite(humidity);
      reading.hidden = !Number.isFinite(temperature) && !Number.isFinite(humidity);
      reading.setAttribute('aria-label', [Number.isFinite(temperature) ? `室温 ${temperature} 摄氏度` : '', Number.isFinite(humidity) ? `湿度 ${humidity}%` : ''].filter(Boolean).join('，') || '温湿度不可用');
    }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      this.events.abort();
      this.dial.cancelDrag();
      this.airflow.dispose();
      this.timer.dispose();
    }
  }

  const app = new AirConditionerApp();
  // 调试读取返回快照，不能绕过输入验证直接修改内部状态。
  window.__ac = Object.freeze({
    get S() { return Object.freeze({ ...app.state }); },
    setTemp: temp => app.update({ temp }),
    setMode: mode => app.update({ mode, power: true }),
    setPower: power => app.update({ power }),
    setSpeed: speed => app.update({ speed }),
    setDirection: direction => app.update({ direction }),
    state: () => ({ ...app.state }),
    timer: () => app.timer ? { timer: app.timer.timer, open: app.timer.open } : null,
    airflow: () => app.airflow.inspect()
  });
