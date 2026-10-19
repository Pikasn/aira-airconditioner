"""审查发现的问题：验证行为边界，不依赖真实设备。"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.device import CompanionDriver, parse_status
from backend.models import DeviceFailure, DeviceSettings, StatePatch
from backend.service import DeviceService
from conftest import FakeDriver, MemoryStore


def test_lost_reply_never_retransmits_a_control_packet(monkeypatch):
    packets = []

    class TimeoutSocket:
        def __init__(self, *args, **kwargs):
            pass

        def settimeout(self, value):
            pass

        def sendto(self, packet, address):
            packets.append(packet)

        def recvfrom(self, count):
            raise TimeoutError("simulated lost acknowledgement")

        def close(self):
            pass

    driver = CompanionDriver(DeviceSettings(ip="192.168.1.20", token="1" * 32))
    protocol = driver.device._protocol
    protocol._discovered = True
    protocol._device_id = b"\x00\x00\x04\xd2"
    monkeypatch.setattr(protocol, "send_handshake", lambda: None)
    monkeypatch.setattr("miio.miioprotocol.socket.socket", TimeoutSocket)
    with pytest.raises(DeviceFailure, match="指令未能确认"):
        driver.apply({"power": True}, {"power": False})
    assert len(packets) == 1, "A lost ACK must not cause a second infrared command"


@pytest.mark.parametrize("load", [None, "", "unknown", False, float("nan"), float("inf"), -1])
def test_missing_optional_power_reading_does_not_disable_controls(load):
    state, telemetry = parse_status(["on", "cool", 24, "small_fan", "off", load])
    assert state["temp"] == 24 and state["power"] is True
    assert telemetry["watts"] is None


def test_saved_settings_cannot_bypass_model_verification_before_control():
    store = MemoryStore()
    store.settings = DeviceSettings(ip="192.168.1.20", token="1" * 32)
    devices = []

    class WrongDevice(FakeDriver):
        def identify(self):
            raise DeviceFailure("unsupported_model", "型号不匹配", 422)

    def factory(settings):
        device = WrongDevice(settings)
        devices.append(device)
        return device

    service = DeviceService(store, factory)
    with pytest.raises(DeviceFailure) as result:
        service.control(StatePatch(power=True))
    assert result.value.code == "unsupported_model"
    assert devices[0].writes == []
    assert service.snapshot()["connected"] is False


def test_busy_device_rejects_new_control_without_queueing(connected):
    client, service, store, devices = connected
    driver = devices[0]
    entered, release = threading.Event(), threading.Event()
    apply = driver.apply

    def blocking_apply(patch, current):
        entered.set()
        assert release.wait(2)
        apply(patch, current)

    driver.apply = blocking_apply

    def second_control():
        try:
            service.control(StatePatch(power=True))
            return None
        except DeviceFailure as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.control, StatePatch(temp=24))
        assert entered.wait(1)
        second = pool.submit(second_control)
        time.sleep(.05)
        returned_while_busy = second.done()
        release.set()
        first.result(timeout=2)
        code = second.result(timeout=2)
    assert returned_while_busy and code == "device_busy"
    assert driver.writes == [{"temp": 24}]


def test_declared_small_body_cannot_bypass_request_size_limit(harness):
    client, service, store, devices = harness
    response = client.post("/api/device", content='{"ip":"' + "x" * 9000 + '"}', headers={"Content-Type": "application/json", "Content-Length": "2"})
    assert response.status_code == 413
    assert not devices


def test_control_failure_only_handshakes_and_reads_to_recover(monkeypatch):
    calls = []

    class LostAckDevice:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, method, parameters, **kwargs):
            calls.append(method)
            if method == "set_power":
                raise TimeoutError("lost ACK")
            return ["on", "cool", 24, "auto_fan", "off", None]

        def send_handshake(self):
            calls.append("handshake")

    monkeypatch.setattr("backend.device.Device", LostAckDevice)
    driver = CompanionDriver(DeviceSettings(ip="192.168.1.20", token="1" * 32))
    with pytest.raises(DeviceFailure):
        driver.apply({"power": True}, {"power": False})
    assert driver.read()[0]["power"] is True
    assert calls == ["set_power", "handshake", "get_prop"]
