  // 连续体积雾使用 GPU 域扭曲噪声，作为气流的柔和底层；不支持 WebGL 时直接由流线承担画面。
  class FlowVolume {
    constructor() {
      this.canvas = document.createElement('canvas');
      this.gl = this.canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, preserveDrawingBuffer: true });
      this.ready = false;
      if (!this.gl) return;
      const gl = this.gl;
      const compile = (type, source) => {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source); gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
          const error = gl.getShaderInfoLog(shader); gl.deleteShader(shader); throw new Error(error);
        }
        return shader;
      };
      try {
        this.vertex = compile(gl.VERTEX_SHADER, 'attribute vec2 position;void main(){gl_Position=vec4(position,0.,1.);}');
        this.fragment = compile(gl.FRAGMENT_SHADER, `
          precision highp float;
          uniform vec2 resolution, size;
          uniform vec3 emitter, primary, secondary;
          uniform float time, speed, travel, pitch, reach, kind, coolMist;
          float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
          float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
            return mix(mix(hash(i),hash(i+vec2(1.,0.)),f.x),mix(hash(i+vec2(0.,1.)),hash(i+vec2(1.,1.)),f.x),f.y);}
          float fbm(vec2 p){float n=0.,a=.53;mat2 r=mat2(.86,.51,-.51,.86);
            for(int i=0;i<4;i++){n+=a*noise(p);p=r*p*2.03+vec2(17.8,9.2);a*=.48;}return n;}

          void main(){
            vec2 pos=vec2(gl_FragCoord.x/resolution.x,(1.-gl_FragCoord.y/resolution.y))*size;
            float dist=pos.y-emitter.z;
            // 风程不能超过画布可用高度，否则窗口较矮时底部会出现一条硬截断线。
            float limit=min(reach,max(24.,size.y-emitter.z));
            if(dist<0.||dist>limit){gl_FragColor=vec4(0.);return;}
            float depth=clamp(dist/max(limit,1.),0.,1.);
            float strength=clamp((speed-86.)/274.,0.,1.);
            float center=(emitter.x+emitter.y)*.5;
            float halfWidth=max(1.,(emitter.y-emitter.x)*.5);

            // 整股气流缓慢摆动，越靠下游摆幅越大。
            float sway=(fbm(vec2(depth*2.3+7.3,travel*.0034))-.5)*(18.+depth*depth*72.);
            float x=pos.x-center-sway;

            // 柔和扩散锥：风口处贴合出风口，下游略微张开。
            float widen=reach*(.12+.08*cos(radians(pitch)));
            float spread=halfWidth+widen*depth;
            float side=abs(x)/max(spread,1.);

            // 不规则涡瓣边缘。
            float erosion=fbm(vec2(x*.0105+travel*.0011,dist*.0068));
            float sideE=side+(erosion-.5)*(.32+.25*depth);
            float body=1.-smoothstep(.55,1.02,sideE);
            body*=smoothstep(0.,22.,dist);

            // 只有两层大尺度噪声：雾面保持平滑连续，细节交给上面的流线层。
            vec2 drift=vec2(0.,-travel*.0036);
            float big=fbm(vec2(x*.0048+2.3,dist*.0026)+drift);
            float mid=fbm(vec2(x*.0120-4.1,dist*.0058)+drift*1.9);
            float mass=smoothstep(.38,.72,big*.60+mid*.40);
            float density=body*(.22+.78*mass);
            density*=smoothstep(0.,.05,depth);
            density*=1.-smoothstep(.62,.985,min(1.,depth+(mid-.5)*.20));
            density*=1.-smoothstep(.90,1.,depth);

            float base=.105;
            if(coolMist>.5) base=.128;
            else if(kind>.5&&kind<1.5) base=.128;
            else if(kind>1.5&&kind<2.5) base=.098;
            else if(kind>2.5&&kind<3.5) base=.092;
            float alpha=density*base*(1.+strength*.30);
            vec3 color=mix(primary,secondary,smoothstep(.34,.74,mid));
            color=mix(color,vec3(.97,1.,1.),smoothstep(.55,.9,mass)*(coolMist>.5?.32:.18));
            gl_FragColor=vec4(color*alpha,alpha);
          }`);
        this.program = gl.createProgram();
        gl.attachShader(this.program, this.vertex); gl.attachShader(this.program, this.fragment); gl.linkProgram(this.program);
        if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(this.program));
        this.buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,1,1]), gl.STATIC_DRAW);
        gl.useProgram(this.program);
        const position = gl.getAttribLocation(this.program, 'position');
        gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
        this.uniforms = Object.fromEntries(['resolution','size','emitter','primary','secondary','time','speed','travel','pitch','reach','kind','coolMist']
          .map(name => [name, gl.getUniformLocation(this.program, name)]));
        gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND);
        this.ready = true;
      } catch { this.dispose(); }
      this.canvas.addEventListener('webglcontextlost', event => { event.preventDefault(); this.ready = false; });
      this.canvas.addEventListener('webglcontextrestored', () => { this.ready = false; });
    }

    render(width, height, emitter, flow) {
      if (!this.ready || this.gl.isContextLost()) return false;
      const gl = this.gl, u = this.uniforms;
      const scale = Math.min(1.6, Math.sqrt(900000 / (width * height)));
      const w = Math.max(1, Math.round(width * scale)), h = Math.max(1, Math.round(height * scale));
      if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
      gl.viewport(0, 0, w, h); gl.useProgram(this.program);
      gl.uniform2f(u.resolution, w, h); gl.uniform2f(u.size, width, height);
      gl.uniform3f(u.emitter, emitter.left, emitter.right, emitter.y);
      gl.uniform3fv(u.primary, flow.profile.primary.split(',').map(v => Number(v) / 255));
      gl.uniform3fv(u.secondary, flow.profile.secondary.split(',').map(v => Number(v) / 255));
      for (const name of ['time','speed','travel','pitch','reach']) gl.uniform1f(u[name], flow[name]);
      gl.uniform1f(u.kind, { cool: 0, heat: 1, dry: 2, fan: 3, auto: 4 }[flow.mode] ?? 4);
      gl.uniform1f(u.coolMist, flow.mode === 'cool' ? 1 : 0);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      return true;
    }

    dispose() {
      const gl = this.gl;
      if (gl) {
        if (this.buffer) gl.deleteBuffer(this.buffer);
        if (this.program) gl.deleteProgram(this.program);
        if (this.vertex) gl.deleteShader(this.vertex);
        if (this.fragment) gl.deleteShader(this.fragment);
        gl.getExtension('WEBGL_lose_context')?.loseContext();
      }
      this.ready = false;
    }
  }

  // 气流主体：一组宽而渐细的柔和流线。每帧按漂移量重算中心线，低分辨率绘制后放大，
  // 得到连续、有厚度、带卷曲的丝带状气流，而不是一根根细线或一团团斑点。
  class FlowStreams {
    constructor() {
      // 两层：veil 是宽而重的雾体（合成时强模糊），canvas 是少量清晰的流线。
      this.veil = document.createElement('canvas');
      this.veilContext = this.veil.getContext('2d');
      this.canvas = document.createElement('canvas');
      this.context = this.canvas.getContext('2d');
      this.width = 0;
      this.height = 0;
      this.points = [];
      this.factor = .62;
      this.cache = new Map();
    }

    resize(width, height, deviceScale) {
      this.width = width;
      this.height = height;
      const w = Math.max(1, Math.round(width * deviceScale * this.factor));
      const h = Math.max(1, Math.round(height * deviceScale * this.factor));
      for (const canvas of [this.canvas, this.veil]) {
        if (canvas.width !== w || canvas.height !== h) {
          canvas.width = w;
          canvas.height = h;
        }
      }
      for (const g of [this.context, this.veilContext]) {
        g.setTransform(w / width, 0, 0, h / height, 0, 0);
        g.imageSmoothingEnabled = true;
        g.imageSmoothingQuality = 'high';
      }
    }

    // 每条气流片的稳定个性：位置、宽窄、明暗、速度、波长、相位、漂移。
    lane(key, lane) {
      const id = key + ':' + lane;
      const cached = this.cache.get(id);
      if (cached) return cached;
      const r = salt => {
        const x = Math.sin((lane + 1) * salt + (key === 'lines' ? 7.31 : 17.93)) * 43758.5453;
        return x - Math.floor(x);
      };
      const r1 = r(12.9898), r2 = r(78.233), r3 = r(39.425), r4 = r(93.989), r5 = r(53.717);
      const params = {
        position: (lane + .5 + (r1 - .5) * .62) / Math.max(2, this._count || 6),
        width: .60 + r2 * 1.00,
        alpha: .55 + r3 * .95,
        length: .60 + r4 * .48,
        speed: .72 + r5 * .58,
        curl: .68 + r1 * .95,
        drift: (r5 - .5) * 13,
        phase1: r1 * 6.283,
        phase2: r3 * 6.283,
        phase3: r5 * 6.283,
        lambda1: .78 + r2 * .48,
        lambda2: .76 + r4 * .52,
        lambda3: .74 + r3 * .6
      };
      this.cache.set(id, params);
      return params;
    }

    draw(emitter, flow, strength) {
      const stream = flow.profile.stream;
      if (!stream) return;
      // 雾体：很宽、彼此重叠，合成时整体强模糊，只留下连续且不均匀的体积。
      this.layer(this.veilContext, emitter, flow, strength, {
        ...stream.veil, key: 'veil', line: false, speed: .72, lengthScale: 1.08, curlScale: .85
      });
      // 流线：细、弯曲明显、速度各异，提供“空气在动”的方向感。
      this.layer(this.context, emitter, flow, strength, {
        ...stream.lines, key: 'lines', line: true, speed: 1, lengthScale: 1, curlScale: 1.32
      });
      // 阵风：少量更快、更短的细线，让气流偶尔“窜”一下。
      this.layer(this.context, emitter, flow, strength, {
        ...stream.lines, key: 'gust', clear: false, line: true, speed: 1.75, lengthScale: .62, curlScale: 1.15,
        count: Math.max(2, Math.round(stream.lines.count * .35)),
        width: stream.lines.width * .5, alpha: stream.lines.alpha * .62
      });
    }

    layer(g, emitter, flow, strength, options) {
      const stream = flow.profile.stream;
      if (options.clear !== false) g.clearRect(0, 0, this.width, this.height);
      const span = emitter.right - emitter.left;
      const count = Math.max(1, options.count || 1);
      this._count = count;
      const steps = options.line ? 42 : 34;
      const points = this.points;
      const pitch = flow.pitch * Math.PI / 180;
      const downness = clamp(Math.sin(pitch), .2, 1);
      const speedNorm = clamp((flow.speed - FAN_SPEED.low) / (FAN_SPEED.high - FAN_SPEED.low), 0, 1);
      // 全局风况：三个互不整除的慢周期叠加，形成看不出循环的阵风。
      const now = flow.time;
      const gust = clamp(.5 + .25 * Math.sin(now * 1.07 + 1.7)
        + .16 * Math.sin(now * .47 + 4.1) + .09 * Math.sin(now * .19 + 2.3), .16, .96);
      const windShift = (Math.sin(now * .19 + .8) * 8 + Math.sin(now * .083 + 2.1) * 5) * clamp(span / 900, .5, 1.2);
      // 平吹更散更短，下吹更聚更长；风速越快越长、扰动越明显。
      const length = Math.max(40, flow.reach * (stream.length || 1) * options.lengthScale
        * (.80 + .28 * downness) * (1 + speedNorm * .16) * (.93 + .12 * gust));
      const widen = .55 + .85 * Math.cos(pitch);
      const boost = 1 + strength * .26;
      // 窄窗时出风口变窄：扰动同步收小，否则流线会交叉成乱麻。
      const breadth = clamp(span / 900, .45, 1.15);
      for (let lane = 0; lane < count; lane++) {
        const profile = this.lane(options.key, lane);
        const travel = flow.travel * options.speed * profile.speed;
        const t = now * profile.speed;
        // 每条气流片自己的呼吸：不会被整排同时吹亮或吹灭。
        const laneGust = clamp(.72 + .34 * Math.sin(t * 1.21 + profile.phase1)
          + .22 * Math.sin(t * .53 + profile.phase2), .35, 1.25);
        // 每条带的横向位置缓慢漂移、宽度缓慢呼吸，避免固定竖棱。
        const position = clamp(profile.position + .030 * Math.sin(t * .21 + profile.phase2), .02, .98);
        const breath = .84 + .30 * Math.sin(t * .90 + profile.phase3);
        const width = (options.width || stream.veil.width) * profile.width * breath;
        const edgeFade = options.line ? 1 : .68 + .32 * Math.sin(Math.PI * position);
        const alpha = (options.alpha || stream.veil.alpha) * profile.alpha
          * (.78 + .34 * laneGust) * boost * edgeFade;
        const curl = (stream.curl || 1) * options.curlScale * profile.curl;
        const laneLength = length * profile.length * (.90 + .14 * laneGust);
        const fanRate = (stream.spread || .1) * widen;
        const drift = profile.drift * breadth * Math.sin(t * .26 + profile.phase2);
        let total = 0;
        for (let step = 0; step <= steps; step++) {
          const u = step / steps, distance = u * laneLength;
          // 四段不同尺度的扰动：大摆动、卷曲、细颤、以及每条的慢漂移。
          const meander = Math.sin(distance / (215 * profile.lambda1) - travel / 124 + profile.phase1)
            * curl * breadth * (4 + distance * .155);
          const curl2 = Math.sin(distance / (92 * profile.lambda2) + travel / 76 + profile.phase2)
            * curl * breadth * (2 + distance * .065);
          const fine = Math.sin(distance / (41 * profile.lambda3) + travel / 37 + profile.phase3)
            * breadth * (options.line ? 3.4 : 1.9) * (.45 + speedNorm * 1.05) * (1 + distance * .014);
          const fan = (position - .5) * fanRate * distance
            + Math.sin(distance / 120 + profile.phase3) * fanRate * distance * .22;
          const point = points[total] || (points[total] = {});
          point.x = emitter.left + span * position + fan + meander + curl2 + fine + drift + windShift;
          point.y = emitter.y + distance;
          const taper = 1 - (options.line ? .50 : .30) * Math.min(1, Math.max(0, (u - .78) / .22));
          // 沿程轻微鼓包/收束，避免每条都是同一种平滑棱形。
          const bulge = .88 + .14 * Math.sin(distance / 138 - travel / 320 + profile.phase3);
          point.w = width * (.64 + .36 * Math.sin(Math.PI * Math.min(1, u * .9))) * taper * bulge;
          total++;
        }
        for (let i = 0; i < total; i++) {
          const before = points[Math.max(0, i - 1)], after = points[Math.min(total - 1, i + 1)];
          const dx = after.x - before.x, dy = after.y - before.y, normal = Math.max(.001, Math.hypot(dx, dy));
          points[i].nx = -dy / normal;
          points[i].ny = dx / normal;
        }
        const first = points[0], last = points[total - 1];
        const gradient = g.createLinearGradient(0, first.y, 0, last.y);
        if (options.line) {
          const color = stream.lines.color || '242,254,255';
          gradient.addColorStop(0, `rgba(${color},0)`);
          gradient.addColorStop(.08, `rgba(${color},${(alpha * .55).toFixed(3)})`);
          gradient.addColorStop(.42, `rgba(${color},${alpha.toFixed(3)})`);
          gradient.addColorStop(.78, `rgba(${color},${(alpha * .45).toFixed(3)})`);
          gradient.addColorStop(1, `rgba(${color},0)`);
        } else {
          gradient.addColorStop(0, `rgba(${flow.profile.secondary},0)`);
          gradient.addColorStop(.06, `rgba(${flow.profile.secondary},${(alpha * .55).toFixed(3)})`);
          gradient.addColorStop(.22, `rgba(${flow.profile.primary},${(alpha * .95).toFixed(3)})`);
          gradient.addColorStop(.55, `rgba(${flow.profile.primary},${alpha.toFixed(3)})`);
          gradient.addColorStop(.86, `rgba(${flow.profile.secondary},${(alpha * .30).toFixed(3)})`);
          gradient.addColorStop(1, `rgba(${flow.profile.secondary},0)`);
        }
        g.fillStyle = gradient;
        g.globalAlpha = 1;
        this.contour(points, 1, total, g);
        g.fill();
        if (options.line) {
          g.globalAlpha = .18;
          g.fillStyle = `rgba(${stream.lines.color || '242,254,255'},1)`;
          this.contour(points, .20, total, g);
          g.fill();
          g.globalAlpha = 1;
        }
      }
    }

    contour(points, width, count, g) {
      const last = count - 1;
      g.beginPath();
      g.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < last; i++) {
        const a = points[i], b = points[i + 1];
        const ax = a.x + a.nx * a.w * width, ay = a.y + a.ny * a.w * width;
        const bx = b.x + b.nx * b.w * width, by = b.y + b.ny * b.w * width;
        g.quadraticCurveTo(ax, ay, (ax + bx) / 2, (ay + by) / 2);
      }
      g.lineTo(points[last].x, points[last].y);
      for (let i = last - 1; i > 0; i--) {
        const a = points[i], b = points[i - 1];
        const ax = a.x - a.nx * a.w * width, ay = a.y - a.ny * a.w * width;
        const bx = b.x - b.nx * b.w * width, by = b.y - b.ny * b.w * width;
        g.quadraticCurveTo(ax, ay, (ax + bx) / 2, (ay + by) / 2);
      }
      g.closePath();
    }

    dispose() {
      this.canvas.width = this.canvas.height = 0;
      this.veil.width = this.veil.height = 0;
      this.points.length = 0;
      this.cache.clear();
    }
  }

  // 绘制只读取模拟状态：体积雾打底，流线塑形，稀疏微光点缀。
  class AirflowRenderer {
    constructor(canvas) {
      this.canvas = canvas;
      this.context = canvas.getContext('2d');
      if (!this.context) throw new Error('Canvas 2D is unavailable');
      this.width = this.height = 0;
      this.volume = new FlowVolume();
      this.streams = new FlowStreams();
    }

    resize(width, height, dpr, resetBitmap, scale = 1) {
      this.width = width;
      this.height = height;
      if (!resetBitmap) return;
      this.canvas.width = Math.round(width * scale * dpr);
      this.canvas.height = Math.round(height * scale * dpr);
      this.context.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
      this.context.imageSmoothingEnabled = true;
      this.context.imageSmoothingQuality = 'high';
      this.streams.resize(width, height, dpr * scale);
      this.dissolve = null;
    }

    // 底边溶解：用缓慢起伏的噪声让气流自然散开，而不是一条水平渐隐线。
    ensureDissolve() {
      if (this.dissolve) return;
      const hash = (x, y, seed) => {
        let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(seed, 1274126177);
        h = Math.imul(h ^ h >>> 13, 1274126177);
        return ((h ^ h >>> 16) >>> 0) / 4294967295;
      };
      const noise = (x, y, seed) => {
        const ix = Math.floor(x), iy = Math.floor(y);
        let fx = x - ix, fy = y - iy;
        fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy);
        const a = hash(ix, iy, seed), b = hash(ix + 1, iy, seed);
        const c = hash(ix, iy + 1, seed), d = hash(ix + 1, iy + 1, seed);
        return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy;
      };
      const width = 192, height = 96;
      const surface = document.createElement('canvas');
      surface.width = width; surface.height = height;
      const g = surface.getContext('2d'), bitmap = g.createImageData(width, height);
      for (let y = 0; y < height; y++) {
        const v = y / (height - 1);
        for (let x = 0; x < width; x++) {
          const u = x / (width - 1);
          const n = noise(u * 6.4, v * 3.8, 5) * .55 + noise(u * 17, v * 8, 11) * .45;
          const ramp = v * v * (1.5 - .5 * v);
          const erase = clamp((n * .74 + ramp - .34) * 1.5, 0, 1);
          const i = (y * width + x) * 4;
          bitmap.data[i] = bitmap.data[i + 1] = bitmap.data[i + 2] = 255;
          bitmap.data[i + 3] = Math.round(erase * 255);
        }
      }
      g.putImageData(bitmap, 0, 0);
      this.dissolve = surface;
    }

    clear() {
      this.context.clearRect(0, 0, this.width, this.height);
    }

    draw(particles, emitter, flow) {
      this.clear();
      const g = this.context;
      this.strength = flow ? clamp((flow.speed - FAN_SPEED.low) / (FAN_SPEED.high - FAN_SPEED.low), 0, 1) : 0;
      const continuous = flow && this.volume.render(this.width, this.height, emitter, flow);
      if (continuous) g.drawImage(this.volume.canvas, 0, 0, this.width, this.height);
      if (flow && flow.profile.stream) {
        this.streams.draw(emitter, flow, this.strength);
        const blur = flow.profile.stream.blur || { veil: 15, line: 1.2 };
        g.save();
        // 雾体强模糊成连续体积，流线只轻微柔化，保留方向感。
        g.filter = `blur(${blur.veil}px)`;
        g.drawImage(this.streams.veil, 0, 0, this.width, this.height);
        g.filter = `blur(${blur.line}px)`;
        g.drawImage(this.streams.canvas, 0, 0, this.width, this.height);
        g.filter = 'none';
        g.restore();
      }
      // 稀疏微光：只有少量亮点，按远近分两遍绘制。
      for (const layer of [0, 1]) {
        for (const p of particles) {
          if (((p.layer >= .5) ? 1 : 0) !== layer) continue;
          const depth = clamp((p.y - emitter.y) / p.reach, 0, 1);
          const alpha = this.opacity(p, emitter);
          if (alpha < .004) continue;
          this.drawMark(p, depth, alpha);
        }
      }
      g.globalAlpha = 1;
      this.ensureDissolve();
      const end = Math.min(this.height * .22, this.height - 2);
      g.globalCompositeOperation = 'destination-out';
      g.drawImage(this.dissolve, 0, this.height - end, this.width, end);
      g.globalCompositeOperation = 'source-over';
    }

    opacity(p, emitter) {
      const depth = clamp((p.y - emitter.y) / p.reach, 0, 1);
      const inlet = 1 - Math.exp(-p.age * 5);
      const fade = Math.pow(1 - depth, p.profile.fade) * clamp((p.lifetime - p.age) / .8, 0, 1);
      const edge = clamp(Math.min(p.x, this.width - p.x) / 40, 0, 1);
      return p.alpha * inlet * fade * edge;
    }

    drawMark(p, depth, alpha) {
      const g = this.context;
      const size = p.size * (p.mode === 'dry' ? 1 - depth * .55 : 1);
      const shimmer = .30 + .70 * Math.pow(Math.max(0, Math.sin(p.phase + p.age * (1.7 + this.strength * 3))), 3);
      g.save();
      g.translate(p.x, p.y);
      g.rotate(p.phase + p.age * p.turn);
      g.globalAlpha = alpha * shimmer;
      const glow = g.createRadialGradient(0, 0, 0, 0, 0, size * 1.8);
      glow.addColorStop(0, `rgba(${p.profile.highlight},.85)`);
      glow.addColorStop(.30, `rgba(${p.profile.secondary},.45)`);
      glow.addColorStop(1, `rgba(${p.profile.primary},0)`);
      g.fillStyle = glow;
      g.fillRect(-size * 1.8, -size * 1.8, size * 3.6, size * 3.6);
      g.restore();
    }

    dispose() {
      this.clear();
      this.volume.dispose();
      this.streams.dispose();
      if (this.dissolve) { this.dissolve.width = this.dissolve.height = 0; this.dissolve = null; }
    }
  }
