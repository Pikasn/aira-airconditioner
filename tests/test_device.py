from types import SimpleNamespace

import pytest

from backend.device import CompanionDriver, parse_status
from backend.discovery import HELLO, parse_hello
from backend.models import MODEL, DeviceFailure, DeviceSettings


def test_device_status_matches_mcn02_protocol_and_has_no_room_sensors():
    state, telemetry = parse_status(["on", "wind", 25, "large_fan", "on", 84.0])
    assert state == {"power": True, "mode": "fan", "temp": 25, "speed": "high", "direction": "swing"}
    assert telemetry == {"temperature": None, "humidity": None, "watts": 84.0}


@pytest.mark.parametrize("values", [[], None, ["on", "cool", 0, "auto_fan", "off", 0], ["on", "cool", True, "auto_fan", "off", 0], ["off", "invalid", 26, "auto_fan", "off", 0], ["off", "cool", float("nan"), "auto_fan", "off", 0]])
def test_unknown_device_state_never_becomes_a_plausible_default(values):
    with pytest.raises(DeviceFailure, match="设备状态无法识别"):
        parse_status(values)


def test_exact_wire_commands_have_no_socket_power_or_arbitrary_methods(monkeypatch):
    calls = []

    class Wire:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, method, parameters, **kwargs):
            calls.append((method, parameters, kwargs))
            return ["ok"]

        def info(self):
            return SimpleNamespace(model=MODEL, firmware_version="test")

    monkeypatch.setattr("backend.device.Device", Wire)
    driver = CompanionDriver(DeviceSettings(ip="192.168.1.20", token="1" * 32))
    assert driver.identify()["model"] == MODEL
    current = {"power": False, "mode": "cool", "temp": 26, "speed": "auto", "direction": "fixed"}
    driver.apply({"power": True, "mode": "fan", "temp": 22, "speed": "high", "direction": "swing"}, current)
    assert calls == [
        ("set_power", ["on"], {"retry_count": 0}),
        ("set_mode", ["wind"], {"retry_count": 0}),
        ("set_tar_temp", [22], {"retry_count": 0}),
        ("set_fan_level", ["large_fan"], {"retry_count": 0}),
        ("set_ver_swing", ["on"], {"retry_count": 0}),
    ]
    calls.clear()
    driver.apply(current, current)
    assert calls == []
    driver.device.send = lambda *args, **kwargs: ["error"]
    with pytest.raises(DeviceFailure, match="没有接受"):
        driver.apply({"power": True}, current)


def test_discovery_never_exposes_the_handshake_token():
    packet = bytes.fromhex("21310020ffffffff000004d200000005") + b"sensitive-token!"
    assert len(HELLO) == 32
    assert len(packet) == 32
    found = parse_hello(packet, "192.168.1.20")
    assert found == {"ip": "192.168.1.20", "deviceId": "1234"}
    assert parse_hello(packet, "8.8.8.8") is None
    assert parse_hello(b"not-miio", "192.168.1.20") is None
