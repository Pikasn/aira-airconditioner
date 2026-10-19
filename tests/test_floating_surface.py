from types import SimpleNamespace
import pytest
from floating_surface import FloatingSurface


@pytest.mark.parametrize('clear_failure',[False,True])
def test_switching_away_clears_alpha_and_hides_native_widget_even_if_clear_fails(clear_failure):
    calls=[]
    surface=FloatingSurface.__new__(FloatingSurface)
    surface.timer=SimpleNamespace(Stop=lambda:calls.append('stop'))
    surface.hide_hint=lambda:calls.append('hint-hidden')
    surface.form=SimpleNamespace(IsDisposed=False,Left=100,Top=200,Capture=True,Hide=lambda:calls.append('managed-hidden'))
    surface.handle=42
    surface.manager=SimpleNamespace(user=SimpleNamespace(ShowWindow=lambda h,mode:calls.append(('native-hidden',h,mode))))
    surface.renderer=SimpleNamespace(PixelFormat=SimpleNamespace(Format32bppPArgb=1),Bitmap=lambda *args:SimpleNamespace(Dispose=lambda:calls.append('disposed')))
    def draw(bitmap,position):
        calls.append(('cleared',position))
        if clear_failure:raise OSError('test compositor failure')
    surface.presenter=SimpleNamespace(size=(126,126),draw=draw)
    surface.suspend()
    assert surface.active is False and surface.down is None
    assert surface.form.Capture is False
    assert calls.index(('cleared',(100,200)))<calls.index(('native-hidden',42,0))
    assert calls[-1]=='managed-hidden' and 'disposed' in calls


def cached_surface():
    surface=FloatingSurface.__new__(FloatingSurface)
    calls=[]
    manager=SimpleNamespace(handle=42,view='compact',hidden=False,edge=None,
        _rect=lambda:(10,20,324,64),_scale=lambda:1,
        user=SimpleNamespace(IsIconic=lambda handle:False))
    manager.floating=surface
    surface.manager=manager;surface.handle=42
    surface.active=surface.composited=True
    surface.closed=surface.navigating=False
    surface.form=SimpleNamespace(Visible=True)
    surface.controls=SimpleNamespace(snapshot=lambda:{'connected':False,'state':None})
    surface.hover=None;surface.last_frame=None
    bitmap=lambda name:SimpleNamespace(Dispose=lambda:None,name=name)
    surface.renderer=SimpleNamespace(render=lambda *args:bitmap('full'),peek=lambda *args:bitmap('peek'))
    surface.presenter=SimpleNamespace(draw=lambda image,pos:calls.append(image.name))
    surface.show_hint=lambda:None
    surface.timer=SimpleNamespace(Stop=lambda:None)
    return surface,calls


def test_same_position_reveal_replaces_the_peek_bitmap_instead_of_using_old_cache():
    surface,calls=cached_surface()
    surface.tick(None,None);surface.tick(None,None)
    surface.manager.hidden=True;surface.manager.edge='left'
    surface.tick(None,None);surface.tick(None,None)
    surface.manager.hidden=False;surface.manager.edge=None
    surface.tick(None,None);surface.tick(None,None)
    assert calls==['full','peek','full']


def test_a_queued_tick_from_a_replaced_surface_cannot_draw_a_temperature_tag():
    surface,calls=cached_surface()
    surface.manager.floating=None
    surface.tick(None,None)
    assert calls==[]


@pytest.mark.parametrize('action,command',[('bubble',5),('home',18),('settings',7)])
def test_navigation_is_queued_and_duplicate_clicks_or_ticks_do_not_run_during_switch(action,command):
    surface,calls=cached_surface()
    surface.hide_hint=lambda:None
    surface.manager.main_handle=99
    surface.manager.chrome=SimpleNamespace(MESSAGE=123)
    surface.manager.user.PostMessageW=lambda *args:calls.append(args) or True
    surface.invoke(action);surface.invoke(action);surface.tick(None,None)
    assert calls==[(99,123,command,0)]
    assert surface.navigating is True
