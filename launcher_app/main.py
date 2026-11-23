"""
MailHub 一体化桌面启动器主入口：
- 启动后展现与参考图一致的樱花书房与二阶堂真红主题启动器界面；
- 自动检查本机 Python / .venv / 后端依赖 / 前端构建产物，缺失时自动安装并流式回传进度；
- 依赖就绪后自动拉起 FastAPI 本地服务并自动打开系统默认浏览器；
- 通过 Windows Job Object、防误关拦截弹窗与系统托盘保证服务在线守护。
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile
from typing import Optional

from PyQt6.QtCore import QRect, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QColor, QIcon, QPainter, QPaintEvent, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from launcher_app.service_manager import (
    APP_URL,
    PORT,
    DependencyService,
    MailHubServiceController,
    SingleInstanceGuard,
    resolve_asset_path,
    resolve_project_root,
)
from launcher_app.shinku_lines import SHINKU
from launcher_app.ui_widgets import (
    CANVAS_REF_HEIGHT,
    CANVAS_REF_WIDTH,
    CloseGuardDialog,
    CustomTitleBar,
    ParchmentConsoleWidget,
    SakuraAmbientOverlay,
    SakuraLaunchButton,
)

logger = logging.getLogger("MailHubLauncher.Main")


def _now_ts() -> str:
    """返回当前时间的 HH:MM:SS 字符串。"""
    return datetime.now().strftime("%H:%M:%S")


def setup_launcher_logging(project_root: Path) -> None:
    """配置启动器运行日志文件与控制台日志。"""
    log_dir = project_root / "data"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "launcher.log"
    except OSError:
        log_file = Path(tempfile.gettempdir()) / "mailhub_launcher.log"

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    root_logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root_logger.addHandler(file_handler)
    except OSError:
        pass

    if not getattr(sys, "frozen", False):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(fmt)
        root_logger.addHandler(stream_handler)


class StartupWorker(QThread):
    """后台异步执行依赖检查、缺失自动安装、服务拉起与浏览器唤醒的工作线程。"""

    log_emitted = pyqtSignal(str, str, str, object, str)
    header_changed = pyqtSignal(str)
    status_changed = pyqtSignal(str, str, str)
    progress_changed = pyqtSignal(object)
    startup_succeeded = pyqtSignal(str)
    startup_failed = pyqtSignal(str)

    def __init__(
        self,
        project_root: Path,
        service_ctrl: MailHubServiceController,
        auto_open_browser: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._project_root = project_root
        self._dep_service = DependencyService(project_root)
        self._service_ctrl = service_ctrl
        self._auto_open_browser = auto_open_browser
        self._install_step_counter = 0

    def _emit_log(
        self,
        icon_name: str,
        message: str,
        badge: Optional[str] = None,
        badge_kind: str = "ok",
    ) -> None:
        self.log_emitted.emit(_now_ts(), icon_name, message, badge, badge_kind)

    def _on_pip_output(self, line: str) -> None:
        """筛选 pip 安装过程中的关键进展输出给羊皮纸日志区，避免刷屏。"""
        lower = line.lower()
        if lower.startswith(("collecting ", "downloading ", "installing collected packages", "successfully installed")):
            self._install_step_counter += 1
            pct = min(68, 32 + self._install_step_counter * 3)
            self.progress_changed.emit(pct)
            short = line if len(line) <= 70 else line[:67] + "..."
            self._emit_log("icon_settings", short, None, "info")

    def _on_npm_output(self, line: str) -> None:
        """筛选前端构建关键日志行。"""
        if any(k in line for k in ("vite", "building", "modules transformed", "built in")):
            short = line if len(line) <= 70 else line[:67] + "..."
            self._emit_log("icon_sync", short, None, "info")

    def run(self) -> None:
        try:
            self.header_changed.emit(SHINKU.HEADER_CHECKING)
            self.status_changed.emit("checking", SHINKU.PILL_CHECKING, _now_ts())
            self.progress_changed.emit(8)

            # 1. 真红欢迎语与引导语
            self._emit_log("icon_info", SHINKU.WELCOME_GREETING)
            self._emit_log("icon_settings", SHINKU.CHECK_GUIDE)

            # 2. 检测或建立 Python 虚拟环境
            self.progress_changed.emit(16)
            if not self._dep_service.venv_python.is_file():
                sys_py = self._dep_service.find_system_python()
                if sys_py is None:
                    self.header_changed.emit(SHINKU.HEADER_INSTALLING)
                    self.status_changed.emit("installing", SHINKU.PILL_INSTALLING, _now_ts())
                    self._emit_log("icon_warning", SHINKU.PYTHON_SYSTEM_MISSING, "…", "busy")
                else:
                    self._emit_log("icon_settings", SHINKU.PYTHON_MISSING_INSTALLING, "…", "busy")

            python_exe, py_ver, venv_created = self._dep_service.ensure_python_and_venv()
            if venv_created:
                self._emit_log("icon_check", SHINKU.VENV_READY, "✓ OK", "ok")
            self._emit_log(
                "icon_folder",
                SHINKU.PYTHON_OK_TEMPLATE.format(version=py_ver),
                "✓ OK",
                "ok",
            )
            self.progress_changed.emit(28)

            # 3 & 4. 检测或自动安装后端核心依赖与前端静态资源
            missing_pkgs = self._dep_service.check_missing_packages(python_exe)
            frontend_built = self._dep_service.is_frontend_built()

            if not missing_pkgs and frontend_built:
                self._emit_log("icon_link", SHINKU.ALL_DEPS_AND_FRONTEND_OK, "✓ OK", "ok")
                self.progress_changed.emit(72)
            else:
                if not missing_pkgs:
                    self._emit_log("icon_link", SHINKU.BACKEND_DEPS_OK, "✓ OK", "ok")
                else:
                    preview_names = ", ".join(missing_pkgs[:4])
                    if len(missing_pkgs) > 4:
                        preview_names += f" 等 {len(missing_pkgs)} 项"
                    self.header_changed.emit(SHINKU.HEADER_INSTALLING)
                    self.status_changed.emit("installing", SHINKU.PILL_INSTALLING, _now_ts())
                    self._emit_log(
                        "icon_warning",
                        SHINKU.BACKEND_DEPS_MISSING_TEMPLATE.format(
                            count=len(missing_pkgs),
                            names=preview_names,
                        ),
                        "…",
                        "busy",
                    )
                    self._dep_service.install_backend_dependencies(
                        python_exe=python_exe,
                        output_cb=self._on_pip_output,
                        mirror_fallback_cb=lambda: self._emit_log(
                            "icon_sync",
                            SHINKU.BACKEND_DEPS_FALLBACK_MIRROR,
                            "…",
                            "busy",
                        ),
                    )
                    self._emit_log("icon_check", SHINKU.BACKEND_DEPS_INSTALLED, "✓ OK", "ok")

                self.progress_changed.emit(72)

                if frontend_built:
                    self._emit_log("icon_folder", SHINKU.FRONTEND_DIST_OK, "✓ OK", "ok")
                else:
                    self.header_changed.emit(SHINKU.HEADER_INSTALLING)
                    self.status_changed.emit("installing", SHINKU.PILL_INSTALLING, _now_ts())
                    self._emit_log("icon_warning", SHINKU.FRONTEND_DIST_MISSING, "…", "busy")
                    self._dep_service.build_frontend_dist(output_cb=self._on_npm_output)
                    self._emit_log("icon_check", SHINKU.FRONTEND_DIST_BUILT, "✓ OK", "ok")

            self.progress_changed.emit(82)

            # 5. 检测本地数据库与邮箱数量
            account_count = self._dep_service.count_mail_accounts()
            if account_count > 0:
                self._emit_log(
                    "icon_mail",
                    SHINKU.DATABASE_ACCOUNTS_TEMPLATE,
                    f"({account_count} 件)",
                    "ok",
                )
            else:
                self._emit_log("icon_mail", SHINKU.DATABASE_FIRST_RUN, "✓ OK", "ok")

            # 6. 启动本地 FastAPI 服务
            self.header_changed.emit(SHINKU.HEADER_CHECKING)
            self.status_changed.emit("starting", SHINKU.PILL_STARTING, _now_ts())
            self.progress_changed.emit(90)
            self._emit_log("icon_sync", SHINKU.STARTING_SERVICE)

            status_flag = self._service_ctrl.start_service(
                python_exe=python_exe,
                server_log_cb=lambda line: self._emit_log("icon_info", line, None, "info"),
            )

            self.progress_changed.emit(100)
            if status_flag == "already_running":
                self._emit_log("icon_check", SHINKU.SERVICE_ALREADY_RUNNING, "✓ OK", "ok")
            else:
                self._emit_log("icon_check", SHINKU.SERVICE_STARTED_OPENING_BROWSER, "✓ OK", "ok")

            self._emit_log("icon_info", SHINKU.KEEP_ONLINE_REMINDER)
            if self._auto_open_browser:
                self._service_ctrl.open_browser(self._service_ctrl.app_url)

            self.header_changed.emit(SHINKU.HEADER_RUNNING)
            self.status_changed.emit("running", SHINKU.PILL_RUNNING, _now_ts())
            self.startup_succeeded.emit(status_flag)

        except Exception as exc:
            logger.exception("Startup pipeline failed")
            detail = str(exc) or exc.__class__.__name__
            self.header_changed.emit(SHINKU.HEADER_ERROR)
            self.status_changed.emit("error", SHINKU.PILL_ERROR, _now_ts())
            self.progress_changed.emit(None)
            self._emit_log(
                "icon_warning",
                SHINKU.ERROR_COMFORT_TEMPLATE.format(detail=detail),
                "✕ 异常",
                "error",
            )
            self.startup_failed.emit(detail)


class LauncherCanvasWidget(QWidget):
    """
    主体视觉画布容器：
    绘制清理后的 1672x899 参考底图，并按等比缩放坐标精准放置羊皮纸命令行面板、
    底部樱花粉启动按钮与边缘飘落樱花动效层。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backdrop = QPixmap(str(resolve_asset_path("backdrop_clean.png")))
        self._canvas_rect = QRect(0, 0, int(CANVAS_REF_WIDTH * 0.72), int(CANVAS_REF_HEIGHT * 0.72))

        self.console = ParchmentConsoleWidget(self)
        self.launch_button = SakuraLaunchButton(SHINKU.BTN_LAUNCH, self)
        self.ambient_overlay = SakuraAmbientOverlay(self)
        self.ambient_overlay.raise_()

    def _compute_canvas_rect(self) -> QRect:
        """按 1672:899 比例计算居中画布绘制区域，避免角色立绘拉伸变形。"""
        w = float(self.width())
        h = float(self.height())
        if w <= 0 or h <= 0:
            return QRect(0, 0, 1, 1)

        target_ratio = CANVAS_REF_WIDTH / CANVAS_REF_HEIGHT
        current_ratio = w / h
        if current_ratio >= target_ratio:
            draw_h = h
            draw_w = h * target_ratio
            offset_x = (w - draw_w) / 2.0
            offset_y = 0.0
        else:
            draw_w = w
            draw_h = w / target_ratio
            offset_x = 0.0
            offset_y = (h - draw_h) / 2.0

        return QRect(int(round(offset_x)), int(round(offset_y)), int(round(draw_w)), int(round(draw_h)))

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._canvas_rect = self._compute_canvas_rect()
        r = self._canvas_rect

        # 羊皮纸终端区域（精确对齐 reference_launcher.png 内部安全框）
        console_x = r.x() + int(round(r.width() * (522.0 / CANVAS_REF_WIDTH)))
        console_y = r.y() + int(round(r.height() * ((310.0 - 42.0) / CANVAS_REF_HEIGHT)))
        console_w = int(round(r.width() * ((1096.0 - 522.0) / CANVAS_REF_WIDTH)))
        console_h = int(round(r.height() * ((638.0 - 310.0) / CANVAS_REF_HEIGHT)))
        self.console.setGeometry(console_x, console_y, console_w, console_h)
        self.console.apply_scale(r.width() / CANVAS_REF_WIDTH)

        # 底部粉色主按钮（精确嵌在两侧金色装饰短线中间）
        btn_x = r.x() + int(round(r.width() * (583.0 / CANVAS_REF_WIDTH)))
        btn_y = r.y() + int(round(r.height() * ((700.0 - 42.0) / CANVAS_REF_HEIGHT)))
        btn_w = int(round(r.width() * ((1089.0 - 583.0) / CANVAS_REF_WIDTH)))
        btn_h = int(round(r.height() * (98.0 / CANVAS_REF_HEIGHT)))
        self.launch_button.setGeometry(btn_x, btn_y, btn_w, btn_h)

        # 边缘花瓣与微光层对齐画布矩形
        self.ambient_overlay.setGeometry(r)
        self.ambient_overlay.raise_()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#FDF4FC"))

        if not self._backdrop.isNull():
            painter.drawPixmap(
                QRectF(self._canvas_rect),
                self._backdrop,
                QRectF(self._backdrop.rect()),
            )


