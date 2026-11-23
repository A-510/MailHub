"""
MailHub 一键启动器：
自动检测后端服务是否就绪，必要时拉起 FastAPI（同时托管前端静态资源），
并优先使用本机 Chrome/Edge 独立应用窗口模式打开主界面，带来近似原生软件体验。
"""

import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("MailHubLauncher")

HOST = "127.0.0.1"
PORT = 8765
APP_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{APP_URL}/api/v1/health"


def is_port_open(host: str, port: int) -> bool:
    """检查本地端口是否已有服务监听。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_for_health(timeout_sec: float = 20.0) -> bool:
    """轮询健康检查接口直到 FastAPI 就绪。"""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def find_chromium_app_browser() -> str | None:
    """查找本机 Edge 或 Chrome 可执行路径以启用无地址栏应用窗口模式。"""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    for cmd in ("msedge", "chrome"):
        found = shutil.which(cmd)
        if found:
            return found
    return None


def launch_window() -> None:
    """弹出 MailHub 桌面应用窗口，如未检测到 Chromium 则回退系统默认浏览器。"""
    browser_exe = find_chromium_app_browser()
    if browser_exe:
        logger.info("Opening MailHub window via %s", browser_exe)
        subprocess.Popen(
            [browser_exe, f"--app={APP_URL}", "--window-size=1440,900"],
            close_fds=True,
        )
    else:
        logger.info("Opening MailHub in default system browser: %s", APP_URL)
        webbrowser.open(APP_URL)


def main() -> int:
    root_dir = Path(__file__).resolve().parent
    backend_dir = root_dir / "backend"
    venv_python = backend_dir / ".venv" / "Scripts" / "python.exe"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    if is_port_open(HOST, PORT):
        logger.info("MailHub service is already running at %s", APP_URL)
        launch_window()
        return 0

    logger.info("Starting MailHub FastAPI service at %s ...", APP_URL)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    server_proc = subprocess.Popen(
        [
            python_exe,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
        ],
        cwd=str(backend_dir),
        creationflags=creation_flags,
    )

    if not wait_for_health(20.0):
        logger.error("MailHub backend did not become ready in time.")
        server_proc.terminate()
        return 1

    logger.info("MailHub is ready! Launching UI...")
    launch_window()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
