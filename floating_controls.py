"""悬浮控件共用设备服务：合并快速调温，断线后不保留待执行指令。"""
import threading
import time
import math

from backend.models import DeviceFailure, StatePatch


class FloatingControls:
    def __init__(self, service):
        self.service = service
        self._condition = threading.Condition()
        self._pending, self._inflight = {}, {}
        self._ready = 0
        self._deadline = 0
        self._closed = False
        self.error_until = 0
        self._thread = threading.Thread(target=self._run, name='floating-controls', daemon=True)
        self._thread.start()

    def snapshot(self):
        snapshot = self.service.snapshot()
        with self._condition:
            if not snapshot['connected']:
                self._pending.clear()
            elif snapshot.get('state'):
                snapshot['state'].update(self._inflight)
                snapshot['state'].update(self._pending)
        return snapshot

    def submit(self, patch):
        checked = StatePatch(**patch).model_dump(exclude_unset=True)
        if not self.service.snapshot()['connected']: return False
        with self._condition:
            if self._closed: return False
            if self._pending.get('power') is False and checked.get('power') is not True and checked.get('power') is not False:return False
            if checked.get('power') is False: self._pending = {'power': False}
            else: self._pending.update(checked)
            self._ready = time.monotonic() + (0 if checked.get('power') is False else .18)
            self._deadline = time.monotonic() + 5
            self._condition.notify()
        return True

    def adjust(self, step):
        snapshot = self.snapshot()
        state = snapshot.get('state') or {}
        temperature = state.get('temp')
        if not snapshot['connected'] or not state.get('power') or type(temperature) not in (int, float) or not math.isfinite(temperature): return False
        return self.submit({'temp': max(16, min(30, round(temperature + step)))})

    def _run(self):
        while True:
            with self._condition:
                while not self._closed and (not self._pending or time.monotonic() < self._ready):
                    self._condition.wait(max(.01, self._ready - time.monotonic()) if self._pending else None)
                if self._closed: return
                patch, self._pending = self._pending, {}
                self._inflight = patch
            try:
                if self.service.snapshot()['connected']:
                    self.service.control(StatePatch(**patch))
            except DeviceFailure as error:
                if error.code == 'device_busy':
                    with self._condition:
                        if not self._closed and time.monotonic()<self._deadline and self._pending.get('power') is not False:
                            self._pending = {**patch, **self._pending}
                            self._ready = time.monotonic() + .2
                else: self.error_until = time.monotonic() + 2
            except Exception:
                self.error_until = time.monotonic() + 2
            finally:
                with self._condition:
                    self._inflight = {}

    def close(self):
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify()
