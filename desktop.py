"""空调桌面入口：独立窗口、单实例，以及随窗口关闭的本机服务。"""

import argparse
import ctypes
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend import __version__, application_root, asset_root, project_instance
from window_chrome import WindowChrome

ROOT = application_root()
LOCAL = ROOT / ".local"
TITLE = "空调"


def read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class SingleInstance:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateMutexW(None, False, "Local\\AirConditioner_" + project_instance(ROOT))
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.existing = ctypes.get_last_error() == 183

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def activate_existing() -> None:
    session=read_json(LOCAL / "session.json")
    owner = session.get("pid")
    if type(owner) is not int:
        return
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    saved_handle=session.get('window')
    if type(saved_handle) is int:
        task_pid=wintypes.DWORD()
        user.GetWindowThreadProcessId(saved_handle,ctypes.byref(task_pid))
        if task_pid.value==owner:
            user.ShowWindow(saved_handle,9)
            user.SetForegroundWindow(saved_handle)
            user.PostMessageW(saved_handle,WindowChrome.MESSAGE,8,0)
            return

    @callback_type
    def visit(handle, _):
        task_pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(task_pid))
        if task_pid.value == owner and user.IsWindowVisible(handle):
            user.ShowWindow(handle, 9)
            user.SetForegroundWindow(handle)
            user.PostMessageW(handle, WindowChrome.MESSAGE, 8, 0)
            return False
        return True

    user.EnumWindows(visit, 0)


class LocalServer:
    def __init__(self):
        import uvicorn
        from backend.app import create_app

        # 先占住端口再交给服务器；不复用其他目录的服务。
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        for port in range(8765, 8796):
            try:
                self.socket.bind(("127.0.0.1", port))
                break
            except OSError:
                continue
        else:
            self.socket.close()
            raise RuntimeError("本机端口暂时不可用，请关闭其他空调程序后重试。")
        self.socket.listen(128)
        self.address = f"http://127.0.0.1:{port}"
        self.app = create_app()
        self.server = uvicorn.Server(uvicorn.Config(
            self.app, host="127.0.0.1", port=port, access_log=False,
            proxy_headers=False, log_config=None, log_level="error",
            loop="asyncio", http="h11", ws="none", timeout_graceful_shutdown=5,
        ))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, name="local-http", daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return
            if not self.thread.is_alive():
                break
            time.sleep(.05)
        self.close()
        raise RuntimeError("本机服务启动失败，请重新打开程序。")

    def get(self, route: str) -> dict:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(self.address + route, timeout=3) as response:
            return json.load(response)

    def close(self) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=8)
        self.socket.close()


def window_size(screen) -> tuple[int, int]:
    saved = read_json(LOCAL / "window.json")
    width, height = saved.get("width", 920), saved.get("height", 540)
    if type(width) is not int or type(height) is not int:
        width, height = 920, 540
    return max(360, min(width, int(screen.width * .94))), max(320, min(height, int(screen.height * .9)))


def run_check(server: LocalServer, report: Path) -> None:
    deadline = time.monotonic() + 8
    status = server.get("/api/status")
    while status["configured"] and not status["connected"] and time.monotonic() < deadline:
        time.sleep(.2)
        status = server.get("/api/status")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    assets = {}
    for route in ("/", "/setup", "/setup.js", "/setup.css", "/desktop.js", "/desktop.css", "/floating.js", "/floating.css", "/favicon.ico", "/assets/inter.woff2"):
        with opener.open(server.address + route, timeout=3) as response:
            assets[route] = response.status == 200 and len(response.read()) > 0
    result = {"version": __version__, "health": server.get("/api/health"), "assets": assets,
              "configured": status["configured"], "connected": status["connected"], "noControlCommands": True}
    save_json(report, result)
    if not all(assets.values()):
        raise RuntimeError("程序资源不完整。")


def main() -> None:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--report", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOCAL / "app.log", maxBytes=512000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if os.name != "nt":
        raise RuntimeError("请在 Windows 中打开此程序。")
    if args.check:
        server = LocalServer()
        try:
            run_check(server, args.report or LOCAL / "check.json")
        finally:
            server.close()
        return

    instance = SingleInstance()
    if instance.existing:
        try:
            # 前一个窗口可能还在启动，稍候再激活。
            for _ in range(20):
                if read_json(LOCAL / "session.json").get("pid"):
                    break
                time.sleep(.1)
            activate_existing()
        finally:
            instance.close()
        return
    server = None
    try:
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Local.AirConditioner.Desktop")
        server = LocalServer()
        save_json(LOCAL / "session.json", {"pid": os.getpid(), "port": int(server.address.rsplit(":", 1)[1])})
        import webview

        os.environ.setdefault("WEBVIEW2_DEFAULT_BACKGROUND_COLOR", "00000000")
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        width, height = window_size(webview.screens[0])
        configured = server.get("/api/status").get("configured")
        chrome = WindowChrome(LOCAL / "appearance.json", server.address, service=server.app.state.device_service)
        window = webview.create_window(
            TITLE, server.address + ("/" if configured else "/setup"), width=width, height=height,
            min_size=(360, 320), resizable=True, text_select=False, zoomable=False,
            transparent=True, frameless=True, shadow=False, background_color="#000000", easy_drag=False, js_api=chrome,
        )
        window.events.before_show += chrome._install

        def remember_size():
            try:
                if chrome.window_state().get("presentation") == "standard":
                    save_json(LOCAL / "window.json", {"width": int(window.width), "height": int(window.height)})
            except (OSError, TypeError, ValueError):
                logging.warning("Window size could not be saved")

        window.events.closing += remember_size
        webview.start(gui="edgechromium", debug=False, icon=str(asset_root() / "assets" / "空调.ico"),
                      private_mode=True, storage_path=str(LOCAL / "webview"))
    finally:
        if server:
            server.close()
        if read_json(LOCAL / "session.json").get("pid") == os.getpid():
            (LOCAL / "session.json").unlink(missing_ok=True)
        instance.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        logging.exception("Desktop startup failed")
        if not ("--check" in sys.argv):
            ctypes.windll.user32.MessageBoxW(None, "空调程序暂时无法启动。\n请查看程序目录下的 .local/app.log。", TITLE, 0x10)
        sys.exit(1)
