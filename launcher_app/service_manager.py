"""
MailHub 启动器核心服务模块：
1. 路径解析与单实例互斥锁；
2. 依赖检查（Python / .venv / requirements.txt / frontend/dist）与缺失自动安装；
3. Windows Job Object 进程树强绑定守护（启动器关闭时保证 uvicorn 不残留）；
4. FastAPI 本地服务生命周期控制、健康检查与浏览器唤醒。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Callable, Optional
import urllib.error
import urllib.request
import webbrowser

logger = logging.getLogger("MailHubLauncher.Service")

HOST = "127.0.0.1"
PORT = 8765
APP_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{APP_URL}/api/v1/health"
TSINGHUA_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

# 必须安装的后端 Python 模块：(导入模块名, pip 包名)
REQUIRED_IMPORTS: list[tuple[str, str]] = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("sqlalchemy", "sqlalchemy"),
    ("pydantic", "pydantic"),
    ("pydantic_settings", "pydantic-settings"),
    ("cryptography", "cryptography"),
    ("imapclient", "imapclient"),
    ("aiosmtplib", "aiosmtplib"),
    ("httpx", "httpx"),
    ("multipart", "python-multipart"),
    ("email_validator", "email-validator"),
]

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

LogCallback = Callable[[str, str, Optional[str], str], None]
ProgressCallback = Callable[[int], None]


def is_frozen() -> bool:
    """判断当前是否处于 PyInstaller 打包后的独立可执行程序模式。"""
    return bool(getattr(sys, "frozen", False))


def resolve_project_root(start_dir: Optional[Path] = None) -> Path:
    """
    解析 MailHub 项目根目录（包含 backend/app/main.py）。
    打包为 exe 时优先以可执行文件所在目录为基准，兼容向上回溯查找。
    """
    if start_dir is not None:
        candidates = [start_dir, *start_dir.parents]
    elif is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        candidates = [exe_dir, *exe_dir.parents]
    else:
        module_root = Path(__file__).resolve().parent.parent
        candidates = [module_root, Path.cwd(), *Path.cwd().parents]

    for candidate in candidates:
        if (candidate / "backend" / "app" / "main.py").is_file():
            return candidate

    return candidates[0]


def resolve_asset_path(rel_path: str) -> Path:
    """
    解析启动器内置资源路径（支持 PyInstaller _MEIPASS 单文件解包与源码直跑）。
    """
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        base_dir = Path(getattr(sys, "_MEIPASS")) / "assets"
    else:
        base_dir = Path(__file__).resolve().parent / "assets"
    return base_dir / rel_path


def build_utf8_env() -> dict[str, str]:
    """构造强制 UTF-8 输出的子进程环境变量，避免中文路径或编码异常。"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class SingleInstanceGuard:
    """基于 Windows 命名互斥锁的启动器单实例守卫。"""

    def __init__(self, mutex_name: str = "Global\\MailHubLauncherSingleInstanceMutex") -> None:
        self._mutex_name = mutex_name
        self._handle: Optional[int] = None
        self.already_running: bool = False

    def acquire(self) -> bool:
        """尝试获取全局互斥锁；若已有实例运行则返回 False。"""
        if os.name != "nt":
            return True
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.restype = wintypes.DWORD

        handle = kernel32.CreateMutexW(None, False, self._mutex_name)
        last_err = kernel32.GetLastError()
        self._handle = handle
        error_already_exists = 183
        if last_err == error_already_exists:
            self.already_running = True
            return False
        return True

    def release(self) -> None:
        """释放互斥锁句柄。"""
        if os.name == "nt" and self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


