  // 固定步长模拟；导风板的角度逐渐传入流线与微光，保留已经吹出的尾迹。
  class AirflowEngine {
    constructor({ canvas, machine, outlet, louver, getState, getClimate, isStatic }) {
      Object.assign(this, { canvas, machine, outlet, louver, getState, getClimate, isStatic });
      this.renderer = new AirflowRenderer(canvas);
      this.state = getState();
      this.width = this.height = 0;
      this.emitter = { left: 0, right: 0, y: 0 };
      this.particles = [];
      this.velocity = { vx: 0, vy: 0 };
      this.time = this.credit = this.sequence = 0;
      this.travel = 0;
      this.seed = SIMULATION.seed;
      this.angle = DIRECTION_PITCH.down;
      this.fixedAngle = this.angle;
      this.speed = 132;
      this.direction = this.mode = '';
      this.swingStart = this.swingOffset = 0;
      this.raf = this.lastFrame = null;
      this.accumulator = 0;
      this.disposed = false;
      this.visible = true;
      this.lastLouverGeometry = '';
      this.tick = now => this.frame(now);
      this.onResize = () => {
        if (this.resize() && this.state.power && this.profile && this.isStatic()) this.staticFrame();
      };
      if (typeof ResizeObserver !== 'undefined') {
        this.observer = new ResizeObserver(this.onResize);
        this.observer.observe(canvas);
        this.observer.observe(machine);
      }
      // DPR 变化未必改变 CSS 尺寸，因此保留窗口 resize 监听。
      window.addEventListener('resize', this.onResize);
      this.resize();
    }

    random() {
      this.seed = (Math.imul(this.seed, 1664525) + 1013904223) >>> 0;
      return this.seed / 4294967296;
    }

    resize() {
      if (this.disposed) return false;
      const machine = this.machine.getBoundingClientRect();
      const outlet = this.outlet.getBoundingClientRect();
      // 在统一的设计坐标中模拟，让风速、粒子大小和扫风幅度一起缩放。
      const designHeight = Number(getComputedStyle(this.machine).getPropertyValue('--design-height')) || 260;
      const scale = Math.max(.1, machine.height / designHeight);
      const face = this.machine.querySelector('.face').getBoundingClientRect();
      const overlap = -(machine.bottom - face.bottom + 4 * scale) + 'px';
      if (overlap !== this.overlap) {
        this.canvas.style.setProperty('--air-overlap', overlap);
        this.overlap = overlap;
      }
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return false;
      const dpr = Math.min(devicePixelRatio || 1, SIMULATION.maxDpr, Math.sqrt(8000000 / (rect.width * rect.height)));
      const width = rect.width / scale, height = rect.height / scale;
      const changed = Math.abs(this.width - width) > .5 || Math.abs(this.height - height) > .5 || this.dpr !== dpr || Math.abs((this.scale || 0) - scale) > .0001;
      this.width = width;
      this.height = height;
      this.dpr = dpr;
      this.scale = scale;
      const inset = Math.max(7, outlet.width / scale * .013);
      this.emitter.left = clamp((outlet.left - rect.left) / scale + inset, 2, this.width - 2);
      this.emitter.right = clamp((outlet.right - rect.left) / scale - inset, 2, this.width - 2);
      this.emitter.y = Math.max(0, (outlet.bottom - rect.top) / scale - 2);
      this.renderer.resize(width, height, dpr, changed, scale);
      if (changed) this.credit = 0;
      return changed;
    }

    updatePalette() {
      if (this.mode === this.state.mode) return;
      this.mode = this.state.mode;
      this.profile = WIND_PROFILES[this.mode];
      if (!this.profile.markAlpha) this.particles.length = 0;
      for (const p of this.particles) p.lifetime = Math.min(p.lifetime, p.age + .4);
    }

    targetSpeed() {
      const { speed, mode, temp } = this.state;
      if (speed !== 'auto') return FAN_SPEED[speed];
      if (mode === 'dry') return 112;
      if (mode === 'fan') return 142;
      const room = this.getClimate().temperature;
      return Number.isFinite(room) ? clamp(124 + Math.abs(room - temp) * 8, 124, 174) : 124;
    }

    targetAngle(time) {
      if (this.direction === 'fixed') return this.fixedAngle;
      if (this.direction === 'swing') {
        return SWING.center + SWING.amplitude * Math.cos(this.swingOffset + (time - this.swingStart) * 2 * Math.PI / SWING.period);
      }
      return DIRECTION_PITCH[this.direction];
    }

    reach(pitch) {
      return (this.height - this.emitter.y) * clamp(.60 + this.speed / 430, .78, 1.38)
        * (.65 + .45 * Math.sin(pitch * Math.PI / 180));
    }

    // 微光跟随同一股气流的速度场，因此会沿着流线的 S 形路径飘动。
    field(x, y, emissionPitch = this.angle) {
      const distance = Math.max(0, y - this.emitter.y);
      const depth = clamp(distance / (this.height - this.emitter.y), 0, 1.3);
      const pitch = emissionPitch * Math.PI / 180;
      const center = (this.emitter.left + this.emitter.right) / 2;
      const half = Math.max(1, (this.emitter.right - this.emitter.left) / 2);
      const position = clamp((x - center) / (half + distance * .12), -1.3, 1.3);
      const jet = this.speed / Math.sqrt(1 + distance / 190);
      const spread = Math.cos(pitch) * .72 * (1 - Math.exp(-distance / 24)) * this.profile.spread;
      const thermal = this.mode === 'heat' ? 1 - .20 * depth * depth
        : (this.mode === 'cool' || this.mode === 'dry') ? 1 + .06 * depth : 1;
      const pulse = 1 + .018 * Math.sin(this.time * .94);
      let vx = position * jet * spread;
      let vy = jet * (.22 + .78 * Math.sin(pitch)) * thermal * pulse;
      const mix = 1 - Math.exp(-distance / 75);
      const advection = this.travel / 185;
      const a = x / 83 + advection * .32, b = distance / 83 - advection * .56;
      const c = x / 39 - advection * .28, e = distance / 39 + advection * .39;
      const fine = x / 19 + distance / 31 - advection * .62;
      const turbulence = (4 + this.speed * .072) * mix * this.profile.turbulence;
      vx += turbulence * (Math.sin(a) * Math.cos(b) + .42 * Math.sin(c) * Math.cos(e) + .12 * Math.sin(fine));
      vy -= turbulence * (Math.cos(a) * Math.sin(b) + .42 * Math.cos(c) * Math.sin(e));
      // 整股气流一起缓慢摆动，和流线共用同一条摆动相位。
      const sway = (Math.sin(distance / 148 - this.travel / 268 + 1.1) * (5 + this.speed * .06)
        + Math.sin(distance / 73 + this.travel / 172) * (2 + this.speed * .030))
        * mix * (this.profile.sway || 1);
      vx += sway;
      this.velocity.vx = vx;
      this.velocity.vy = Math.max(24, vy);
      return this.velocity;
    }

    spawn() {
      const position = ((this.sequence++ * .61803398875) + this.random() * .07) % 1;
      const x = this.emitter.left + position * (this.emitter.right - this.emitter.left);
      const y = this.emitter.y + this.random() * 2;
      const velocity = this.field(x, y);
      const profile = this.profile;
      this.particles.push({
        x, y, vx: velocity.vx, vy: velocity.vy, pitch: this.angle, profile,
        age: 0, lifetime: 1.2 + this.random() * 1.8, mode: this.mode,
        alpha: profile.markAlpha * (.55 + this.random() * .45),
        size: profile.markSize[0] + this.random() * profile.markSize[1],
        phase: this.random() * Math.PI * 2, turn: (this.random() - .5) * .8,
        layer: this.random(), reach: this.reach(this.angle) * profile.reach
      });
    }

    advance(dt) {
      if (!this.width || !this.height) return;
      this.time += dt;
      this.angle += (this.targetAngle(this.time) - this.angle) * (1 - Math.exp(-dt * 5));
      this.speed += (this.targetSpeed() - this.speed) * (1 - Math.exp(-dt * 2.2));
      this.travel += this.speed * dt;
      const density = clamp((this.emitter.right - this.emitter.left) / 760, .42, 1.08);
      if (this.profile.markAlpha) {
        this.credit += (9 + this.speed * .07) * density * this.profile.emission * dt;
        while (this.credit >= 1) {
          if (this.particles.length < 180) this.spawn();
          this.credit -= 1;
        }
      }
      const response = 1 - Math.exp(-dt * 6);
      let alive = 0;
      for (const p of this.particles) {
        p.age += dt;
        const distance = Math.max(0, p.y - this.emitter.y);
        p.pitch += (this.angle - p.pitch) * (1 - Math.exp(-dt * 5 / (1 + distance / 70)));
        const velocity = this.field(p.x, p.y, p.pitch);
        p.vx += (velocity.vx - p.vx) * response;
        p.vy += (velocity.vy - p.vy) * response;
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.reach = this.reach(p.pitch) * p.profile.reach;
        if (p.age >= p.lifetime || p.y > Math.min(this.height + 20, this.emitter.y + p.reach) || p.x < -20 || p.x > this.width + 20) continue;
        this.particles[alive++] = p;
      }
      this.particles.length = alive;
    }

    draw() {
      this.renderer.draw(this.particles, this.emitter, { time: this.time, speed: this.speed, travel: this.travel,
        pitch: this.angle, reach: this.reach(this.angle), mode: this.mode, profile: this.profile });
      this.setLouver(this.angle);
    }

    setLouver(pitch) {
      // 正面投影只改变开口内的高度和位置，扫风极限也不越过出风口。
      const opening = pitch === null ? null : clamp((pitch - 8) / 78, 0, 1);
      const top = opening === null ? 0 : 10 + opening * 16;
      const height = opening === null ? 100 : 36 + opening * 30;
      const geometry = `${top.toFixed(2)}:${height.toFixed(2)}`;
      if (geometry === this.lastLouverGeometry) return;
      this.louver.style.setProperty('--vane-top', `${top.toFixed(2)}%`);
      this.louver.style.setProperty('--vane-height', `${height.toFixed(2)}%`);
      this.lastLouverGeometry = geometry;
    }

    frame(now) {
      this.raf = null;
      if (this.disposed || !this.state.power || document.hidden || this.isStatic()) return;
      const dt = this.lastFrame === null ? SIMULATION.step : clamp((now - this.lastFrame) / 1000, 0, SIMULATION.maxFrameDelta);
      this.lastFrame = now;
      this.accumulator += dt;
      while (this.accumulator >= SIMULATION.step) {
        this.advance(SIMULATION.step);
        this.accumulator -= SIMULATION.step;
      }
      this.draw();
      this.raf = requestAnimationFrame(this.tick);
    }

    start() {
      if (!this.visible) return;
      if (this.disposed || !this.state.power || this.raf !== null || document.hidden || this.isStatic()) return;
      this.resize();
      this.lastFrame = null;
      this.accumulator = 0;
      this.raf = requestAnimationFrame(this.tick);
    }

    stop() {
      if (this.raf !== null) cancelAnimationFrame(this.raf);
      this.raf = this.lastFrame = null;
      this.accumulator = 0;
    }

    clear() {
      this.particles.length = 0;
      this.credit = this.time = this.travel = 0;
      this.renderer.clear();
    }

    staticFrame() {
      this.stop();
      this.resize();
      this.clear();
      this.seed = SIMULATION.seed;
      this.sequence = 0;
      this.swingStart = this.swingOffset = 0;
      this.angle = this.targetAngle(0);
      this.speed = this.targetSpeed();
      for (let i = 0; i < SIMULATION.staticSteps; i++) this.advance(SIMULATION.step);
      this.draw();
    }

    sync() {
      if (this.disposed) return;
      this.state = this.getState();
      this.updatePalette();
      if (this.direction !== this.state.direction) {
        if (this.state.direction === 'fixed') this.fixedAngle = this.angle;
        if (this.state.direction === 'swing') {
          this.swingStart = this.time;
          this.swingOffset = Math.acos(clamp((this.angle - SWING.center) / SWING.amplitude, -1, 1));
        }
        this.direction = this.state.direction;
      }
      if (!this.state.power) {
        this.stop();
        this.clear();
        this.direction = '';
        this.setLouver(null);
      } else if (!this.visible) this.stop();
      else if (this.isStatic()) this.staticFrame();
      else this.start();
    }

    setVisible(visible) {
      if (this.visible === visible) return;
      this.visible = visible;
      if (visible) { this.resize(); this.sync(); }
      else this.stop();
    }

    inspect() {
      const count = this.particles.length;
      let vx = 0, vy = 0, downward = 0;
      for (const p of this.particles) {
        vx += p.vx; vy += p.vy;
        if (p.vy > 0) downward++;
      }
      const rect = this.canvas.getBoundingClientRect();
      return {
        engine: 'layered-flow-v9', volume: this.renderer.volume.ready ? 'gpu' : 'texture', count, running: this.raf !== null,
        appearance: this.mode === 'cool' ? 'continuous-mist' : 'layered',
        style: this.profile?.name, palette: this.profile ? [this.profile.primary, this.profile.secondary] : [],
        stream: this.profile?.stream ?? null,
        particleKinds: count ? { mark: count } : {},
        pitch: this.angle, speed: this.speed, speedSetting: this.state.speed,
        time: this.time, travel: this.travel, reach: this.reach(this.angle),
        louverAngle: this.angle,
        emitter: { ...this.emitter, pageY: rect.top + this.emitter.y * this.scale },
        size: { width: this.width, height: this.height, scale: this.scale, bitmapPixels: this.canvas.width * this.canvas.height },
        meanVelocity: { x: count ? vx / count : 0, y: count ? vy / count : 0 },
        downwardFraction: count ? downward / count : 0
      };
    }

    dispose() {
      if (this.disposed) return;
      this.stop();
      this.observer?.disconnect();
      window.removeEventListener('resize', this.onResize);
      this.clear();
      this.renderer.dispose();
      this.disposed = true;
    }
  }
