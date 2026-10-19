const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const folder = __dirname;
const read = name => fs.readFileSync(path.join(folder, name), 'utf8').trimEnd();
const sources = ['refactor-config.js', 'refactor-dial.js', 'refactor-renderer.js', 'refactor-engine.js', 'device-bridge.js', 'refactor-timer.js', 'refactor-controller.js'];
const script = `(() => {\n  'use strict';\n\n${sources.map(read).join('\n\n')}\n})();`;
new vm.Script(script, { filename: 'index.html' });
let markup = read('refactor-markup.html');
markup = markup.replace('</defs>', '  <symbol id="icon-direction-fixed" viewBox="0 0 24 24"><path d="M8 6v12M16 6v12"/></symbol>\n</defs>');
markup = markup.replace('</svg>27°</span>', '</svg><data id="roomTemperature" value="27">27°</data></span>')
  .replace('</svg>58%</span>', '</svg><data id="roomHumidity" value="58">58%</data></span>');
markup += `\n<a class="device-settings" id="deviceSettings" href="/setup" aria-label="空调设置" title="空调设置" hidden><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2.5" y="4" width="19" height="11" rx="3"/><path d="M5 11.5h14M6 15v1.5m6-1.5v3m6-3v1.5M17 7h1"/></svg></a>\n<a class="connection-note" id="deviceConnection" href="/setup" hidden>连接空调</a>\n<div class="command-message" id="deviceMessage" role="status" aria-live="polite" hidden></div>`;
const extraCss = `
[hidden]{display:none!important}
button:disabled{cursor:default;opacity:.45}
.device-settings{position:fixed;right:clamp(12px,2vw,27px);bottom:clamp(10px,2vh,23px);width:30px;height:30px;color:#668c9e;display:grid;place-items:center;border-radius:50%;z-index:20}
.device-settings:hover{color:var(--accent);background:#fff8}
.device-settings svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.45;stroke-linecap:round}
.device-settings circle{fill:#f1f5f7}
.connection-note{position:fixed;left:clamp(14px,2vw,29px);bottom:clamp(15px,2vh,30px);color:#819ca9;font-size:11px;text-decoration:none}
.connection-note:hover{color:var(--accent)}
.command-message{position:fixed;top:24px;left:50%;transform:translateX(-50%);max-width:calc(100% - 40px);padding:10px 16px;border:1px solid #fff;background:#fffc;border-radius:18px;color:#7e949f;font-size:12px;line-height:1.5;box-shadow:0 7px 26px -16px #5c7d8c}
`;
const html = `${read('refactor-head.html')}\n<style>\n${read('refactor-styles.css')}\n${extraCss}</style>\n</head>\n<body class="mode-cool">\n${markup}\n<script>\n${script}\n</script>\n</body>\n</html>\n`;
fs.writeFileSync(path.join(__dirname, '../index.html'), html);
console.log('Built integrated frontend: '+Buffer.byteLength(html)+' bytes');
