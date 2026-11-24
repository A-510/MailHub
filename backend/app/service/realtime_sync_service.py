import asyncio
from dataclasses import dataclass, field
import logging
import socket
import threading
import time
from typing import Any, Callable

from app.core.database import SessionLocal
from app.model.entities import Account
from app.repository.account_repo import account_repo
from app.repository.email_repo import email_repo
from app.repository.setting_repo import setting_repo
from app.service.crypto_service import crypto_service
import app.service.imap_sync_service as imap_sync_mod
from app.service.imap_sync_service import (
    ImapSyncFetchResult,
    _decode_imap_text,
    imap_sync_service,
    is_imap_auth_error,
    normalize_secret,
)
from app.service.oauth_service import oauth_service

logger = logging.getLogger(__name__)

# 按服务商设置 IDLE 续约周期：
# Gmail / Outlook / iCloud 的 IDLE 推送稳定，4 分钟续约一次穿透 NAT/代理；
# 国内邮箱部分服务器会静默丢失 IDLE 通知或较早断连，30 秒同连接续约可兼顾秒级推送与兜底拉取。
_IDLE_REFRESH_SECONDS_BY_PROVIDER: dict[str, float] = {
    "gmail": 60.0,
    "outlook": 60.0,
    "icloud": 60.0,
}
DEFAULT_IDLE_REFRESH_SECONDS = 5.0
FAST_POLL_INTERVAL_SECONDS = 5.0
IDLE_SLICE_SECONDS = 0.25
OAUTH_SESSION_MAX_SECONDS = 45 * 60.0


def _get_idle_refresh_seconds(provider: str) -> float:
    """根据邮箱服务商特性返回合理的 IDLE 续约间隔秒数。"""
    return _IDLE_REFRESH_SECONDS_BY_PROVIDER.get(provider, DEFAULT_IDLE_REFRESH_SECONDS)


def _has_mailbox_update_event(responses: list[Any]) -> tuple[bool, bool]:
    """
    解析 IMAP IDLE / NOOP 返回的非请求响应。
    返回值: (has_update, is_bye)。
    """
    has_update = False
    is_bye = False
    for item in responses or ():
        if not isinstance(item, (tuple, list)):
            text = _decode_imap_text(item).upper()
            if "BYE" in text:
                is_bye = True
            elif "EXISTS" in text or "RECENT" in text:
                has_update = True
            continue

        upper_tokens = {
            _decode_imap_text(part).strip().upper()
            for part in item
            if isinstance(part, (bytes, bytearray, str))
        }
        if "BYE" in upper_tokens:
            is_bye = True
        if "EXISTS" in upper_tokens or "RECENT" in upper_tokens:
            has_update = True
    return has_update, is_bye


