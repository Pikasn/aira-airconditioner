"""Windows 双击入口。后台服务隐藏运行，开关都通过本机服务核对。"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from pathlib import Path

from backend import __version__, project_instance

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOCAL = ROOT / ".local"


def api(address: str, path: str, *, post: bool = False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        address + path, data=b"{}" if post else None,
        headers={"Content-Type": "application/json", "X-Aira-Request": "1"},
    )
    with opener.open(request, timeout=2) as response:
        return json.load(response)


def server_info(address: str) -> dict | None:
    try:
        result = api(address, "/api/health")
        return result if result.get("service") == "aira" and result.get("ok") is True else None
    except (OSError, ValueError):
        return None


def healthy(address: str) -> bool:
    info = server_info(address)
    return bool(info and info.get("instance") == project_instance(ROOT) and info.get("version") == __version__)


def check_instance(info: dict, *, stopping: bool = False) -> None:
    if info.get("instance") != project_instance(ROOT):
        raise RuntimeError("Another AIRA folder or an older service is using this port. Stop that service or choose --port.")
    if not stopping and info.get("version") != __version__:
        raise RuntimeError("Stop the running AIRA service before starting this updated version.")


def prepare() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or newer is required.")
    LOCAL.mkdir(exist_ok=True)
    if not PYTHON.exists():
        venv.EnvBuilder(with_pip=False).create(ROOT / ".venv")
    fingerprint = hashlib.sha256((ROOT / "requirements.txt").read_bytes() + b"\x00" + (ROOT / "constraints.txt").read_bytes()).hexdigest()
    marker = LOCAL / "requirements.sha256"
    installed = marker.read_text(encoding="ascii").strip() if marker.exists() else None
    with (LOCAL / "install.log").open("a", encoding="utf-8") as log:
        check = subprocess.run([str(PYTHON), "-c", "import fastapi, uvicorn, miio"], stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        if check.returncode or installed != fingerprint:
            print("Preparing AIRA for the first run...")
            subprocess.run(
                [sys.executable, "-m", "pip", "--python", str(PYTHON), "install", "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt")],
                check=True, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            marker.write_text(fingerprint + "\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start or stop AIRA")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    address = f"http://127.0.0.1:{args.port}"
    info = server_info(address)
    if info:
        check_instance(info, stopping=args.stop)
    if args.stop:
        if info:
            api(address, "/api/shutdown", post=True)
            for _ in range(30):
                if not server_info(address):
                    print("AIRA stopped.")
                    return
                time.sleep(.2)
            raise RuntimeError("AIRA is still stopping. Please retry shortly.")
        print("AIRA is not running.")
        return
    if not healthy(address):
        prepare()
        with (LOCAL / "server.log").open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(PYTHON), "-m", "backend", "--port", str(args.port)], cwd=ROOT,
                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        for _ in range(60):
            if healthy(address):
                break
            if process.poll() is not None:
                raise RuntimeError("AIRA could not start. Check .local/server.log or whether the port is in use.")
            time.sleep(.25)
        else:
            raise RuntimeError("AIRA startup timed out. See .local/server.log.")
    if not args.no_browser:
        try:
            path = "/" if api(address, "/api/status").get("configured") else "/setup"
        except (OSError, ValueError):
            path = "/setup"
        webbrowser.open(address + path)
    print(f"AIRA is ready: {address}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"AIRA: {error}", file=sys.stderr)
        sys.exit(1)
