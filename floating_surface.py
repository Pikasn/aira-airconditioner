"""原生逐像素透明悬浮层。网页继续服务标准窗口，悬浮轮廓不再硬裁剪。"""
import ctypes
import logging
import math
import time
from ctypes import wintypes as W

from floating_controls import FloatingControls
from floating_graphics import FloatingRenderer, BUTTONS, PAD


class Blend(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ubyte) for name in ('operation','flags','alpha','format')]


class BitmapInfo(ctypes.Structure):
    _fields_ = [('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),
                ('bits',W.WORD),('compression',W.DWORD),('image',W.DWORD),
                ('x',W.LONG),('y',W.LONG),('colors',W.DWORD),('important',W.DWORD)]


class AlphaPresenter:
    def __init__(self, handle):
        self.handle = handle
        self.user, self.gdi = ctypes.WinDLL('user32',use_last_error=True), ctypes.WinDLL('gdi32',use_last_error=True)
        self.gdi.CreateCompatibleDC.argtypes=[W.HDC];self.gdi.CreateCompatibleDC.restype=W.HDC
        self.gdi.CreateDIBSection.argtypes=[W.HDC,ctypes.POINTER(BitmapInfo),W.UINT,ctypes.POINTER(ctypes.c_void_p),W.HANDLE,W.DWORD]
        self.gdi.CreateDIBSection.restype=W.HBITMAP
        self.gdi.SelectObject.argtypes=[W.HDC,W.HGDIOBJ];self.gdi.SelectObject.restype=W.HGDIOBJ
        self.gdi.DeleteObject.argtypes=[W.HGDIOBJ];self.gdi.DeleteDC.argtypes=[W.HDC]
        self.user.UpdateLayeredWindow.argtypes=[W.HWND,W.HDC,ctypes.POINTER(W.POINT),ctypes.POINTER(W.SIZE),W.HDC,ctypes.POINTER(W.POINT),W.DWORD,ctypes.POINTER(Blend),W.DWORD]
        self.dc=self.gdi.CreateCompatibleDC(None)
        self.bitmap=self.original=None
        self.size=None

    def draw(self, bitmap, position):
        from System.Drawing import Rectangle
        from System.Drawing.Imaging import ImageLockMode, PixelFormat
        size=(bitmap.Width,bitmap.Height)
        if size!=self.size:
            self._release_bitmap()
            self.bits=ctypes.c_void_p()
            info=BitmapInfo(size=ctypes.sizeof(BitmapInfo),width=size[0],height=-size[1],planes=1,bits=32)
            self.bitmap=self.gdi.CreateDIBSection(self.dc,ctypes.byref(info),0,ctypes.byref(self.bits),None,0)
            if not self.bitmap: raise ctypes.WinError(ctypes.get_last_error())
            self.original=self.gdi.SelectObject(self.dc,self.bitmap)
            self.size=size
        locked=bitmap.LockBits(Rectangle(0,0,*size),ImageLockMode.ReadOnly,PixelFormat.Format32bppPArgb)
        try:
            for row in range(size[1]):
                ctypes.memmove(self.bits.value+row*size[0]*4,locked.Scan0.ToInt64()+row*locked.Stride,size[0]*4)
        finally: bitmap.UnlockBits(locked)
        destination,source,dimensions=W.POINT(*position),W.POINT(0,0),W.SIZE(*size)
        if not self.user.UpdateLayeredWindow(self.handle,None,ctypes.byref(destination),ctypes.byref(dimensions),self.dc,ctypes.byref(source),0,ctypes.byref(Blend(0,0,255,1)),2):
            raise ctypes.WinError(ctypes.get_last_error())

    def _release_bitmap(self):
        if self.bitmap:
            self.gdi.SelectObject(self.dc,self.original)
            self.gdi.DeleteObject(self.bitmap)
            self.bitmap=None

    def close(self):
        self._release_bitmap()
        if self.dc:self.gdi.DeleteDC(self.dc);self.dc=None


class FloatingSurface:
    def __init__(self, manager, service):
        from System.Windows.Forms import Timer, Form, FormBorderStyle, FormStartPosition, Cursors
        self.cursors=Cursors
        self.manager=manager;self.form=Form()
        self.form.Text='空调';self.form.FormBorderStyle=getattr(FormBorderStyle,'None')
        self.form.StartPosition=FormStartPosition.Manual
        self.form.ShowInTaskbar=True
        self.form.Icon=manager.form.Icon
        self.handle=int(self.form.Handle.ToInt64())
        style=manager.user.GetWindowLongPtrW(self.handle,-20)
        manager.user.SetWindowLongPtrW(self.handle,-20,style|0x80000)
        if manager.floating_controls is None:manager.floating_controls=FloatingControls(service)
        self.controls=manager.floating_controls;self.renderer=FloatingRenderer()
        self.presenter=AlphaPresenter(self.handle)
        self.active=False;self.hover=None;self.down=None;self.moved=False
        self.changed=time.monotonic();self.last_frame=None
        self.composited=False
        self.timer=Timer();self.timer.Interval=40;self.timer.Tick+=self.tick
        self.hint=Form();self.hint.FormBorderStyle=getattr(FormBorderStyle,'None')
        self.hint.ShowInTaskbar=False;self.hint.StartPosition=FormStartPosition.Manual
        self.hint_handle=int(self.hint.Handle.ToInt64())
        style=manager.user.GetWindowLongPtrW(self.hint_handle,-20)
        manager.user.SetWindowLongPtrW(self.hint_handle,-20,style|0x80000|0x80|0x8000000|0x20)
        manager.user.SetWindowLongPtrW(self.hint_handle,-8,self.handle)
        self.hint_presenter=AlphaPresenter(self.hint_handle)
        self.hint_text=None
        self.form.KeyPreview=True
        self.form.MouseDown+=self.mouse_down;self.form.MouseMove+=self.mouse_move
        self.form.MouseUp+=self.mouse_up;self.form.MouseLeave+=self.mouse_leave
        self.form.MouseWheel+=self.mouse_wheel;self.form.KeyDown+=self.key_down
        self.form.MouseCaptureChanged+=self.capture_changed
        self.form.FormClosing+=self.form_closing
        self.closing=False
        self.closed=False;self.navigating=False

    def owns_surface(self):
        return (not self.closed and not self.navigating and self.active
                and self.manager.floating is self and self.manager.handle == self.handle)

    def form_closing(self,sender,event):
        if str(event.CloseReason)=='ApplicationExitCall':return
        if not self.closing:
            event.Cancel=True
            self.manager.user.PostMessageW(self.manager.main_handle,0x0010,0,0)

    def present(self, previous):
        if self.closed:return
        self.composited=False
        self.navigating=False
        self.active=True;self.hover=None;self.down=None;self.hide_hint()
        self.form.TopMost=self.manager._is_topmost()
        self.form.Show()
        self.blocked_until=time.monotonic()+.25
        self.last_frame=None;self.timer.Start();self.tick(None,None)

    def suspend(self):
        self.active=False;self.timer.Stop();self.hide_hint();self.down=None
        self.form.Capture=False
        # 先清空合成器缓存，再隐藏原生窗口，避免贴边温度签残影留在桌面。
        if self.presenter.size and not self.form.IsDisposed:
            bitmap=None
            try:
                bitmap=self.renderer.Bitmap(*self.presenter.size,self.renderer.PixelFormat.Format32bppPArgb)
                self.presenter.draw(bitmap,(self.form.Left,self.form.Top))
            except Exception:logging.warning('Floating surface clearing deferred',exc_info=True)
            finally:
                if bitmap is not None:bitmap.Dispose()
        self.manager.user.ShowWindow(self.handle,0)
        self.form.Hide()

    def tick(self,sender,event):
        if not self.owns_surface() or self.manager.user.IsIconic(self.handle):return
        try:
            m=self.manager;rect=m._rect();dpi=m._scale()
            if not self.form.Visible:return
            if not self.composited:
                style=m.user.GetWindowLongPtrW(m.handle,-20)
                m.user.SetWindowLongPtrW(m.handle,-20,style & ~0x80000)
                m.user.SetWindowLongPtrW(m.handle,-20,style|0x80000)
                self.composited=True
            state=self.controls.snapshot();s=state.get('state') or {}
            speed={'low':16,'medium':30,'high':56,'auto':24}.get(s.get('speed'),24)
            angle=(time.monotonic()*speed)%360 if m.view=='bubble' and state.get('connected') and s.get('power') else 0
            phase=1 if m.view=='compact' else 0
            pixels,position=rect[2:],rect[:2]
            body=(PAD,PAD,rect[2]/dpi-2*PAD,rect[3]/dpi-2*PAD)
            # 收起和展开都进入缓存键；否则展开后的完整位置会命中收起前的旧缓存。
            key=(rect,dpi,m.view,m.hidden,m.edge,str(state),self.hover,round(angle),phase)
            if key==self.last_frame:
                self.show_hint();return
            if m.hidden:
                from presentations import peek_rectangle
                px,py,pw,ph=peek_rectangle(rect[2],rect[3],dpi,m.edge)
                bitmap=self.renderer.peek((rect[2],rect[3]),dpi,(px/dpi,py/dpi,pw/dpi,ph/dpi),state)
            else:
                bitmap=self.renderer.render(pixels,dpi,body,phase,state,self.hover,angle)
            try:
                if not self.owns_surface():return
                self.presenter.draw(bitmap,position)
                self.last_frame=key
            finally:bitmap.Dispose()
            self.form.AccessibleName='温控悬浮球' if m.view=='bubble' else '温控悬浮条'
            self.show_hint()
        except Exception:
            self.timer.Stop();logging.exception('Floating alpha rendering failed')

    def hit(self,x,y):
        m=self.manager
        if m.hidden:return 'peek'
        if m.view=='bubble':return 'bubble'
        x,y=x/m._scale()-PAD,y/m._scale()-PAD
        for name,(bx,by,bw,bh) in BUTTONS.items():
            if bx<=x<bx+bw and by<=y<by+bh:return name
        return None

    def mouse_down(self,sender,event):
        if not self.owns_surface() or time.monotonic()<self.blocked_until:return
        if str(event.Button)=='Right':self.hide_hint();self.manager.handle_action(9);return
        if str(event.Button)!='Left':return
        if self.manager.hidden:self.manager._reveal();return
        point=W.POINT();self.manager.user.GetCursorPos(ctypes.byref(point))
        self.down=(point.x,point.y,self.manager._rect(),self.hit(event.X,event.Y))
        self.moved=False;self.form.Capture=True;self.hide_hint()

    def mouse_move(self,sender,event):
        if not self.owns_surface():return
        if self.down:
            p=W.POINT();self.manager.user.GetCursorPos(ctypes.byref(p))
            sx,sy,rect,action=self.down;dx,dy=p.x-sx,p.y-sy
            if not self.moved and math.hypot(dx,dy)>4*self.manager._scale():
                self.moved=True;self.manager.drag_start()
            if self.moved:
                self.manager.user.SetWindowPos(self.manager.handle,None,rect[0]+dx,rect[1]+dy,*rect[2:],0x14)
            return
        hovered=self.hit(event.X,event.Y)
        self.form.Cursor=self.cursors.Hand if hovered else self.cursors.SizeAll
        if hovered!=self.hover:
            self.hover=hovered;self.changed=time.monotonic();self.hide_hint()

    def mouse_up(self,sender,event):
        if not self.owns_surface() or not self.down or str(event.Button)!='Left':return
        action=self.down[3];self.down=None;self.form.Capture=False
        if self.moved:self.manager.drag_end();return
        if action==self.hit(event.X,event.Y):self.invoke(action)

    def mouse_leave(self,sender,event):
        if not self.down:self.hover=None;self.hide_hint()

    def capture_changed(self,sender,event):
        if self.down and not self.form.Capture:
            self.down=None
            if self.manager.dragging:self.manager.drag_end()

    def mouse_wheel(self,sender,event):
        if self.owns_surface():self.controls.adjust(1 if event.Delta>0 else -1)

    def key_down(self,sender,event):
        if not self.owns_surface():return
        key=str(event.KeyCode)
        if key in ('Up','Right','Add','Oemplus'):self.controls.adjust(1)
        elif key in ('Down','Left','Subtract','OemMinus'):self.controls.adjust(-1)
        elif key=='Escape':self.request_navigation(18)
        elif key in ('Enter','Space') and self.manager.view=='bubble':self.request_navigation(5)
        else:return
        event.Handled=True;event.SuppressKeyPress=True

    def invoke(self,action):
        if not self.owns_surface():return
        self.hide_hint();m=self.manager
        if action=='bubble':self.request_navigation(5);return
        if action=='home':self.request_navigation(18);return
        if action=='settings':self.request_navigation(7);return
        if action=='peek':m._reveal();return
        state=self.controls.snapshot();s=state.get('state') or {}
        if not state.get('connected'):return
        if action=='power':self.controls.submit({'power':not s.get('power')})
        elif action in ('minus','plus'):self.controls.adjust(1 if action=='plus' else -1)
        elif action in ('mode','speed','direction'):
            field={'mode':'mode','speed':'speed','direction':'direction'}[action]
            values={'mode':['cool','heat','dry','fan','auto'],'speed':['auto','low','medium','high'],'direction':['fixed','swing']}[action]
            value=values[(values.index(s.get(field))+1)%len(values)] if s.get(field) in values else values[0]
            self.controls.submit({field:value,**({'power':True} if field!='speed' else {})})

    def request_navigation(self, action):
        if not self.owns_surface():return
        # MouseUp / KeyDown 返回后再由主窗口切换，避免在控件事件内销毁自己。
        self.navigating=True;self.timer.Stop();self.hide_hint()
        if not self.manager.user.PostMessageW(self.manager.main_handle,self.manager.chrome.MESSAGE,action,0):
            self.navigating=False;self.timer.Start()
            logging.warning('Floating navigation could not be queued')

    def hide_hint(self):
        self.manager.user.ShowWindow(self.hint_handle,0)
        self.hint_text=None

    def show_hint(self):
        from floating_graphics import LABELS
        if not self.owns_surface():return
        m=self.manager
        if not self.hover or self.down or m.menu.Visible or m.hidden or time.monotonic()-self.changed<.65:return
        text=LABELS.get(self.hover)
        state=self.controls.snapshot().get('state') or {}
        if self.hover=='mode':text={'cool':'制冷','heat':'制热','dry':'除湿','fan':'送风','auto':'自动'}.get(state.get('mode'),'模式')
        elif self.hover=='speed':text={'auto':'自动风','low':'低风','medium':'中风','high':'高风'}.get(state.get('speed'),'风速')
        elif self.hover=='direction':text='上下扫风' if state.get('direction')=='swing' else '固定风向'
        if not text or self.hint_text==text:return
        rect=m._rect();dpi=m._scale();bitmap=self.renderer.hint(text,dpi)
        try:
            width,height=bitmap.Width,bitmap.Height
            cx=rect[0]+rect[2]//2
            if m.view=='compact' and self.hover in BUTTONS:
                bx,by,bw,bh=BUTTONS[self.hover];cx=rect[0]+round((PAD+bx+bw/2)*dpi)
            left,top,right,bottom=m._work()
            x=max(left,min(cx-width//2,right-width));y=rect[1]+rect[3]+round(4*dpi)
            if y+height>bottom:y=rect[1]-height-round(4*dpi)
            m.user.SetWindowPos(self.hint_handle,-1 if m._is_topmost() else -2,x,y,width,height,0x10)
            self.hint_presenter.draw(bitmap,(x,y))
            m.user.ShowWindow(self.hint_handle,4);self.hint_text=text
        finally:bitmap.Dispose()

    def close(self):
        if self.closed:return
        self.closed=True
        self.suspend();self.timer.Dispose()
        self.hint_presenter.close();self.hint.Dispose();self.presenter.close();self.renderer.close()
        self.closing=True;self.form.Close();self.form.Dispose()
