  class TemperatureDial {
    constructor({ element, progress, knob, readout, getState, getLimits, onChange, signal }) {
      Object.assign(this, { element, progress, knob, readout, getState, getLimits, onChange });
      this.pointerId = null;
      this.lastTemperature = null;
      this.lastPower = null;
      this.frame = null;
      this.displayAngle = null;
      this.feedbackTimer = null;
      this.box = element.closest('.dial-box');
      this.motion = matchMedia('(prefers-reduced-motion: reduce)');
      this.readoutAnimation = null;
      element.addEventListener('pointerdown', event => this.beginDrag(event), { signal });
      element.addEventListener('pointermove', event => this.moveDrag(event), { signal });
      for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
        element.addEventListener(type, event => {
          if (event.pointerId === this.pointerId) this.cancelDrag();
        }, { signal });
      }
      element.addEventListener('wheel', event => this.handleWheel(event), { passive: false, signal });
      element.addEventListener('keydown', event => this.handleKey(event), { signal });
      element.querySelector('#track').setAttribute('d', this.arc(DIAL.start, DIAL.end));
      this.ticks = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      this.ticks.setAttribute('class', 'dial-ticks');
      this.ticks.setAttribute('aria-hidden', 'true');
      progress.before(this.ticks);
      const hints=document.createElement('div');
      hints.className='dial-step-hints';hints.setAttribute('aria-hidden','true');
      hints.innerHTML='<span>−</span><span>+</span>';this.box.append(hints);
      this.motion.addEventListener('change',()=>{if(this.motion.matches)this.stopMotion()},{signal});
      signal?.addEventListener('abort', () => this.dispose(), { once:true });
    }

    point(angle) {
      const radians = angle * Math.PI / 180;
      return [DIAL.center + DIAL.radius * Math.cos(radians), DIAL.center + DIAL.radius * Math.sin(radians)];
    }

    arc(start, end) {
      if (end - start < .5) return '';
      const [x0, y0] = this.point(start), [x1, y1] = this.point(end);
      return `M ${roundCoordinate(x0)} ${roundCoordinate(y0)} A ${DIAL.radius} ${DIAL.radius} 0 ${end - start > 180 ? 1 : 0} 1 ${roundCoordinate(x1)} ${roundCoordinate(y1)}`;
    }

    temperatureAt(event) {
      const rect = this.element.getBoundingClientRect();
      const dx = event.clientX - rect.left - rect.width / 2;
      const dy = event.clientY - rect.top - rect.height / 2;
      if (Math.hypot(dx, dy) < rect.width * DIAL.deadZone) return null;
      let angle = Math.atan2(dy, dx) * 180 / Math.PI;
      if (angle < 0) angle += 360;
      if (angle > 45 && angle < 135) angle = angle < 90 ? 45 : 135;
      if (angle < DIAL.start) angle += 360;
      angle = clamp(angle, DIAL.start, DIAL.end);
      const limits = this.getLimits();
      return limits.min + (angle - DIAL.start) / (DIAL.end - DIAL.start) * (limits.max - limits.min);
    }

    beginDrag(event) {
      if (!this.getState().power || event.button !== 0 || !event.isPrimary || this.pointerId !== null) return;
      let temperature = this.temperatureAt(event);
      this.stepClick = temperature === null;
      if (this.stepClick) {
        const rect = this.element.getBoundingClientRect();
        temperature = this.getState().temp + (event.clientX >= rect.left + rect.width / 2 ? 1 : -1);
      }
      event.preventDefault();
      this.pointerId = event.pointerId;
      this.element.setPointerCapture(event.pointerId);
      this.element.classList.add('is-dragging');
      this.onChange(temperature);
      this.press();
    }

    moveDrag(event) {
      if (event.pointerId !== this.pointerId || !this.getState().power || this.stepClick) return;
      const temperature = this.temperatureAt(event);
      if (temperature !== null) this.onChange(temperature);
    }

    cancelDrag() {
      const pointerId = this.pointerId;
      this.pointerId = null;
      this.element.classList.remove('is-dragging');
      if (pointerId !== null && this.element.hasPointerCapture(pointerId)) {
        this.element.releasePointerCapture(pointerId);
      }
    }

    handleWheel(event) {
      if (!this.getState().power || event.ctrlKey || !event.deltaY) return;
      event.preventDefault();
      event.stopPropagation();
      this.onChange(this.getState().temp - Math.sign(event.deltaY));
      this.press();
    }

    handleKey(event) {
      const state = this.getState();
      if (!state.power) return;
      const limits = this.getLimits();
      let temperature;
      if (event.key === 'Home') temperature = limits.min;
      else if (event.key === 'End') temperature = limits.max;
      else if (Object.hasOwn(KEY_STEPS, event.key)) temperature = state.temp + KEY_STEPS[event.key];
      else return;
      event.preventDefault();
      this.onChange(temperature);
      this.press();
    }

    reduced() { return this.motion.matches || document.body.classList.contains('freeze'); }

    press() {
      if (this.reduced()) return;
      this.pressAnimation?.cancel();
      this.pressAnimation = this.progress.animate([
        {strokeWidth:7,filter:'drop-shadow(0 0 5px var(--accent))'},
        {strokeWidth:4,filter:'drop-shadow(0 0 0px transparent)'}
      ], {duration:360,easing:'ease-out'});
    }

    drawAngle(angle) {
      this.displayAngle = angle;
      const [x,y] = this.point(angle);
      this.progress.setAttribute('d', this.arc(DIAL.start, angle));
      this.progress.style.opacity = angle > DIAL.start + .01 ? '' : '0';
      this.knob.setAttribute('transform', `translate(${roundCoordinate(x)} ${roundCoordinate(y)})`);
    }

    animateTo(angle, immediate) {
      this.targetAngle=angle;
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      this.frame = null;
      if (immediate || this.reduced() || this.displayAngle === null) { this.drawAngle(angle); return; }
      const start = this.displayAngle, started = performance.now();
      const tick = now => {
        const progress = Math.min(1, (now-started)/240);
        this.drawAngle(start+(angle-start)*(1-Math.pow(1-progress,3)));
        if (progress < 1) this.frame=requestAnimationFrame(tick);
        else this.frame=null;
      };
      this.frame=requestAnimationFrame(tick);
    }

    changeFeedback(delta) {
      if (this.reduced() || !delta) return;
      this.readoutAnimation?.cancel();
      this.readoutAnimation=this.readout.animate([
        {transform:`translateY(${delta>0?8:-8}px) scale(.94)`,opacity:.24,filter:'blur(1px)'},
        {transform:'translateY(0) scale(1)',opacity:1,filter:'blur(0)'}
      ], {duration:300,easing:'cubic-bezier(.18,.8,.25,1)'});
      this.box.dataset.delta=`${delta>0?'+':'−'}${Math.abs(delta)}°`;
      this.box.classList.add('is-changing');
      clearTimeout(this.feedbackTimer);
      this.feedbackTimer=setTimeout(()=>this.box.classList.remove('is-changing'),650);
      this.press();
    }

    buildTicks(limits) {
      this.ticks.replaceChildren();
      for (let temp=limits.min; temp<=limits.max; temp++) {
        const angle=DIAL.start+(temp-limits.min)/(limits.max-limits.min)*(DIAL.end-DIAL.start);
        const radians=angle*Math.PI/180;
        const line=document.createElementNS('http://www.w3.org/2000/svg','line');
        const radius=DIAL.radius-13;
        for(const [name,value] of Object.entries({x1:180+radius*Math.cos(radians),y1:180+radius*Math.sin(radians),x2:180+(radius-4)*Math.cos(radians),y2:180+(radius-4)*Math.sin(radians)}))line.setAttribute(name,roundCoordinate(value));
        line.dataset.temp=temp;
        this.ticks.append(line);
      }
    }

    dispose() {
      this.cancelDrag();
      this.stopMotion();
    }

    stopMotion() {
      if(this.frame!==null)cancelAnimationFrame(this.frame);
      clearTimeout(this.feedbackTimer);
      this.readoutAnimation?.cancel();this.pressAnimation?.cancel();
      this.frame=null;
      this.box.classList.remove('is-changing');
      if(this.targetAngle!==undefined)this.drawAngle(this.targetAngle);
    }

    render({ temp, power }) {
      const limits = this.getLimits();
      const range = `${limits.min}:${limits.max}`;
      if (power !== this.lastPower) {
        this.element.classList.toggle('is-off', !power);
        this.element.setAttribute('aria-disabled', String(!power));
        if (!power) { this.cancelDrag();this.stopMotion(); }
        this.lastPower = power;
      }
      if (temp === this.lastTemperature && range === this.lastRange) return;
      if (range !== this.lastRange) this.buildTicks(limits);
      const angle = DIAL.start + (temp - limits.min) / (limits.max - limits.min) * (DIAL.end - DIAL.start);
      const previous=this.lastTemperature;
      this.animateTo(angle, previous === null || !power);
      this.readout.textContent = temp;
      if (previous !== null && power && temp !== previous) this.changeFeedback(temp-previous);
      for (const tick of this.ticks.children) tick.classList.toggle('selected', Number(tick.dataset.temp)===temp);
      this.element.setAttribute('aria-valuenow', String(temp));
      this.element.setAttribute('aria-valuemin', String(limits.min));
      this.element.setAttribute('aria-valuemax', String(limits.max));
      this.element.setAttribute('aria-valuetext', `${temp} 摄氏度`);
      this.lastTemperature = temp;
      this.lastRange = range;
    }
  }
