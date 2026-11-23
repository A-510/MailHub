import logging
from logging.handlers import RotatingFileHandler
import sys

from app.core.config import settings


def setup_logging() -> None:
    """
    初始化全局日志系统。
    同时输出至标准输出与本地 data/backend.log 轮转日志文件，
    严格使用标准库 logging，不输出任何敏感凭证信息。
    """
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(stream_handler)

    try:
        file_handler = RotatingFileHandler(
            settings.backend_log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError:
        # 只读目录或受限环境下允许静默退回标准输出日志
        pass

    # 降低第三方库啰嗦日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
