import pytest

from backend.device import parse_status


@pytest.mark.parametrize("mode", ["auto", "dry", "wind"])
def test_zero_temperature_in_modes_without_a_target_stays_unknown(mode):
    state, telemetry = parse_status(["on", mode, 0, "small_fan", "off", 18.0])
    assert state["power"] is True
    assert state["temp"] is None
    assert telemetry["temperature"] is None


def test_absent_target_does_not_disconnect_or_block_other_controls(connected):
    client, _, _, devices = connected
    driver = devices[0]
    driver.state.update(power=True, mode="auto", temp=None)
    assert client.post("/api/refresh", json={}).json()["connected"]
    response = client.patch("/api/state", json={"temp": 24})
    assert response.status_code == 422
    assert response.json()["snapshot"]["connected"]
    assert driver.writes == []
    assert client.patch("/api/state", json={"speed": "high"}).json()["connected"]
    assert client.patch("/api/state", json={"mode": "cool", "temp": 24}).json()["state"]["temp"] == 24
