# 贡献指南

感谢你愿意改进 AIRA。这个项目是 Windows 桌面应用，涉及 Python 后端、WebView2 前端、原生窗口/悬浮窗口与 PyInstaller 打包，请先阅读下面的约定。

## 开发环境

- Windows 10/11（64 位）
- Python 3.11+
- Node.js（可选，仅用于重新构建前端；没有 Node 时可用 `frontend/build.py`）
- Microsoft Edge WebView2 Runtime

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-desktop.txt -r requirements-dev.txt
```

## 运行与测试

```powershell
python desktop.py          # 以源码方式运行桌面程序
python -m pytest tests -q  # 运行自动化测试
```

提交前请确保测试全部通过。测试使用内存存储与模拟驱动，不会连接真实设备或发送红外指令。

## 修改界面

界面源码位于 `frontend/`，`index.html` 是构建产物，**不要直接编辑**。

```powershell
node frontend/build.cjs    # 有 Node
python frontend/build.py   # 没有 Node（与 Node 构建输出一致）
```

修改 `frontend/refactor-*.js`、`refactor-*.css`、`refactor-markup.html` 后重新构建，并检查主界面、定时面板与窄窗口布局。

## 打包

```powershell
python -m pip install -r requirements-build.txt
python build.py
```

产物位于 `dist/空调`。发布前请在干净目录解压安装包，确认 `空调.exe` 与 `_internal` 一起工作，并运行 `空调.exe --check` 自检。

## 提交约定

- 一个提交只做一件事，提交信息使用简洁的祈使句（例如 `fix: 设备忙时保留调温设置`、`feat: 定时面板`、`docs: 补充设备连接说明`）。
- 涉及界面的改动请附截图；涉及设备控制的改动请说明是否在真实设备上验证过。
- 不要在提交中包含 `.local/`、日志、Token、IP、设备 ID、个人路径或其他本机数据。
- 不要提交 `dist/`、`build/`、`.venv/`、`__pycache__/` 等生成物。

## Pull Request 自查

- [ ] 测试通过（`python -m pytest tests -q`）
- [ ] 前端已重新构建（如修改了 `frontend/`）
- [ ] 没有提交任何凭据或个人数据
- [ ] 行为变化已更新 `CHANGELOG.md` 与相关文档
- [ ] 真实设备相关行为已说明验证范围

## 设备与安全

- 控制逻辑遵循“先读、再写、写后重读确认；超时/丢包只补读，不重发控制”的原则。
- 本机接口只监听 `127.0.0.1`，新增接口需要沿用同源、请求头、JSON 与请求体大小校验。
- 修改凭据存储时请保持 Windows 当前用户的 DPAPI 加密方式。

## 许可证

提交代码即表示同意以 GPL-3.0 许可发布。
