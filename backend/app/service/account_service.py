import asyncio
import logging
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.model.entities import Account
from app.repository.account_repo import account_repo
from app.schema.schemas import (
    AccountCreate,
    AccountOut,
    AccountTestRequest,
    AccountTestResult,
    AccountUpdate,
)
from app.service.crypto_service import crypto_service
from app.service.imap_sync_service import imap_sync_service, normalize_secret
from app.service.provider_preset_service import (
    detect_provider_from_email,
    get_preset_by_id,
    resolve_preset_hosts,
)

logger = logging.getLogger(__name__)


class AccountService:
    """邮箱渠道管理业务逻辑层。"""

    def _to_out(self, account: Account, counts_map: dict[int, tuple[int, int]]) -> AccountOut:
        unread, total = counts_map.get(account.id, (0, 0))
        return AccountOut(
            id=account.id,
            label=account.label,
            email=account.email,
            provider=account.provider,
            auth_type=account.auth_type,
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            imap_ssl=account.imap_ssl,
            smtp_host=account.smtp_host,
            smtp_port=account.smtp_port,
            smtp_ssl=account.smtp_ssl,
            badge_color=account.badge_color,
            signature=account.signature,
            is_enabled=account.is_enabled,
            include_in_unified=account.include_in_unified,
            notify_enabled=account.notify_enabled,
            sort_order=account.sort_order,
            last_synced_at=account.last_synced_at,
            sync_status=account.sync_status,
            last_error=account.last_error,
            is_demo=account.is_demo,
            unread_count=unread,
            total_count=total,
        )

    def list_accounts(self, db: Session) -> list[AccountOut]:
        """列出全部已配置邮箱账号及其未读统计。"""
        accounts = account_repo.list_all(db)
        counts_map = account_repo.get_counts_by_account(db)
        return [self._to_out(acc, counts_map) for acc in accounts]

    def get_account_out(self, db: Session, account_id: int) -> AccountOut:
        """获取单个账号详情（不存在抛出 ValueError）。"""
        acc = account_repo.get_by_id(db, account_id)
        if not acc:
            raise ValueError("未找到指定邮箱账号。")
        counts_map = account_repo.get_counts_by_account(db)
        return self._to_out(acc, counts_map)

    async def test_connection(self, payload: AccountTestRequest) -> AccountTestResult:
        """测试指定账号与服务器的 IMAP/SMTP 连通性。"""
        ok, imap_ok, smtp_ok, message, resolved_smtp_port, resolved_smtp_ssl = (
            await imap_sync_service.test_connection(
                email_addr=str(payload.email),
                provider=payload.provider,
                secret=payload.secret,
                imap_host=payload.imap_host,
                imap_port=payload.imap_port,
                imap_ssl=payload.imap_ssl,
                smtp_host=payload.smtp_host,
                smtp_port=payload.smtp_port,
                smtp_ssl=payload.smtp_ssl,
            )
        )
        return AccountTestResult(
            ok=ok,
            imap_ok=imap_ok,
            smtp_ok=smtp_ok,
            message=message,
            resolved_smtp_port=resolved_smtp_port if smtp_ok else None,
            resolved_smtp_ssl=resolved_smtp_ssl if smtp_ok else None,
        )

    async def create_account(self, db: Session, payload: AccountCreate) -> AccountOut:
        """创建新邮箱渠道，支持入库前验证连接并经 Fernet 加密存储凭据。"""
        email_str = str(payload.email).strip()
        if account_repo.get_by_email(db, email_str):
            raise ValueError(f"邮箱 {email_str} 已存在，请勿重复添加。")

        if payload.auth_type == "password" and not (payload.secret and payload.secret.strip()):
            raise ValueError("使用账号密码/授权码方式添加邮箱时，必须填写密码或授权码。")

        provider = payload.provider
        if provider == "custom" and not payload.imap_host.strip():
            detected = detect_provider_from_email(email_str)
            provider = detected.id

        preset = get_preset_by_id(provider)
        default_imap_host, default_smtp_host = resolve_preset_hosts(preset, email_str)
        imap_host = payload.imap_host.strip() or default_imap_host
        smtp_host = payload.smtp_host.strip() or default_smtp_host
        if not imap_host or not smtp_host:
            raise ValueError("请完整填写 IMAP 和 SMTP 服务器主机地址。")

        normalized_secret = (
            normalize_secret(provider, payload.secret, imap_host) if payload.secret else None
        )

        resolved_smtp_port = payload.smtp_port
        resolved_smtp_ssl = payload.smtp_ssl

        # 前端提交新增账号时强制预校验 IMAP/SMTP 登录，防止无效密码假成功入库
        if payload.auth_type == "password" and payload.verify_connection and normalized_secret:
            ok, _imap_ok, _smtp_ok, msg, resolved_smtp_port, resolved_smtp_ssl = (
                await imap_sync_service.test_connection(
                    email_addr=email_str,
                    provider=provider,
                    secret=normalized_secret,
                    imap_host=imap_host,
                    imap_port=payload.imap_port,
                    imap_ssl=payload.imap_ssl,
                    smtp_host=smtp_host,
                    smtp_port=payload.smtp_port,
                    smtp_ssl=payload.smtp_ssl,
                )
            )
            if not ok:
                raise ValueError(msg)

        next_order = account_repo.get_max_sort_order(db) + 1
        acc = Account(
            label=payload.label.strip(),
            email=email_str,
            provider=provider,
            auth_type=payload.auth_type,
            encrypted_secret=crypto_service.encrypt(normalized_secret) if normalized_secret else None,
            imap_host=imap_host,
            imap_port=payload.imap_port,
            imap_ssl=payload.imap_ssl,
            smtp_host=smtp_host,
            smtp_port=resolved_smtp_port,
            smtp_ssl=resolved_smtp_ssl,
            badge_color=payload.badge_color or preset.badge_color,
            signature=payload.signature,
            include_in_unified=payload.include_in_unified,
            notify_enabled=payload.notify_enabled,
            sort_order=next_order,
            is_demo=False,
        )
        created = account_repo.create(db, acc)
        logger.info("Added new email account id=%s provider=%s", created.id, created.provider)
        from app.service.scheduler_service import scheduler_service

        scheduler_service.notify_accounts_changed()
        counts_map = account_repo.get_counts_by_account(db)
        return self._to_out(created, counts_map)

    def update_account(self, db: Session, account_id: int, payload: AccountUpdate) -> AccountOut:
        """修改邮箱设置（别名、授权码、服务器、签名、聚合/通知开关等）。"""
        acc = account_repo.get_by_id(db, account_id)
        if not acc:
            raise ValueError("未找到指定邮箱账号。")

        data = payload.model_dump(exclude_unset=True)
        connection_fields = {"secret", "imap_host", "imap_port", "imap_ssl", "is_enabled"}
        needs_restart = bool(connection_fields.intersection(data.keys()))

        if "secret" in data:
            secret_val = data.pop("secret")
            if secret_val:
                normalized = normalize_secret(acc.provider, str(secret_val), acc.imap_host)
                acc.encrypted_secret = crypto_service.encrypt(normalized)
                acc.last_error = None
                acc.sync_status = "idle"
        for field, value in data.items():
            setattr(acc, field, value)

        saved = account_repo.save(db, acc)
        from app.service.scheduler_service import scheduler_service

        scheduler_service.notify_accounts_changed(
            force_restart_account_id=saved.id if needs_restart else None
        )
        counts_map = account_repo.get_counts_by_account(db)
        return self._to_out(saved, counts_map)

    def delete_account(self, db: Session, account_id: int) -> None:
        """删除邮箱账号及其关联本地邮件。"""
        acc = account_repo.get_by_id(db, account_id)
        if not acc:
            raise ValueError("未找到指定邮箱账号。")
        account_repo.delete(db, acc)
        imap_sync_service.clear_account_cache(account_id)
        from app.service.scheduler_service import scheduler_service

        scheduler_service.notify_accounts_changed()
        logger.info("Deleted email account id=%s", account_id)

    def reorder_accounts(self, db: Session, ordered_ids: list[int]) -> list[AccountOut]:
        """更新「我的邮箱」显示顺序。"""
        account_repo.reorder(db, ordered_ids)
        return self.list_accounts(db)

    async def sync_all_accounts(
        self,
        db: Session,
        *,
        inbox_only: bool = False,
        source: str = "manual",
    ) -> dict[str, object]:
        """并发调度全部已启用账号执行邮件同步（每账号独立会话隔离）。"""
        accounts = account_repo.list_all(db)
        enabled_ids = [acc.id for acc in accounts if acc.is_enabled]
        if not enabled_ids:
            return {"ok": True, "fetched": 0, "results": []}

        sem = asyncio.Semaphore(4)

        async def _sync_one(aid: int) -> dict[str, object]:
            async with sem:
                with SessionLocal() as task_db:
                    acc = account_repo.get_by_id(task_db, aid)
                    if acc is None or not acc.is_enabled:
                        return {"account_id": aid, "ok": True, "fetched": 0, "message": "账号已停用"}
                    ok, fetched, message = await imap_sync_service.sync_account(
                        task_db,
                        acc,
                        inbox_only=inbox_only,
                        source=source,
                    )
                    return {"account_id": aid, "ok": ok, "fetched": fetched, "message": message}

        results = list(await asyncio.gather(*(_sync_one(aid) for aid in enabled_ids)))
        total_fetched = sum(int(item["fetched"]) for item in results)
        return {"ok": True, "fetched": total_fetched, "results": results}

    async def sync_single_account(
        self,
        db: Session,
        account_id: int,
        *,
        inbox_only: bool = False,
        source: str = "manual",
    ) -> dict[str, object]:
        """调度单个邮箱立即执行同步。"""
        acc = account_repo.get_by_id(db, account_id)
        if not acc:
            raise ValueError("未找到指定邮箱账号。")
        ok, fetched, message = await imap_sync_service.sync_account(
            db,
            acc,
            inbox_only=inbox_only,
            source=source,
        )
        return {"ok": ok, "fetched": fetched, "message": message}

    async def quick_check_accounts(self, account_id: int | None = None) -> dict[str, object]:
        """触发实时连接瞬时检查（或在未启用实时长连接时快速增量同步收件箱）。"""
        from app.service.realtime_sync_service import realtime_sync_manager

        return await realtime_sync_manager.trigger_quick_check(account_id=account_id)


account_service = AccountService()
