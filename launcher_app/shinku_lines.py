"""
二阶堂真红（《五彩斑斓的世界》）角色台词与 MailHub 启动器文案库。

语言风格契合设定：
- 半透明的魔法使，理性、冷静而温柔，自称「我」，称呼用户为「你」；
- 融入经典台词（“首先要把事实当作事实来确认”、“就算烦恼，想不明白的东西还是不明白”、
  “现在不明白的事情，未来的你终会理解全部”、“一同构筑五彩斑斓的世界吧”、
  “希望明天对你而言，也是美好的一天”）与生活萌点（不加糖的黑咖啡、薄煎饼）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShinkuDialogs:
    """集中管理二阶堂真红风格的启动器日志、状态胶囊与守护弹窗文案。"""

    # 窗口标题与头栏标题（保持原图日英双语标题栏视觉）
    WINDOW_TITLE: str = "MailHub Launcher - メールハブ ランチャー"
    HEADER_CHECKING: str = "MailHub サービス初期化中..."
    HEADER_INSTALLING: str = "依存関係を自動導入中..."
    HEADER_RUNNING: str = "MailHub サービス稼働中..."
    HEADER_ERROR: str = "環境の確認が必要です..."

    # 欢迎与初始引导语
    WELCOME_GREETING: str = (
        "欢迎回来，我是半透明的魔法使・二阶堂真红。"
    )
    CHECK_GUIDE: str = (
        "首先要把事实当作事实来确认——让我替你检查运行环境。"
    )
    DRY_RUN_PREVIEW_NOTE: str = (
        "（预览模式）不明白的事情现在这样就好，一切都准备妥当。"
    )

    # 依赖检测阶段
    CHECKING_PYTHON: str = "确认 Python 解释器与虚拟环境……"
    PYTHON_OK_TEMPLATE: str = "Python 虚拟环境已确认（{version}）"
    PYTHON_MISSING_INSTALLING: str = (
        "缺少虚拟环境……不明白的配置交给我，正在自动建立 .venv。"
    )
    PYTHON_SYSTEM_MISSING: str = (
        "未找到 Python，先泡杯黑咖啡等我自动安装吧。"
    )
    VENV_READY: str = "Python 独立虚拟环境已构筑完成"

    CHECKING_BACKEND_DEPS: str = "核对后端核心依赖组件……"
    BACKEND_DEPS_OK: str = "后端核心依赖已全部就绪"
    ALL_DEPS_AND_FRONTEND_OK: str = "前后端运行依赖与书房资源已就绪"
    BACKEND_DEPS_MISSING_TEMPLATE: str = (
        "缺少 {count} 项依赖（{names}），正在自动安装……"
    )
    BACKEND_DEPS_FALLBACK_MIRROR: str = (
        "默认源不太顺畅……换用清华镜像源再试一次。"
    )
    BACKEND_DEPS_INSTALLED: str = "缺失依赖全部补全，没有什么值得担心的"

    CHECKING_FRONTEND_DIST: str = "确认前端书房界面资源（frontend/dist）……"
    FRONTEND_DIST_OK: str = "前端书房静态资源已就绪"
    FRONTEND_DIST_MISSING: str = (
        "界面资源未构建，正在自动编译（吃块薄煎饼稍等吧）……"
    )
    FRONTEND_DIST_BUILT: str = "前端界面构建完成"

    CHECKING_DATABASE: str = "读取本地书房账本与邮箱配置……"
    DATABASE_ACCOUNTS_TEMPLATE: str = "本地邮箱配置已确认"
    DATABASE_FIRST_RUN: str = "首次开启书房，将自动载入示例信箱"

    # 服务启动与打开浏览器阶段
    STARTING_SERVICE: str = (
        "一同构筑只属于我们的『MailHub 五彩斑斓世界』吧……"
    )
    SERVICE_ALREADY_RUNNING: str = (
        "本地服务已在 8765 端口运行，直接为你开启书房。"
    )
    PORT_OCCUPIED_BY_OTHER: str = (
        "端口 8765 被其他程序占用，请释放后再让我重试。"
    )
    SERVICE_STARTED_OPENING_BROWSER: str = (
        "服务已苏醒，愿明天对你而言也是美好的一天！"
    )
    KEEP_ONLINE_REMINDER: str = (
        "约定好了哦：请保持启动器在线，关闭我服务也会沉睡。"
    )

    # 运行中互动与异常安慰
    REOPEN_BROWSER_LOG: str = (
        "正在重新为你开启 MailHub 书房网页窗口（http://127.0.0.1:8765）。"
    )
    SERVICE_UNEXPECTED_EXIT: str = (
        "哎呀，本地服务突然安静下来了……先把情况记录下来，点击下方按钮让我重新唤醒它吧。"
    )
    ERROR_COMFORT_TEMPLATE: str = (
        "就算烦恼，想不明白的问题一下子还是解不开的——别慌，报错已记下：{detail}。"
        "休息一下，点击下方按钮再试一次就好。"
    )

    # 状态胶囊文案
    PILL_INITIALIZING: str = "正在准备魔法阵…"
    PILL_CHECKING: str = "正在检查电脑运行环境"
    PILL_INSTALLING: str = "正在自动安装缺失依赖"
    PILL_STARTING: str = "正在唤醒 MailHub 服务"
    PILL_RUNNING: str = "服务在线守护中 · 请勿关闭"
    PILL_ERROR: str = "遇到了小状况 · 请查看日志"
    PILL_PREVIEW: str = "起動の準備が整いました"

    # 底部粉色主按钮文案（保留原画日语美学）
    BTN_LAUNCH: str = "サービスを起動"
    BTN_CHECKING: str = "環境を確認中…"
    BTN_INSTALLING: str = "依存導入中…"
    BTN_STARTING: str = "サービス起動中…"
    BTN_OPEN_BROWSER: str = "ブラウザを開く"
    BTN_RETRY: str = "再試行・重新启动"

    # 防误关守护弹窗（Requirement 4）
    CLOSE_DIALOG_TITLE: str = "二阶堂真红的提醒"
    CLOSE_DIALOG_BODY: str = (
        "MailHub 本地服务正在我的守护下运行着哦。\n\n"
        "一旦把我彻底关掉，后台服务就会立刻停止，网页里的邮件也无法继续收发了。\n"
        "不如让我缩小到系统托盘，喝着黑咖啡默默在后台为你守候吧？"
    )
    CLOSE_BTN_TRAY: str = "最小化到托盘（保持服务在线）"
    CLOSE_BTN_EXIT: str = "停止服务并退出"
    CLOSE_BTN_CANCEL: str = "留在这里"

    # 系统托盘文案
    TRAY_TOOLTIP_RUNNING: str = "MailHub Launcher - 服务在线守护中（双击显示窗口）"
    TRAY_TOOLTIP_STOPPED: str = "MailHub Launcher - 服务待机中"
    TRAY_MINIMIZED_TITLE: str = "MailHub 启动器仍在在线守护"
    TRAY_MINIMIZED_MSG: str = (
        "我已悄悄退到系统托盘喝黑咖啡了，邮件服务依然保持在线。双击托盘图标随时呼唤我。"
    )


SHINKU = ShinkuDialogs()
