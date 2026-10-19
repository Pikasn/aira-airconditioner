"""定时任务：接口约定、持久化与到点执行。"""

import json
import time

from conftest import FakeDriver, MemoryStore

from backend.models import DeviceSettings
from backend.service import DeviceService


def due_in(seconds):
    return int(time.time()) + seconds


def test_timer_needs_connection(harness):
    client, service, store, devices = harness
    data = client.get("/api/timer").json()
    assert data["timer"] is None
    assert client.post("/api/timer", json={"action": "off", "due": due_in(600)}).status_code == 409
    assert service.snapshot()["timer"] is None


def test_set_get_and_cancel_timer(connected):
    client, service, store, devices = connected
    due = due_in(600)
    response = client.post("/api/timer", json={"action": "off", "due": due})
    assert response.status_code == 200
    timer = response.json()["timer"]
    assert timer["action"] == "off" and timer["due"] == due
    assert 590 <= timer["remaining"] <= 600
    assert client.get("/api/timer").json()["timer"]["action"] == "off"

    cancelled = client.request("DELETE", "/api/timer", json={})
    assert cancelled.status_code == 200
    assert cancelled.json()["timer"] is None
    assert not devices[0].writes, "设置/取消定时不应下发控制"


def test_timer_validation(connected):
    client, service, store, devices = connected
    bad_bodies = [
        {"action": "off", "due": due_in(-10)},
        {"action": "off", "due": due_in(25 * 3600)},
        {"action": "toggle", "due": due_in(600)},
        {"action": "off", "due": 1.5},
        {"action": "off", "due": True},
        {"action": "off", "due": due_in(600), "temp": 24},
        {"due": due_in(600)},
        {},
    ]
    for body in bad_bodies:
        assert client.post("/api/timer", json=body).status_code == 422, body
    assert service.snapshot()["timer"] is None
    assert not devices[0].writes


def test_timer_fires_once_and_clears(connected):
    client, service, store, devices = connected
    service._timer = {"action": "off", "due": int(time.time()) - 1, "retries": 0}
    service._check_timer()
    assert service.snapshot()["timer"] is None
    assert devices[0].writes == [{"power": False}]
    assert service.snapshot()["state"]["power"] is False
    service._check_timer()
    assert len(devices[0].writes) == 1, "同一个定时只能执行一次"


def test_timer_turn_on_uses_power(connected):
    client, service, store, devices = connected
    service._timer = {"action": "on", "due": int(time.time()) - 1, "retries": 0}
    service._check_timer()
    assert devices[0].writes == [{"power": True}]
    assert service.snapshot()["timer"] is None


def test_timer_retries_when_device_is_temporarily_unavailable(connected):
    client, service, store, devices = connected
    devices[0].offline = True
    service._timer = {"action": "off", "due": int(time.time()) - 1, "retries": 0}
    service._check_timer()
    timer = service.snapshot()["timer"]
    assert timer is not None and timer["due"] > int(time.time())
    assert "error" in timer
    devices[0].offline = False
    service._timer["due"] = int(time.time()) - 1
    service._check_timer()
    assert service.snapshot()["timer"] is None
    assert devices[0].writes[-1] == {"power": False}


def test_timer_marks_failure_after_retries(connected):
    client, service, store, devices = connected
    devices[0].offline = True
    service._timer = {"action": "off", "due": int(time.time()) - 1, "retries": 0}
    service._check_timer()
    service._timer["due"] = int(time.time()) - 1
    service._check_timer()
    service._timer["due"] = int(time.time()) - 1
    service._check_timer()
    timer = service.snapshot()["timer"]
    assert timer is not None and timer["failed"] is True
    assert timer["error"]
    service._check_timer()
    assert service.snapshot()["timer"]["failed"] is True
    assert not devices[0].writes


def make_service(tmp_path, store=None, factory=FakeDriver):
    store = store or MemoryStore()
    if store.settings is None:
        store.settings = DeviceSettings(ip="192.168.1.9", token="1" * 32)
    return DeviceService(store, lambda settings: factory(settings), timer_path=tmp_path / "timer.json")


def test_timer_survives_service_restart(tmp_path):
    service = make_service(tmp_path)
    due = due_in(900)
    service.set_timer("off", due)
    saved = json.loads((tmp_path / "timer.json").read_text(encoding="utf-8"))
    assert saved["action"] == "off" and saved["due"] == due

    restarted = make_service(tmp_path)
    timer = restarted.timer()
    assert timer["action"] == "off" and timer["due"] == due
    assert 880 <= timer["remaining"] <= 900


def test_cancel_timer_removes_saved_state(tmp_path):
    service = make_service(tmp_path)
    service.set_timer("on", due_in(600))
    assert (tmp_path / "timer.json").exists()
    service.clear_timer()
    assert service.timer() is None
    assert not (tmp_path / "timer.json").exists()
