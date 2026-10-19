"""标准窗口、贴边悬窗与温控浮球的原生布局和本机偏好。"""

import ctypes
import json
import logging
import time
from ctypes import wintypes
from pathlib import Path

MODES = ("standard", "compact", "bubble")


def fit_rectangle(rect, work, minimum=(1, 1)):
    """支持负坐标副屏，恢复保存的位置时不把窗口留在已拔掉的屏幕上。"""
    x, y, width, height = rect
    left, top, right, bottom = work
    width = min(max(minimum[0], width), right - left)
    height = min(max(minimum[1], height), bottom - top)
    return (max(left, min(x, right - width)), max(top, min(y, bottom - height)), width, height)


def peek_rectangle(width, height, scale, edge):
    """收起后仅保留温度签，其余位置不遮挡桌面或截获鼠标。"""
    peek_width, peek_height = (round(value * scale) for value in ((44, 36) if edge in ("left", "right") else (60, 28)))
    if edge in ("left", "right"):
        return (width - peek_width if edge == "left" else 0, (height - peek_height) // 2, peek_width, peek_height)
    return ((width - peek_width) // 2, height - peek_height if edge == "top" else 0, peek_width, peek_height)


def compact_main_rectangle(rect, work, scale):
    """首次升级将过高的主窗口收紧为横向构图，之后继续记忆用户尺寸。"""
    x, y, old_width, old_height = rect
    width = min(round(920 * scale), round((work[2] - work[0]) * .82))
    height = min(round(width * .58), round((work[3] - work[1]) * .82))
    minimum = (round(360 * scale), round(320 * scale))
    width, height = max(width, minimum[0]), max(height, minimum[1])
    return fit_rectangle((round(x + (old_width - width) / 2), round(y + (old_height - height) / 2), width, height), work, minimum)


class PresentationManager:
    def __init__(self, chrome, window, preferences_path, address):
        from System.Drawing import Point
        from System.Drawing import Region
        from System import IntPtr, Int64
        from System.Windows.Forms import ContextMenuStrip, FormWindowState, Timer, ToolStripMenuItem

        self.chrome, self.window, self.form = chrome, window, window.native
        self.user, self.handle = chrome._user, chrome._handle
        self.main_form,self.main_handle=self.form,self.handle
        self.Point, self.FormWindowState = Point, FormWindowState
        self.Region, self.IntPtr, self.Int64 = Region, IntPtr, Int64
        self.surface_region = None
        self.path, self.address = Path(preferences_path), address
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        self.saved = saved if isinstance(saved, dict) else {}
        self.floating_topmost = self.saved.get("floatingTopmost") is True
        # 每次启动都回到空调主界面，悬浮模式仅由本次明确选择进入。
        self.mode = 'standard'
        self.view, self.setup = "standard", False
        self.edge, self.hidden, self.dragging = None, False, False
        self.expanded_rect = None
        self.move_token = None
        self.last_inside = time.monotonic()
        self.base_style = self.user.GetWindowLongPtrW(self.handle, -16)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.gdi.CreateEllipticRgn.argtypes = [ctypes.c_int] * 4
        self.gdi.CreateEllipticRgn.restype = wintypes.HRGN
        self.gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        self.gdi.CreateRoundRectRgn.restype = wintypes.HRGN
        self.gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.timer = Timer()
        self.timer.Interval = 120
        self.timer.Tick += self._tick
        self.menu = ContextMenuStrip()
        self._menu_callbacks = []
        for label, action in (("空调主界面", 50), ("温控悬浮条", 51), ("温控悬浮球", 52), ("设置", 7), ("退出", 3)):
            item = ToolStripMenuItem(label)
            def clicked(sender, event, command=action):
                self.user.PostMessageW(self.main_handle, self.chrome.MESSAGE, command, 0)
            self._menu_callbacks.append(clicked)
            item.Click += clicked
            self.menu.Items.Add(item)
        self.chrome._presentations = self
        self.native_floating = getattr(chrome, '_service', None) is not None
        self.floating_controls = None
        self.floating = None
        first_layout = self.saved.get('mainLayoutRevision') != 1
        if first_layout:
            rectangle = self.saved.get('standard', self._rect())
            if (isinstance(rectangle, (list, tuple)) and len(rectangle) == 4
                    and all(type(v) is int for v in rectangle) and rectangle[2] > 0
                    and rectangle[3] > 0 and rectangle[2] / rectangle[3] < 1.35):
                self.saved['standard'] = list(compact_main_rectangle(rectangle, self._work(), self._scale()))
            self.saved['mainLayoutRevision'] = 1
        self._apply(self.mode)
        if first_layout:self._save()

    def _rect(self):
        rect = wintypes.RECT()
        self.user.GetWindowRect(self.handle, ctypes.byref(rect))
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def _work(self):
        from window_chrome import MonitorInfo
        monitor = self.user.MonitorFromWindow(self.handle, 2)
        info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
        if not self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (info.work.left, info.work.top, info.work.right, info.work.bottom)

    def _scale(self):
        return self.user.GetDpiForWindow(self.handle) / 96

    def _notify(self):
        try:
            if self.main_form.webview.CoreWebView2 is not None:
                self.main_form.webview.ExecuteScriptAsync("window.dispatchEvent(new Event('nativewindowchange'))")
        except Exception:
            logging.debug("Window presentation notification deferred")

    def _save(self):
        self.saved["presentation"] = self.mode
        self.saved["floatingTopmost"] = self.floating_topmost
        try:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.saved, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            logging.warning("Window presentation could not be saved")

    def _remember(self):
        if self.setup: return
        if self.view == "bubble":
            self.saved["bubble"] = list(self._rect())
        elif self.view == "compact" and self.mode == "compact":
            self.saved["compact"] = list(self.expanded_rect if self.hidden else self._rect())
        elif self.view == "standard" and self.form.WindowState != self.FormWindowState.Minimized:
            rect = self.form.RestoreBounds
            self.saved["standard"] = [rect.X, rect.Y, rect.Width, rect.Height] if self.user.IsZoomed(self.handle) else list(self._rect())

    def _saved_rect(self, name, logical_size):
        saved = self.saved.get(name)
        if isinstance(saved, list) and len(saved) == 4 and all(type(v) is int and abs(v) < 100000 for v in saved):
            return tuple(saved)
        if name == "standard": return self._rect()
        scale = self._scale()
        left, top, right, bottom = self._work()
        width, height = (round(value * scale) for value in logical_size)
        return ((left + right - width) // 2, (top + bottom - height) // 2, width, height)

    def _set_rect(self, rect, view):
        scale = self._scale()
        minimum = (84, 84) if view == "bubble" else (324, 64) if view == "compact" else (360, 320)
        if not getattr(self, 'floating', None) and view in ('bubble','compact'):
            minimum = (72,72) if view=='bubble' else (312,52)
        if self.user.IsZoomed(self.handle) or self.user.IsIconic(self.handle): self.user.ShowWindow(self.handle, 9)
        style = self.user.GetWindowLongPtrW(self.handle, -16)
        style = (style & ~(0x00C00000 | 0x00050000)) | (self.base_style & 0x00050000)
        if view != "standard": style &= ~0x00010000  # 悬浮模式不参与系统自动最大化贴靠。
        if view in ("bubble", "compact"): style &= ~0x00040000
        self.user.SetWindowLongPtrW(self.handle, -16, style)
        self._clear_region()
        rect = fit_rectangle(rect, self._work(), tuple(round(value * scale) for value in minimum))
        self.user.SetWindowPos(self.handle, -1 if self._is_topmost(view) else -2, *rect, 0x0030)
        self._set_region(view, rect[2], rect[3])
        return rect

    def _set_region(self, view, width, height, peek=False):
        if getattr(self, 'floating', None):return
        region = None
        if view == "bubble":
            region = self.gdi.CreateEllipticRgn(0, 0, width + 1, height + 1)
        elif view == "compact":
            x, y, width, height = peek_rectangle(width, height, self._scale(), self.edge) if peek else (0, 0, width, height)
            radius = min(width, height)
            region = self.gdi.CreateRoundRectRgn(x, y, x + width + 1, y + height + 1, radius, radius)
        if region:
            # 交给 WinForms 持有；直接 SetWindowRgn 会在后续样式／布局刷新时被重置。
            try:
                managed = self.Region.FromHrgn(self.IntPtr(self.Int64(ctypes.c_ssize_t(region).value)))
            finally:
                self.gdi.DeleteObject(region)
            previous = self.surface_region
            self.form.Region = managed
            self.surface_region = managed
            if previous is not None: previous.Dispose()

    def _clear_region(self):
        self.form.Region = None
        if self.surface_region is not None:
            self.surface_region.Dispose()
            self.surface_region = None

    def _apply(self, view, rect=None):
        previous = self.view
        floating = getattr(self, 'floating', None)
        native = getattr(self,'native_floating',False)
        if native:
            if view in ('compact','bubble'):
                if floating is not None:
                    self.form,self.handle=self.main_form,self.main_handle
                    floating.close()
                from floating_surface import FloatingSurface
                floating=self.floating=FloatingSurface(self,self.chrome._service)
                self.form,self.handle=floating.form,floating.handle
                self.main_form.Hide()
            else:
                self.form,self.handle=self.main_form,self.main_handle
                self.floating=None
                if floating is not None:floating.close()
                floating=None
        self.view = view
        self.edge, self.hidden = None, False
        self.dragging=False
        self.expanded_rect = None
        self.last_inside = time.monotonic()
        compact, bubble = ((324,64),(84,84)) if floating else ((312,52),(72,72))
        defaults = {"standard": (1120, 740), "compact": compact, "bubble": bubble, "settings": (480, 760)}
        if rect is None: rect = self._saved_rect(view, defaults[view])
        if view == "bubble":
            diameter = round(bubble[0] * self._scale())
            rect = (*rect[:2], diameter, diameter)
        elif view == "compact":
            rect = (*rect[:2], *(round(v*self._scale()) for v in compact))
        self.chrome._set_surface(view)
        self._set_rect(rect, view)
        if view == "compact": self.timer.Start()
        else: self.timer.Stop()
        if view == "compact" and self.mode == "compact": self.drag_end()
        if floating and view in ('compact','bubble'):floating.present(previous)
        elif native:self.main_form.Show();self.main_form.Activate()
        self._notify()

    def _change_mode(self, mode):
        if mode not in MODES: return
        position = self._rect() if mode == self.view and self.view in ('bubble','compact') and not self.setup else None
        self._remember()
        self.mode, self.setup = mode, False
        self._apply(mode, position)
        self._save()
        self._navigate("/")

    def _is_topmost(self, view=None):
        return (view or self.view) in ("compact", "bubble") and self.floating_topmost

    def _set_floating_topmost(self, enabled):
        self.floating_topmost = enabled
        self.user.SetWindowPos(self.handle, -1 if self._is_topmost() else -2, 0, 0, 0, 0, 0x0013)
        self._save()
        self._notify()

    def _navigate(self, path):
        core = self.main_form.webview.CoreWebView2
        if core is not None: core.Navigate(self.address + path)

    def page_ready(self, is_setup):
        if is_setup == self.setup:
            self._notify()
            return
        self._remember()
        self.setup = is_setup
        if is_setup:
            self._apply("settings")
        else:
            self._apply(self.mode)

    def handle_action(self, action):
        if action in (50, 51, 52): self._change_mode(MODES[action - 50])
        elif action in (80, 81): self._set_floating_topmost(action == 81)
        elif action in (5,18) and self.view in ('compact','bubble') and not self.setup:
            self._change_mode('standard')
        elif action == 6:
            self.user.PostMessageW(self.main_handle, 0x0010, 0, 0)
        elif action == 7:
            self._navigate("/setup")
        elif action == 8:
            if self.view in ('bubble','compact'):self._change_mode('standard')
        elif action == 9:
            cursor = wintypes.POINT()
            self.user.GetCursorPos(ctypes.byref(cursor))
            self.menu.Show(self.Point(cursor.x, cursor.y))
        elif action in (60, 61): self.page_ready(action == 61)
        else: return False
        return True

    def drag_start(self):
        if self.hidden: self._reveal()
        self.dragging, self.edge = True, None

    def move_window(self, token, dx, dy, finished):
        if token != self.move_token:
            self.move_token = token
            if self.user.IsZoomed(self.handle): self.user.ShowWindow(self.handle, 9)
            self.drag_start()
            self.move_origin, self.move_scale = self._rect(), self._scale()
        x, y, width, height = self.move_origin
        self.user.SetWindowPos(self.handle, None, x + round(dx * self.move_scale), y + round(dy * self.move_scale), width, height, 0x0014)
        if finished: self.drag_end()

    def drag_end(self):
        self.dragging = False
        if self.view == "compact" and not self.setup:
            x, y, width, height = self._rect()
            if self.mode == "compact":
                left, top, right, bottom = self._work()
                snap = round(26 * self._scale())
                distances = {"left": max(0, x - left), "right": max(0, right - x - width), "top": max(0, y - top), "bottom": max(0, bottom - y - height)}
                edge = min(distances, key=distances.get)
                self.edge = edge if distances[edge] <= snap else None
                if self.edge == "left": x = left
                elif self.edge == "right": x = right - width
                elif self.edge == "top": y = top
                elif self.edge == "bottom": y = bottom - height
                self.expanded_rect = (x, y, width, height)
                if self.edge: self.user.SetWindowPos(self.handle, None, x, y, width, height, 0x0014)
        self.last_inside = time.monotonic()
        self._remember()
        self._save()
        self._notify()

    def _reveal(self):
        if not self.expanded_rect: return
        self.user.SetWindowPos(self.handle, None, *self.expanded_rect, 0x0014)
        self._set_region("compact", self.expanded_rect[2], self.expanded_rect[3])
        self.hidden = False
        self.last_inside = time.monotonic()
        self._notify()

    def _hide(self):
        x, y, width, height = self.expanded_rect
        left, top, right, bottom = self._work()
        tab = round((44 if self.edge in ("left", "right") else 28) * self._scale())
        if self.edge == "left": x = left - width + tab
        elif self.edge == "right": x = right - tab
        elif self.edge == "top": y = top - height + tab
        elif self.edge == "bottom": y = bottom - tab
        self._set_region("compact", width, height, peek=True)
        self.user.SetWindowPos(self.handle, None, x, y, width, height, 0x0014)
        self.hidden = True
        self._notify()

    def _tick(self, sender, event):
        try:
            if self.dragging or self.setup or self.menu.Visible or self.user.IsIconic(self.handle): return
            if self.mode != "compact" or not self.edge or not self.expanded_rect: return
            point = wintypes.POINT()
            self.user.GetCursorPos(ctypes.byref(point))
            x, y, width, height = self._rect()
            if self.hidden:
                px, py, width, height = peek_rectangle(width, height, self._scale(), self.edge)
                x, y = x + px, y + py
            inside = x <= point.x < x + width and y <= point.y < y + height
            if inside:
                self.last_inside = time.monotonic()
                if self.hidden: self._reveal()
            elif not self.hidden and time.monotonic() - self.last_inside > .75:
                self._hide()
        except Exception:
            self.timer.Stop()
            logging.exception("Floating window timer stopped")

    def snapshot(self):
        return {"presentation": self.mode, "view": self.view,
                "edge": self.edge, "edgeHidden": self.hidden, "topmost": self._is_topmost(),
                "floatingTopmost": self.floating_topmost, "nativeFloating":getattr(self,'native_floating',False)}

    def close(self):
        self.timer.Stop()
        if not self.form.IsDisposed:self._remember()
        self._save()
        if getattr(self,'floating',None):self.floating.close()
        if getattr(self,'floating_controls',None):self.floating_controls.close()
        self.timer.Dispose()
        self.menu.Dispose()
        if self.surface_region is not None:
            self.surface_region.Dispose()
            self.surface_region = None
