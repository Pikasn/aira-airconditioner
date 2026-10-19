import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


def test_initial_status_is_unconfigured_and_does_not_invent_sensors(harness):
    client, *_ = harness
    data = client.get("/api/status").json()
    assert not data["configured"] and not data["connected"]
    assert data["state"] is None
    assert data["telemetry"]["temperature"] is None
    assert data["telemetry"]["humidity"] is None
    assert data["capabilities"]["directions"] == ["fixed", "swing"]
    assert data["capabilities"]["temperature"]["max"] == 30
    assert client.patch("/api/state", json={"power": True}).status_code == 409


def test_connect_validates_before_saving_and_never_returns_secret(connected):
    client, service, store, devices = connected
    assert store.settings.ip == "192.168.1.20"
    assert not devices[0].writes, "Connection testing must never send IR control"
    assert "1" * 32 not in json.dumps(service.snapshot())
    previous = store.settings
    bad = client.post("/api/device", json={"ip": "192.168.1.21", "token": "0" * 32})
    assert bad.status_code == 503
    assert store.settings == previous
    assert service.snapshot()["connected"]
    assert service.snapshot()["device"]["ip"] == "192.168.1.20"
    assert "0" * 32 not in bad.text
    assert client.post("/api/device", json={"ip": "192.168.1.22"}).status_code == 200
    assert store.settings.token.get_secret_value() == "1" * 32


@pytest.mark.parametrize("body", [
    {"temp": 31}, {"temp": 15}, {"temp": 24.2}, {"temp": True}, {"temp": "24"},
    {"power": "false"}, {"power": 1}, {"mode": "invalid"}, {"speed": "fast"},
    {"direction": "down"}, {"direction": "up"}, {"temp": None}, {},
    {"power": False, "temp": 24}, {"raw_command": "toggle_plug"},
])
def test_bad_commands_never_reach_device(connected, body):
    client, service, store, devices = connected
    before = service.snapshot()
    assert client.patch("/api/state", json=body).status_code == 422
    assert not devices[0].writes
    assert service.snapshot() == before


def test_all_controls_read_back_actual_state_and_offline_does_not_queue(connected):
    client, service, store, devices = connected
    patch = {"power": True, "temp": 24, "mode": "heat", "speed": "high", "direction": "swing"}
    result = client.patch("/api/state", json=patch)
    assert result.status_code == 200 and result.json()["state"] == patch
    driver = devices[0]
    driver.offline = True
    failed = client.patch("/api/state", json={"temp": 23})
    assert failed.status_code == 503
    assert not failed.json()["snapshot"]["connected"]
    assert driver.writes == [patch]
    driver.offline = False
    refreshed = client.post("/api/refresh", json={})
    assert refreshed.json()["connected"]
    assert refreshed.json()["state"]["temp"] == 24
    assert driver.writes == [patch]
    assert client.patch("/api/state", json={"power": False}).json()["state"]["power"] is False


def test_partial_failure_returns_actual_state_without_optimistic_success(connected):
    client, service, store, devices = connected
    devices[0].partial_failure = True
    result = client.patch("/api/state", json={"power": True, "temp": 22})
    assert result.status_code == 502
    actual = result.json()["snapshot"]
    assert actual["connected"] and actual["state"]["power"] is True
    assert actual["state"]["temp"] == 26
    assert len(devices[0].writes) == 1


@pytest.mark.parametrize("ip", ["127.0.0.1", "8.8.8.8", "169.254.169.254", "localhost", "::1", "192.168.1.20/path"])
def test_connection_only_accepts_lan_ipv4(harness, ip):
    client, service, store, devices = harness
    response = client.post("/api/device", json={"ip": ip, "token": "a" * 32})
    assert response.status_code == 422
    assert not devices and store.settings is None


def test_validation_redacts_tokens_and_private_files_are_not_served(harness):
    client, *_ = harness
    invalid = "secret-do-not-return"
    response = client.post("/api/device", json={"ip": "192.168.1.20", "token": invalid})
    assert response.status_code == 422 and invalid not in response.text
    response = client.post("/api/device", json={"ip": "192.168.1.20", "token": {"secret": invalid}})
    assert response.status_code == 422 and invalid not in response.text
    for path in ("/.local/device.json", "/backend/settings.py", "/requirements.txt", "/../backend/models.py", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_request_origin_and_content_guards(harness):
    client, *_ = harness
    for method, path in (("POST", "/api/discover"), ("PATCH", "/api/state"), ("POST", "/api/device")):
        assert client.request(method, path, json={}, headers={"Origin": "https://example.com"}).status_code == 403
    assert client.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/api/discover", json={}, headers={"X-Aira-Request": "0"}).status_code == 403
    assert client.post("/api/discover", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/api/device", content="x" * 9000, headers={"Content-Type": "application/json"}).status_code == 413
    assert client.get("/api/status", headers={"Origin": "http://127.0.0.1"}).status_code == 200


def test_read_only_discovery_is_bounded_and_rate_limited(harness):
    client, service, store, devices = harness
    found = client.post("/api/discover", json={})
    assert found.json() == {"devices": [{"ip": "192.168.1.20", "deviceId": "1234"}]}
    assert not devices and store.settings is None
    assert client.post("/api/discover", json={}).status_code == 429


def test_snapshot_is_detached_and_device_operations_are_serial(connected):
    client, service, store, devices = connected
    detached = service.snapshot()
    detached["state"]["temp"] = 99
    detached["capabilities"]["directions"].append("up")
    assert service.snapshot()["state"]["temp"] == 26
    assert service.snapshot()["capabilities"]["directions"] == ["fixed", "swing"]
    driver = devices[0]
    read = driver.read
    guard = threading.Lock()
    active = peak = 0

    def delayed_read():
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(.01)
        result = read()
        with guard:
            active -= 1
        return result

    driver.read = delayed_read
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: service.refresh(), range(10)))
    assert peak == 1


def test_static_pages_and_security_headers(harness):
    client, *_ = harness
    for url in ("/", "/setup", "/setup.js", "/setup.css"):
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"
        assert "connect-src 'self'" in response.headers["content-security-policy"]
