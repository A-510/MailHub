from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.database import Base


def utc_now() -> datetime:
    """返回带 UTC 时区信息的当前时间。"""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """确保 SQLite 读写均保持 UTC 时区语义与一致的无偏移字符串存储格式。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Account(Base):
    """邮箱渠道账号 ORM 模型（敏感凭据均以密文形式存储）。"""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    auth_type: Mapped[str] = mapped_column(String(16), nullable=False, default="password")

    # 加密存储的授权码/密码或 OAuth2 access_token / refresh_token
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    imap_host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    imap_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    imap_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=465)
    smtp_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    badge_color: Mapped[str] = mapped_column(String(32), nullable=False, default="#8B6CE8")
    signature: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_in_unified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    emails: Mapped[list["Email"]] = relationship(
        "Email",
        back_populates="account",
        cascade="all, delete-orphan",
    )


class Email(Base):
    """本地缓存的邮件实体 ORM 模型。"""

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    folder: Mapped[str] = mapped_column(String(32), nullable=False, default="inbox", index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="work", index=True)

    sender_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sender_avatar_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    to_addresses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cc_addresses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    bcc_addresses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    subject: Mapped[str] = mapped_column(String(512), nullable=False, default="(无主题)")
    snippet: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    html_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    text_body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    has_remote_images: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_headers: Mapped[str] = mapped_column(Text, nullable=False, default="")

    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    account: Mapped["Account"] = relationship("Account", back_populates="emails")
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        back_populates="email",
        cascade="all, delete-orphan",
    )


class Attachment(Base):
    """邮件附件元数据 ORM 模型。"""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("emails.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    local_path: Mapped[str] = mapped_column(Text, nullable=False, default="")

    email: Mapped["Email"] = relationship("Email", back_populates="attachments")


class ClassificationRule(Base):
    """智能邮件分类规则 ORM 模型。"""

    __tablename__ = "classification_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    field: Mapped[str] = mapped_column(String(32), nullable=False, default="sender_email")
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    target_category: Mapped[str] = mapped_column(String(32), nullable=False, default="work")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class AppSetting(Base):
    """应用键值持久化设置表。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)


class SyncLog(Base):
    """邮箱同步与系统提醒日志表。"""

    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now, index=True)
