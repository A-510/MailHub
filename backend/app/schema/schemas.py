from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import AfterValidator, BaseModel, EmailStr, Field


def _ensure_utc(dt: datetime) -> datetime:
    """确保序列化输出的 datetime 携带 UTC 时区信息（避免裸时间被前端误当本地时间）。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]


ProviderType = Literal["gmail", "outlook", "qq", "163", "126", "icloud", "school", "custom"]
AuthType = Literal["password", "oauth2"]
FolderType = Literal["inbox", "sent", "drafts", "archive", "spam", "trash"]
CategoryType = Literal["work", "study", "social", "subscription"]
ThemeModeType = Literal["light", "dark", "system"]
MotionLevelType = Literal["full", "gentle", "off"]
FontSizeType = Literal["sm", "md", "lg"]
ListDensityType = Literal["compact", "comfortable"]


class ProviderPresetOut(BaseModel):
    """邮箱渠道预设响应模型。"""

    id: str
    name: str
    domains: list[str]
    imap_host: str
    imap_port: int
    imap_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    supports_oauth: bool
    requires_imap_id: bool
    badge_color: str
    auth_guide_url: str
    auth_guide_tip: str


class AccountCreate(BaseModel):
    """创建或测试邮箱账号请求模型。"""

    label: str = Field(min_length=1, max_length=64)
    email: EmailStr
    provider: ProviderType = "custom"
    auth_type: AuthType = "password"
    secret: str | None = Field(default=None, max_length=4096)
    imap_host: str = Field(default="", max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_ssl: bool = True
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_ssl: bool = True
    badge_color: str = Field(default="#8B6CE8", max_length=32)
    signature: str = Field(default="", max_length=2000)
    include_in_unified: bool = True
    notify_enabled: bool = True
    verify_connection: bool = False


class AccountTestRequest(BaseModel):
    """连接测试请求模型。"""

    email: EmailStr
    provider: ProviderType = "custom"
    secret: str = Field(min_length=1, max_length=4096)
    imap_host: str = Field(default="", max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_ssl: bool = True
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_ssl: bool = True


class AccountTestResult(BaseModel):
    """连接测试诊断结果。"""

    ok: bool
    imap_ok: bool
    smtp_ok: bool
    message: str
    resolved_smtp_port: int | None = None
    resolved_smtp_ssl: bool | None = None


class AccountUpdate(BaseModel):
    """更新邮箱账号属性请求模型。"""

    label: str | None = Field(default=None, min_length=1, max_length=64)
    secret: str | None = Field(default=None, max_length=4096)
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_ssl: bool | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_ssl: bool | None = None
    badge_color: str | None = Field(default=None, max_length=32)
    signature: str | None = Field(default=None, max_length=2000)
    is_enabled: bool | None = None
    include_in_unified: bool | None = None
    notify_enabled: bool | None = None


class AccountReorderRequest(BaseModel):
    """账号排序更新请求模型。"""

    ordered_ids: list[int] = Field(min_length=1)


class AccountOut(BaseModel):
    """返回给前端的安全邮箱账号视图（绝不暴露密钥）。"""

    id: int
    label: str
    email: str
    provider: str
    auth_type: str
    imap_host: str
    imap_port: int
    imap_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    badge_color: str
    signature: str
    is_enabled: bool
    include_in_unified: bool
    notify_enabled: bool
    sort_order: int
    last_synced_at: UtcDatetime | None
    sync_status: str
    last_error: str | None
    is_demo: bool
    unread_count: int = 0
    total_count: int = 0


class AttachmentOut(BaseModel):
    """附件响应模型。"""

    id: int
    filename: str
    content_type: str
    size_bytes: int


class EmailSummaryOut(BaseModel):
    """左页邮件列表项响应模型。"""

    id: int
    account_id: int
    account_label: str
    account_email: str
    account_color: str
    folder: str
    category: str
    sender_name: str
    sender_email: str
    sender_avatar_key: str
    subject: str
    snippet: str
    is_read: bool
    is_starred: bool
    has_attachments: bool
    received_at: UtcDatetime


class EmailDetailOut(EmailSummaryOut):
    """右页邮件详情完整响应模型。"""

    message_id: str
    to_addresses: list[str]
    cc_addresses: list[str]
    bcc_addresses: list[str]
    html_body: str
    text_body: str
    has_remote_images: bool
    raw_headers: str
    attachments: list[AttachmentOut]


class FolderCountsOut(BaseModel):
    """左侧文件夹实时统计数。"""

    inbox: int = 0
    inbox_unread: int = 0
    unread: int = 0
    starred: int = 0
    sent: int = 0
    drafts: int = 0
    archive: int = 0
    spam: int = 0
    trash: int = 0


class EmailListResponse(BaseModel):
    """分页邮件列表响应模型。"""

    items: list[EmailSummaryOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    folder_counts: FolderCountsOut


class EmailPatchRequest(BaseModel):
    """单封邮件状态更新请求模型。"""

    is_read: bool | None = None
    is_starred: bool | None = None
    folder: FolderType | None = None
    category: CategoryType | None = None


class EmailBatchRequest(BaseModel):
    """批量邮件操作请求模型。"""

    email_ids: list[int] = Field(min_length=1)
    action: Literal["mark_read", "mark_unread", "star", "unstar", "archive", "trash", "spam", "delete_forever"]


class DraftSaveRequest(BaseModel):
    """保存或更新草稿请求模型。"""

    draft_id: int | None = None
    account_id: int
    to_addresses: list[str] = Field(default_factory=list)
    cc_addresses: list[str] = Field(default_factory=list)
    subject: str = Field(default="", max_length=512)
    html_body: str = Field(default="")
    text_body: str = Field(default="")


class ClassificationRuleCreate(BaseModel):
    """创建自动分类规则请求模型。"""

    name: str = Field(min_length=1, max_length=128)
    field: Literal["sender_email", "sender_name", "subject"] = "sender_email"
    pattern: str = Field(min_length=1, max_length=255)
    target_category: CategoryType = "work"
    is_enabled: bool = True


class ClassificationRuleUpdate(BaseModel):
    """更新自动分类规则请求模型。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    field: Literal["sender_email", "sender_name", "subject"] | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=255)
    target_category: CategoryType | None = None
    is_enabled: bool | None = None


