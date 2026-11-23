"""
MailHub 启动器高保真自定义 UI 控件模块：
- CustomTitleBar：复刻参考图淡紫粉定制标题栏（图标、双语标题、SVG 窗口按钮、拖拽/最大化）；
- ParchmentConsoleWidget：悬浮于羊皮纸便签内部的命令行日志流、状态胶囊与细进度条；
- SakuraLaunchButton：QPainter 矢量绘制樱花粉胶囊启动按钮（四态交互与流光忙碌态）；
- SakuraAmbientOverlay：边缘轻量飘落樱花瓣与微光呼吸层；
- CloseGuardDialog：二阶堂真红防误关守护弹窗。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import html
import math
from pathlib import Path
import random
from typing import Optional

from PyQt6.QtCore import (
    QBuffer,
    QIODevice,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QTextBlockFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from launcher_app.service_manager import resolve_asset_path
from launcher_app.shinku_lines import SHINKU

# 参考画布主体基准尺寸（完整 1672x941 裁去顶部 42px 标题栏）
CANVAS_REF_WIDTH = 1672.0
CANVAS_REF_HEIGHT = 899.0


def pick_cjk_font(candidates: list[str], fallback: str) -> str:
    """从系统已安装字体中选择最匹配的中日文字体，不可用时回退。"""
    available = set(QFontDatabase.families())
    for family in candidates:
        if family in available:
            return family
    return fallback


class WindowControlButton(QPushButton):
    """参考图右上角风格的极简矢量窗口控制按钮（最小化 / 最大化 / 关闭）。"""

    def __init__(
        self,
        kind: str,
        tooltip: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind  # "minimize" | "maximize" | "close"
        self._hovered = False
        self._pressed = False
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(36, 28)
        self.setFlat(True)

    def enterEvent(self, event: object) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        is_close = self._kind == "close"
        if self._pressed:
            bg = QColor(235, 118, 158, 220) if is_close else QColor(222, 198, 238, 185)
            painter.setBrush(bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 7, 7)
        elif self._hovered:
            bg = QColor(246, 174, 204, 200) if is_close else QColor(235, 215, 246, 175)
            painter.setBrush(bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 7, 7)

        stroke_color = QColor("#FFFFFF") if (is_close and self._pressed) else QColor("#58476D")
        pen = QPen(stroke_color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        if self._kind == "minimize":
            painter.drawLine(QPointF(cx - 5.5, cy + 0.5), QPointF(cx + 5.5, cy + 0.5))
        elif self._kind == "maximize":
            painter.drawRect(QRectF(cx - 5.0, cy - 5.0, 10.0, 10.0))
        else:
            painter.drawLine(QPointF(cx - 5.0, cy - 5.0), QPointF(cx + 5.0, cy + 5.0))
            painter.drawLine(QPointF(cx + 5.0, cy - 5.0), QPointF(cx - 5.0, cy + 5.0))


class CustomTitleBar(QWidget):
    """
    1:1 复刻参考图顶部的淡紫粉自定义窗口标题栏。
    支持左键拖动、双击最大化/还原、最小化与触发防误关拦截。
    """

    minimize_clicked = pyqtSignal()
    maximize_toggled = pyqtSignal()
    close_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(38)
        self._drag_offset: Optional[QPoint] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        # 左侧 app_icon.png
        icon_label = QLabel(self)
        icon_pixmap = QPixmap(str(resolve_asset_path("app_icon.png")))
        if not icon_pixmap.isNull():
            icon_label.setPixmap(
                icon_pixmap.scaled(
                    22,
                    22,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        icon_label.setFixedSize(22, 22)
        layout.addWidget(icon_label)

        # 双语标题文字
        ui_font_name = pick_cjk_font(
            ["Yu Gothic UI", "Meiryo UI", "Microsoft YaHei UI", "Noto Sans CJK JP"],
            "Microsoft YaHei UI",
        )
        title_label = QLabel(SHINKU.WINDOW_TITLE, self)
        title_font = QFont(ui_font_name, 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #54426A; background: transparent;")
        layout.addWidget(title_label)

        layout.addStretch(1)

        # 右侧窗口控制按钮
        self.btn_minimize = WindowControlButton("minimize", "最小化", parent=self)
        self.btn_maximize = WindowControlButton("maximize", "最大化 / 还原", parent=self)
        self.btn_close = WindowControlButton("close", "关闭或最小化到托盘", parent=self)

        self.btn_minimize.clicked.connect(self.minimize_clicked.emit)
        self.btn_maximize.clicked.connect(self.maximize_toggled.emit)
        self.btn_close.clicked.connect(self.close_clicked.emit)

        layout.addWidget(self.btn_minimize)
        layout.addWidget(self.btn_maximize)
        layout.addWidget(self.btn_close)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, QColor("#FBF0FD"))
        grad.setColorAt(0.5, QColor("#FDF4FE"))
        grad.setColorAt(1.0, QColor("#F8ECFA"))
        painter.fillRect(self.rect(), grad)

        # 底部分割线
        painter.setPen(QPen(QColor("#DFC8EB"), 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            if win is not None and not win.isMaximized():
                self._drag_offset = event.globalPosition().toPoint() - win.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            win = self.window()
            if win is not None and not win.isMaximized():
                win.move(event.globalPosition().toPoint() - self._drag_offset)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_toggled.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ParchmentConsoleWidget(QWidget):
    """
    悬浮于羊皮纸便签中央的浅色命令行日志流控件：
    1. 顶部薰衣草圆角头栏（>_ 图标 + 动态状态标题）及虚线分割线；
    2. 中部透明只读富文本日志流（[时间戳] + 图标 + 文本 + 状态标记）；
    3. 底部状态胶囊（时间戳 + 语义配色圆角徽标）与按需显示的 4px 进度条。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._scale = 0.72
        self._icon_data_uris: dict[str, str] = {}

        self._ui_font = pick_cjk_font(
            ["Microsoft YaHei UI", "Yu Gothic UI", "Noto Sans CJK SC", "Segoe UI"],
            "Microsoft YaHei UI",
        )
        self._mono_font = pick_cjk_font(
            ["Cascadia Mono", "Consolas", "Noto Sans Mono CJK JP"],
            "Consolas",
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. 顶部终端头栏（右侧留出空间避让参考图右上角的 MAILHUB 圆形邮戳）
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 40, 0)
        self.header_frame = QFrame(self)
        self.header_frame.setObjectName("ConsoleHeaderFrame")
        header_inner = QHBoxLayout(self.header_frame)
        header_inner.setContentsMargins(10, 4, 12, 4)
        header_inner.setSpacing(8)

        self.header_icon = QLabel(self.header_frame)
        console_pix = QPixmap(str(resolve_asset_path("icons/icon_console.png")))
        if not console_pix.isNull():
            self.header_icon.setPixmap(
                console_pix.scaled(
                    22,
                    18,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        header_inner.addWidget(self.header_icon)

        self.header_title = QLabel(SHINKU.HEADER_CHECKING, self.header_frame)
        header_inner.addWidget(self.header_title, 1)

        header_row.addWidget(self.header_frame, 1)
        root.addLayout(header_row)

        # 2. 虚线分割线容器
        self.divider_line = QFrame(self)
        self.divider_line.setFixedHeight(5)
        self.divider_line.setStyleSheet(
            "background: transparent; border: none; border-bottom: 1.5px dashed #E5B4CB;"
        )
        root.addWidget(self.divider_line)
        root.addSpacing(2)

        # 3. 日志流浏览器（透明底色，可划词复制）
        self.log_browser = QTextBrowser(self)
        self.log_browser.setReadOnly(True)
        self.log_browser.setOpenExternalLinks(False)
        self.log_browser.setFrameShape(QFrame.Shape.NoFrame)
        self.log_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_browser.document().setDocumentMargin(2.0)  # type: ignore[union-attr]
        self.log_browser.setStyleSheet(
            """
            QTextBrowser {
                background: transparent;
                border: none;
                color: #4A3963;
                selection-background-color: #F6C8DE;
                selection-color: #3E2B54;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 2px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(196, 134, 174, 0.55);
                border-radius: 3px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(186, 108, 158, 0.85);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            """
        )
        self._register_inline_icons()
        root.addWidget(self.log_browser, 1)

        # 4. 底部状态胶囊栏
        root.addSpacing(4)
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 12, 0)
        status_layout.setSpacing(10)

        self.status_time_label = QLabel("[--:--:--]", self)
        status_layout.addWidget(self.status_time_label)

        self.status_pill = QFrame(self)
        pill_layout = QHBoxLayout(self.status_pill)
        pill_layout.setContentsMargins(10, 3, 12, 3)
        pill_layout.setSpacing(6)

        self.pill_icon_label = QLabel(self.status_pill)
        self.pill_text_label = QLabel(SHINKU.PILL_INITIALIZING, self.status_pill)
        pill_layout.addWidget(self.pill_icon_label)
        pill_layout.addWidget(self.pill_text_label)
        status_layout.addWidget(self.status_pill)
        status_layout.addStretch(1)
        root.addLayout(status_layout)

        # 5. 细进度条（仅在检测/安装/启动阶段展示）
        root.addSpacing(4)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background: rgba(218, 186, 212, 0.35);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #F39AC3, stop:1 #A88DC6
                );
                border-radius: 2px;
            }
            """
        )
        self.progress_bar.hide()
        root.addWidget(self.progress_bar)

        self.set_status_pill("checking", SHINKU.PILL_INITIALIZING, "--:--:--")
        self.apply_scale(0.72)

    def _register_inline_icons(self) -> None:
        """将所有日志小图标编码为内存 PNG Data URI，确保在 QTextBrowser 中跨环境清晰显示。"""
        icon_names = [
            "icon_info",
            "icon_settings",
            "icon_folder",
            "icon_link",
            "icon_sync",
            "icon_check",
            "icon_warning",
            "icon_mail",
            "icon_play",
            "icon_refresh",
        ]
        for name in icon_names:
            path = resolve_asset_path(f"icons/{name}.png")
            if not path.is_file():
                continue
            pix = QPixmap(str(path)).scaled(
                24,
                24,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            pix.save(buf, "PNG")
            encoded = base64.b64encode(bytes(buf.data())).decode("ascii")
            self._icon_data_uris[name] = f"data:image/png;base64,{encoded}"

    def apply_scale(self, scale: float) -> None:
        """随主窗口缩放同步调节字体与头栏高度。"""
        self._scale = max(0.5, min(1.5, scale))
        header_pt = max(9, int(round(11.0 * self._scale / 0.72)))
        log_pt = max(8, int(round(8.2 * self._scale / 0.72)))
        pill_pt = max(8, int(round(8.8 * self._scale / 0.72)))

        self.header_frame.setStyleSheet(
            """
            #ConsoleHeaderFrame {
                background-color: rgba(235, 220, 240, 0.86);
                border: 1px solid rgba(196, 172, 214, 0.45);
                border-radius: 8px;
            }
            """
        )
        h_font = QFont(self._ui_font, header_pt)
        h_font.setWeight(QFont.Weight.Bold)
        self.header_title.setFont(h_font)
        self.header_title.setStyleSheet("color: #4D3B69; background: transparent;")

        b_font = QFont(self._ui_font, log_pt)
        self.log_browser.setFont(b_font)

        t_font = QFont(self._mono_font, log_pt)
        self.status_time_label.setFont(t_font)
        self.status_time_label.setStyleSheet("color: #6E5B88; background: transparent;")

        p_font = QFont(self._ui_font, pill_pt)
        p_font.setWeight(QFont.Weight.DemiBold)
        self.pill_text_label.setFont(p_font)

    def set_header_title(self, text: str) -> None:
        """更新便签头栏状态标题。"""
        self.header_title.setText(text)

    def clear_logs(self) -> None:
        """清空当前日志区。"""
        self.log_browser.clear()

    def append_log(
        self,
        timestamp: str,
        icon_name: str,
        message: str,
        badge_text: Optional[str] = None,
        badge_kind: str = "ok",
    ) -> None:
        """
        向便签命令行流追加一条独立成行的日志记录。
        badge_kind 支持: "ok" / "busy" / "warn" / "error" / "info"
        """
        safe_ts = html.escape(timestamp)
        safe_msg = html.escape(message)

        icon_html = ""
        data_uri = self._icon_data_uris.get(icon_name)
        if data_uri:
            icon_sz = max(11, int(round(13 * self._scale / 0.72)))
            icon_html = (
                f'<img src="{data_uri}" width="{icon_sz}" height="{icon_sz}" '
                'style="vertical-align: middle;">&nbsp;'
            )

        badge_html = ""
        if badge_text:
            color_map = {
                "ok": "#2E8B57",
                "busy": "#B54579",
                "warn": "#C47D2B",
                "error": "#D6456B",
                "info": "#6B578B",
            }
            badge_color = color_map.get(badge_kind, "#2E8B57")
            badge_html = (
                f'&nbsp;&nbsp;<span style="color:{badge_color}; font-weight:600;">'
                f"{html.escape(badge_text)}</span>"
            )

        row_html = (
            f'<span style="font-family:\'{self._mono_font}\', Consolas, monospace; '
            f'color:#6E5B88;">[{safe_ts}]</span>&nbsp;&nbsp;'
            f"{icon_html}"
            f'<span style="color:#4A3963;">{safe_msg}</span>'
            f"{badge_html}"
        )
        doc = self.log_browser.document()
        cursor = self.log_browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        block_fmt = QTextBlockFormat()
        block_fmt.setBottomMargin(1.5)
        block_fmt.setTopMargin(0.0)
        block_fmt.setLineHeight(108.0, 1)  # ProportionalHeight = 1

        if doc is not None and not doc.isEmpty():
            cursor.insertBlock(block_fmt)
        else:
            cursor.setBlockFormat(block_fmt)

        cursor.insertHtml(row_html)
        self.log_browser.setTextCursor(cursor)
        self.log_browser.ensureCursorVisible()

    def set_status_pill(self, state: str, text: str, timestamp: str) -> None:
        """
        切换底部状态胶囊样式与文本。
        state: "checking" | "installing" | "starting" | "ready" | "running" | "error"
        """
        self.status_time_label.setText(f"[{timestamp}]")
        styles = {
            "checking": ("#EFE5F8", "#D7C2EC", "#58476D", "icons/icon_sync.png"),
            "installing": ("#FFE8F1", "#F2B8D2", "#B54579", "icons/icon_settings.png"),
            "starting": ("#EFE5F8", "#CBB3E6", "#58476D", "icons/icon_play.png"),
            "ready": ("#DDF2DF", "#B4DFB8", "#2D8A4E", "icons/icon_check.png"),
            "running": ("#DDF2DF", "#A9DAA8", "#277A44", "icons/icon_check.png"),
            "error": ("#FDE4E8", "#F2B0BD", "#C93A57", "icons/icon_warning.png"),
        }
        bg, border, fg, icon_rel = styles.get(state, styles["checking"])
        self.status_pill.setStyleSheet(
            f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            """
        )
        self.pill_text_label.setStyleSheet(f"color: {fg}; background: transparent; border: none;")
        self.pill_text_label.setText(text)

        pix = QPixmap(str(resolve_asset_path(icon_rel)))
        if not pix.isNull():
            self.pill_icon_label.setPixmap(
                pix.scaled(
                    15,
                    15,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.pill_icon_label.setStyleSheet("background: transparent; border: none;")

    def set_progress(self, value: Optional[int]) -> None:
        """设置或隐藏底部 4px 樱花粉进度条（传 None 时隐藏）。"""
        if value is None:
            self.progress_bar.hide()
            return
        self.progress_bar.setValue(max(0, min(100, value)))
        if not self.progress_bar.isVisible():
            self.progress_bar.show()


class SakuraLaunchButton(QPushButton):
    """
    1:1 矢量绘制参考图底部樱花粉胶囊主按钮：
    外圈玫瑰阴影 + 浅粉描边环 + 立体粉色渐变 + 内圈白色虚线 + 信封图标 + 粗体文字 + 实心播放三角。
    """

    def __init__(self, text: str = SHINKU.BTN_LAUNCH, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self._hovered = False
        self._pressed = False
        self._shimmer_phase = 0.0
        self._font_family = pick_cjk_font(
            ["Yu Gothic UI", "Meiryo UI", "Noto Sans CJK JP", "Microsoft YaHei UI"],
            "Microsoft YaHei UI",
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._shimmer_timer = QTimer(self)
        self._shimmer_timer.setInterval(45)
        self._shimmer_timer.timeout.connect(self._tick_shimmer)

    def set_busy_mode(self, busy: bool, text: str) -> None:
        """切换按钮忙碌禁用态（启用流光动效）或恢复可点击态。"""
        self.setText(text)
        self.setEnabled(not busy)
        if busy:
            self.setCursor(Qt.CursorShape.WaitCursor)
            if not self._shimmer_timer.isActive():
                self._shimmer_timer.start()
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._shimmer_timer.stop()
        self.update()

    def _tick_shimmer(self) -> None:
        self._shimmer_phase = (self._shimmer_phase + 0.035) % 1.4
        if self.isVisible():
            self.update()

    def enterEvent(self, event: object) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        if w <= 10 or h <= 10:
            return

        y_offset = 1.5 if (self._pressed and self.isEnabled()) else (-1.0 if (self._hovered and self.isEnabled()) else 0.0)

        # 1. 柔和玫瑰外阴影
        shadow_rect = QRectF(6.0, 7.0 + y_offset * 0.5, w - 12.0, h - 10.0)
        shadow_rad = shadow_rect.height() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(186, 98, 146, 52 if self.isEnabled() else 28))
        painter.drawRoundedRect(shadow_rect, shadow_rad, shadow_rad)

        # 2. 外圈浅粉柔框
        outer_rect = QRectF(4.0, 3.0 + y_offset, w - 8.0, h - 10.0)
        outer_rad = outer_rect.height() / 2.0
        painter.setBrush(QColor("#FFF0F7"))
        painter.setPen(QPen(QColor("#EEB5CE"), max(1.6, h * 0.025)))
        painter.drawRoundedRect(outer_rect, outer_rad, outer_rad)

        # 3. 内部主体渐变胶囊
        inset = max(3.5, h * 0.055)
        inner_rect = outer_rect.adjusted(inset, inset, -inset, -inset)
        inner_rad = inner_rect.height() / 2.0
        grad = QLinearGradient(inner_rect.topLeft(), inner_rect.bottomLeft())

        if not self.isEnabled():
            grad.setColorAt(0.0, QColor("#E7CBE0"))
            grad.setColorAt(0.55, QColor("#CFA9C8"))
            grad.setColorAt(1.0, QColor("#B98FB4"))
        elif self._pressed:
            grad.setColorAt(0.0, QColor("#DA72A2"))
            grad.setColorAt(0.5, QColor("#CA6193"))
            grad.setColorAt(1.0, QColor("#E488B6"))
        elif self._hovered:
            grad.setColorAt(0.0, QColor("#FFC8E2"))
            grad.setColorAt(0.52, QColor("#F596C2"))
            grad.setColorAt(1.0, QColor("#DF74A7"))
        else:
            grad.setColorAt(0.0, QColor("#FFB5D6"))
            grad.setColorAt(0.52, QColor("#EE84B6"))
            grad.setColorAt(1.0, QColor("#D56499"))

        painter.setBrush(grad)
        painter.setPen(QPen(QColor("#FFF6FB"), max(1.5, h * 0.024)))
        painter.drawRoundedRect(inner_rect, inner_rad, inner_rad)

        # 忙碌态流光扫过特效
        if not self.isEnabled():
            clip = QPainterPath()
            clip.addRoundedRect(inner_rect, inner_rad, inner_rad)
            painter.save()
            painter.setClipPath(clip)
            sweep_x = inner_rect.left() + (self._shimmer_phase - 0.2) * inner_rect.width()
            shimmer = QLinearGradient(sweep_x - 45, 0, sweep_x + 45, 0)
            shimmer.setColorAt(0.0, QColor(255, 255, 255, 0))
            shimmer.setColorAt(0.5, QColor(255, 255, 255, 75))
            shimmer.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(inner_rect, shimmer)
            painter.restore()

        # 4. 白色虚线内环
        dash_inset = max(4.5, h * 0.065)
        dash_rect = inner_rect.adjusted(dash_inset, dash_inset, -dash_inset, -dash_inset)
        dash_pen = QPen(QColor(255, 245, 252, 200), max(1.1, h * 0.016))
        dash_pen.setDashPattern([5.0, 4.5])
        painter.setPen(dash_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(dash_rect, dash_rect.height() / 2.0, dash_rect.height() / 2.0)

        # 5. 文本排版测量（左侧信封 + 文本 + 右侧实心播放三角整体居中）
        font_pt = max(11, int(round(h * 0.30)))
        font = QFont(self._font_family, font_pt)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text_str = self.text()
        text_w = fm.horizontalAdvance(text_str)

        env_w = h * 0.35
        env_h = h * 0.25
        tri_sz = h * 0.19
        gap = h * 0.14
        total_content_w = env_w + gap + text_w + gap + tri_sz
        start_x = inner_rect.center().x() - total_content_w / 2.0
        center_y = inner_rect.center().y()

        # 左侧白色信封图标（微倾角度呼应原画）
        painter.save()
        painter.translate(start_x + env_w / 2.0, center_y)
        painter.rotate(-6.0)
        env_rect = QRectF(-env_w / 2.0, -env_h / 2.0, env_w, env_h)
        painter.setBrush(QColor(255, 255, 255, 245))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(env_rect, 4.0, 4.0)
        # 信封内部粉紫折痕线
        flap_pen = QPen(QColor("#DE72A6"), max(1.6, h * 0.025))
        flap_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        flap_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(flap_pen)
        painter.drawLine(
            QPointF(env_rect.left() + 2.5, env_rect.top() + 2.5),
            QPointF(0.0, 2.0),
        )
        painter.drawLine(
            QPointF(0.0, 2.0),
            QPointF(env_rect.right() - 2.5, env_rect.top() + 2.5),
        )
        painter.restore()

        # 中间文字（带轻微暖粉投影增强立体感）
        text_x = start_x + env_w + gap
        text_rect = QRectF(text_x, inner_rect.top(), text_w + 8.0, inner_rect.height())
        painter.setPen(QColor(156, 54, 102, 110))
        painter.drawText(
            text_rect.translated(0, 1.4),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text_str,
        )
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text_str,
        )

        # 右侧白色实心播放三角
        tri_x = text_x + text_w + gap
        tri_path = QPainterPath()
        tri_path.moveTo(tri_x, center_y - tri_sz * 0.56)
        tri_path.lineTo(tri_x + tri_sz, center_y)
        tri_path.lineTo(tri_x, center_y + tri_sz * 0.56)
        tri_path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPath(tri_path)


@dataclass
class _PetalParticle:
    x_ratio: float
    y_ratio: float
    speed_y: float
    drift_amp: float
    phase: float
    angle: float
    spin: float
    size: float
    opacity: float


@dataclass
class _SparkleNode:
    x_ratio: float
    y_ratio: float
    phase: float
    speed: float
    size: float


class SakuraAmbientOverlay(QWidget):
    """
    边缘轻量化樱花花瓣飘落与星光闪烁透明覆盖层（不拦截鼠标事件，避开中心羊皮纸区）。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._petal_pix = QPixmap(str(resolve_asset_path("decor/sakura_petal.png")))
        self._sparkle_pix = QPixmap(str(resolve_asset_path("decor/sparkle.png")))

        rng = random.Random(2026)
        # 分布在左右两侧立绘周边区域，避免穿过中心日志影响阅读
        side_xs = [0.05, 0.14, 0.21, 0.78, 0.87, 0.94]
        self._petals: list[_PetalParticle] = [
            _PetalParticle(
                x_ratio=x,
                y_ratio=rng.uniform(0.02, 0.85),
                speed_y=rng.uniform(0.0014, 0.0024),
                drift_amp=rng.uniform(0.006, 0.014),
                phase=rng.uniform(0.0, math.tau),
                angle=rng.uniform(0.0, 360.0),
                spin=rng.uniform(-1.3, 1.3),
                size=rng.uniform(18.0, 26.0),
                opacity=rng.uniform(0.45, 0.78),
            )
            for x in side_xs
        ]

        # 4 颗呼吸微光点缀在标题徽标与花枝边角
        self._sparkles: list[_SparkleNode] = [
            _SparkleNode(0.325, 0.115, 0.0, 0.05, 22.0),
            _SparkleNode(0.425, 0.055, 1.6, 0.06, 18.0),
            _SparkleNode(0.195, 0.205, 3.1, 0.045, 20.0),
            _SparkleNode(0.835, 0.145, 4.4, 0.055, 19.0),
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._step)
        self._timer.start()

    def set_paused(self, paused: bool) -> None:
        """隐藏或最小化至托盘时暂停定时器以减少后台 CPU 占用。"""
        if paused:
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start()

    def _step(self) -> None:
        for p in self._petals:
            p.y_ratio += p.speed_y
            p.phase += 0.045
            p.angle = (p.angle + p.spin) % 360.0
            if p.y_ratio > 1.05:
                p.y_ratio = -0.06

        for s in self._sparkles:
            s.phase = (s.phase + s.speed) % math.tau

        if self.isVisible():
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        w = float(self.width())
        h = float(self.height())
        if w <= 0 or h <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if not self._petal_pix.isNull():
            for p in self._petals:
                cx = (p.x_ratio + math.sin(p.phase) * p.drift_amp) * w
                cy = p.y_ratio * h
                scale_sz = p.size * (h / CANVAS_REF_HEIGHT)
                painter.save()
                painter.setOpacity(p.opacity)
                painter.translate(cx, cy)
                painter.rotate(p.angle)
                target = QRectF(-scale_sz / 2.0, -scale_sz / 2.0, scale_sz, scale_sz)
                painter.drawPixmap(target, self._petal_pix, QRectF(self._petal_pix.rect()))
                painter.restore()

        if not self._sparkle_pix.isNull():
            for s in self._sparkles:
                alpha = 0.25 + 0.55 * (0.5 + 0.5 * math.sin(s.phase))
                scale = (0.85 + 0.25 * math.sin(s.phase)) * s.size * (h / CANVAS_REF_HEIGHT)
                cx = s.x_ratio * w
                cy = s.y_ratio * h
                painter.save()
                painter.setOpacity(alpha)
                target = QRectF(cx - scale / 2.0, cy - scale / 2.0, scale, scale)
                painter.drawPixmap(target, self._sparkle_pix, QRectF(self._sparkle_pix.rect()))
                painter.restore()


class CloseGuardDialog(QDialog):
    """
    二阶堂真红主题防误关拦截弹窗（Requirement 4）：
    防止用户误关闭启动器导致后台服务下线，引导优先最小化到系统托盘保持在线。
    """

    ACTION_TRAY = 1
    ACTION_EXIT = 2
    ACTION_CANCEL = 0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.chosen_action = self.ACTION_CANCEL
        self.setFixedWidth(450)

        ui_font = pick_cjk_font(
            ["Microsoft YaHei UI", "Noto Sans CJK SC", "Segoe UI"],
            "Microsoft YaHei UI",
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        card = QFrame(self)
        card.setObjectName("GuardCard")
        card.setStyleSheet(
            """
            #GuardCard {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFFDF9, stop:1 #FCEEF4
                );
                border: 2px solid #D9AAC2;
                border-radius: 18px;
            }
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(14)

        # 顶部图标与标题
        head = QHBoxLayout()
        head.setSpacing(10)
        icon_lbl = QLabel(card)
        pix = QPixmap(str(resolve_asset_path("app_icon.png")))
        if not pix.isNull():
            icon_lbl.setPixmap(
                pix.scaled(
                    30,
                    30,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        head.addWidget(icon_lbl)

        title_lbl = QLabel(SHINKU.CLOSE_DIALOG_TITLE, card)
        t_font = QFont(ui_font, 12)
        t_font.setWeight(QFont.Weight.Bold)
        title_lbl.setFont(t_font)
        title_lbl.setStyleSheet("color: #543D6E; background: transparent;")
        head.addWidget(title_lbl, 1)
        card_layout.addLayout(head)

        # 真红提示正文
        body_lbl = QLabel(SHINKU.CLOSE_DIALOG_BODY, card)
        body_lbl.setWordWrap(True)
        b_font = QFont(ui_font, 10)
        body_lbl.setFont(b_font)
        body_lbl.setStyleSheet("color: #58476D; line-height: 1.5; background: transparent;")
        card_layout.addWidget(body_lbl)

        # 推荐主按钮：最小化到系统托盘
        btn_tray = QPushButton(SHINKU.CLOSE_BTN_TRAY, card)
        btn_tray.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_tray.setFixedHeight(40)
        btn_tray.setFont(QFont(ui_font, 10, QFont.Weight.Bold))
        btn_tray.setStyleSheet(
            """
            QPushButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #F49BC4, stop:1 #DE73A5
                );
                color: white;
                border: 2px solid #FFE8F2;
                border-radius: 20px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #FAACD0, stop:1 #E682B2
                );
            }
            """
        )
        btn_tray.clicked.connect(lambda: self._finish(self.ACTION_TRAY))
        card_layout.addWidget(btn_tray)

        # 底部双操作：停止退出 / 取消
        sub_row = QHBoxLayout()
        sub_row.setSpacing(10)

        btn_exit = QPushButton(SHINKU.CLOSE_BTN_EXIT, card)
        btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exit.setFixedHeight(34)
        btn_exit.setFont(QFont(ui_font, 9))
        btn_exit.setStyleSheet(
            """
            QPushButton {
                background: #FFF6FA;
                color: #C93A57;
                border: 1.5px solid #EBADC0;
                border-radius: 17px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #FCE3EA;
            }
            """
        )
        btn_exit.clicked.connect(lambda: self._finish(self.ACTION_EXIT))

        btn_cancel = QPushButton(SHINKU.CLOSE_BTN_CANCEL, card)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setFixedHeight(34)
        btn_cancel.setFont(QFont(ui_font, 9))
        btn_cancel.setStyleSheet(
            """
            QPushButton {
                background: #F6EFFC;
                color: #58476D;
                border: 1.5px solid #D5C1EA;
                border-radius: 17px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #ECE0F7;
            }
            """
        )
        btn_cancel.clicked.connect(lambda: self._finish(self.ACTION_CANCEL))

        sub_row.addWidget(btn_exit, 1)
        sub_row.addWidget(btn_cancel, 1)
        card_layout.addLayout(sub_row)

        outer.addWidget(card)

    def _finish(self, action: int) -> None:
        self.chosen_action = action
        self.accept() if action != self.ACTION_CANCEL else self.reject()
