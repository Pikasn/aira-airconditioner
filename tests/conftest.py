import copy

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.models import MODEL, DeviceFailure
from backend.service import DeviceService


class MemoryStore:
    def __init__(self):
        self.settings = None

    def load(self):
        return self.settings

    def save(self, settings):
        self.settings = settings


class FakeDriver:
    def __init__(self, settings):
        self.settings = settings
        self.state = {"power": False, "temp": 26, "mode": "cool", "speed": "auto", "direction": "fixed"}
        self.writes = []
        self.offline = self.reject = False
        self.partial_failure = False

    def identify(self):
        if self.settings.token.get_secret_value() == "0" * 32:
            raise DeviceFailure("unreachable", "设备无法连接")
        return {"model": MODEL, "firmware": "test"}

    def read(self):
        if self.offline:
            raise DeviceFailure("unreachable", "设备无法连接")
        return self.state.copy(), {"temperature": None, "humidity": None, "watts": 46.0}

    def apply(self, patch, current):
        self.writes.append(copy.deepcopy(patch))
        if self.reject:
            raise DeviceFailure("command_rejected", "设备没有接受指令", 502)
        if self.partial_failure:
            self.state["power"] = patch.get("power", self.state["power"])
            raise DeviceFailure("command_timeout", "指令未能确认", 502)
        self.state.update(patch)


@pytest.fixture
def harness():
    store = MemoryStore()
    devices = []

    def factory(settings):
        driver = FakeDriver(settings)
        devices.append(driver)
        return driver

    service = DeviceService(store, factory)
    app = create_app(service, poll=False, discover=lambda: [{"ip": "192.168.1.20", "deviceId": "1234"}])
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Aira-Request": "1"}) as client:
        yield client, service, store, devices


@pytest.fixture
def connected(harness):
    client, service, store, devices = harness
    response = client.post("/api/device", json={"ip": "192.168.1.20", "token": "1" * 32})
    assert response.status_code == 200
    return harness
