import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import __version__, project_instance

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("aira_launcher", ROOT / "launch.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_launcher_refuses_other_folder_before_starting_or_stopping(monkeypatch):
    info = {"service": "aira", "ok": True, "instance": "another-project", "version": __version__}
    monkeypatch.setattr(launcher, "server_info", lambda address: info)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Must not start over another service"))
    monkeypatch.setattr(launcher, "api", lambda *args, **kwargs: pytest.fail("Must not stop another service"))
    for option in (["--no-browser"], ["--stop"]):
        monkeypatch.setattr(launcher.sys, "argv", ["launch.py", *option])
        with pytest.raises(RuntimeError, match="Another AIRA"):
            launcher.main()


def test_same_folder_old_build_can_be_stopped_but_not_reused():
    info = {"instance": project_instance(launcher.ROOT), "version": "0.0.0"}
    with pytest.raises(RuntimeError, match="updated version"):
        launcher.check_instance(info)
    launcher.check_instance(info, stopping=True)


def test_dependency_file_change_synchronizes_an_importable_environment(tmp_path, monkeypatch):
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"test executable placeholder")
    (tmp_path / "requirements.txt").write_text("example==1\n", encoding="utf-8")
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("example==1\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "PYTHON", python)
    monkeypatch.setattr(launcher, "LOCAL", tmp_path / ".local")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    launcher.prepare()
    assert sum("install" in command for command in commands) == 1
    launcher.prepare()
    assert sum("install" in command for command in commands) == 1
    constraints.write_text("example==2\n", encoding="utf-8")
    launcher.prepare()
    assert sum("install" in command for command in commands) == 2


def test_health_identifies_project_without_exposing_a_filesystem_path(harness):
    client, *_ = harness
    health = client.get("/api/health").json()
    assert health["version"] == __version__
    assert health["instance"] == project_instance(ROOT)
    assert str(ROOT) not in str(health)