class LauncherMainWindow(QMainWindow):
    """MailHub 启动器主窗口（集成自定义标题栏、自动初始化、在线守护与系统托盘）。"""

    def __init__(
        self,
        project_root: Path,
        port: int = PORT,
        dry_run_ui: bool = False,
        auto_open_browser: bool = True,
        screenshot_out: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self._project_root = project_root
        self._port = port
        self._dry_run_ui = dry_run_ui
        self._auto_open_browser = auto_open_browser
        self._screenshot_out = screenshot_out
        self._service_ctrl = MailHubServiceController(project_root, port=port)
        self._worker: Optional[StartupWorker] = None
        self._force_exit = False
        self._is_running_state = False
        self._tray_hint_shown = False

        self.setWindowTitle(SHINKU.WINDOW_TITLE)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self._app_icon = QIcon(str(resolve_asset_path("app_icon.ico")))
        if self._app_icon.isNull():
            self._app_icon = QIcon(str(resolve_asset_path("app_icon.png")))
        self.setWindowIcon(self._app_icon)

        # 按参考画布 1672x941 的 0.72 倍设置初始尺寸（1204x678），适合常见屏幕
        self.resize(1204, 678)
        self.setMinimumSize(920, 520)

        central = QWidget(self)
        central.setObjectName("MainShell")
        central.setStyleSheet("#MainShell { border: 1px solid #D9C4E7; background: #FDF4FC; }")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(1, 1, 1, 1)
        root_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(central)
        self.canvas = LauncherCanvasWidget(central)
        root_layout.addWidget(self.title_bar)
        root_layout.addWidget(self.canvas, 1)

        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_toggled.connect(self._toggle_maximize)
        self.title_bar.close_clicked.connect(self.close)
        self.canvas.launch_button.clicked.connect(self._on_launch_button_clicked)

        self._setup_tray()

        # 运行期进程心跳检测（每 4 秒核查本地服务是否意外退出）
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(4000)
        self._heartbeat_timer.timeout.connect(self._check_service_heartbeat)

        if self._dry_run_ui:
            self._populate_dry_run_preview()
        else:
            QTimer.singleShot(120, self.start_pipeline)

        if self._screenshot_out is not None:
            if self._dry_run_ui:
                QTimer.singleShot(1400, self._capture_and_exit)
            else:
                # 真实模式下等启动成功且进度条收起后再抓取最终运行态截图
                self._pending_screenshot_timer = QTimer(self)
                self._pending_screenshot_timer.setSingleShot(True)
                self._pending_screenshot_timer.timeout.connect(self._capture_and_exit)
                QTimer.singleShot(18000, self._capture_and_exit)  # 兜底超时截图

    def _setup_tray(self) -> None:
        """初始化系统托盘图标与右键菜单，确保服务可后台常驻在线。"""
        self.tray_icon = QSystemTrayIcon(self._app_icon, self)
        self.tray_icon.setToolTip(SHINKU.TRAY_TOOLTIP_STOPPED)

        menu = QMenu(self)
        act_show = menu.addAction("显示启动器窗口")
        act_open = menu.addAction("打开 MailHub 网页端")
        menu.addSeparator()
        act_restart = menu.addAction("重启本地服务")
        act_exit = menu.addAction("停止服务并退出")

        act_show.triggered.connect(self.restore_from_tray)
        act_open.triggered.connect(lambda: self._service_ctrl.open_browser(self._service_ctrl.app_url))
        act_restart.triggered.connect(self._restart_service_action)
        act_exit.triggered.connect(self.shutdown_and_exit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def restore_from_tray(self) -> None:
        """从系统托盘恢复并前置主窗口。"""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.canvas.ambient_overlay.set_paused(False)

    def _minimize_to_tray(self) -> None:
        """隐藏主窗口至系统托盘，保持后端服务继续运行。"""
        self.canvas.ambient_overlay.set_paused(True)
        self.hide()
        if not self._tray_hint_shown and self.tray_icon.isVisible():
            self._tray_hint_shown = True
            self.tray_icon.showMessage(
                SHINKU.TRAY_MINIMIZED_TITLE,
                SHINKU.TRAY_MINIMIZED_MSG,
                self._app_icon,
                3500,
            )

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _populate_dry_run_preview(self) -> None:
        """填充静态预览模式日志（仅用于视觉验收比对，不启动真实进程）。"""
        ts = "10:24:16"
        console = self.canvas.console
        console.clear_logs()
        console.set_header_title(SHINKU.HEADER_CHECKING)
        console.append_log(ts, "icon_info", SHINKU.WELCOME_GREETING)
        console.append_log(ts, "icon_settings", SHINKU.CHECK_GUIDE)
        console.append_log("10:24:17", "icon_folder", SHINKU.PYTHON_OK_TEMPLATE.format(version="3.12.12"), "✓ OK", "ok")
        console.append_log("10:24:17", "icon_link", SHINKU.BACKEND_DEPS_OK, "✓ OK", "ok")
        console.append_log("10:24:18", "icon_mail", SHINKU.DATABASE_ACCOUNTS_TEMPLATE, "(5 件)", "ok")
        console.append_log("10:24:19", "icon_check", SHINKU.SERVICE_STARTED_OPENING_BROWSER, "✓ OK", "ok")
        console.append_log("10:24:19", "icon_info", SHINKU.KEEP_ONLINE_REMINDER)
        console.set_status_pill("ready", SHINKU.PILL_PREVIEW, "10:24:20")
        self.canvas.launch_button.set_busy_mode(False, SHINKU.BTN_LAUNCH)

    def start_pipeline(self) -> None:
        """发起一轮完整的依赖自检、缺失自动安装与服务启动流程。"""
        if self._worker is not None and self._worker.isRunning():
            return

        self._is_running_state = False
        self._heartbeat_timer.stop()
        self.canvas.console.clear_logs()
        self.canvas.launch_button.set_busy_mode(True, SHINKU.BTN_CHECKING)

        self._worker = StartupWorker(
            project_root=self._project_root,
            service_ctrl=self._service_ctrl,
            auto_open_browser=self._auto_open_browser,
            parent=self,
        )
        self._worker.log_emitted.connect(self.canvas.console.append_log)
        self._worker.header_changed.connect(self.canvas.console.set_header_title)
        self._worker.status_changed.connect(self._on_status_changed)
        self._worker.progress_changed.connect(self.canvas.console.set_progress)
        self._worker.startup_succeeded.connect(self._on_startup_succeeded)
        self._worker.startup_failed.connect(self._on_startup_failed)
        self._worker.start()

    def _on_status_changed(self, state: str, pill_text: str, ts: str) -> None:
        self.canvas.console.set_status_pill(state, pill_text, ts)
        if state == "installing":
            self.canvas.launch_button.set_busy_mode(True, SHINKU.BTN_INSTALLING)
        elif state == "starting":
            self.canvas.launch_button.set_busy_mode(True, SHINKU.BTN_STARTING)

    def _on_startup_succeeded(self, _flag: str) -> None:
        self._is_running_state = True
        self.canvas.launch_button.set_busy_mode(False, SHINKU.BTN_OPEN_BROWSER)
        self.tray_icon.setToolTip(SHINKU.TRAY_TOOLTIP_RUNNING)
        QTimer.singleShot(900, lambda: self.canvas.console.set_progress(None))
        self._heartbeat_timer.start()
        if self._screenshot_out is not None:
            QTimer.singleShot(1100, self._capture_and_exit)

    def _on_startup_failed(self, _detail: str) -> None:
        self._is_running_state = False
        self._heartbeat_timer.stop()
        self.canvas.launch_button.set_busy_mode(False, SHINKU.BTN_RETRY)
        self.tray_icon.setToolTip(SHINKU.TRAY_TOOLTIP_STOPPED)

    def _on_launch_button_clicked(self) -> None:
        if self._dry_run_ui:
            self.canvas.console.append_log(
                _now_ts(),
                "icon_info",
                SHINKU.DRY_RUN_PREVIEW_NOTE,
            )
            return

        if self._is_running_state and self._service_ctrl.is_running():
            self.canvas.console.append_log(_now_ts(), "icon_play", SHINKU.REOPEN_BROWSER_LOG)
            self._service_ctrl.open_browser(self._service_ctrl.app_url)
        else:
            self.start_pipeline()

    def _check_service_heartbeat(self) -> None:
        """定期确认由启动器托管的 uvicorn 进程仍然在线。"""
        if not self._is_running_state:
            return
        if self._service_ctrl.managed_by_launcher and not self._service_ctrl.is_running():
            self._is_running_state = False
            self._heartbeat_timer.stop()
            self.canvas.console.set_header_title(SHINKU.HEADER_ERROR)
            self.canvas.console.set_status_pill("error", SHINKU.PILL_ERROR, _now_ts())
            self.canvas.console.append_log(
                _now_ts(),
                "icon_warning",
                SHINKU.SERVICE_UNEXPECTED_EXIT,
                "✕ 中断",
                "error",
            )
            self.canvas.launch_button.set_busy_mode(False, SHINKU.BTN_RETRY)
            self.tray_icon.setToolTip(SHINKU.TRAY_TOOLTIP_STOPPED)
            if self.isHidden():
                self.restore_from_tray()

    def _restart_service_action(self) -> None:
        self._service_ctrl.stop_service()
        self.restore_from_tray()
        self.start_pipeline()

    def shutdown_and_exit(self) -> None:
        """停止本地服务与子进程树并彻底退出启动器。"""
        self._force_exit = True
        self._heartbeat_timer.stop()
        self.canvas.ambient_overlay.set_paused(True)
        self._service_ctrl.stop_service()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        拦截关闭事件：若服务仍在运行，阻止误关，引导用户最小化到系统托盘保持在线。
        """
        if self._force_exit or self._dry_run_ui:
            self._service_ctrl.stop_service()
            if hasattr(self, "tray_icon"):
                self.tray_icon.hide()
            event.accept()
            return

        if self._is_running_state or (self._worker is not None and self._worker.isRunning()):
            dlg = CloseGuardDialog(self)
            dlg.exec()
            if dlg.chosen_action == CloseGuardDialog.ACTION_TRAY:
                event.ignore()
                self._minimize_to_tray()
                return
            if dlg.chosen_action == CloseGuardDialog.ACTION_EXIT:
                self.shutdown_and_exit()
                event.accept()
                return
            event.ignore()
            return

        self._service_ctrl.stop_service()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        event.accept()

    def _capture_and_exit(self) -> None:
        """调试辅助：抓取当前渲染窗口保存至指定文件后退出。"""
        if self._screenshot_out is not None:
            self._screenshot_out.parent.mkdir(parents=True, exist_ok=True)
            pix = self.grab()
            pix.save(str(self._screenshot_out), "PNG")
            logger.info("Saved launcher screenshot to %s", self._screenshot_out)
        self.shutdown_and_exit()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析启动器命令行参数。"""
    parser = argparse.ArgumentParser(description="MailHub Launcher")
    parser.add_argument(
        "--port",
        type=int,
        default=PORT,
        help="本地服务监听端口（默认 8765）",
    )
    parser.add_argument(
        "--dry-run-ui",
        action="store_true",
        help="仅预览启动器界面，不检测或启动本地服务",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="启动服务成功后不自动打开浏览器",
    )
    parser.add_argument(
        "--screenshot-out",
        type=Path,
        default=None,
        help="自动截取主窗口图像并退出（供视觉验收）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """启动器应用程序入口。"""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    project_root = resolve_project_root()
    setup_launcher_logging(project_root)

    # 设定 Windows AppUserModelID，确保任务栏显示 MailHub 自定义图标而非通用 Python 图标
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "MailHub.Launcher.Desktop.App"
            )
        except (AttributeError, OSError):
            pass

    # 单实例检查（干跑预览、截图或自定义测试端口时不拦截）
    instance_guard = SingleInstanceGuard()
    if not args.dry_run_ui and args.screenshot_out is None and args.port == PORT:
        if not instance_guard.acquire():
            logger.info("Another MailHubLauncher instance is already running; opening browser.")
            target_url = f"http://127.0.0.1:{args.port}"
            if not args.no_browser and MailHubServiceController.is_service_healthy(
                f"{target_url}/api/v1/health"
            ):
                MailHubServiceController.open_browser(target_url)
            return 0

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    icon = QIcon(str(resolve_asset_path("app_icon.ico")))
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = LauncherMainWindow(
        project_root=project_root,
        port=args.port,
        dry_run_ui=args.dry_run_ui,
        auto_open_browser=not args.no_browser,
        screenshot_out=args.screenshot_out,
    )
    window.show()

    exit_code = app.exec()
    instance_guard.release()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
