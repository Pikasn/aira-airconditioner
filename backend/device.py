"""米家空调伴侣 2 的局域网适配，只暴露经过核对的五类控制。"""

import math

from miio import Device

from .models import MODEL, DeviceFailure, DeviceSettings

PROPERTIES = ["power", "mode", "tar_temp", "fan_level", "ver_swing", "load_power"]
MODES = {"cool": "cool", "heat": "heat", "dry": "dry", "fan": "wind", "auto": "auto"}
SPEEDS = {"auto": "auto_fan", "low": "small_fan", "medium": "medium_fan", "high": "large_fan"}
DIRECTIONS = {"fixed": "off", "swing": "on"}
SETTERS = {"power": "set_power", "mode": "set_mode", "temp": "set_tar_temp", "speed": "set_fan_level", "direction": "set_ver_swing"}


def parse_status(values: object) -> tuple[dict, dict]:
    try:
        if not isinstance(values, list) or len(values) != 6:
            raise ValueError
        power, mode, temperature, speed, swing, load = values
        if power not in ("on", "off") or type(temperature) not in (int, float):
            raise ValueError
        no_target = temperature == 0 and mode in ("auto", "dry", "wind")
        if not math.isfinite(temperature) or (not no_target and not 16 <= temperature <= 30) or temperature != int(temperature):
            raise ValueError
        state = {
            "power": power == "on", "mode": {v: k for k, v in MODES.items()}[mode],
            "temp": None if no_target else int(temperature), "speed": {v: k for k, v in SPEEDS.items()}[speed],
            "direction": {v: k for k, v in DIRECTIONS.items()}[swing],
        }
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise DeviceFailure("invalid_status", "设备状态无法识别，请先在米家完成空调遥控匹配", 502) from error
    try:
        watts = float(load) if type(load) in (int, float, str) else None
    except (ValueError, TypeError, OverflowError):
        watts = None
    if watts is not None and (not math.isfinite(watts) or watts < 0):
        watts = None
    return state, {"temperature": None, "humidity": None, "watts": watts}


class CompanionDriver:
    def __init__(self, settings: DeviceSettings):
        self.device = Device(settings.ip, settings.token.get_secret_value(), timeout=2)
        # 此参数表示“额外重试次数”，0 才是只发送一次。
        self.device.retry_count = 0
        self._needs_handshake = False

    def _prepare_read(self) -> None:
        if self._needs_handshake:
            self.device.send_handshake()
            self._needs_handshake = False

    def identify(self) -> dict:
        try:
            self._prepare_read()
            info = self.device.info()
            if info.model != MODEL:
                raise DeviceFailure("unsupported_model", "检测到的设备不是米家空调伴侣 2", 422)
            return {"model": info.model, "firmware": info.firmware_version}
        except DeviceFailure:
            raise
        except Exception as error:
            self._needs_handshake = True
            raise DeviceFailure("unreachable", "连接失败，请检查 IP、Token 和同一局域网连接") from error

    def read(self) -> tuple[dict, dict]:
        try:
            self._prepare_read()
            return parse_status(self.device.send("get_prop", PROPERTIES, retry_count=0))
        except DeviceFailure:
            raise
        except Exception as error:
            self._needs_handshake = True
            raise DeviceFailure("unreachable", "设备暂时无法连接，请检查电源和局域网") from error

    def apply(self, patch: dict, current: dict) -> None:
        for key in ("power", "mode", "temp", "speed", "direction"):
            if key not in patch or patch[key] == current[key]:
                continue
            value = patch[key]
            if key == "power":
                value = "on" if value else "off"
            elif key == "mode":
                value = MODES[value]
            elif key == "speed":
                value = SPEEDS[value]
            elif key == "direction":
                value = DIRECTIONS[value]
            try:
                result = self.device.send(SETTERS[key], [value], retry_count=0)
            except Exception as error:
                self._needs_handshake = True
                raise DeviceFailure("command_timeout", "指令未能确认，正在同步设备状态", 502) from error
            if result != ["ok"]:
                raise DeviceFailure("command_rejected", "设备没有接受该指令，请检查米家的空调遥控匹配", 502)
