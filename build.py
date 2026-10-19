"""开发者重新构建入口，运行程序本身不需要 Python 或 Node。"""
import shutil
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__

root = Path(__file__).resolve().parent
node = shutil.which("node")
if node:
    subprocess.run([node, str(root / "frontend" / "build.cjs")], check=True)
else:
    subprocess.run([sys.executable, str(root / "frontend" / "build.py")], check=True)
PyInstaller.__main__.run([
    str(root / "空调.spec"), "--noconfirm", "--distpath", str(root / "dist"),
    "--workpath", str(root / "build"),
])