# Windows Job Object C 结构体定义（兼容 32/64 位）
class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsJobGuard:
    """
    Windows Job Object 守卫：
    设置 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE，将子进程树与启动器进程强绑定，
    保证无论启动器正常退出还是意外终止，后端 uvicorn 进程都不会变成孤儿进程。
    """

    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    def __init__(self) -> None:
        self._job_handle: Optional[int] = None
        if os.name == "nt":
            self._init_job()

    def _init_job(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            logger.warning("Failed to create Windows Job Object.")
            return

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            job,
            self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            logger.warning("Failed to configure JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.")
            kernel32.CloseHandle(job)
            return
        self._job_handle = job

    def assign_pid(self, pid: int) -> bool:
        """将指定 PID 的进程加入当前 Job Object。"""
        if os.name != "nt" or not self._job_handle or pid <= 0:
            return False
        kernel32 = ctypes.windll.kernel32
        process_all_access = 0x1F0FFF
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

        proc_handle = kernel32.OpenProcess(process_all_access, False, pid)
        if not proc_handle:
            logger.warning("Failed to open process PID=%d for Job Object assignment.", pid)
            return False
        try:
            ok = bool(kernel32.AssignProcessToJobObject(self._job_handle, proc_handle))
            if not ok:
                logger.warning("AssignProcessToJobObject failed for PID=%d.", pid)
            return ok
        finally:
            kernel32.CloseHandle(proc_handle)

    def close(self) -> None:
        """关闭 Job 句柄，触发系统清理所有绑定子进程。"""
        if os.name == "nt" and self._job_handle:
            ctypes.windll.kernel32.CloseHandle(self._job_handle)
            self._job_handle = None


@dataclass
class EnvironmentCheckResult:
    """环境与依赖检测汇总结构。"""

    python_exe: str
    python_version: str
    venv_created: bool
    missing_packages: list[str]
    frontend_ready: bool
    account_count: int


class DependencyService:
    """负责自动检测电脑环境、创建虚拟环境及安装缺失前后端依赖。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.backend_dir = project_root / "backend"
        self.frontend_dir = project_root / "frontend"
        self.venv_dir = self.backend_dir / ".venv"
        self.venv_python = self.venv_dir / "Scripts" / "python.exe"
        self.requirements_file = self.backend_dir / "requirements.txt"

    @staticmethod
    def _probe_python_version(python_exe: str) -> Optional[str]:
        """校验目标可执行文件是否为有效 Python >= 3.10，并返回版本字符串。"""
        try:
            proc = subprocess.run(
                [
                    python_exe,
                    "-c",
                    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=CREATE_NO_WINDOW,
                env=build_utf8_env(),
            )
            if proc.returncode != 0:
                return None
            ver = proc.stdout.strip()
            parts = ver.split(".")
            if len(parts) >= 2 and (int(parts[0]), int(parts[1])) >= (3, 10):
                return ver
            return None
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            logger.debug("Probe python failed for %s: %s", python_exe, exc)
            return None

    def find_system_python(self) -> Optional[tuple[str, str]]:
        """查找本机已安装的 Python 3.10+ 可执行文件路径及版本号。"""
        candidates: list[str] = []

        # 非打包状态下，当前运行 Python 也是高优先级候选
        if not is_frozen() and sys.executable:
            candidates.append(sys.executable)

        # 通过 py 启动器探测
        py_launcher = shutil.which("py")
        if py_launcher:
            try:
                proc = subprocess.run(
                    [py_launcher, "-3", "-c", "import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    candidates.append(proc.stdout.strip())
            except (OSError, subprocess.SubprocessError):
                pass

        for cmd in ("python", "python3"):
            found = shutil.which(cmd)
            if found:
                candidates.append(found)

        # 常见 Windows Python / Conda 安装位置回退
        local_app = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        for base in (local_app / "Programs" / "Python", program_files):
            if base.exists():
                for py_dir in sorted(base.glob("Python3*"), reverse=True):
                    candidates.append(str(py_dir / "python.exe"))

        seen: set[str] = set()
        for path in candidates:
            norm = os.path.normcase(os.path.abspath(path))
            if norm in seen or not os.path.isfile(path):
                continue
            seen.add(norm)
            ver = self._probe_python_version(path)
            if ver:
                return path, ver
        return None

    def install_python_via_winget(self, output_cb: Optional[Callable[[str], None]] = None) -> bool:
        """当电脑完全没有 Python 时，尝试调用 winget 自动安装 Python 3.12。"""
        winget = shutil.which("winget")
        if not winget:
            logger.error("winget not available; cannot auto-install Python.")
            return False

        cmd = [
            winget,
            "install",
            "-e",
            "--id",
            "Python.Python.3.12",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--silent",
        ]
        rc = self._run_streaming_command(cmd, cwd=self.project_root, output_cb=output_cb)
        return rc == 0

    def ensure_python_and_venv(
        self,
        output_cb: Optional[Callable[[str], None]] = None,
    ) -> tuple[str, str, bool]:
        """
        确保 backend/.venv 存在且可用。
        返回值：(python_exe, version, newly_created)
        """
        if self.venv_python.is_file():
            ver = self._probe_python_version(str(self.venv_python))
            if ver:
                return str(self.venv_python), ver, False

        found = self.find_system_python()
        if found is None:
            installed = self.install_python_via_winget(output_cb=output_cb)
            if installed:
                found = self.find_system_python()

        if found is None:
            raise RuntimeError("未检测到可用的 Python 3.10+ 环境，请安装 Python 后重试。")

        sys_python, sys_ver = found
        logger.info("Creating virtual environment at %s using %s", self.venv_dir, sys_python)
        proc = subprocess.run(
            [sys_python, "-m", "venv", str(self.venv_dir)],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
            env=build_utf8_env(),
        )
        if proc.returncode != 0 or not self.venv_python.is_file():
            err_msg = (proc.stderr or proc.stdout or "创建虚拟环境失败").strip()
            raise RuntimeError(f"创建虚拟环境失败：{err_msg}")

        ver = self._probe_python_version(str(self.venv_python)) or sys_ver
        return str(self.venv_python), ver, True

    @staticmethod
    def check_missing_packages(python_exe: str) -> list[str]:
        """在目标 Python 环境中检测必需第三方包，返回缺失的 pip 包名列表。"""
        modules_json = json.dumps([mod for mod, _ in REQUIRED_IMPORTS])
        script = (
            "import importlib, json, sys;"
            f"mods = {modules_json};"
            "missing = [];"
            "\nfor m in mods:\n"
            "    try:\n"
            "        importlib.import_module(m)\n"
            "    except Exception:\n"
            "        missing.append(m)\n"
            "print(json.dumps(missing))\n"
        )
        proc = subprocess.run(
            [python_exe, "-c", script],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
            env=build_utf8_env(),
        )
        if proc.returncode != 0:
            logger.warning("Package probe returned %d: %s", proc.returncode, proc.stderr)
            return [pkg for _, pkg in REQUIRED_IMPORTS]

        try:
            missing_mods = json.loads(proc.stdout.strip() or "[]")
        except json.JSONDecodeError:
            return [pkg for _, pkg in REQUIRED_IMPORTS]

        mod_to_pkg = dict(REQUIRED_IMPORTS)
        return [mod_to_pkg[m] for m in missing_mods if m in mod_to_pkg]

    @staticmethod
    def _run_streaming_command(
        cmd: list[str],
        cwd: Path,
        output_cb: Optional[Callable[[str], None]] = None,
    ) -> int:
        """执行命令并实时按行回传 stdout/stderr，避免长耗时安装无反馈。"""
        logger.info("Running command: %s (cwd=%s)", " ".join(cmd), cwd)
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            env=build_utf8_env(),
        )
        if proc.stdout is not None:
            for line in proc.stdout:
                cleaned = line.rstrip()
                if cleaned:
                    logger.debug("[cmd] %s", cleaned)
                    if output_cb is not None:
                        output_cb(cleaned)
        return proc.wait()

    def build_pip_install_cmd(self, python_exe: str, use_mirror: bool = False) -> list[str]:
        """构造安装后端依赖的 pip 命令。"""
        cmd = [
            python_exe,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(self.requirements_file),
        ]
        if use_mirror:
            cmd.extend(["-i", TSINGHUA_PYPI_MIRROR, "--trusted-host", "pypi.tuna.tsinghua.edu.cn"])
        return cmd

    def install_backend_dependencies(
        self,
        python_exe: str,
        output_cb: Optional[Callable[[str], None]] = None,
        mirror_fallback_cb: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        自动安装缺失的后端 Python 依赖；
        默认源失败时自动切换清华镜像源重试一次。
        """
        if not self.requirements_file.is_file():
            raise FileNotFoundError(f"未找到依赖清单：{self.requirements_file}")

        rc = self._run_streaming_command(
            self.build_pip_install_cmd(python_exe, use_mirror=False),
            cwd=self.backend_dir,
            output_cb=output_cb,
        )
        if rc != 0:
            logger.warning("Default PyPI install failed (rc=%d), switching to mirror.", rc)
            if mirror_fallback_cb is not None:
                mirror_fallback_cb()
            rc = self._run_streaming_command(
                self.build_pip_install_cmd(python_exe, use_mirror=True),
                cwd=self.backend_dir,
                output_cb=output_cb,
            )
        if rc != 0:
            raise RuntimeError(f"自动安装后端依赖失败（退出码 {rc}），请检查网络连接。")

        remaining = self.check_missing_packages(python_exe)
        if remaining:
            raise RuntimeError(f"安装完成后仍缺少以下组件：{', '.join(remaining)}")

    def is_frontend_built(self) -> bool:
        """检查编译后的前端静态页面是否存在。"""
        return (self.frontend_dir / "dist" / "index.html").is_file()

    def build_frontend_dist(self, output_cb: Optional[Callable[[str], None]] = None) -> None:
        """当 frontend/dist 缺失时，调用 npm 自动安装并构建前端。"""
        npm_cmd = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm_cmd:
            raise RuntimeError("前端构建产物缺失且系统未安装 Node.js / npm，无法自动构建。")

        if not (self.frontend_dir / "node_modules").exists():
            rc_install = self._run_streaming_command(
                [npm_cmd, "install"],
                cwd=self.frontend_dir,
                output_cb=output_cb,
            )
            if rc_install != 0:
                raise RuntimeError("npm install 执行失败，请检查前端依赖配置。")

        rc_build = self._run_streaming_command(
            [npm_cmd, "run", "build"],
            cwd=self.frontend_dir,
            output_cb=output_cb,
        )
        if rc_build != 0 or not self.is_frontend_built():
            raise RuntimeError("前端构建（npm run build）未能产出 dist/index.html。")

    def count_mail_accounts(self) -> int:
        """以只读方式统计本地 SQLite 数据库中已配置的邮箱账号数量。"""
        db_path = self.project_root / "data" / "mailhub.db"
        if not db_path.is_file():
            return 0
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
                )
                if cur.fetchone() is None:
                    return 0
                cur.execute("SELECT COUNT(*) FROM accounts")
                row = cur.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("Could not query local accounts table: %s", exc)
            return 0