def _enable_tcp_keepalive(client: Any) -> None:
    """尝试开启底层 TCP Keepalive，降低家用路由/代理静默掐断长连接的概率。"""
    try:
        sock = client.socket()
        if sock is not None and hasattr(sock, "setsockopt"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except Exception:
        pass


def _run_account_watch_session(
    *,
    account_id: int,
    host: str,
    port: int,
    use_ssl: bool,
    email_addr: str,
    secret: str,
    auth_type: str,
    provider: str,
    sync_days: int,
    known_uids: set[str],
    stop_event: threading.Event,
    check_now_event: threading.Event,
    ingest_callback: Callable[[ImapSyncFetchResult, str], set[str]],
    connected_callback: Callable[[str], None] | None = None,
    idle_refresh_seconds: float | None = None,
    fast_poll_interval: float = FAST_POLL_INTERVAL_SECONDS,
    idle_slice_seconds: float = IDLE_SLICE_SECONDS,
) -> None:
    """
    单账号同步阻塞式长连接监控会话（运行在工作线程中）：
    1. 连接后先增量检查一次 INBOX，收割断线期间到达的新邮件；
    2. 服务端支持 RFC 2177 IDLE 时进入低开销长连接推送等待，收到 EXISTS/RECENT 秒级拉取；
    3. 服务端不支持或拒绝 IDLE 时，在同一长连接上以 15s 间隔做 NOOP + UID 增量检查。
    """
    client = imap_sync_mod._imap_connect_and_auth(
        host=host,
        port=port,
        use_ssl=use_ssl,
        email_addr=email_addr,
        secret=secret,
        auth_type=auth_type,
        provider=provider,
    )
    in_idle = False
    session_started = time.monotonic()
    effective_idle_refresh = (
        idle_refresh_seconds
        if idle_refresh_seconds is not None
        else _get_idle_refresh_seconds(provider)
    )

    try:
        _enable_tcp_keepalive(client)
        # 必须使用真实 SELECT(readonly=False) 而非 EXAMINE(readonly=True)，确保 QQ/Exchange 等服务端正常触发 IDLE EXISTS 推送；
        # 抓取报文全部使用 BODY.PEEK[]，绝不会修改服务器未读状态。
        select_info = client.select_folder("INBOX", readonly=False)

        try:
            supports_idle = bool(client.has_capability(b"IDLE"))
        except Exception:
            supports_idle = False

        mode = "idle" if supports_idle else "fast_poll"
        logger.info(
            "Realtime watch connected: account_id=%s provider=%s mode=%s refresh=%.1fs",
            account_id,
            provider,
            mode,
            effective_idle_refresh if supports_idle else fast_poll_interval,
        )
        if connected_callback is not None:
            connected_callback(mode)

        # 连接刚建立时先清除此前积压的 check_now 信号并立即执行一次增量查新
        check_now_event.clear()
        t_init = time.monotonic()
        initial_result = imap_sync_mod._pull_inbox_incremental_on_client(
            client,
            known_uids=known_uids,
            sync_days=sync_days,
            select_first=False,
            send_noop=False,
            select_info=select_info,
        )
        if initial_result.new_messages:
            logger.info(
                "Realtime initial pull found %d message(s) for account_id=%s in %dms",
                len(initial_result.new_messages),
                account_id,
                int((time.monotonic() - t_init) * 1000),
            )
            known_uids = ingest_callback(initial_result, mode)

        if supports_idle:
            while not stop_event.is_set():
                if auth_type == "oauth2" and (time.monotonic() - session_started) >= OAUTH_SESSION_MAX_SECONDS:
                    return

                try:
                    client.idle()
                    in_idle = True
                except Exception as exc:
                    logger.warning(
                        "Server %s rejected IDLE command (%s), degrading to %ss fast poll",
                        host,
                        exc,
                        fast_poll_interval,
                    )
                    in_idle = False
                    supports_idle = False
                    if connected_callback is not None:
                        connected_callback("fast_poll")
                    break

                idle_started = time.monotonic()
                triggered_by_push = False
                triggered_by_focus = False
                fast_empty_count = 0

                while not stop_event.is_set():
                    if check_now_event.is_set():
                        triggered_by_focus = True
                        break

                    # 防坑：Windows 下 select 无法感知 TLS 解密缓冲区内的滞留报文，必须检查 ssl.pending()
                    try:
                        sock = client.socket()
                        pending_fn = getattr(sock, "pending", None)
                        if callable(pending_fn) and pending_fn() > 0:
                            triggered_by_push = True
                            break
                    except Exception:
                        pass

                    if (time.monotonic() - idle_started) >= effective_idle_refresh:
                        break

                    t0 = time.monotonic()
                    resps = client.idle_check(timeout=idle_slice_seconds)
                    elapsed = time.monotonic() - t0

                    if resps:
                        fast_empty_count = 0
                        has_update, is_bye = _has_mailbox_update_event(resps)
                        if is_bye:
                            raise ConnectionResetError("IMAP server sent BYE during IDLE")
                        if has_update:
                            triggered_by_push = True
                            break
                    else:
                        # 防坑：对端静默断开 TCP 时 select/recv 可能瞬间返回空列表，避免 CPU 100% 空转
                        if elapsed < min(0.05, idle_slice_seconds * 0.25):
                            fast_empty_count += 1
                            if fast_empty_count >= 2:
                                raise ConnectionResetError("IMAP IDLE socket returned immediate empty EOF")
                        else:
                            fast_empty_count = 0

                done_resps: list[Any] = []
                try:
                    done_res = client.idle_done()
                    if isinstance(done_res, tuple) and len(done_res) >= 2 and isinstance(done_res[1], list):
                        done_resps = done_res[1]
                finally:
                    in_idle = False

                if stop_event.is_set():
                    return

                done_update, done_bye = _has_mailbox_update_event(done_resps)
                if done_bye:
                    raise ConnectionResetError("IMAP server sent BYE on IDLE DONE")
                if done_update:
                    triggered_by_push = True

                was_focus = check_now_event.is_set() or triggered_by_focus
                check_now_event.clear()
                pull_source = "focus" if (was_focus and not triggered_by_push) else "idle"
                diag_reason = "idle_push" if triggered_by_push else ("focus" if was_focus else "idle_refresh")

                t_pull = time.monotonic()
                delta = imap_sync_mod._pull_inbox_incremental_on_client(
                    client,
                    known_uids=known_uids,
                    sync_days=sync_days,
                    select_first=False,
                    send_noop=not triggered_by_push,
                    select_info=None,
                )
                if delta.new_messages:
                    logger.info(
                        "Realtime pull (%s) fetched %d new message(s) for account_id=%s in %dms",
                        diag_reason,
                        len(delta.new_messages),
                        account_id,
                        int((time.monotonic() - t_pull) * 1000),
                    )
                    known_uids = ingest_callback(delta, pull_source)

        # 不支持 IDLE（或刚被服务端拒绝 IDLE 降级）时进入同连接快速轮询
        if not supports_idle:
            slice_sec = min(0.25, max(0.05, fast_poll_interval / 4))
            while not stop_event.is_set():
                if auth_type == "oauth2" and (time.monotonic() - session_started) >= OAUTH_SESSION_MAX_SECONDS:
                    return

                deadline = time.monotonic() + fast_poll_interval
                triggered_by_focus = False
                while not stop_event.is_set():
                    if check_now_event.is_set():
                        triggered_by_focus = True
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    stop_event.wait(timeout=min(slice_sec, remaining))

                if stop_event.is_set():
                    return

                was_focus = check_now_event.is_set() or triggered_by_focus
                check_now_event.clear()
                pull_source = "focus" if was_focus else "fast_poll"

                t_pull = time.monotonic()
                delta = imap_sync_mod._pull_inbox_incremental_on_client(
                    client,
                    known_uids=known_uids,
                    sync_days=sync_days,
                    select_first=False,
                    send_noop=True,
                    select_info=None,
                )
                if delta.new_messages:
                    logger.info(
                        "Realtime pull (%s) fetched %d new message(s) for account_id=%s in %dms",
                        pull_source,
                        len(delta.new_messages),
                        account_id,
                        int((time.monotonic() - t_pull) * 1000),
                    )
                    known_uids = ingest_callback(delta, pull_source)
    finally:
        if in_idle:
            try:
                client.idle_done()
            except Exception:
                pass
        try:
            client.logout()
        except Exception:
            try:
                client.shutdown()
            except Exception:
                pass


@dataclass
class _AccountWatchHandle:
    """单个账号的实时监控句柄。"""

    account_id: int
    fingerprint: tuple[Any, ...]
    stop_event: threading.Event = field(default_factory=threading.Event)
    check_now_event: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task[None] | None = None
    mode: str = "starting"


class RealtimeSyncManager:
    """管理全部启用邮箱账号的 IMAP IDLE 长连接推送与快速降级轮询协程。"""

    def __init__(self) -> None:
        self._handles: dict[int, _AccountWatchHandle] = {}
        self._last_quick_check_ts: dict[int, float] = {}

    @staticmethod
    def _build_fingerprint(account: Account) -> tuple[Any, ...]:
        """提取决定长连接是否需要重建的配置指纹（排除 OAuth 自动续期引起的 access_token 变动）。"""
        credential_part = (
            account.encrypted_refresh_token
            if account.auth_type == "oauth2"
            else account.encrypted_secret
        )
        return (
            account.imap_host,
            account.imap_port,
            account.imap_ssl,
            account.auth_type,
            account.provider,
            credential_part,
        )

    async def _stop_handle(self, handle: _AccountWatchHandle) -> None:
        """优雅终止单个监控协程及底层线程连接。"""
        handle.stop_event.set()
        task = handle.task
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.5)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass

    async def reconcile(
        self,
        enabled_accounts: list[Account],
        *,
        active: bool,
        force_restart_ids: set[int] | None = None,
    ) -> None:
        """根据当前配置和账号列表调和长连接监控协程集合。"""
        if not active:
            await self.stop_all()
            return

        desired: dict[int, tuple[Any, ...]] = {
            acc.id: self._build_fingerprint(acc)
            for acc in enabled_accounts
            if acc.is_enabled and not acc.is_demo
        }

        to_stop: list[_AccountWatchHandle] = []
        for acc_id in list(self._handles.keys()):
            handle = self._handles[acc_id]
            should_restart = (
                acc_id not in desired
                or handle.fingerprint != desired[acc_id]
                or (force_restart_ids is not None and acc_id in force_restart_ids)
                or (handle.task is not None and handle.task.done())
            )
            if should_restart:
                to_stop.append(self._handles.pop(acc_id))

        if to_stop:
            await asyncio.gather(*(self._stop_handle(h) for h in to_stop), return_exceptions=True)

        for acc_id, fp in desired.items():
            if acc_id not in self._handles:
                handle = _AccountWatchHandle(account_id=acc_id, fingerprint=fp)
                handle.task = asyncio.create_task(
                    self._watch_account_loop(acc_id, handle),
                    name=f"mailhub-realtime-watch-{acc_id}",
                )
                self._handles[acc_id] = handle

    async def stop_all(self) -> None:
        """停止全部账号的实时监控协程。"""
        handles = list(self._handles.values())
        self._handles.clear()
        if handles:
            await asyncio.gather(*(self._stop_handle(h) for h in handles), return_exceptions=True)

    async def _watch_account_loop(self, account_id: int, handle: _AccountWatchHandle) -> None:
        """单账号断线重连守护循环，按错误类型执行指数退避。"""
        backoff_seconds = 5.0
        loop = asyncio.get_running_loop()

        while not handle.stop_event.is_set():
            email_addr = f"account#{account_id}"
            session_start = time.monotonic()
            try:
                with SessionLocal() as db:
                    account = account_repo.get_by_id(db, account_id)
                    if account is None or not account.is_enabled or account.is_demo:
                        return
                    email_addr = account.email
                    if account.auth_type == "oauth2":
                        secret = await oauth_service.ensure_valid_access_token(db, account)
                    else:
                        raw_secret = crypto_service.decrypt(account.encrypted_secret) or ""
                        secret = normalize_secret(account.provider, raw_secret, account.imap_host)

                    if not secret:
                        raise RuntimeError("未找到有效登录凭据，请在设置中重新输入密码或完成浏览器授权。")

                    cfg = setting_repo.get_all(db)
                    sync_days = int(cfg.get("sync_days", 30))
                    known_uids = email_repo.get_uids_by_folder(db, account.id, "inbox")
                    host = account.imap_host
                    port = account.imap_port
                    use_ssl = account.imap_ssl
                    auth_type = account.auth_type
                    provider = account.provider

                def ingest_callback(fetch_result: ImapSyncFetchResult, source: str) -> set[str]:
                    fut = asyncio.run_coroutine_threadsafe(
                        imap_sync_service.ingest_fetch_result(
                            account_id,
                            fetch_result,
                            mode="inbox",
                            source=source,
                        ),
                        loop,
                    )
                    fut.result(timeout=30.0)
                    with SessionLocal() as inner_db:
                        return email_repo.get_uids_by_folder(inner_db, account_id, "inbox")

                def connected_callback(mode: str) -> None:
                    handle.mode = mode
                    imap_sync_service.mark_realtime_connected(account_id)

                session_start = time.monotonic()
                await asyncio.to_thread(
                    _run_account_watch_session,
                    account_id=account_id,
                    host=host,
                    port=port,
                    use_ssl=use_ssl,
                    email_addr=email_addr,
                    secret=secret,
                    auth_type=auth_type,
                    provider=provider,
                    sync_days=sync_days,
                    known_uids=known_uids,
                    stop_event=handle.stop_event,
                    check_now_event=handle.check_now_event,
                    ingest_callback=ingest_callback,
                    connected_callback=connected_callback,
                )
                if handle.stop_event.is_set():
                    break
                backoff_seconds = 5.0
            except asyncio.CancelledError:
                handle.stop_event.set()
                raise
            except Exception as exc:
                if handle.stop_event.is_set():
                    break
                elapsed = time.monotonic() - session_start
                if elapsed > 15.0:
                    backoff_seconds = 5.0

                if is_imap_auth_error(exc):
                    backoff_seconds = max(backoff_seconds, 120.0)
                    next_backoff = min(backoff_seconds * 2, 300.0)
                else:
                    next_backoff = min(backoff_seconds * 2, 60.0)

                handle.mode = "reconnecting"
                logger.warning(
                    "Realtime IMAP watch error for %s (%s), retrying in %.1fs: %s",
                    email_addr,
                    account_id,
                    backoff_seconds,
                    exc,
                )
                try:
                    imap_sync_service.record_realtime_error(account_id, exc)
                except Exception:
                    pass

                await asyncio.to_thread(handle.stop_event.wait, backoff_seconds)
                backoff_seconds = next_backoff

    async def trigger_quick_check(
        self,
        *,
        account_id: int | None = None,
        cooldown_seconds: float = 2.0,
    ) -> dict[str, Any]:
        """
        前端切回窗口或手动触发瞬时检查时调用：
        - 已连接实时长连接的账号直接唤醒 IDLE / fast_poll（零建连开销）；
        - 未开启实时连接或正在重连中的账号并发执行一次轻量 inbox_only 同步。
        """
        now = time.monotonic()
        with SessionLocal() as db:
            accounts = account_repo.list_all(db)
            target_ids = [
                acc.id
                for acc in accounts
                if acc.is_enabled
                and not acc.is_demo
                and (account_id is None or acc.id == account_id)
            ]

        woken = 0
        throttled = 0
        fallback_ids: list[int] = []

        for acc_id in target_ids:
            last_ts = self._last_quick_check_ts.get(acc_id, 0.0)
            if (now - last_ts) < cooldown_seconds:
                throttled += 1
                continue
            self._last_quick_check_ts[acc_id] = now

            handle = self._handles.get(acc_id)
            if (
                handle is not None
                and handle.task is not None
                and not handle.task.done()
                and handle.mode in ("idle", "fast_poll", "starting")
            ):
                handle.check_now_event.set()
                woken += 1
            else:
                fallback_ids.append(acc_id)

        fetched = 0
        if fallback_ids:
            sem = asyncio.Semaphore(4)

            async def _run_fallback(aid: int) -> int:
                async with sem:
                    with SessionLocal() as task_db:
                        acc = account_repo.get_by_id(task_db, aid)
                        if acc is None or not acc.is_enabled or acc.is_demo:
                            return 0
                        ok, count, _ = await imap_sync_service.sync_account(
                            task_db,
                            acc,
                            inbox_only=True,
                            source="focus",
                        )
                        return count if ok else 0

            counts = await asyncio.gather(*(_run_fallback(aid) for aid in fallback_ids))
            fetched = sum(counts)

        return {
            "ok": True,
            "woken": woken,
            "synced": len(fallback_ids),
            "throttled": throttled,
            "fetched": fetched,
        }


realtime_sync_manager = RealtimeSyncManager()
