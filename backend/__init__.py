"""AIRA 的本机空调伴侣服务。"""

import hashlib
import sys
from pathlib import Path

__version__ = "1.6.2"


def application_root() -> Path:
    """可写状态在程序旁，打包后的资源独立放在内部目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def asset_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", application_root()))


def project_instance(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).casefold().encode("utf-8")).hexdigest()[:20]
