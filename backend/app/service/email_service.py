from datetime import datetime, timezone
import html
import re
import uuid
from sqlalchemy.orm import Session

from app.model.entities import Email
from app.repository.account_repo import account_repo
from app.repository.email_repo import email_repo
from app.schema.schemas import (
    AttachmentOut,
    DraftSaveRequest,
    EmailDetailOut,
    EmailListResponse,
    EmailPatchRequest,
    EmailSummaryOut,
    FolderCountsOut,
)
from app.service.smtp_send_service import smtp_send_service

HTML_TAG_RE = re.compile(r"<[^>]+>")


class EmailService:
    """邮件列表检索、状态流转、草稿与发送核心服务层。"""

    def _to_summary(self, item: Email) -> EmailSummaryOut:
        return EmailSummaryOut(
            id=item.id,
            account_id=item.account_id,
            account_label=item.account.label if item.account else "",
            account_email=item.account.email if item.account else "",
            account_color=item.account.badge_color if item.account else "#8B6CE8",
            folder=item.folder,
            category=item.category,
            sender_name=item.sender_name,
            sender_email=item.sender_email,
            sender_avatar_key=item.sender_avatar_key,
            subject=item.subject,
            snippet=item.snippet,
            is_read=item.is_read,
            is_starred=item.is_starred,
            has_attachments=item.has_attachments,
            received_at=item.received_at,
        )

    def _to_detail(self, item: Email) -> EmailDetailOut:
        return EmailDetailOut(
            id=item.id,
            account_id=item.account_id,
            account_label=item.account.label if item.account else "",
            account_email=item.account.email if item.account else "",
            account_color=item.account.badge_color if item.account else "#8B6CE8",
            folder=item.folder,
            category=item.category,
            sender_name=item.sender_name,
            sender_email=item.sender_email,
            sender_avatar_key=item.sender_avatar_key,
            subject=item.subject,
            snippet=item.snippet,
            is_read=item.is_read,
            is_starred=item.is_starred,
            has_attachments=item.has_attachments,
            received_at=item.received_at,
            message_id=item.message_id,
            to_addresses=list(item.to_addresses or []),
            cc_addresses=list(item.cc_addresses or []),
            bcc_addresses=list(item.bcc_addresses or []),
            html_body=item.html_body,
            text_body=item.text_body,
            has_remote_images=item.has_remote_images,
            raw_headers=item.raw_headers,
            attachments=[
                AttachmentOut(
                    id=att.id,
                    filename=att.filename,
                    content_type=att.content_type,
                    size_bytes=att.size_bytes,
                )
                for att in item.attachments
            ],
        )

    def list_emails(
        self,
        db: Session,
        *,
        folder: str = "inbox",
        category: str = "all",
        account_id: int | None = None,
        account_ids: list[int] | None = None,
        query: str = "",
        unread_only: bool = False,
        has_attachments: bool = False,
        page: int = 1,
        page_size: int = 8,
    ) -> EmailListResponse:
        """分页获取邮件并附带实时文件夹统计数。"""
        items, total, total_pages = email_repo.list_emails(
            db,
            folder=folder,
            category=category,
            account_id=account_id,
            account_ids=account_ids,
            query=query,
            unread_only=unread_only,
            has_attachments=has_attachments,
            page=page,
            page_size=page_size,
        )
        counts = email_repo.get_folder_counts(db, account_id=account_id, account_ids=account_ids)
        return EmailListResponse(
            items=[self._to_summary(it) for it in items],
            total=total,
            page=min(max(1, page), total_pages),
            page_size=page_size,
            total_pages=total_pages,
            folder_counts=FolderCountsOut(**counts),
        )

    def get_email(self, db: Session, email_id: int) -> EmailDetailOut:
        """获取邮件详情，不存在则抛出 ValueError。"""
        item = email_repo.get_by_id(db, email_id)
        if not item:
            raise ValueError("未找到该封邮件。")
        return self._to_detail(item)

    def patch_email(self, db: Session, email_id: int, payload: EmailPatchRequest) -> EmailDetailOut:
        """更新单封邮件已读/星标/文件夹/分类状态。"""
        item = email_repo.get_by_id(db, email_id)
        if not item:
            raise ValueError("未找到该封邮件。")
        updates = payload.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(item, key, value)
        saved = email_repo.save(db, item)
        return self._to_detail(saved)

    def delete_email(self, db: Session, email_id: int) -> None:
        """彻底删除单封邮件。"""
        item = email_repo.get_by_id(db, email_id)
        if not item:
            raise ValueError("未找到该封邮件。")
        email_repo.delete(db, item)

    def batch_action(self, db: Session, email_ids: list[int], action: str) -> int:
        """执行批量邮件操作并返回处理数量。"""
        return email_repo.batch_update(db, email_ids, action)

    def save_draft(self, db: Session, payload: DraftSaveRequest) -> EmailDetailOut:
        """新建或更新草稿箱邮件。"""
        acc = account_repo.get_by_id(db, payload.account_id)
        if not acc:
            raise ValueError("所选发件账号不存在。")

        plain = payload.text_body.strip()
        if not plain and payload.html_body:
            plain = " ".join(HTML_TAG_RE.sub(" ", payload.html_body).split())
        html_content = payload.html_body.strip() or f"<div>{html.escape(plain)}</div>"
        snippet = " ".join(plain.split())[:160]

        if payload.draft_id is not None:
            existing = email_repo.get_by_id(db, payload.draft_id)
            if existing and existing.folder == "drafts":
                existing.account_id = acc.id
                existing.to_addresses = payload.to_addresses
                existing.cc_addresses = payload.cc_addresses
                existing.subject = payload.subject or "(无主题草稿)"
                existing.html_body = html_content
                existing.text_body = plain
                existing.snippet = snippet
                existing.received_at = datetime.now(timezone.utc)
                saved = email_repo.save(db, existing)
                return self._to_detail(saved)

        draft = Email(
            account_id=acc.id,
            message_uid=f"draft-{uuid.uuid4().hex[:12]}",
            message_id="",
            folder="drafts",
            category="work",
            sender_name=acc.label,
            sender_email=acc.email,
            sender_avatar_key=acc.provider,
            to_addresses=payload.to_addresses,
            cc_addresses=payload.cc_addresses,
            bcc_addresses=[],
            subject=payload.subject or "(无主题草稿)",
            snippet=snippet,
            html_body=html_content,
            text_body=plain,
            is_read=True,
            is_starred=False,
            has_attachments=False,
            received_at=datetime.now(timezone.utc),
        )
        created = email_repo.create(db, draft)
        return self._to_detail(created)

    async def send_email(
        self,
        db: Session,
        *,
        account_id: int,
        to_addresses: list[str],
        cc_addresses: list[str],
        bcc_addresses: list[str],
        subject: str,
        html_body: str,
        text_body: str,
        in_reply_to: str = "",
        draft_id: int | None = None,
        uploaded_files: list[tuple[str, str, bytes]] | None = None,
    ) -> EmailDetailOut:
        """调度 SMTP 发信服务并入库发件箱。"""
        acc = account_repo.get_by_id(db, account_id)
        if not acc:
            raise ValueError("所选发件账号不存在。")

        sent = await smtp_send_service.send_email(
            db,
            account=acc,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            bcc_addresses=bcc_addresses,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            in_reply_to=in_reply_to,
            draft_id=draft_id,
            uploaded_files=uploaded_files,
        )
        refreshed = email_repo.get_by_id(db, sent.id)
        return self._to_detail(refreshed or sent)


email_service = EmailService()