class ClassificationRuleOut(BaseModel):
    """自动分类规则响应模型。"""

    id: int
    name: str
    field: str
    pattern: str
    target_category: str
    is_enabled: bool


class AppSettingsOut(BaseModel):
    """完整应用设置响应模型。"""

    theme_mode: ThemeModeType = "light"
    show_mascots: bool = True
    mascot_opacity: float = Field(default=0.96, ge=0.2, le=1.0)
    custom_mascot_left: str | None = None
    custom_mascot_right: str | None = None
    show_particles: bool = True
    motion_level: MotionLevelType = "full"
    font_size: FontSizeType = "md"
    list_density: ListDensityType = "comfortable"
    default_account_id: int | None = None
    smart_send_from: bool = True
    undo_send_seconds: int = Field(default=5, ge=0, le=30)
    sync_interval_minutes: int = Field(default=5, ge=0, le=60)
    sync_days: int = Field(default=30, ge=0, le=365)
    realtime_push: bool = True
    desktop_notifications: bool = True
    block_remote_images: bool = False
    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = ""
    oauth_microsoft_client_id: str = ""


class AppSettingsPatch(BaseModel):
    """应用设置局部更新模型。"""

    theme_mode: ThemeModeType | None = None
    show_mascots: bool | None = None
    mascot_opacity: float | None = Field(default=None, ge=0.2, le=1.0)
    custom_mascot_left: str | None = None
    custom_mascot_right: str | None = None
    show_particles: bool | None = None
    motion_level: MotionLevelType | None = None
    font_size: FontSizeType | None = None
    list_density: ListDensityType | None = None
    default_account_id: int | None = None
    smart_send_from: bool | None = None
    undo_send_seconds: int | None = Field(default=None, ge=0, le=30)
    sync_interval_minutes: int | None = Field(default=None, ge=0, le=60)
    sync_days: int | None = Field(default=None, ge=0, le=365)
    realtime_push: bool | None = None
    desktop_notifications: bool | None = None
    block_remote_images: bool | None = None
    oauth_google_client_id: str | None = None
    oauth_google_client_secret: str | None = None
    oauth_microsoft_client_id: str | None = None


class OAuthStartRequest(BaseModel):
    """发起浏览器 OAuth2 PKCE 登录请求模型。"""

    provider: Literal["gmail", "outlook"]
    label: str = Field(default="", max_length=64)
    email_hint: str = Field(default="", max_length=255)


class OAuthStartResponse(BaseModel):
    """发起浏览器 OAuth2 登录返回结果。"""

    state: str
    auth_url: str
    browser_opened: bool


class OAuthStatusResponse(BaseModel):
    """轮询 OAuth2 授权状态响应模型。"""

    state: str
    status: Literal["pending", "completed", "failed", "expired"]
    message: str = ""
    account: AccountOut | None = None


class StorageInfoOut(BaseModel):
    """本地存储占用统计响应模型。"""

    db_size_bytes: int
    attachments_size_bytes: int
    attachments_count: int
    emails_count: int
    accounts_count: int
    demo_accounts_count: int


class SyncLogOut(BaseModel):
    """同步与通知日志响应模型。"""

    id: int
    account_id: int | None
    status: str
    fetched_count: int
    message: str
    created_at: UtcDatetime


class DiagnosticsAccountSummary(BaseModel):
    """脱敏后的邮箱渠道诊断摘要（不含明文邮箱全称或凭据）。"""

    id: int
    provider: str
    auth_type: str
    masked_email: str
    imap_host: str
    imap_port: int
    imap_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    is_enabled: bool
    is_demo: bool
    sync_status: str
    last_synced_at: UtcDatetime | None
    last_error: str | None


class DiagnosticsSettingsSummary(BaseModel):
    """脱敏后的运行设置摘要。"""

    theme_mode: str
    motion_level: str
    sync_interval_minutes: int
    sync_days: int
    realtime_push: bool = True
    undo_send_seconds: int
    block_remote_images: bool
    oauth_google_configured: bool
    oauth_microsoft_configured: bool


class DiagnosticsSyncLogSummary(BaseModel):
    """脱敏后的同步日志摘要。"""

    status: str
    fetched_count: int
    message: str
    created_at: UtcDatetime


class DiagnosticsOut(BaseModel):
    """用于 Issue 排障的脱敏诊断快照与 Markdown 报告。"""

    event_id: str
    generated_at: UtcDatetime
    app_name: str
    app_version: str
    git_commit: str | None
    os_info: str
    python_version: str
    arch: str
    host: str
    port: int
    frontend_dist_ready: bool
    secret_key_mode: Literal["env", "file", "missing"]
    storage: StorageInfoOut
    settings_summary: DiagnosticsSettingsSummary
    accounts: list[DiagnosticsAccountSummary]
    recent_sync_logs: list[DiagnosticsSyncLogSummary]
    backend_log_lines: list[str]
    launcher_log_lines: list[str]
    markdown_report: str
