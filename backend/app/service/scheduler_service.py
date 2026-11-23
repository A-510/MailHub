import asyncio
import logging

from app.core.database import SessionLocal
from app.repository.account_repo import account_repo
from app.repository.setting_repo import setting_repo
from app.service.imap_sync_service import imap_sync_service

logger = logging.getLogger(__name__)


class SchedulerService:
    """后台异步自动收信定时调度器。"""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    def start(self) -> None:
        """在 FastAPI 启动阶段拉起后台同步协程（按当前事件循环创建新 Event）。"""
        if self._task is None or self._task.done():
            self._stop_event = asyncio.Event()
            self._task = asyncio.create_task(self._run_loop(), name="mailhub-sync-scheduler")
            logger.info("Background mail sync scheduler started.")

    async def stop(self) -> None:
        """在 FastAPI 关闭阶段优雅终止后台协程。"""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            self._stop_event = None
            logger.info("Background mail sync scheduler stopped.")

    async def _run_loop(self) -> None:
        while self._stop_event is not None and not self._stop_event.is_set():
            interval_minutes = 5
            try:
                with SessionLocal() as db:
                    cfg = setting_repo.get_all(db)
                    interval_minutes = int(cfg.get("sync_interval_minutes", 5))
            except Exception as exc:
                logger.warning("Failed reading sync interval: %s", exc)

            wait_seconds = max(60, interval_minutes * 60) if interval_minutes > 0 else 60
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                break
            except asyncio.TimeoutError:
                pass

            if interval_minutes <= 0:
                continue

            try:
                with SessionLocal() as db:
                    accounts = account_repo.list_all(db)
                    for acc in accounts:
                        if acc.is_enabled and not acc.is_demo:
                            await imap_sync_service.sync_account(db, acc)
            except Exception as exc:
                logger.warning("Scheduled sync round encountered error: %s", exc)


scheduler_service = SchedulerService()
