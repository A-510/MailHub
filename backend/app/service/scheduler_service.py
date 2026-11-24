import asyncio
import logging

from app.core.config import settings
from app.core.database import SessionLocal
from app.repository.account_repo import account_repo
from app.repository.setting_repo import setting_repo
from app.service.event_bus import mail_event_bus
from app.service.imap_sync_service import imap_sync_service
from app.service.realtime_sync_service import realtime_sync_manager

logger = logging.getLogger(__name__)


class SchedulerService:
    """后台异步自动收信与实时长连接调度器。"""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._wakeup_event: asyncio.Event | None = None
        self._force_restart_ids: set[int] = set()

    def start(self) -> None:
        """在 FastAPI 启动阶段重置事件总线并拉起后台调度协程。"""
        mail_event_bus.reset_for_startup()
        if self._task is None or self._task.done():
            self._stop_event = asyncio.Event()
            self._wakeup_event = asyncio.Event()
            self._force_restart_ids.clear()
            self._task = asyncio.create_task(self._run_loop(), name="mailhub-sync-scheduler")
            logger.info("Background mail sync scheduler started.")

    async def stop(self) -> None:
        """在 FastAPI 关闭阶段释放 SSE 连接、关闭 IMAP 长连接并优雅终止后台协程。"""
        mail_event_bus.close_all()
        if self._stop_event is not None:
            self._stop_event.set()
        await realtime_sync_manager.stop_all()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            self._stop_event = None
            self._wakeup_event = None
            logger.info("Background mail sync scheduler stopped.")

    def notify_config_changed(self) -> None:
        """配置变更（如同步间隔或实时推送开关变化）时立即唤醒调度循环。"""
        if self._wakeup_event is not None:
            self._wakeup_event.set()

    def notify_accounts_changed(self, force_restart_account_id: int | None = None) -> None:
        """账号增删改后立即唤醒调度循环以调和长连接监控器。"""
        if force_restart_account_id is not None:
            self._force_restart_ids.add(force_restart_account_id)
        if self._wakeup_event is not None:
            self._wakeup_event.set()

    async def _run_concurrent_sync(
        self,
        account_ids: list[int],
        *,
        inbox_only: bool,
        source: str,
    ) -> None:
        """使用独立数据库会话并发同步多个账号，避免单个慢账号阻塞全局。"""
        if not account_ids:
            return
        sem = asyncio.Semaphore(4)

        async def _sync_one(aid: int) -> None:
            async with sem:
                with SessionLocal() as db:
                    acc = account_repo.get_by_id(db, aid)
                    if acc is None or not acc.is_enabled or acc.is_demo:
                        return
                    await imap_sync_service.sync_account(
                        db,
                        acc,
                        inbox_only=inbox_only,
                        source=source,
                    )

        results = await asyncio.gather(*(_sync_one(aid) for aid in account_ids), return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.warning("Background concurrent sync item error: %s", res)

    async def _run_loop(self) -> None:
        is_first_round = True
        while self._stop_event is not None and not self._stop_event.is_set():
            interval_minutes = 5
            realtime_push = True
            enabled_real_accounts = []
            enabled_real_ids: list[int] = []
            try:
                with SessionLocal() as db:
                    cfg = setting_repo.get_all(db)
                    interval_minutes = int(cfg.get("sync_interval_minutes", 5))
                    realtime_push = bool(cfg.get("realtime_push", True))
                    accounts = account_repo.list_all(db)
                    enabled_real_accounts = [
                        acc for acc in accounts if acc.is_enabled and not acc.is_demo
                    ]
                    enabled_real_ids = [acc.id for acc in enabled_real_accounts]
            except Exception as exc:
                logger.warning("Failed reading sync configuration: %s", exc)

            force_ids = set(self._force_restart_ids)
            self._force_restart_ids.clear()

            if settings.enable_realtime_sync:
                try:
                    await realtime_sync_manager.reconcile(
                        enabled_real_accounts,
                        active=(realtime_push and interval_minutes > 0),
                        force_restart_ids=force_ids or None,
                    )
                except Exception as exc:
                    logger.warning("Realtime sync reconcile warning: %s", exc)

                # 若未开启实时推送但启用了自动同步，启动首轮立即快速检查一次 INBOX 消除冷启动等待
                if is_first_round and interval_minutes > 0 and not realtime_push and enabled_real_ids:
                    try:
                        await self._run_concurrent_sync(enabled_real_ids, inbox_only=True, source="startup")
                    except Exception as exc:
                        logger.warning("Startup inbox sync warning: %s", exc)

            is_first_round = False

            stop_waiter = asyncio.create_task(self._stop_event.wait())
            wakeup_waiter = (
                asyncio.create_task(self._wakeup_event.wait())
                if self._wakeup_event is not None
                else None
            )
            waiters = [stop_waiter] + ([wakeup_waiter] if wakeup_waiter is not None else [])
            wait_timeout: float | None = max(60, interval_minutes * 60) if interval_minutes > 0 else None

            try:
                done, _pending = await asyncio.wait(
                    waiters,
                    timeout=wait_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for task in waiters:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)

            if self._stop_event.is_set():
                break

            if wakeup_waiter is not None and wakeup_waiter in done:
                if self._wakeup_event is not None:
                    self._wakeup_event.clear()
                continue

            if interval_minutes <= 0:
                continue

            try:
                with SessionLocal() as db:
                    target_ids = [
                        acc.id
                        for acc in account_repo.list_all(db)
                        if acc.is_enabled and not acc.is_demo
                    ]
                if target_ids:
                    await self._run_concurrent_sync(target_ids, inbox_only=False, source="scheduled")
            except Exception as exc:
                logger.warning("Scheduled sync round encountered error: %s", exc)


scheduler_service = SchedulerService()
