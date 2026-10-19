"""串行访问设备，保存可核对的状态；断线时不缓存待执行的控制。

定时任务同样由本机服务执行：即使主窗口隐藏（悬浮条/浮球），到点仍会下发一次控制。
"""

import copy
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .device import CompanionDriver
from .models import CAPABILITIES, MODEL, ConnectionInput, DeviceFailure, DeviceSettings, StatePatch
from .settings import SettingsStore

TIMER_MIN_LEAD = 30
TIMER_MAX_LEAD = 24 * 3600
TIMER_RETRY_DELAY = 20
TIMER_MAX_RETRIES = 2


class DeviceService:
    def __init__(self, store: SettingsStore, driver_factory=CompanionDriver, timer_path=None):
        self.store = store
        self.driver_factory = driver_factory
        self._lock = threading.Lock()
        self._operations = threading.Lock()
        self._shutdown = threading.Event()
        self._thread = None
        self._settings = self._driver = self._state = None
        self._identified = False
        self._info = {"model": MODEL}
        self._telemetry = {"temperature": None, "humidity": None, "watts": None}
        self._connected = False
        self._last_seen = None
        self._error = None
        self._timer_path = Path(timer_path) if timer_path else None
        self._timer = self._load_timer()
        try:
            self._settings = store.load()
            if self._settings:
                self._driver = driver_factory(self._settings)
        except Exception:
            self._settings = None
            self._error = {"code": "config_unreadable", "message": "保存的连接信息无法读取，请重新连接"}

    # ------------------------------------------------------------------ 定时
    def _load_timer(self):
        if not self._timer_path or not self._timer_path.exists():
            return None
        try:
            data = json.loads(self._timer_path.read_text(encoding="utf-8"))
            action = data.get("action")
            due = data.get("due")
            retries = data.get("retries", 0)
            if action not in ("on", "off") or type(due) is not int or type(retries) is not int:
                raise ValueError
            return {
                "action": action,
                "due": due,
                "retries": max(0, min(TIMER_MAX_RETRIES, retries)),
            }
        except (OSError, ValueError, TypeError):
            return None

    def _write_timer(self) -> None:
        """调用方需持有 _lock。写入失败时抛出 OSError。"""
        if not self._timer_path:
            return
        self._timer_path.parent.mkdir(parents=True, exist_ok=True)
        if self._timer is None:
            try:
                self._timer_path.unlink()
            except FileNotFoundError:
                pass
            return
        descriptor, temporary = tempfile.mkstemp(prefix="timer-", suffix=".tmp", dir=self._timer_path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(self._timer, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._timer_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _timer_view_locked(self):
        if not self._timer:
            return None
        view = {
            "action": self._timer["action"],
            "due": int(self._timer["due"]),
            "remaining": max(0, int(self._timer["due"] - time.time())),
            "failed": bool(self._timer.get("failed")),
        }
        if self._timer.get("error"):
            view["error"] = self._timer["error"]
        return view

    def timer(self):
        with self._lock:
            return self._timer_view_locked()

    def set_timer(self, action: str, due: int) -> dict:
        if not self._settings or not self._driver:
            raise DeviceFailure("not_configured", "请先连接空调伴侣", 409)
        if action not in ("on", "off"):
            raise DeviceFailure("invalid_timer", "定时动作不正确", 422)
        now = int(time.time())
        lead = int(due) - now
        if lead < TIMER_MIN_LEAD or lead > TIMER_MAX_LEAD:
            raise DeviceFailure("invalid_timer", "定时时间需在 30 秒到 24 小时之间", 422)
        with self._lock:
            self._timer = {"action": action, "due": int(due), "retries": 0}
            try:
                self._write_timer()
            except OSError:
                self._timer = None
                raise DeviceFailure("timer_save_failed", "无法保存定时设置，请检查目录权限", 500) from None
        return self.snapshot()

    def clear_timer(self) -> dict:
        with self._lock:
            self._timer = None
            try:
                self._write_timer()
            except OSError:
                pass
        return self.snapshot()

    def _timer_delay(self):
        with self._lock:
            if not self._timer or self._timer.get("failed"):
                return None
            return max(0.0, self._timer["due"] - time.time())

    def _check_timer(self) -> None:
        with self._lock:
            timer = self._timer
            if not timer or timer.get("failed") or timer["due"] > time.time():
                return
            action, retries = timer["action"], timer.get("retries", 0)
            self._timer = None
            try:
                self._write_timer()
            except OSError:
                pass
        try:
            self.control(StatePatch(power=(action == "on")))
        except DeviceFailure as error:
            if retries < TIMER_MAX_RETRIES:
                # 设备忙/暂时离线时保留定时，稍后再执行，避免静默失败。
                with self._lock:
                    self._timer = {
                        "action": action,
                        "due": int(time.time()) + TIMER_RETRY_DELAY,
                        "retries": retries + 1,
                        "error": error.message,
                    }
                    try:
                        self._write_timer()
                    except OSError:
                        pass
            else:
                # 重试用尽：保留一条失败记录，让界面明确显示失败，而不是误报“已执行”。
                with self._lock:
                    self._timer = {
                        "action": action,
                        "due": int(time.time()),
                        "retries": retries + 1,
                        "failed": True,
                        "error": "定时执行失败，请检查设备后手动处理",
                    }
                    try:
                        self._write_timer()
                    except OSError:
                        pass

    # ------------------------------------------------------------------ 状态
    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy({
                "configured": self._settings is not None,
                "connected": self._connected,
                "device": {**self._info, "ip": self._settings.ip if self._settings else None},
                "tokenSaved": self._settings is not None,
                "capabilities": CAPABILITIES,
                "state": self._state,
                "telemetry": self._telemetry,
                "lastSeen": self._last_seen,
                "error": self._error,
                "timer": self._timer_view_locked(),
            })

    def _record(self, state: dict, telemetry: dict) -> None:
        with self._lock:
            self._record_locked(state, telemetry)

    def _record_locked(self, state: dict, telemetry: dict) -> None:
        self._state, self._telemetry = state, telemetry
        self._connected = True
        self._last_seen = datetime.now(timezone.utc).isoformat()
        self._error = None

    def _ensure_identified(self) -> None:
        if self._identified:
            return
        try:
            info = self._driver.identify()
        except DeviceFailure as error:
            self._unavailable(error)
            raise
        with self._lock:
            self._info = info
        self._identified = True

    @contextmanager
    def _write_operation(self):
        if not self._operations.acquire(blocking=False):
            raise DeviceFailure("device_busy", "设备正在处理其他操作，请稍后再试", 409)
        try:
            if self._shutdown.is_set():
                raise DeviceFailure("service_stopping", "服务正在停止", 503)
            yield
        finally:
            self._operations.release()

    def _unavailable(self, error: DeviceFailure) -> None:
        with self._lock:
            self._connected = False
            self._error = {"code": error.code, "message": error.message}

    def configure(self, connection: ConnectionInput) -> dict:
        with self._write_operation():
            token = connection.token
            if token is None or not token.get_secret_value():
                token = self._settings.token if self._settings else None
            try:
                settings = DeviceSettings(ip=connection.ip, token=token)
            except ValidationError:
                raise DeviceFailure("invalid_connection", "请填写局域网 IP 和 32 位 Token", 422) from None
            candidate = self.driver_factory(settings)
            info = candidate.identify()
            state, telemetry = candidate.read()
            # 连接验证通过后再保存，失败不会覆盖原有连接。
            try:
                self.store.save(settings)
            except Exception:
                raise DeviceFailure("save_failed", "无法保存本机连接信息，请检查目录权限", 500) from None
            with self._lock:
                self._settings, self._driver, self._info = settings, candidate, info
                self._identified = True
                self._record_locked(state, telemetry)
                # 换了一台设备后，旧的定时不再有意义。
                if self._timer:
                    self._timer = None
                    try:
                        self._write_timer()
                    except OSError:
                        pass
        return self.snapshot()

    def refresh(self) -> dict:
        with self._operations:
            if not self._driver:
                return self.snapshot()
            try:
                self._ensure_identified()
                self._record(*self._driver.read())
            except DeviceFailure as error:
                self._unavailable(error)
        return self.snapshot()

    def control(self, command: StatePatch) -> dict:
        patch = command.model_dump(exclude_unset=True)
        with self._write_operation():
            if not self._driver:
                raise DeviceFailure("not_configured", "请先连接空调伴侣", 409)
            self._ensure_identified()
            write_attempted = False
            try:
                current, telemetry = self._driver.read()
                self._record(current, telemetry)
                if "temp" in patch and current["temp"] is None and patch.get("mode", current["mode"]) not in ("cool", "heat"):
                    raise DeviceFailure("temperature_unavailable", "当前模式没有设定温度，请先切换制冷或制热", 422)
                write_attempted = True
                self._driver.apply(patch, current)
                state, telemetry = self._driver.read()
                if any(state[key] != value for key, value in patch.items()):
                    # 部分固件状态更新稍慢，只重读一次，绝不重发控制。
                    time.sleep(.35)
                    state, telemetry = self._driver.read()
                self._record(state, telemetry)
                if any(state[key] != value for key, value in patch.items()):
                    raise DeviceFailure("not_confirmed", "设备尚未确认新设置，已同步当前状态", 502)
            except DeviceFailure as error:
                if error.code == "temperature_unavailable":
                    raise
                if write_attempted:
                    try:
                        self._record(*self._driver.read())
                    except DeviceFailure as read_error:
                        self._unavailable(read_error)
                else:
                    self._unavailable(error)
                raise error
        return self.snapshot()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._poll, name="aira-device-poll", daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        failures = 0
        while not self._shutdown.is_set():
            try:
                self._check_timer()
                status = self.refresh()
                failures = 0 if status["connected"] or not status["configured"] else failures + 1
            except Exception:
                self._unavailable(DeviceFailure("read_failed", "设备状态读取失败，请稍后重试"))
                failures += 1
            wait = min(30, 5 * 2 ** min(failures, 3))
            delay = self._timer_delay()
            if delay is not None:
                wait = min(wait, max(1.0, delay))
            if self._shutdown.wait(wait):
                break

    def stop(self) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)
