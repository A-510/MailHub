from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.model.entities import Account, Email, SyncLog


class AccountRepository:
    """邮箱渠道账号仓储层，负责 accounts 表的持久化操作。"""

    def list_all(self, db: Session) -> list[Account]:
        """按 sort_order 与 id 升序返回全部邮箱账号。"""
        stmt = select(Account).order_by(Account.sort_order.asc(), Account.id.asc())
        return list(db.scalars(stmt).all())

    def get_by_id(self, db: Session, account_id: int) -> Account | None:
        """根据主键 ID 查询邮箱账号。"""
        return db.get(Account, account_id)

    def get_by_email(self, db: Session, email_address: str) -> Account | None:
        """根据邮箱地址查询账号（忽略大小写）。"""
        stmt = select(Account).where(func.lower(Account.email) == email_address.strip().lower())
        return db.scalar(stmt)

    def create(self, db: Session, account: Account) -> Account:
        """新增邮箱账号。"""
        db.add(account)
        db.commit()
        db.refresh(account)
        return account

    def save(self, db: Session, account: Account) -> Account:
        """保存邮箱账号变更。"""
        db.add(account)
        db.commit()
        db.refresh(account)
        return account

    def delete(self, db: Session, account: Account) -> None:
        """删除邮箱账号及其级联邮件。"""
        db.delete(account)
        db.commit()

    def get_max_sort_order(self, db: Session) -> int:
        """获取当前最大排序值。"""
        val = db.scalar(select(func.max(Account.sort_order)))
        return int(val) if val is not None else -1

    def reorder(self, db: Session, ordered_ids: list[int]) -> None:
        """批量更新邮箱账号排序权重。"""
        accounts = self.list_all(db)
        order_map = {acc_id: idx for idx, acc_id in enumerate(ordered_ids)}
        next_tail = len(ordered_ids)
        for acc in accounts:
            if acc.id in order_map:
                acc.sort_order = order_map[acc.id]
            else:
                acc.sort_order = next_tail
                next_tail += 1
        db.commit()

    def get_counts_by_account(self, db: Session) -> dict[int, tuple[int, int]]:
        """
        统计每个账号在收件箱中的 (未读数, 总数)。
        返回映射: {account_id: (unread_count, total_count)}
        """
        rows = db.execute(
            select(
                Email.account_id,
                func.count(Email.id),
                func.sum(func.iif(Email.is_read.is_(False), 1, 0)),
            )
            .where(Email.folder == "inbox")
            .group_by(Email.account_id)
        ).all()
        result: dict[int, tuple[int, int]] = {}
        for account_id, total_cnt, unread_cnt in rows:
            result[int(account_id)] = (int(unread_cnt or 0), int(total_cnt or 0))
        return result

    def add_sync_log(
        self,
        db: Session,
        account_id: int | None,
        status: str,
        fetched_count: int,
        message: str,
    ) -> SyncLog:
        """记录同步日志，仅保留最近 100 条。"""
        log = SyncLog(
            account_id=account_id,
            status=status,
            fetched_count=fetched_count,
            message=message,
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        # 清理超出 100 条的旧日志避免无限增长
        old_ids = list(
            db.scalars(select(SyncLog.id).order_by(SyncLog.created_at.desc(), SyncLog.id.desc()).offset(100)).all()
        )
        if old_ids:
            db.query(SyncLog).filter(SyncLog.id.in_(old_ids)).delete(synchronize_session=False)
            db.commit()
        return log

    def list_sync_logs(self, db: Session, limit: int = 30) -> list[SyncLog]:
        """获取最近同步通知日志。"""
        stmt = select(SyncLog).order_by(SyncLog.created_at.desc(), SyncLog.id.desc()).limit(limit)
        return list(db.scalars(stmt).all())


account_repo = AccountRepository()
