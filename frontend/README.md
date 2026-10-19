# frontend

界面源码按固定顺序拼接成根目录的 `index.html`。**不要直接编辑 `index.html`**，它是由构建脚本生成的。

## 构建

```powershell
node frontend/build.cjs    # 需要 Node
python frontend/build.py   # 不需要 Node，输出与 Node 构建逐字节一致
```

## 源文件顺序

1. `refactor-config.js` — 常量、控制项、气流参数
2. `refactor-dial.js` — 温度圆环交互
3. `refactor-renderer.js` — 体积雾、流线、微光渲染
4. `refactor-engine.js` — 气流模拟
5. `device-bridge.js` — 合并/串行控制、定时接口、轮询
6. `refactor-timer.js` — 定时折叠面板
7. `refactor-controller.js` — 状态机与界面绑定

`refactor-head.html`、`refactor-markup.html`、`refactor-styles.css` 提供页面骨架与样式；构建时还会注入设置页入口与提示节点。

## 注意

- `index.html` 是发布与打包使用的产物，提交前请重新构建。
- 修改渲染或交互后，请检查主界面、定时面板、窄窗口（约 360×620 与 700×900）以及「减少动态效果」模式。
- 气流遵循 `frontend/refactor-config.js` 中的 `WIND_PROFILES`；截图与调参时可以使用 `?freeze=1` 冻结为静态帧。
