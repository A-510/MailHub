import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MailEventBus:
    """
    轻量级进程内事件总线：将后台实时推送/同步入库结果广播给所有 SSE 订阅端。
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._closing: bool = False

    @property
    def subscriber_count(self) -> int:
        """返回当前活跃 SSE 订阅连接数。"""
        return len(self._subscribers)

    def reset_for_startup(self) -> None:
        """在应用启动阶段重置关闭状态与残留队列（兼容测试环境反复启停）。"""
        self._closing = False
        self._subscribers.clear()

    def subscribe(self) -> asyncio.Queue[dict[str, Any] | None]:
        """注册新的 SSE 客户端订阅队列。"""
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
        if self._closing:
            queue.put_nowait(None)
            return queue
        self._subscribers.add(queue)
        logger.info("SSE client subscribed (active_subscribers=%d)", len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        """注销 SSE 客户端订阅队列。"""
        if queue in self._subscribers:
            self._subscribers.discard(queue)
            logger.info("SSE client unsubscribed (active_subscribers=%d)", len(self._subscribers))

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """向全部订阅者非阻塞广播事件；队列满时自动淘汰最旧消息避免阻塞收信流程。"""
        if self._closing:
            return
        if not self._subscribers:
            if event_type == "mail_synced":
                logger.warning(
                    "Published SSE %s with 0 active subscribers (account_id=%s fetched=%s source=%s)",
                    event_type,
                    data.get("account_id"),
                    data.get("fetched_count"),
                    data.get("source"),
                )
            return
        payload: dict[str, Any] = {"type": event_type, "data": data}
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.debug("Dropped SSE event %s for congested subscriber", event_type)
        if event_type == "mail_synced":
            logger.info(
                "Published SSE %s to %d subscriber(s) (account_id=%s fetched=%s source=%s)",
                event_type,
                len(self._subscribers),
                data.get("account_id"),
                data.get("fetched_count"),
                data.get("source"),
            )

    def close_all(self) -> None:
        """应用关闭时向所有活跃 SSE 客户端推送退出哨兵，避免连接挂起阻塞关闭。"""
        self._closing = True
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass


mail_event_bus = MailEventBus()