class MailHubServiceController:
    """
    负责启动、健康检测、在线守护以及优雅关闭 MailHub FastAPI 本地服务。
    """

    def __init__(self, project_root: Path, port: int = PORT) -> None:
        self.project_root = project_root
        self.backend_dir = project_root / "backend"
        self.port = port
        self.app_url = f"http://{HOST}:{port}"
        self.health_url = f"{self.app_url}/api/v1/health"
        self.process: Optional[subprocess.Popen[str]] = None
        self.managed_by_launcher: bool = False
        self._job_guard: Optional[WindowsJobGuard] = None
        self._log_thread: Optional[threading.Thread] = None

    @staticmethod
    def is_port_open(host: str = HOST, port: int = PORT) -> bool:
        """检查本地服务端口是否已被监听。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.6)
            return sock.connect_ex((host, port)) == 0

    @staticmethod
    def is_service_healthy(health_url: str = HEALTH_URL) -> bool:
        """请求 /api/v1/health 接口并验证返回 status == ok。"""
        try:
            with urllib.request.urlopen(health_url, timeout=1.5) as resp:
                if resp.status != 200:
                    return False
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                return payload.get("status") == "ok"
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return False

    def is_running(self) -> bool:
        """判断由启动器管理的后端进程是否仍然存活（或外部健康实例在线）。"""
        if self.process is not None:
            return self.process.poll() is None
        return self.managed_by_launcher is False and self.is_service_healthy(self.health_url)

    def start_service(
        self,
        python_exe: str,
        server_log_cb: Optional[Callable[[str], None]] = None,
        timeout_sec: float = 25.0,
    ) -> str:
        """
        启动 FastAPI 服务。
        返回状态标识：
        - "already_running": 已有健康的 MailHub 服务在线；
        - "started": 本启动器成功拉起新服务并已通过健康检查。
        """
        if self.is_service_healthy(self.health_url):
            self.managed_by_launcher = False
            logger.info("Existing MailHub service detected at %s", self.app_url)
            return "already_running"

        if self.is_port_open(HOST, self.port):
            raise RuntimeError(
                f"端口 {self.port} 已被其他程序占用，且未响应 MailHub 健康检查。"
            )

        self.stop_service()
        self._job_guard = WindowsJobGuard()

        cmd = [
            python_exe,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            HOST,
            "--port",
            str(self.port),
        ]
        logger.info("Launching MailHub backend: %s", " ".join(cmd))
        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.backend_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            env=build_utf8_env(),
        )
        self.managed_by_launcher = True
        self._job_guard.assign_pid(self.process.pid)

        self._start_log_pump(self.process, server_log_cb)

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"后端服务在启动过程中意外退出（退出码 {self.process.returncode}）。"
                )
            if self.is_service_healthy(self.health_url):
                logger.info("MailHub service is healthy at %s", self.app_url)
                return "started"
            time.sleep(0.3)

        self.stop_service()
        raise RuntimeError("MailHub 后端服务启动超时，未能通过健康检查。")

    def _start_log_pump(
        self,
        proc: subprocess.Popen[str],
        server_log_cb: Optional[Callable[[str], None]],
    ) -> None:
        """异步读取 uvicorn 进程输出，防止管道阻塞并筛选关键日志转发给 UI。"""

        def _pump() -> None:
            if proc.stdout is None:
                return
            for line in proc.stdout:
                cleaned = line.rstrip()
                if not cleaned:
                    continue
                logger.info("[uvicorn] %s", cleaned)
                if server_log_cb is not None:
                    # 屏蔽启动器自身健康轮询产生的 access 日志刷屏
                    if "/api/v1/health" in cleaned and "200 OK" in cleaned:
                        continue
                    if any(
                        key in cleaned
                        for key in ("ERROR", "CRITICAL", "Traceback", "Application startup complete")
                    ):
                        server_log_cb(cleaned)

        self._log_thread = threading.Thread(target=_pump, name="uvicorn-log-pump", daemon=True)
        self._log_thread.start()

    @staticmethod
    def open_browser(url: str = APP_URL) -> None:
        """使用系统默认浏览器打开 MailHub 网页端。"""
        logger.info("Opening browser at %s", url)
        webbrowser.open(url)

    def stop_service(self) -> None:
        """干净关闭由本启动器托管的 uvicorn 服务进程树与 Job Object。"""
        if self.process is not None:
            pid = self.process.pid
            if self.process.poll() is None:
                logger.info("Stopping MailHub backend PID=%d ...", pid)
                try:
                    self.process.terminate()
                    self.process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    logger.warning("Terminate timed out for PID=%d; forcing taskkill.", pid)
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/T", "/F", "/PID", str(pid)],
                            capture_output=True,
                            creationflags=CREATE_NO_WINDOW,
                        )
                    else:
                        self.process.kill()
                except OSError as exc:
                    logger.warning("Error while terminating PID=%d: %s", pid, exc)
            self.process = None

        if self._job_guard is not None:
            self._job_guard.close()
            self._job_guard = None
        self.managed_by_launcher = False
