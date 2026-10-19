import json

from backend.models import DeviceSettings
from backend.settings import SettingsStore


def test_windows_encrypted_atomic_settings_round_trip(tmp_path):
    path = tmp_path / "private" / "device.json"
    store = SettingsStore(path)
    assert store.load() is None
    settings = DeviceSettings(ip="192.168.1.20", token="a" * 32)
    store.save(settings)
    text = path.read_text(encoding="utf-8")
    assert "a" * 32 not in text
    assert set(json.loads(text)) == {"version", "ip", "protectedToken"}
    assert store.load() == settings
    assert "a" * 32 not in repr(settings)
    changed = DeviceSettings(ip="192.168.1.21", token="b" * 32)
    store.save(changed)
    assert store.load() == changed
    assert list(path.parent.glob("*.tmp")) == []
