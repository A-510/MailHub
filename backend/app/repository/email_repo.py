import math
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session, joinedload

from app.model.entities import Account, Attachment, Email


class EmailRepository:
    """邮件与附件数据库仓储层（含 SQLite FTS5 全文检索）。"""

    def _apply_scope_filters(
        self,
        stmt: object,
        folder: str,
        account_id: int | None,
        account_ids: list[int] | None,
        category: str | None,
        unread_only: bool,
        has_attachments: bool,
    ) -> object:
        conditions = []

        # 筛选所属账号范围
        if account_id is not None:
            conditions.append(Email.account_id == account_id)
        elif account_ids is not None:
            if len(account_ids) == 0:
                conditions.append(Email.account_id == -1)
            else:
                conditions.append(Email.account_id.in_(account_ids))

        # 左侧特殊虚拟视图：未读 / 星标，其余为实体文件夹
        if folder == "unread":
            conditions.append(Email.folder == "inbox")
            conditions.append(Email.is_read.is_(False))
        elif folder == "starred":
            conditions.append(Email.is_starred.is_(True))
            conditions.append(Email.folder != "trash")
        else:
            conditions.append(Email.folder == folder)

        if category and category != "all":
            conditions.append(Email.category == category)

        if unread_only:
            conditions.append(Email.is_read.is_(False))

        if has_attachments:
            conditions.append(Email.has_attachments.is_(True))

        if conditions:
            stmt = stmt.where(and_(*conditions))  # type: ignore[attr-defined]
        return stmt

    def _search_fts_ids(self, db: Session, query_text: str) -> list[int]:
        """
        优先使用 FTS5 匹配，并在包含特殊字符或短中文分词场景下补充 LIKE 兜底，
        保证中英文关键词都能准确命中。
        """
        cleaned = query_text.strip()
        if not cleaned:
            return []

        matched_ids: set[int] = set()
        # 构造安全 FTS5 短语查询（用双引号转义避免语法符错误）
        safe_phrase = cleaned.replace('"', '""')
        try:
            fts_rows = db.execute(
                text("SELECT rowid FROM emails_fts WHERE emails_fts MATCH :q LIMIT 500"),
                {"q": f'"{safe_phrase}"*'},
            ).all()
            matched_ids.update(int(r[0]) for r in fts_rows)
        except Exception:
            # 某些特殊符号组合可能导致 MATCH 语法回退，安全交由下方 LIKE 处理
            pass

        like_pattern = f"%{cleaned}%"
        like_rows = db.scalars(
            select(Email.id).where(
                or_(
                    Email.subject.ilike(like_pattern),
                    Email.sender_name.ilike(like_pattern),
                    Email.sender_email.ilike(like_pattern),
                    Email.snippet.ilike(like_pattern),
                    Email.text_body.ilike(like_pattern),
                )
            )
        ).all()
        matched_ids.update(int(eid) for eid in like_rows)
        return list(matched_ids)

    def list_emails(
        self,
        db: Session,
        *,
        folder: str = "inbox",
        category: str | None = None,
        account_id: int | None = None,
        account_ids: list[int] | None = None,
        query: str = "",
        unread_only: bool = False,
        has_attachments: bool = False,
        page: int = 1,
        page_size: int = 12,
    ) -> tuple[list[Email], int, int]:
        """分页检索邮件列表，返回 (当前页邮件, 总条数, 总页数)。"""
        base_stmt = select(Email).options(joinedload(Email.account))
        base_stmt = self._apply_scope_filters(
            base_stmt,
            folder=folder,
            account_id=account_id,
            account_ids=account_ids,
            category=category,
            unread_only=unread_only,
            has_attachments=has_attachments,
        )

        count_stmt = select(func.count(Email.id))
        count_stmt = self._apply_scope_filters(
            count_stmt,
            folder=folder,
            account_id=account_id,
            account_ids=account_ids,
            category=category,
            unread_only=unread_only,
            has_attachments=has_attachments,
        )

        if query.strip():
            matched_ids = self._search_fts_ids(db, query)
            if not matched_ids:
                return [], 0, 1
            base_stmt = base_stmt.where(Email.id.in_(matched_ids))
            count_stmt = count_stmt.where(Email.id.in_(matched_ids))

        total = int(db.scalar(count_stmt) or 0)
        total_pages = max(1, math.ceil(total / page_size))
        safe_page = min(max(1, page), total_pages)
        offset = (safe_page - 1) * page_size

        items = list(
            db.scalars(
                base_stmt.order_by(Email.received_at.desc(), Email.id.desc())
                .offset(offset)
                .limit(page_size)
            )
            .unique()
            .all()
        )
        return items, total, total_pages

    def get_folder_counts(
        self,
        db: Session,
        account_id: int | None = None,
        account_ids: list[int] | None = None,
    ) -> dict[str, int]:
        """计算各文件夹及虚拟视图数量统计。"""
        scope_conds = []
        if account_id is not None:
            scope_conds.append(Email.account_id == account_id)
        elif account_ids is not None:
            if len(account_ids) == 0:
                scope_conds.append(Email.account_id == -1)
            else:
                scope_conds.append(Email.account_id.in_(account_ids))

        folder_rows = db.execute(
            select(Email.folder, func.count(Email.id))
            .where(*scope_conds)
            .group_by(Email.folder)
        ).all()
        counts: dict[str, int] = {
            "inbox": 0,
            "inbox_unread": 0,
            "unread": 0,
            "starred": 0,
            "sent": 0,
            "drafts": 0,
            "archive": 0,
            "spam": 0,
            "trash": 0,
        }
        for folder_name, cnt in folder_rows:
            if folder_name in counts:
                counts[folder_name] = int(cnt or 0)

        unread_count = db.scalar(
            select(func.count(Email.id)).where(
                *scope_conds,
                Email.folder == "inbox",
                Email.is_read.is_(False),
            )
        )
        starred_count = db.scalar(
            select(func.count(Email.id)).where(
                *scope_conds,
                Email.is_starred.is_(True),
                Email.folder != "trash",
            )
        )
        counts["inbox_unread"] = int(unread_count or 0)
        counts["unread"] = int(unread_count or 0)
        counts["starred"] = int(starred_count or 0)
        return counts

    def get_by_id(self, db: Session, email_id: int) -> Email | None:
        """查询单封邮件完整详情（预加载账号与附件）。"""
        stmt = (
            select(Email)
            .options(joinedload(Email.account), joinedload(Email.attachments))
            .where(Email.id == email_id)
        )
        return db.scalar(stmt)

    def exists_uid(self, db: Session, account_id: int, folder: str, message_uid: str) -> bool:
        """检查指定账号指定文件夹下的 UID 是否已入库，防止重复拉取。"""
        stmt = select(Email.id).where(
            Email.account_id == account_id,
            Email.folder == folder,
            Email.message_uid == message_uid,
        )
        return db.scalar(stmt) is not None

    def get_uid_map_by_folder(self, db: Session, account_id: int, folder: str) -> dict[str, Email]:
        """获取指定账号指定文件夹下的 UID 到邮件实体映射，用于增量同步与状态刷新。"""
        stmt = select(Email).where(
            Email.account_id == account_id,
            Email.folder == folder,
        )
        items = db.scalars(stmt).all()
        return {item.message_uid: item for item in items if item.message_uid}

    def get_message_id_map_by_folder(self, db: Session, account_id: int, folder: str) -> dict[str, Email]:
        """获取指定账号指定文件夹下非空 Message-ID（小写）到邮件实体映射，用于去重。"""
        stmt = select(Email).where(
            Email.account_id == account_id,
            Email.folder == folder,
            Email.message_id != "",
        )
        items = db.scalars(stmt).all()
        result: dict[str, Email] = {}
        for item in items:
            normalized_id = item.message_id.strip().lower()
            if normalized_id and normalized_id not in result:
                result[normalized_id] = item
        return result

    def get_all_message_ids_for_account(self, db: Session, account_id: int) -> set[str]:
        """获取指定账号下所有文件夹中非空 Message-ID（小写）集合，用于归档目录去重。"""
        stmt = select(Email.message_id).where(
            Email.account_id == account_id,
            Email.message_id != "",
        )
        raw_ids = db.scalars(stmt).all()
        return {mid.strip().lower() for mid in raw_ids if mid and mid.strip()}

    def mark_starred_by_message_ids(self, db: Session, account_id: int, message_ids: set[str]) -> int:
        """根据虚拟星标目录返回的 Message-ID 集合，为指定账号补齐星标状态并返回更新数量。"""
        normalized_ids = {mid.strip().lower() for mid in message_ids if mid and mid.strip()}
        if not normalized_ids:
            return 0

        stmt = select(Email).where(
            Email.account_id == account_id,
            Email.is_starred.is_(False),
            Email.message_id != "",
        )
        candidates = db.scalars(stmt).all()
        updated_count = 0
        for item in candidates:
            if item.message_id.strip().lower() in normalized_ids:
                item.is_starred = True
                db.add(item)
                updated_count += 1
        if updated_count > 0:
            db.commit()
        return updated_count

    def create(self, db: Session, email_obj: Email) -> Email:
        """保存新邮件（含附件级联）。"""
        db.add(email_obj)
        db.commit()
        db.refresh(email_obj)
        return email_obj

    def save(self, db: Session, email_obj: Email) -> Email:
        """保存邮件状态修改。"""
        db.add(email_obj)
        db.commit()
        db.refresh(email_obj)
        return email_obj

    def delete(self, db: Session, email_obj: Email) -> None:
        """永久删除单封邮件。"""
        db.delete(email_obj)
        db.commit()

    def batch_update(self, db: Session, email_ids: list[int], action: str) -> int:
        """批量更新或删除邮件，返回受影响条数。"""
        if not email_ids:
            return 0
        items = list(db.scalars(select(Email).where(Email.id.in_(email_ids))).all())
        if action == "delete_forever":
            for item in items:
                db.delete(item)
            db.commit()
            return len(items)

        for item in items:
            if action == "mark_read":
                item.is_read = True
            elif action == "mark_unread":
                item.is_read = False
            elif action == "star":
                item.is_starred = True
            elif action == "unstar":
                item.is_starred = False
            elif action == "archive":
                item.folder = "archive"
            elif action == "trash":
                item.folder = "trash"
            elif action == "spam":
                item.folder = "spam"
        db.commit()
        return len(items)

    def get_attachment(self, db: Session, attachment_id: int) -> Attachment | None:
        """根据 ID 获取附件记录。"""
        return db.get(Attachment, attachment_id)

    def list_all_for_classification(self, db: Session) -> list[Email]:
        """读取现有邮件用于规则更新后的可选重分类。"""
        return list(db.scalars(select(Email)).all())


email_repo = EmailRepository()
