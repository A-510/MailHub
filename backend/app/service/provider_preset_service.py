from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    """主流邮箱服务商协议预设配置。"""

    id: str
    name: str
    domains: tuple[str, ...]
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


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        id="qq",
        name="QQ 邮箱",
        domains=("qq.com", "foxmail.com"),
        imap_host="imap.qq.com",
        imap_port=993,
        imap_ssl=True,
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_ssl=True,
        supports_oauth=False,
        requires_imap_id=False,
        badge_color="#3B82F6",
        auth_guide_url="https://mail.qq.com/",
        auth_guide_tip="请使用 QQ 邮箱网页版 -> 设置 -> 账户 -> POP3/IMAP 服务中生成的 16 位授权码登录（非 QQ 登录密码）。",
    ),
    ProviderPreset(
        id="163",
        name="网易 163 邮箱",
        domains=("163.com", "yeah.net"),
        imap_host="imap.163.com",
        imap_port=993,
        imap_ssl=True,
        smtp_host="smtp.163.com",
        smtp_port=465,
        smtp_ssl=True,
        supports_oauth=False,
        requires_imap_id=True,
        badge_color="#E11D48",
        auth_guide_url="https://mail.163.com/",
        auth_guide_tip="请使用网易邮箱网页版 -> 设置 -> POP3/SMTP/IMAP 中开启 IMAP 并生成客户端授权码；MailHub 会自动附带 IMAP ID 避免安全拦截。",
    ),
    ProviderPreset(
        id="126",
        name="网易 126 邮箱",
        domains=("126.com",),
        imap_host="imap.126.com",
        imap_port=993,
        imap_ssl=True,
        smtp_host="smtp.126.com",
        smtp_port=465,
        smtp_ssl=True,
        supports_oauth=False,
        requires_imap_id=True,
        badge_color="#DC2626",
        auth_guide_url="https://mail.126.com/",
        auth_guide_tip="请使用 126 邮箱网页版开启 IMAP 并生成授权密码；MailHub 已兼容 RFC 2971 IMAP ID 协议。",
    ),
    ProviderPreset(
        id="gmail",
        name="Gmail",
        domains=("gmail.com", "googlemail.com"),
        imap_host="imap.gmail.com",
        imap_port=993,
        imap_ssl=True,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_ssl=False,
        supports_oauth=True,
        requires_imap_id=False,
        badge_color="#EA4335",
        auth_guide_url="https://myaccount.google.com/apppasswords",
        auth_guide_tip="支持点击「浏览器 OAuth2 登录」（需在设置填入 Google Client ID），或使用 Google 账户两步验证生成的应用专用密码。",
    ),
    ProviderPreset(
        id="outlook",
        name="Outlook / Microsoft 365",
        domains=("outlook.com", "hotmail.com", "live.com", "msn.com"),
        imap_host="outlook.office365.com",
        imap_port=993,
        imap_ssl=True,
        smtp_host="smtp.office365.com",
        smtp_port=587,
        smtp_ssl=False,
        supports_oauth=True,
        requires_imap_id=False,
        badge_color="#0078D4",
        auth_guide_url="https://account.live.com/proofs/manage/additional",
        auth_guide_tip="微软已停用基础密码登录，建议使用「跳转浏览器 OAuth2 登录」（需在设置配置 Microsoft Client ID）。",
    ),
    ProviderPreset(
        id="icloud",
        name="iCloud 邮箱",
        domains=("icloud.com", "me.com", "mac.com"),
        imap_host="imap.mail.me.com",
        imap_port=993,
        imap_ssl=True,
        smtp_host="smtp.mail.me.com",
        smtp_port=587,
        smtp_ssl=False,
        supports_oauth=False,
        requires_imap_id=False,
        badge_color="#0EA5E9",
        auth_guide_url="https://appleid.apple.com/account/manage",
        auth_guide_tip="请在 Apple ID 账户管理页面的「App 专用密码」中生成密码并填入。",
    ),
    ProviderPreset(
        id="school",
        name="学校 / 教育邮箱",
        domains=("edu.cn", "edu"),
        imap_host="",
        imap_port=993,
        imap_ssl=True,
        smtp_host="",
        smtp_port=465,
        smtp_ssl=True,
        supports_oauth=False,
        requires_imap_id=False,
        badge_color="#6366F1",
        auth_guide_url="",
        auth_guide_tip="校园邮箱通常需填写学校邮件中心提供的 IMAP/SMTP 服务器地址及独立客户端密码。",
    ),
    ProviderPreset(
        id="custom",
        name="企业 / 自定义邮箱",
        domains=(),
        imap_host="",
        imap_port=993,
        imap_ssl=True,
        smtp_host="",
        smtp_port=465,
        smtp_ssl=True,
        supports_oauth=False,
        requires_imap_id=False,
        badge_color="#8B6CE8",
        auth_guide_url="",
        auth_guide_tip="输入企业或自建邮局提供的 IMAP 与 SMTP 服务器主机及端口即可接入。",
    ),
)

_PRESET_MAP: dict[str, ProviderPreset] = {preset.id: preset for preset in PROVIDER_PRESETS}


def list_provider_presets() -> list[dict[str, object]]:
    """返回前端展示所需的全部邮箱预设字典列表。"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "domains": list(p.domains),
            "imap_host": p.imap_host,
            "imap_port": p.imap_port,
            "imap_ssl": p.imap_ssl,
            "smtp_host": p.smtp_host,
            "smtp_port": p.smtp_port,
            "smtp_ssl": p.smtp_ssl,
            "supports_oauth": p.supports_oauth,
            "requires_imap_id": p.requires_imap_id,
            "badge_color": p.badge_color,
            "auth_guide_url": p.auth_guide_url,
            "auth_guide_tip": p.auth_guide_tip,
        }
        for p in PROVIDER_PRESETS
    ]


def get_preset_by_id(provider_id: str) -> ProviderPreset:
    """根据渠道 ID 获取预设，未知类型回退至 custom。"""
    return _PRESET_MAP.get(provider_id, _PRESET_MAP["custom"])


def detect_provider_from_email(email_address: str) -> ProviderPreset:
    """根据邮箱地址后缀自动识别最匹配的邮箱服务商。"""
    if "@" not in email_address:
        return _PRESET_MAP["custom"]
    domain = email_address.rsplit("@", 1)[1].strip().lower()
    for preset in PROVIDER_PRESETS:
        for known in preset.domains:
            if domain == known or domain.endswith(f".{known}"):
                return preset
    # 对常见企业后缀如 exmail.qq.com 或自建域名做兜底推断
    return _PRESET_MAP["custom"]


def resolve_preset_hosts(preset: ProviderPreset, email_address: str) -> tuple[str, str]:
    """根据预设与具体邮箱域名解析推荐的 IMAP/SMTP 主机（兼容 yeah.net 等独立域）。"""
    if "@" in email_address:
        domain = email_address.rsplit("@", 1)[1].strip().lower()
        if domain == "yeah.net":
            return "imap.yeah.net", "smtp.yeah.net"
    return preset.imap_host, preset.smtp_host
