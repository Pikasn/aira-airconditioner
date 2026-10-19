"""只发送 miIO 发现报文；不获取或返回任何响应中的 Token。"""

import ipaddress
import socket
import time

from .models import PRIVATE_NETWORKS

HELLO = bytes.fromhex("21310020") + b"\xff" * 28


def parse_hello(data: bytes, ip: str) -> dict | None:
    try:
        address = ipaddress.IPv4Address(ip)
        if not any(address in network for network in PRIVATE_NETWORKS):
            return None
        if len(data) != 32 or data[:4] != bytes.fromhex("21310020"):
            return None
        return {"ip": str(address), "deviceId": str(int.from_bytes(data[8:12], "big"))}
    except ipaddress.AddressValueError:
        return None


def discover_devices(duration: float = 3.0) -> list[dict]:
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
        channel.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        channel.settimeout(.25)
        channel.bind(("0.0.0.0", 0))
        channel.sendto(HELLO, ("255.255.255.255", 54321))
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline and len(found) < 50:
            try:
                data, (ip, port) = channel.recvfrom(1024)
                if port == 54321 and (device := parse_hello(data, ip)):
                    found[ip] = device
            except socket.timeout:
                continue
    return sorted(found.values(), key=lambda item: ipaddress.IPv4Address(item["ip"]))
