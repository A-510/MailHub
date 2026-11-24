"""MailHub 启动器核心逻辑单元测试。"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from unittest.mock import patch

from launcher_app.service_manager import (
    TSINGHUA_PYPI_MIRROR,
    DependencyService,
    MailHubServiceController,
    WindowsJobGuard,
    resolve_asset_path,
    resolve_project_root,
)
from launcher_app.shinku_lines import SHINKU


def test_project_root_and_assets_resolution() -> None:
    """验证能正确解析项目根目录与内部 UI 素材路径。"""
    root = resolve_project_root()
    assert (root / "backend" / "app" / "main.py").is_file()
    assert resolve_asset_path("backdrop_clean.png").is_file()
    assert resolve_asset_path("app_icon.ico").is_file()
    assert resolve_asset_path("app_icon.png").is_file()
    assert resolve_asset_path("icons/icon_console.png").is_file()
    assert resolve_asset_path("icons/icon_close.svg").is_file()


def test_shinku_dialogs_complete() -> None:
    """确保所有二阶堂真红文案字段均已配置且非空。"""
    for f in fields(SHINKU):
        val = getattr(SHINKU, f.name)
        assert isinstance(val, str) and len(val.strip()) > 0, f"Empty line: {f.name}"


def test_check_missing_packages_against_project_venv() -> None:
    """验证当前项目 .venv 中所有后端依赖检查通过，且伪造缺失模块能被检出。"""
    root = resolve_project_root()
    dep = DependencyService(root)
    assert dep.venv_python.is_file()
    missing = dep.check_missing_packages(str(dep.venv_python))
    assert missing == []

    # 测试不存在的虚拟模块检测逻辑
    fake_imports = [("non_existent_xyz_module_12345", "non-existent-pkg")]
    with patch("launcher_app.service_manager.REQUIRED_IMPORTS", fake_imports):
        missing_fake = dep.check_missing_packages(str(dep.venv_python))
        assert missing_fake == ["non-existent-pkg"]


def test_pip_install_fallback_to_tsinghua_mirror(tmp_path: Path) -> None:
    """验证主 PyPI 源安装失败时自动切换至清华镜像重试。"""
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "requirements.txt").write_text("fastapi>=0.115.0\n", encoding="utf-8")

    dep = DependencyService(tmp_path)
    calls: list[list[str]] = []
    mirror_notified = []

    def fake_run(cmd: list[str], cwd: Path, output_cb=None) -> int:  # type: ignore[no-untyped-def]
        calls.append(cmd)
        # 第一次默认源失败，第二次清华源成功
        return 1 if len(calls) == 1 else 0

    with (
        patch.object(dep, "_run_streaming_command", side_effect=fake_run),
        patch.object(dep, "check_missing_packages", return_value=[]),
    ):
        dep.install_backend_dependencies(
            python_exe="python.exe",
            mirror_fallback_cb=lambda: mirror_notified.append(True),
        )

    assert len(calls) == 2
    assert TSINGHUA_PYPI_MIRROR not in calls[0]
    assert TSINGHUA_PYPI_MIRROR in calls[1]
    assert mirror_notified == [True]


def test_count_mail_accounts_safe(tmp_path: Path) -> None:
    """验证在数据库缺失与存在时均能安全统计邮箱账号数。"""
    dep_missing = DependencyService(tmp_path)
    assert dep_missing.count_mail_accounts() == 0

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_file = data_dir / "mailhub.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT)")
    conn.execute("INSERT INTO accounts (email) VALUES ('a@example.com'), ('b@example.com')")
    conn.commit()
    conn.close()

    assert dep_missing.count_mail_accounts() == 2


def test_windows_job_guard_kills_child_on_close() -> None:
    """验证 Windows Job Object 关闭时能自动连带结束绑定子进程。"""
    if sys.platform != "win32":
        return

    guard = WindowsJobGuard()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assigned = guard.assign_pid(proc.pid)
        assert assigned is True
        assert proc.poll() is None
        guard.close()
        # Job 关闭后系统会立即终止关联进程
        exit_code = proc.wait(timeout=5)
        assert exit_code is not None
    finally:
        if proc.poll() is None:
            proc.kill()
        guard.close()


def test_port_and_health_check_negative() -> None:
    """验证未监听端口时端口检测和健康检查返回 False 而不抛异常。"""
    assert MailHubServiceController.is_port_open("127.0.0.1", 59998) is False
    assert MailHubServiceController.is_service_healthy("http://127.0.0.1:59998/api/v1/health") is False


def test_service_controller_real_spawn_and_clean_stop() -> None:
    """验证真实拉起 MailHub 后端服务并通过健康检查，关闭后干净释放端口。"""
    root = resolve_project_root()
    dep = DependencyService(root)
    assert dep.venv_python.is_file()

    test_port = 18765
    ctrl = MailHubServiceController(root, port=test_port)
    try:
        status = ctrl.start_service(str(dep.venv_python), timeout_sec=20.0)
        assert status == "started"
        assert ctrl.is_service_healthy(ctrl.health_url) is True
        assert ctrl.is_running() is True
    finally:
        ctrl.stop_service()

    # 确认释放后端口已不再监听
    for _ in range(10):
        if not MailHubServiceController.is_port_open("127.0.0.1", test_port):
            break
        time.sleep(0.2)
    assert MailHubServiceController.is_port_open("127.0.0.1", test_port) is False


def test_build_browser_url_adds_cache_buster() -> None:
    """验证启动器打开本地入口时自动追加防缓存时间戳参数，同时保留自带查询参数。"""
    busted = MailHubServiceController.build_browser_url("http://127.0.0.1:8765")
    assert busted.startswith("http://127.0.0.1:8765?v=")
    assert busted.split("?v=", 1)[1].isdigit()

    preserved = MailHubServiceController.build_browser_url("http://127.0.0.1:8765?tour=1")
    assert preserved == "http://127.0.0.1:8765?tour=1"

    opened_urls: list[str] = []
    with patch("launcher_app.service_manager.webbrowser.open", side_effect=lambda u: opened_urls.append(u)):
        MailHubServiceController.open_browser("http://127.0.0.1:8765")
    assert len(opened_urls) == 1
    assert opened_urls[0].startswith("http://127.0.0.1:8765?v=")
