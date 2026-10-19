"""悬浮控件的超采样绘制。返回预乘 Alpha 位图，轮廓不使用二值窗口裁剪。"""
import math

COLORS = {'cool': (47,163,212), 'heat': (225,140,62), 'dry': (124,145,180),
          'fan': (67,158,123), 'auto': (55,153,148)}
PAD = 6
SIZES = {'bubble': (84,84), 'compact': (324,64)}
BUTTONS = {'power': (10,10,28,32), 'minus': (40,10,24,32), 'plus': (100,10,24,32),
           'mode': (144,10,28,32), 'speed': (176,10,28,32), 'direction': (208,10,28,32),
           'settings': (240,10,28,32), 'home': (272,10,28,32)}
LABELS = {'power':'开关', 'minus':'降温', 'plus':'升温', 'mode':'模式', 'speed':'风速',
          'direction':'扫风', 'settings':'设置', 'home':'空调主界面', 'bubble':'打开空调'}


class FloatingRenderer:
    def __init__(self):
        import clr
        clr.AddReference('System.Drawing')
        from System.Drawing import Bitmap, Color, Font, FontStyle, Graphics, GraphicsUnit, Pen, SolidBrush, RectangleF
        from System.Drawing.Drawing2D import GraphicsPath, SmoothingMode, InterpolationMode, PixelOffsetMode, LinearGradientBrush
        from System.Drawing.Imaging import PixelFormat, ImageLockMode
        from System.Drawing.Text import TextRenderingHint
        self.Bitmap, self.Color, self.Font, self.FontStyle, self.Graphics = Bitmap, Color, Font, FontStyle, Graphics
        self.GraphicsUnit, self.Pen, self.Brush, self.Rect = GraphicsUnit, Pen, SolidBrush, RectangleF
        self.Path, self.Smoothing, self.Interpolation, self.PixelOffset = GraphicsPath, SmoothingMode, InterpolationMode, PixelOffsetMode
        self.Gradient, self.PixelFormat, self.LockMode, self.TextHint = LinearGradientBrush, PixelFormat, ImageLockMode, TextRenderingHint
        self.fonts = {}

    def _color(self, rgb, alpha=255):
        return self.Color.FromArgb(int(alpha), *[int(v) for v in rgb])

    def _font(self, size):
        size = round(size * 2) / 2
        if size not in self.fonts:
            self.fonts[size] = self.Font('Segoe UI', float(size), self.FontStyle.Regular, self.GraphicsUnit.Pixel)
        return self.fonts[size]

    def _rounded(self, rect, radius):
        x,y,w,h = rect
        radius = min(radius, w/2, h/2)
        d = radius * 2
        p = self.Path()
        for rx,ry,angle in [(x,y,180),(x+w-d,y,270),(x+w-d,y+h-d,0),(x,y+h-d,90)]:
            p.AddArc(float(rx),float(ry),float(d),float(d),float(angle),90.)
        p.CloseFigure()
        return p

    def _fill_round(self, graphics, rect, radius, color):
        p, brush = self._rounded(rect,radius), self.Brush(color)
        try: graphics.FillPath(brush,p)
        finally: brush.Dispose(); p.Dispose()

    def _text(self, graphics, text, center, size, color):
        font = self._font(size)
        measured = graphics.MeasureString(str(text),font)
        brush = self.Brush(color)
        try: graphics.DrawString(str(text), font, brush, float(center[0]-measured.Width/2), float(center[1]-measured.Height/2))
        finally: brush.Dispose()

    def _icon(self, g, name, cx, cy, color, state):
        from System.Drawing.Drawing2D import LineCap
        pen = self.Pen(color, 1.3)
        pen.StartCap = pen.EndCap = LineCap.Round
        def line(x1,y1,x2,y2): g.DrawLine(pen,float(cx+x1),float(cy+y1),float(cx+x2),float(cy+y2))
        def arc(x,y,w,h,start,sweep): g.DrawArc(pen,float(cx+x),float(cy+y),float(w),float(h),float(start),float(sweep))
        try:
            if name=='power': arc(-6,-6,12,12,-48,276);line(0,-8,0,-1)
            elif name in ('plus','minus'):
                line(-4,0,4,0)
                if name=='plus': line(0,-4,0,4)
            elif name=='home':
                g.DrawRectangle(pen,float(cx-6),float(cy-5),12.,10.)
                line(-6,-2,6,-2)
            elif name=='settings':
                line(-6,-4,6,-4);line(-6,4,6,4)
                g.DrawEllipse(pen,float(cx-4),float(cy-6),4.,4.)
                g.DrawEllipse(pen,float(cx+1),float(cy+2),4.,4.)
            elif name=='direction':
                if state.get('direction')=='swing':
                    line(-3,-7,-3,7);line(-3,-7,-6,-4);line(-3,-7,0,-4)
                    line(3,7,3,-7);line(3,7,0,4);line(3,7,6,4)
                else: line(0,-6,0,6);line(0,6,-4,2);line(0,6,4,2)
            elif name=='speed':
                speed=state.get('speed','auto')
                if speed=='auto': self._text(g,'A',(cx,cy),14,color)
                else:
                    count={'low':1,'medium':2,'high':3}.get(speed,1)
                    for i in range(count):
                        x=(i-(count-1)/2)*4
                        line(x,5,x,1-i*3)
            elif name=='mode':
                mode=state.get('mode','cool')
                if mode=='cool':
                    for a in [0,60,120]:
                        r=math.radians(a);line(-7*math.cos(r),-7*math.sin(r),7*math.cos(r),7*math.sin(r))
                elif mode=='heat':
                    g.DrawEllipse(pen,float(cx-3),float(cy-3),6.,6.)
                    for a in range(0,360,45):
                        r=math.radians(a);line(5*math.cos(r),5*math.sin(r),7*math.cos(r),7*math.sin(r))
                elif mode=='dry':
                    p=self.Path();p.AddBezier(float(cx),float(cy-7),float(cx-11),float(cy+5),float(cx-2),float(cy+10),float(cx+4),float(cy+4));p.AddBezier(float(cx+4),float(cy+4),float(cx+7),float(cy),float(cx+2),float(cy-5),float(cx),float(cy-7));g.DrawPath(pen,p);p.Dispose()
                elif mode=='fan':
                    line(-7,-3,2,-3);arc(0,-7,5,4,180,230);line(-7,1,6,1);line(-7,5,1,5);arc(-1,5,5,4,-160,-230)
                else: self._text(g,'A',(cx,cy),14,color)
        finally: pen.Dispose()

    def render(self, pixels, dpi, body, phase, snapshot, hovered=None, angle=0, opacity=1):
        """body 是画布内的逻辑机身矩形；phase 0 为浮球，1 为横条。"""
        ss = 3
        high = self.Bitmap(max(1,pixels[0]*ss), max(1,pixels[1]*ss), self.PixelFormat.Format32bppPArgb)
        g = self.Graphics.FromImage(high)
        try:
            g.SmoothingMode=self.Smoothing.AntiAlias
            g.PixelOffsetMode=self.PixelOffset.HighQuality
            g.TextRenderingHint=self.TextHint.AntiAliasGridFit
            g.ScaleTransform(float(dpi*ss),float(dpi*ss))
            state=snapshot.get('state') or {}
            online=bool(snapshot.get('connected'))
            accent=COLORS.get(state.get('mode'),COLORS['cool']) if online else (137,158,168)
            x,y,w,h=body
            # 低对比度软阴影与连续 Alpha 边缘，不描绘白色硬边。
            for inset,alpha in [(4,2),(3,3),(2,4),(1,5)]:
                self._fill_round(g,(x-inset,y-inset+1,w+2*inset,h+2*inset),h/2+inset,self._color((54,78,92),alpha))
            p=self._rounded(body,h/2)
            lower=tuple(round(244*.87+c*.13) for c in accent)
            brush=self.Gradient(self.Rect(float(x),float(y),float(w),float(h)),self._color((249,252,253)),self._color(lower),90.)
            g.FillPath(brush,p);brush.Dispose();p.Dispose()
            valid=type(state.get('temp')) in (int,float) and online
            value=str(round(state['temp'])) if valid else '—'
            ink=(51,76,89) if online else (140,158,167)
            if online and not state.get('power'): ink=(107,130,141)
            center_x=x+(w/2)*(1-phase)+(82)*phase
            self._text(g,value,(center_x,y+h/2-1),25-2*phase,self._color(ink))
            if valid:
                self._text(g,'°',(center_x+(18 if phase<.5 else 17),y+h/2-7),13,self._color(ink,170))
            if phase<.9:
                pen=self.Pen(self._color(accent,int(24*(1-phase))),.55)
                g.DrawEllipse(pen,float(x+7),float(y+7),float(w-14),float(h-14));pen.Dispose()
                if online and state.get('power'):
                    pen=self.Pen(self._color(accent,int(125*(1-phase))),1.05)
                    g.DrawArc(pen,float(x+7),float(y+7),float(w-14),float(h-14),float(angle),45.);pen.Dispose()
            if phase>.7:
                visibility=min(1,(phase-.7)/.3)
                for name,(bx,by,bw,bh) in BUTTONS.items():
                    if hovered==name: self._fill_round(g,(x+bx,y+by,bw,bh),min(bw,bh)/2,self._color((255,255,255),150))
                    enabled=online or name in ('settings','home')
                    if name in ('minus','plus'): enabled=enabled and valid and state.get('power')
                    rgb=accent if name in ('mode','power','direction') and state.get('power') else (119,143,156)
                    if not enabled: rgb=(174,190,198)
                    self._icon(g,name,x+bx+bw/2,y+by+bh/2,self._color(rgb,int(255*visibility)),state)
                pen=self.Pen(self._color(accent,36),.7);g.DrawLine(pen,float(x+136),float(y+18),float(x+136),float(y+h-18));pen.Dispose()
        finally: g.Dispose()
        result=self.Bitmap(pixels[0],pixels[1],self.PixelFormat.Format32bppPArgb)
        out=self.Graphics.FromImage(result)
        try:
            out.InterpolationMode=self.Interpolation.HighQualityBicubic
            out.PixelOffsetMode=self.PixelOffset.HighQuality
            out.DrawImage(high,0,0,pixels[0],pixels[1])
        finally: out.Dispose();high.Dispose()
        return result

    def hint(self, text, dpi):
        width=max(62,min(186,len(text)*11+24));height=34
        bitmap=self.Bitmap(round(width*dpi),round(height*dpi),self.PixelFormat.Format32bppPArgb)
        g=self.Graphics.FromImage(bitmap)
        try:
            g.SmoothingMode=self.Smoothing.AntiAlias;g.TextRenderingHint=self.TextHint.AntiAliasGridFit
            g.ScaleTransform(float(dpi),float(dpi))
            self._fill_round(g,(3,4,width-6,height-7),9,self._color((56,78,91),12))
            self._fill_round(g,(3,2,width-6,height-7),9,self._color((244,249,252),248))
            self._text(g,text,(width/2,height/2-2),11,self._color((91,117,132)))
        finally:g.Dispose()
        return bitmap

    def peek(self, pixels, dpi, body, snapshot):
        bitmap=self.Bitmap(*pixels,self.PixelFormat.Format32bppPArgb)
        g=self.Graphics.FromImage(bitmap)
        try:
            g.SmoothingMode=self.Smoothing.AntiAlias;g.TextRenderingHint=self.TextHint.AntiAliasGridFit
            g.ScaleTransform(float(dpi),float(dpi))
            x,y,w,h=body
            self._fill_round(g,(x+1,y+1,w-2,h-2),min(w,h)/2,self._color((239,247,250),250))
            value=(snapshot.get('state') or {}).get('temp')
            text=str(round(value))+'°' if snapshot.get('connected') and type(value) in (int,float) else '—'
            self._text(g,text,(x+w/2,y+h/2-1),16,self._color((67,99,115)))
        finally:g.Dispose()
        return bitmap

    def close(self):
        for font in self.fonts.values(): font.Dispose()
        self.fonts.clear()
