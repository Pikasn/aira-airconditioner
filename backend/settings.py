"""凭据只保存于本机；Windows 使用当前用户的 DPAPI 加密 Token。"""

import base64
import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

from .models import DeviceSettings


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("当前凭据存储需要 Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = DataBlob()
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError("本机凭据加密或解密失败")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> DeviceSettings | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("未知配置版本")
        token = _dpapi(base64.b64decode(data["protectedToken"], validate=True), decrypt=True).decode("ascii")
        return DeviceSettings(ip=data["ip"], token=token)

    def save(self, settings: DeviceSettings) -> None:
        protected = _dpapi(settings.token.get_secret_value().encode("ascii"))
        payload = {"version": 1, "ip": settings.ip, "protectedToken": base64.b64encode(protected).decode("ascii")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix="device-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
