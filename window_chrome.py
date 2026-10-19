"""本程序的原生毛玻璃与无标题栏窗口，不改变整窗透明度。"""

import ctypes
import logging
import math
import threading
import json
from ctypes import wintypes
from pathlib import Path


class Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


class MinMaxInfo(ctypes.Structure):
    _fields_ = [(name, wintypes.POINT) for name in ("reserved", "max_size", "max_position", "min_track", "max_track")]


class StyleInfo(ctypes.Structure):
    _fields_ = [("old", wintypes.DWORD), ("new", wintypes.DWORD)]


class WindowChrome:
    """所有窗口动作经本窗口的消息队列执行，网页只接触受限的窗口接口。"""

    MESSAGE = 0x8000 + 37
    ACTIONS = {"minimize": 1, "maximize": 2, "close": 3, "drag": 4,
               "open-main": 5, "dismiss": 6, "settings": 7, "reveal": 8, "menu": 9,
               "resize-left": 10, "resize-right": 11, "resize-top": 12,
               "resize-top-left": 13, "resize-top-right": 14, "resize-bottom": 15,
               "resize-bottom-left": 16, "resize-bottom-right": 17, "home": 18}

    def __init__(self, preferences_path=None, address="", service=None):
        self._service = service
        self._handle = None
        self._callback = None
        self._glass = False
        self._presentations = None
        self._tray = self._tray_icon = None
        self._preferences_path = preferences_path or Path(".local") / "appearance.json"
        self._address = address
        self._move_lock = threading.Lock()
        self._move_packet = None
        self._move_sequence = self._applied_move = 0

    def _install(self, window):
        # before_show 在 WinForms 窗口线程运行，子类化不能从工作线程安装。
        from System.Drawing import Color

        self._form = window.native
        self._handle = int(self._form.Handle.ToInt64())
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self._controls = ctypes.WinDLL("comctl32", use_last_error=True)
        self._user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._user.SendMessageW.argtypes = self._user.PostMessageW.argtypes
        self._user.SendMessageW.restype = wintypes.LPARAM
        self._user.IsZoomed.argtypes = [wintypes.HWND]
        self._user.IsIconic.argtypes = [wintypes.HWND]
        self._user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self._user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user.GetDpiForWindow.argtypes = [wintypes.HWND]
        self._user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self._user.MonitorFromWindow.restype = wintypes.HMONITOR
        self._user.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        self._user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self._user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self._user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self._dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self._dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        callback_type = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
        self._controls.SetWindowSubclass.argtypes = [wintypes.HWND, callback_type, ctypes.c_size_t, ctypes.c_size_t]
        self._controls.DefSubclassProc.argtypes = self._user.PostMessageW.argtypes
        self._controls.DefSubclassProc.restype = wintypes.LPARAM
        self._controls.RemoveWindowSubclass.argtypes = [wintypes.HWND, callback_type, ctypes.c_size_t]
        self._callback = callback_type(self._message)
        if not self._controls.SetWindowSubclass(self._handle, self._callback, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        style = self._user.GetWindowLongPtrW(self._handle, -16)
        self._user.SetWindowLongPtrW(self._handle, -16, (style & ~0x00C00000) | 0x000F0000)

        # 黑色 GDI 表面交给 DWM 合成；WebView2 保持逐像素透明，机身与粒子仍完全清晰。
        self._form.BackColor = Color.Black
        self._form.webview.DefaultBackgroundColor = Color.Transparent
        self._set_attribute(20, 0)  # 浅色玻璃，不受系统深色标题栏影响。
        self._set_attribute(33, 2)  # 系统圆角。
        self._set_attribute(34, 0xFFFFFFFE)  # 不绘制与界面分离的系统边框。
        extended = self._dwm.DwmExtendFrameIntoClientArea(self._handle, ctypes.byref(Margins(-1, -1, -1, -1))) == 0
        self._glass = extended and self._set_attribute(38, 3)  # Desktop Acrylic，透出窗口后面的内容。
        if not self._glass:
            # 不支持系统毛玻璃时提供可读的浅色窗口，绝不降低所有控件的不透明度。
            self._form.BackColor = Color.FromArgb(239, 243, 245)
            logging.warning("Desktop Acrylic unavailable on this Windows version")
        self._user.SetWindowPos(self._handle, None, 0, 0, 0, 0, 0x0027)  # FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER
        from presentations import PresentationManager
        self._presentations = PresentationManager(self, window, self._preferences_path, self._address)
        self._install_tray()
        def navigation_visibility(sender,event):
            if self._presentations.view in ('compact','bubble') and self._presentations.floating:
                self._form.Hide()
        self._navigation_visibility=navigation_visibility
        self._form.webview.NavigationStarting+=navigation_visibility
        # 单实例唤回消息始终发给隐藏的主窗口，避免被提示浮层截获。
        session_path=Path(self._preferences_path).parent/'session.json'
        try:
            session=json.loads(session_path.read_text(encoding='utf-8'))
            if isinstance(session,dict) and session.get('pid'):
                temporary=session_path.with_suffix('.tmp')
                temporary.write_text(json.dumps({**session,'window':self._handle}),encoding='utf-8')
                temporary.replace(session_path)
        except (OSError,ValueError):logging.debug('Window activation handle could not be saved')

    def _set_attribute(self, attribute, value):
        data = wintypes.DWORD(value)
        return self._dwm.DwmSetWindowAttribute(self._handle, attribute, ctypes.byref(data), ctypes.sizeof(data)) == 0

    def _install_tray(self):
        from System.Drawing import Icon
        from System.Windows.Forms import NotifyIcon, MouseButtons
        from backend import asset_root

        self._tray_icon = Icon(str(asset_root() / 'assets' / '空调.ico'))
        self._tray = NotifyIcon()
        self._tray.Icon = self._tray_icon
        self._tray.Text = '空调'
        self._tray.ContextMenuStrip = self._presentations.menu
        def clicked(sender, event):
            if event.Button == MouseButtons.Left:
                self.set_presentation('standard')
        self._tray_clicked = clicked
        self._tray.MouseClick += clicked
        self._tray.Visible = True

    def _close_tray(self):
        if self._tray is not None:
            self._tray.Visible = False
            self._tray.ContextMenuStrip = None
            self._tray.Dispose()
            self._tray = None
        if self._tray_icon is not None:
            self._tray_icon.Dispose()
            self._tray_icon = None

    def _set_surface(self, view):
        self._set_attribute(38, 3 if view in ("standard", "settings") else 1)
        self._set_attribute(33, 2 if view in ("standard", "settings") else 1)

    def _message(self, handle, message, wparam, lparam, subclass, reference):
        try:
            if message == 0x007C and ctypes.c_int(wparam).value == -16:
                style = ctypes.cast(lparam, ctypes.POINTER(StyleInfo)).contents
                style.new &= ~0x00C00000  # WinForms 更新内部状态时同样保持无标题栏。
            if message == 0x0083 and wparam:  # NCCALCSIZE：保留系统拖动/缩放样式，移除可见标题栏。
                return 0
            if message == 0x0084:  # NCHITTEST：只把随 DPI 缩放的窄边缘交给系统调整大小。
                if not self._user.IsZoomed(handle) and not (self._presentations and self._presentations.view in ("bubble", "compact")):
                    rect = wintypes.RECT()
                    self._user.GetWindowRect(handle, ctypes.byref(rect))
                    edge = max(4, round(6 * self._user.GetDpiForWindow(handle) / 96))
                    x, y = ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value
                    left, right = x < rect.left + edge, x >= rect.right - edge
                    top, bottom = y < rect.top + edge, y >= rect.bottom - edge
                    if top: return 13 if left else 14 if right else 12
                    if bottom: return 16 if left else 17 if right else 15
                    if left: return 10
                    if right: return 11
                return 1
            if message == 0x0024:  # GETMINMAXINFO：最大化严格限制在当前屏幕工作区。
                result = self._controls.DefSubclassProc(handle, message, wparam, lparam)
                monitor = self._user.MonitorFromWindow(handle, 2)
                info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
                if monitor and self._user.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    bounds = ctypes.cast(lparam, ctypes.POINTER(MinMaxInfo)).contents
                    bounds.max_position.x = info.work.left - info.monitor.left
                    bounds.max_position.y = info.work.top - info.monitor.top
                    bounds.max_size.x = info.work.right - info.work.left
                    bounds.max_size.y = info.work.bottom - info.work.top
                    view = self._presentations.view if self._presentations else "standard"
                    minimum = ((84, 84) if view == "bubble" else (324, 64)) if self._service is not None and view in ("bubble", "compact") else (72, 72) if view == "bubble" else (312, 52) if view == "compact" else (360, 320)
                    scale = self._user.GetDpiForWindow(handle) / 96
                    bounds.min_track.x, bounds.min_track.y = (round(value * scale) for value in minimum)
                    if view == "bubble":
                        bounds.max_track.x, bounds.max_track.y = bounds.min_track.x, bounds.min_track.y
                return result
            if message == self.MESSAGE:
                if wparam == 70 and self._presentations:
                    with self._move_lock:
                        packet = self._move_packet
                    if packet and packet[-1] > self._applied_move:
                        self._applied_move = packet[-1]
                        self._presentations.move_window(*packet[:-1])
                    return 0
                if self._presentations and self._presentations.handle_action(wparam):
                    return 0
                if wparam == 1:
                    self._user.PostMessageW(handle, 0x0112, 0xF020, 0)
                elif wparam == 2:
                    self._user.PostMessageW(handle, 0x0112, 0xF120 if self._user.IsZoomed(handle) else 0xF030, 0)
                elif wparam == 3:
                    self._user.PostMessageW(handle, 0x0010, 0, 0)
                elif wparam == 4 or 10 <= wparam <= 17:
                    if self._presentations: self._presentations.drag_start()
                    self._user.ReleaseCapture()
                    point = wintypes.POINT()
                    self._user.GetCursorPos(ctypes.byref(point))
                    position = ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)
                    self._user.SendMessageW(handle, 0x00A1, 2 if wparam == 4 else wparam, position)
                    if self._presentations and self._presentations.dragging: self._presentations.drag_end()
                return 0
            if message == 0x0231 and self._presentations:
                self._presentations.drag_start()
            elif message == 0x0232 and self._presentations:
                self._presentations.drag_end()
            if message == 0x0082:  # NCDESTROY：先卸载回调，避免销毁后悬挂引用。
                self._close_tray()
                if self._presentations: self._presentations.close()
                self._controls.RemoveWindowSubclass(handle, self._callback, 1)
                self._handle = None
        except Exception:
            logging.exception("Native window message failed")
        return self._controls.DefSubclassProc(handle, message, wparam, lparam)

    def window_action(self, action):
        if self._handle and action in self.ACTIONS:
            self._user.PostMessageW(self._handle, self.MESSAGE, self.ACTIONS[action], 0)
        return None

    def window_state(self):
        return {"maximized": bool(self._handle and self._user.IsZoomed(self._handle)), "glass": self._glass,
                "tray": bool(self._tray is not None and self._tray.Visible),
                **(self._presentations.snapshot() if self._presentations else {"presentation": "standard", "view": "standard"})}

    def set_presentation(self, mode):
        if self._handle and mode in ("standard", "compact", "bubble"):
            self._user.PostMessageW(self._handle, self.MESSAGE, 50 + ("standard", "compact", "bubble").index(mode), 0)

    def page_ready(self, is_settings):
        if self._handle and type(is_settings) is bool:
            self._user.PostMessageW(self._handle, self.MESSAGE, 61 if is_settings else 60, 0)

    def set_floating_topmost(self, enabled):
        if self._handle and type(enabled) is bool:
            self._user.PostMessageW(self._handle, self.MESSAGE, 81 if enabled else 80, 0)

    def drag_window(self, token, dx, dy, finished, sequence):
        if not self._handle or type(finished) is not bool: return
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in (token, dx, dy, sequence)): return
        if abs(dx) > 100000 or abs(dy) > 100000: return
        with self._move_lock:
            if sequence <= self._move_sequence: return
            self._move_sequence = sequence
            self._move_packet = (token, dx, dy, finished, sequence)
        self._user.PostMessageW(self._handle, self.MESSAGE, 70, 0)
