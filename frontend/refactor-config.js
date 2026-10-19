  const TEMPERATURE = Object.freeze({ min: 16, max: 32 });
  const CLIMATE = Object.freeze({ temperature: 27, humidity: 58 });
  const DIAL = Object.freeze({ center: 180, radius: 138, start: 135, end: 405, deadZone: .26 });
  const SIMULATION = Object.freeze({ step: 1 / 60, maxFrameDelta: .05, maxParticles: 180, maxDpr: 3, seed: 84619, staticSteps: 240 });
  const FAN_SPEED = Object.freeze({ low: 86, medium: 185, high: 360 });
  const DIRECTION_PITCH = Object.freeze({ up: 16, mid: 48, down: 78, fixed: 78 });
  const SWING = Object.freeze({ center: 47, amplitude: 39, period: 5.6 });
  const KEY_STEPS = Object.freeze({ ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 2, PageDown: -2 });
  const DEFAULT_STATE = Object.freeze({ power: true, temp: 26, mode: 'cool', speed: 'auto', direction: 'down' });
  const CONTROLS = {
    mode: {
      id: 'modeControl', order: ['cool', 'heat', 'dry', 'fan', 'auto'],
      labels: { cool: '制冷', heat: '制热', dry: '除湿', fan: '送风', auto: '自动' }
    },
    speed: {
      id: 'speedControl', order: ['auto', 'low', 'medium', 'high'],
      labels: { auto: '自动风速', low: '低风速', medium: '中风速', high: '高风速' }
    },
    direction: {
      id: 'directionControl', order: ['up', 'mid', 'down', 'swing'],
      labels: { up: '平吹', mid: '斜下', down: '下吹', swing: '上下扫风', fixed: '停止扫风' }
    }
  };
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const roundCoordinate = value => (Math.round(value * 100) / 100).toString();
  const requiredElement = id => {
    const element = document.getElementById(id);
    if (!element) throw new Error('Missing element: ' + id);
    return element;
  };

  // stream 描述气流主体：count 条流线，width 中段最大宽度，alpha 主透明度，
  // curl 摆动幅度，length 相对风程，spread 下游张开程度。
  // markAlpha/markSize 控制稀疏微光；制冷不画微光，只保留连续雾带与流线。
  const WIND_PROFILES = {
    cool: {
      name:'连续冷雾 · 柔和雾带', primary:'12,133,218', secondary:'72,195,239', highlight:'242,254,255',
      stream:{ veil:{ count:12, width:178, alpha:.100 }, lines:{ count:9, width:8, alpha:.190, color:'242,254,255' }, blur:{ veil:12, line:2.2 }, curl:1.52, length:.98, spread:.13 },
      markAlpha:0, markSize:[0,0], emission:1, turbulence:1.02, spread:.9,
      reach:1.10, fade:.80, sway:1
    },
    heat: {
      name:'琥珀暖雾 · 舒卷热流', primary:'226,147,78', secondary:'249,204,143', highlight:'255,247,221',
      stream:{ veil:{ count:11, width:172, alpha:.112 }, lines:{ count:8, width:8, alpha:.195, color:'255,247,221' }, blur:{ veil:12, line:2.2 }, curl:1.82, length:1.0, spread:.17 },
      markAlpha:.45, markSize:[2.2,2.6], emission:1.2, turbulence:1.85, spread:1.3,
      reach:1.02, fade:.80, sway:1.35
    },
    dry: {
      name:'淡紫水汽 · 渐隐微珠', primary:'126,132,197', secondary:'186,184,227', highlight:'249,247,255',
      stream:{ veil:{ count:10, width:150, alpha:.098 }, lines:{ count:7, width:6, alpha:.175, color:'249,247,255' }, blur:{ veil:13, line:2.4 }, curl:1.02, length:.90, spread:.10 },
      markAlpha:.50, markSize:[2.0,2.2], emission:1.6, turbulence:.65, spread:.7,
      reach:.94, fade:.80, sway:.75
    },
    fan: {
      name:'青绿清风 · 轻盈流线', primary:'82,169,145', secondary:'161,215,188', highlight:'245,255,250',
      stream:{ veil:{ count:11, width:155, alpha:.090 }, lines:{ count:10, width:6, alpha:.195, color:'245,255,250' }, blur:{ veil:11, line:2.1 }, curl:1.52, length:1.0, spread:.12 },
      markAlpha:.40, markSize:[1.8,2.0], emission:1.3, turbulence:1.25, spread:1.18,
      reach:1.06, fade:.82, sway:1.15
    },
    auto: {
      name:'双色柔雾 · 舒适气流', primary:'89,171,177', secondary:'146,174,223', highlight:'243,255,252',
      stream:{ veil:{ count:11, width:162, alpha:.098 }, lines:{ count:9, width:7, alpha:.190, color:'243,255,252' }, blur:{ veil:12, line:2.2 }, curl:1.40, length:1.0, spread:.12 },
      markAlpha:.45, markSize:[2.0,2.2], emission:1.3, turbulence:1.15, spread:1,
      reach:1.04, fade:.82, sway:1.05
    }
  };
