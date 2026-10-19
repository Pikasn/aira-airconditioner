import sys
from types import SimpleNamespace

import backend
import desktop
from window_chrome import WindowChrome


def test_packaged_state_and_assets_have_separate_roots(tmp_path, monkeypatch):
    runtime = tmp_path / "程序"
    resources = runtime / "_internal"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(runtime / "空调.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(resources), raising=False)
    assert backend.application_root() == runtime
    assert backend.asset_root() == resources


def test_single_instance_is_released_after_process_handles_close(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    first = desktop.SingleInstance()
    second = desktop.SingleInstance()
    try:
        assert first.existing is False
        assert second.existing is True
    finally:
        second.close()
        first.close()
    restarted = desktop.SingleInstance()
    try:
        assert restarted.existing is False
    finally:
        restarted.close()


def test_saved_window_size_fits_current_display(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "LOCAL", tmp_path)
    screen = SimpleNamespace(width=1280, height=720)
    desktop.save_json(tmp_path / "window.json", {"width": 8000, "height": 4000})
    assert desktop.window_size(screen) == (1203, 648)
    desktop.save_json(tmp_path / "window.json", {"width": -1, "height": False})
    assert desktop.window_size(screen) == (920, 540)


def test_packaged_frontend_assets_are_local_and_unbranded(harness):
    client, *_ = harness
    index = client.get("/")
    assert index.status_code == 200
    assert '<title>空调</title>' in index.text
    assert 'machine-logo' not in index.text
    assert 'cdn.jsdelivr.net' not in index.text
    assert 'AIRA' not in client.get('/setup').text
    assert client.get('/favicon.ico').content[:4] == b'\x00\x00\x01\x00'
    assert client.get('/assets/inter.woff2').content[:4] == b'wOF2'
    assert client.get('/desktop.css').status_code == 200
    assert client.get('/desktop.js').status_code == 200
    assert client.get('/window_chrome.py').status_code == 404
    assert client.get('/assets/空调.svg').status_code == 404
    assert client.get('/.local/device.json').status_code == 404


def test_delayed_drag_packets_cannot_override_the_final_position():
    chrome = WindowChrome()
    sent = []
    chrome._handle = 1
    chrome._user = SimpleNamespace(PostMessageW=lambda *args: sent.append(args))
    chrome.drag_window(1, 80, 12, True, 3)
    chrome.drag_window(1, 30, 4, False, 2)
    chrome.drag_window(1, float('nan'), 0, True, 4)
    assert chrome._move_packet == (1, 80, 12, True, 3)
    assert len(sent) == 1
