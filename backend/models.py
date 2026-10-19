"""前后端唯一的设备能力和输入约定。"""

import ipaddress
import re
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

MODEL = "lumi.acpartner.mcn02"
CAPABILITIES = {
    "temperature": {"min": 16, "max": 30, "step": 1},
    "modes": ["cool", "heat", "dry", "fan", "auto"],
    "speeds": ["auto", "low", "medium", "high"],
    "directions": ["fixed", "swing"],
    "roomTemperature": False,
    "humidity": False,
}
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class DeviceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ip: str
    token: SecretStr = Field(repr=False)

    @field_validator("ip")
    @classmethod
    def private_ip(cls, value: str) -> str:
        address = ipaddress.IPv4Address(value.strip())
        if not any(address in network for network in PRIVATE_NETWORKS):
            raise ValueError("请填写设备的局域网 IPv4 地址")
        return str(address)

    @field_validator("token")
    @classmethod
    def valid_token(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[a-fA-F0-9]{32}", value.get_secret_value()):
            raise ValueError("Token 应为 32 位十六进制字符")
        return value


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ip: str
    token: SecretStr | None = Field(default=None, repr=False)


class StatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    power: bool | None = None
    temp: int | None = Field(default=None, ge=16, le=30)
    mode: Literal["cool", "heat", "dry", "fan", "auto"] | None = None
    speed: Literal["auto", "low", "medium", "high"] | None = None
    direction: Literal["fixed", "swing"] | None = None

    @model_validator(mode="after")
    def valid_patch(self):
        values = self.model_dump(exclude_unset=True)
        if not values or any(value is None for value in values.values()):
            raise ValueError("请提供有效的控制项")
        if values.get("power") is False and len(values) > 1:
            raise ValueError("关机指令不能同时更改其他设置")
        return self


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimerInput(BaseModel):
    """定时任务：在 due（Unix 秒）执行一次开机或关机。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["on", "off"]
    due: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_due(self):
        lead = self.due - int(time.time())
        if lead < 30 or lead > 24 * 3600:
            raise ValueError("定时时间需在 30 秒到 24 小时之间")
        return self


class DeviceFailure(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
