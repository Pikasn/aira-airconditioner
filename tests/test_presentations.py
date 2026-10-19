from presentations import fit_rectangle, peek_rectangle, compact_main_rectangle
from presentations import PresentationManager
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('rect,work,scale', [
    ((100, 200, 509, 760), (0, 0, 1920, 1040), 1),
    ((-1700, 200, 764, 1140), (-1920, 0, 0, 1040), 1.5),
    ((4000, -300, 509, 760), (0, 0, 800, 600), 1),
])
def test_compact_main_layout_fits_the_monitor_and_preserves_landscape_proportions(rect,work,scale):
    x,y,width,height=compact_main_rectangle(rect,work,scale)
    assert work[0]<=x and work[1]<=y and x+width<=work[2] and y+height<=work[3]
    assert width/height>=1.6


def test_saved_widget_on_unplugged_monitor_returns_to_current_work_area():
    assert fit_rectangle((4000, -300, 430, 260), (0, 0, 1920, 1040)) == (1490, 0, 430, 260)


def test_floating_widget_preserves_negative_monitor_coordinates():
    assert fit_rectangle((-1700, 200, 430, 260), (-1920, -100, 0, 980)) == (-1700, 200, 430, 260)


def test_saved_size_is_bounded_by_small_screen_and_minimum_size():
    assert fit_rectangle((-100, -100, 4000, 2000), (10, 20, 650, 500), (360, 220)) == (10, 20, 640, 480)
    assert fit_rectangle((0, 0, 10, 10), (0, 0, 800, 600), (360, 220)) == (0, 0, 360, 220)


@pytest.mark.parametrize('rect,edge,expanded,hidden', [
    ((-35, 200, 312, 52), 'left', (0, 200, 312, 52), (-268, 200, 312, 52)),
    ((1630, 200, 312, 52), 'right', (1608, 200, 312, 52), (1876, 200, 312, 52)),
    ((500, -20, 312, 52), 'top', (500, 0, 312, 52), (500, -24, 312, 52)),
    ((500, 1000, 312, 52), 'bottom', (500, 988, 312, 52), (500, 1012, 312, 52)),
])
def test_control_strip_docks_at_each_edge_and_leaves_a_recoverable_tab(rect, edge, expanded, hidden):
    manager = PresentationManager.__new__(PresentationManager)
    calls = []
    manager.user = SimpleNamespace(SetWindowPos=lambda handle, order, *args: calls.append(args[:4]))
    manager.handle = 1
    manager.mode = manager.view = 'compact'
    manager.setup = manager.hidden = False
    manager._rect = lambda: rect
    manager._work = lambda: (0, 0, 1920, 1040)
    manager._scale = lambda: 1
    manager._remember = manager._save = manager._notify = lambda: None
    manager._set_region = lambda *args, **kwargs: None
    manager.drag_end()
    assert manager.edge == edge
    assert manager.expanded_rect == expanded
    manager._hide()
    assert manager.hidden is True
    assert calls[-1] == hidden
    px, py, pw, ph = peek_rectangle(hidden[2], hidden[3], 1, edge)
    visible = (hidden[0] + px, hidden[1] + py, pw, ph)
    assert visible[0] >= 0 and visible[1] >= 0
    assert visible[0] + pw <= 1920 and visible[1] + ph <= 1040
    assert pw >= 44 and ph >= 28
    manager._reveal()
    assert manager.hidden is False
    assert calls[-1] == expanded


def test_round_surface_is_owned_by_the_form_and_old_handles_are_released():
    manager = PresentationManager.__new__(PresentationManager)
    deleted, released = [], []
    manager.form = SimpleNamespace(Region=None)
    manager.surface_region = None
    manager.Int64 = manager.IntPtr = lambda value: value
    manager.Region = SimpleNamespace(FromHrgn=lambda handle: SimpleNamespace(handle=handle, Dispose=lambda: released.append(handle)))
    manager.gdi = SimpleNamespace(CreateEllipticRgn=lambda *args: 0x90000001,
                                  CreateRoundRectRgn=lambda *args: 0x90000002,
                                  DeleteObject=lambda handle: deleted.append(handle))
    manager._set_region('bubble', 108, 108)
    assert manager.form.Region is manager.surface_region
    assert manager.form.Region.handle == 0x90000001
    manager._set_region('bubble', 108, 108)
    assert released == [0x90000001]
    manager._clear_region()
    assert manager.form.Region is None and manager.surface_region is None
    assert deleted == [0x90000001, 0x90000001]
    assert len(released) == 2


@pytest.mark.parametrize('view', ['standard','settings','compact','bubble'])
@pytest.mark.parametrize('enabled', [False, True])
def test_settings_never_inherits_the_floating_window_topmost_state(view, enabled):
    manager = PresentationManager.__new__(PresentationManager)
    calls = []
    manager.user = SimpleNamespace(IsZoomed=lambda handle: False, IsIconic=lambda handle: False,
        GetWindowLongPtrW=lambda *args: 0, SetWindowLongPtrW=lambda *args: None,
        SetWindowPos=lambda *args: calls.append(args))
    manager.handle, manager.base_style = 1, 0
    manager.mode, manager.view = 'bubble', view
    manager.floating_topmost = enabled
    manager._scale = lambda: 1
    manager._work = lambda: (0,0,1920,1080)
    manager._clear_region = lambda: None
    manager._set_region = lambda *args: None
    manager._set_rect((100,100,480,760), view)
    assert calls[-1][1] == (-1 if enabled and view in ('compact','bubble') else -2)


@pytest.mark.parametrize('view,target,rect,expected',[
    ('bubble','compact',(800,300,126,126),None),
    ('compact','bubble',(425,315,486,96),None),
    ('compact','compact',(425,315,486,96),(425,315,486,96)),
])
def test_native_modes_restore_their_own_position_instead_of_morphing(view,target,rect,expected):
    manager=PresentationManager.__new__(PresentationManager)
    manager.floating=object();manager.setup=False;manager.view=view
    manager._rect=lambda:rect;manager._scale=lambda:1.5
    manager._remember=manager._save=lambda:None
    applied=[];manager._apply=lambda mode,position:applied.append((mode,position))
    manager._navigate=lambda path:None
    manager._change_mode(target)
    assert applied==[(target,expected)]


@pytest.mark.parametrize('view,action',[('bubble',5),('bubble',18),('compact',18),('bubble',8),('compact',8)])
def test_floating_click_or_home_returns_to_main_without_intermediate_mode(view,action):
    manager=PresentationManager.__new__(PresentationManager)
    manager.setup=False;manager.view=view
    calls=[];manager._change_mode=lambda mode:calls.append(mode)
    assert manager.handle_action(action) is True
    assert calls==['standard']
