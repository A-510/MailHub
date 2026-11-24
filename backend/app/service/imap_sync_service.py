import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import email as py_email
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
import html
import logging
from pathlib import Path
import re
import smtplib
import socket
import ssl
from typing import Any, Callable
from urllib.parse import unquote
from weakref import WeakKeyDictionary

from imapclient import IMAPClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.model.entities import Account, Attachment, Email
from app.repository.account_repo import account_repo
from app.repository.email_repo import email_repo
from app.repository.setting_repo import setting_repo
from app.service.classification_service import classification_service
from app.service.crypto_service import crypto_service
from app.service.event_bus import mail_event_bus
from app.service.oauth_service import oauth_service
from app.service.provider_preset_service import (
    detect_provider_from_email,
    get_preset_by_id,
    resolve_preset_hosts,
)

logger = logging.getLogger(__name__)

REMOTE_IMG_PATTERN = re.compile(r'<img\b[^>]*\bsrc\s*=\s*["\']?(?:https?:)?//', re.IGNORECASE)
IMG_CID_SRC_PATTERN = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*)(["\']?)cid:([^"\'\s>]+)\2',
    re.IGNORECASE,
)
MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024
TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")
GMAIL_APP_PASS_PATTERN = re.compile(r"^[a-zA-Z]{4}(?:\s+[a-zA-Z]{4}){3}$")
BYTES_REPR_PATTERN = re.compile(r"^b(['\"])(.*)\1$", re.DOTALL)

SYNC_FOLDER_ORDER: tuple[str, ...] = ("inbox", "sent", "drafts", "archive", "spam", "trash")
FOLDER_LABELS_ZH: dict[str, str] = {
    "inbox": "收件箱",
    "sent": "发件箱",
    "drafts": "草稿箱",
    "archive": "归档",
    "spam": "垃圾邮件",
    "trash": "回收站",
}

_FOLDER_NAME_ALIASES: dict[str, set[str]] = {
    "inbox": {"inbox", "收件箱"},
    "sent": {
        "sent",
        "sent items",
        "sent messages",
        "sent mail",
        "sentbox",
        "已发送",
        "已发送邮件",
        "已发邮件",
        "发件箱",
    },
    "drafts": {"draft", "drafts", "草稿", "草稿箱"},
    "archive": {"archive", "archives", "archived", "归档", "已归档", "存档", "归档邮件"},
    "spam": {
        "spam",
        "junk",
        "junk email",
        "junk e-mail",
        "junk mail",
        "bulk",
        "bulk mail",
        "垃圾邮件",
        "垃圾箱",
    },
    "trash": {
        "trash",
        "deleted",
        "deleted items",
        "deleted messages",
        "bin",
        "回收站",
        "已删除",
        "已删除邮件",
        "废纸篓",
    },
}
_STARRED_FOLDER_ALIASES: set[str] = {"starred", "flagged", "已加星标", "星标邮件"}


@dataclass
class ImapSyncFetchResult:
    """单账号多文件夹 IMAP 拉取结果容器。"""

    new_messages: list[tuple[str, int, bytes, bool, bool]] = field(default_factory=list)
    flag_updates: dict[str, dict[str, tuple[bool, bool]]] = field(default_factory=dict)
    starred_message_ids: set[str] = field(default_factory=set)
    synced_folders: list[str] = field(default_factory=list)
    skipped_all_mail_uids: set[str] = field(default_factory=set)


def _decode_imap_text(value: Any) -> str:
    """将 IMAP 返回的 bytes 或字符串安全解码为 str。"""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value) if value is not None else ""


def resolve_imap_folders(
    listed_folders: list[tuple[Any, Any, Any]],
) -> tuple[dict[str, str], str | None, str | None]:
    """
    根据 IMAP LIST 响应（RFC 6154 Special-Use Flags 优先，名称/末级目录名匹配兜底）
    解析出标准本地文件夹到远程文件夹名的映射，以及星标目录与全部邮件目录。
    """
    candidates: list[tuple[set[str], str, str, str]] = []
    for item in listed_folders:
        if len(item) < 3:
            continue
        raw_flags, raw_delimiter, raw_name = item[0], item[1], item[2]
        norm_flags = {_decode_imap_text(flag).strip().lower() for flag in (raw_flags or ())}
        if "\\noselect" in norm_flags or "\\nonexistent" in norm_flags:
            continue

        folder_name = _decode_imap_text(raw_name).strip()
        if not folder_name:
            continue
        delimiter = _decode_imap_text(raw_delimiter).strip() or "/"
        full_norm = folder_name.lower()

        # 按目录分隔符、'/' 与 '.' 拆分并取末级名称，兼容如 INBOX.Sent、其他文件夹/垃圾邮件 等格式
        parts = [folder_name]
        for sep in ({delimiter, "/", "."} - {""}):
            next_parts: list[str] = []
            for part in parts:
                next_parts.extend(part.split(sep))
            parts = next_parts
        non_empty_parts = [p.strip().lower() for p in parts if p.strip()]
        leaf_norm = non_empty_parts[-1] if non_empty_parts else full_norm

        candidates.append((norm_flags, folder_name, full_norm, leaf_norm))

    folder_map: dict[str, str] = {}
    starred_remote_folder: str | None = None
    all_mail_remote_folder: str | None = None

    # 第一轮：RFC 6154 Special-Use Flags 优先识别
    for norm_flags, folder_name, full_norm, _leaf_norm in candidates:
        if "\\inbox" in norm_flags or full_norm == "inbox":
            folder_map.setdefault("inbox", folder_name)
        if "\\sent" in norm_flags:
            folder_map.setdefault("sent", folder_name)
        if "\\drafts" in norm_flags:
            folder_map.setdefault("drafts", folder_name)
        if "\\archive" in norm_flags:
            folder_map.setdefault("archive", folder_name)
        if "\\junk" in norm_flags or "\\spam" in norm_flags:
            folder_map.setdefault("spam", folder_name)
        if "\\trash" in norm_flags:
            folder_map.setdefault("trash", folder_name)
        if "\\flagged" in norm_flags and starred_remote_folder is None:
            starred_remote_folder = folder_name
        if "\\all" in norm_flags and all_mail_remote_folder is None:
            all_mail_remote_folder = folder_name

    # 第二轮：目录全名或末级目录名精准匹配，仅补齐第一轮未命中的文件夹
    for _norm_flags, folder_name, full_norm, leaf_norm in candidates:
        for local_folder in SYNC_FOLDER_ORDER:
            if local_folder in folder_map:
                continue
            aliases = _FOLDER_NAME_ALIASES[local_folder]
            if full_norm in aliases or leaf_norm in aliases:
                folder_map[local_folder] = folder_name

        if starred_remote_folder is None and (
            full_norm in _STARRED_FOLDER_ALIASES or leaf_norm in _STARRED_FOLDER_ALIASES
        ):
            starred_remote_folder = folder_name

    folder_map.setdefault("inbox", "INBOX")
    return folder_map, starred_remote_folder, all_mail_remote_folder


def normalize_secret(provider: str, secret: str, host: str = "") -> str:
    """
    规范化用户输入的邮箱密码或授权码：
    对于 Gmail 16 位应用专用密码（如 'abcd efgh ijkl mnop'），自动去除中间空格。
    """
    cleaned = secret.strip()
    is_gmail = provider == "gmail" or "gmail.com" in host.lower()
    if is_gmail and GMAIL_APP_PASS_PATTERN.match(cleaned):
        return re.sub(r"\s+", "", cleaned)
    return cleaned


def get_safe_local_hostname() -> str:
    """
    获取可用于 SMTP EHLO 命令的纯 ASCII 本地主机名。
    Windows 计算机名若含中文等非 ASCII 字符，aiosmtplib 默认构造 EHLO 会抛出 UnicodeEncodeError，
    此时自动回退为 'localhost'。
    """
    try:
        fqdn = socket.getfqdn().strip()
        if fqdn and not any(ch.isspace() for ch in fqdn):
            fqdn.encode("ascii")
            return fqdn
    except (UnicodeEncodeError, OSError):
        pass
    return "localhost"


def build_smtp_transport_candidates(
    smtp_port: int,
    smtp_ssl: bool,
    smtp_host: str = "",
    provider: str = "",
) -> list[tuple[int, bool]]:
    """
    构造 SMTP 传输参数候选列表：优先尝试用户配置，对于标准 465/587 端口补充常用回退方案
    （例如 465 SSL 被本地代理或网络中断时自动回退 587 STARTTLS；网易 163/126/yeah.net 补充 994 SSL）。
    """
    candidates: list[tuple[int, bool]] = [(smtp_port, smtp_ssl)]
    lower_host = smtp_host.lower()
    is_netease = provider in ("163", "126") or any(
        dom in lower_host for dom in ("163.com", "126.com", "yeah.net")
    )

    if is_netease:
        netease_map: dict[tuple[int, bool], list[tuple[int, bool]]] = {
            (465, True): [(994, True), (587, False)],
            (994, True): [(465, True)],
            (587, False): [(994, True), (465, True)],
        }
        for extra in netease_map.get((smtp_port, smtp_ssl), []):
            if extra not in candidates:
                candidates.append(extra)
        return candidates

    fallback_map: dict[tuple[int, bool], list[tuple[int, bool]]] = {
        (465, True): [(587, False)],
        (587, False): [(465, True)],
        (587, True): [(587, False), (465, True)],
        (465, False): [(465, True), (587, False)],
    }
    for extra in fallback_map.get((smtp_port, smtp_ssl), []):
        if extra not in candidates:
            candidates.append(extra)
    return candidates


def is_imap_auth_error(exc: Exception) -> bool:
    """判断异常是否为明确的 IMAP 认证/凭据拒绝（遇到此类错误时应拉长重试间隔）。"""
    lower = str(exc).lower()
    return (
        "application-specific password required" in lower
        or "185833" in lower
        or "basic authentication is disabled" in lower
        or "logindisabled" in lower
        or "web login required" in lower
        or "webloginrequired" in lower
        or "unsafe login" in lower
        or "authenticationfailed" in lower
        or "invalid credentials" in lower
        or "username and password not accepted" in lower
        or "login error or password error" in lower
        or ("auth" in lower and "fail" in lower)
    )


def _is_smtp_auth_error(exc: Exception) -> bool:
    """判断异常是否为明确的 SMTP 身份凭据拒绝（密码或应用码错误时不应再切换端口重试）。"""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return True
    lower = str(exc).lower()
    return (
        "username and password not accepted" in lower
        or "application-specific password required" in lower
        or "authentication failed" in lower
        or "invalid credentials" in lower
    )


def _smtp_login_preserve_auth_error(
    server: smtplib.SMTP,
    email_addr: str,
    secret: str,
) -> None:
    """
    执行 SMTP 登录认证并在遇到明确的 534/535 凭据拒绝时立即抛出异常。
    标准库 smtplib.SMTP.login() 在首个 AUTH 方式返回 535 后会继续尝试下一个机制，
    部分服务器（如 Gmail 587）会在第二次 AUTH 时直接断开连接，导致真实 535 错误被
    SMTPServerDisconnected('Connection unexpectedly closed') 覆盖。
    """
    server.ehlo_or_helo_if_needed()
    if not server.has_extn("auth"):
        server.login(email_addr, secret)
        return

    advertised_authlist = server.esmtp_features.get("auth", "").split()
    preferred_auths = ("CRAM-MD5", "PLAIN", "LOGIN")
    authlist = [auth for auth in preferred_auths if auth in advertised_authlist]
    if not authlist:
        server.login(email_addr, secret)
        return

    server.user, server.password = email_addr, secret
    last_auth_exc: smtplib.SMTPAuthenticationError | None = None
    for authmethod in authlist:
        method_name = "auth_" + authmethod.lower().replace("-", "_")
        auth_fn = getattr(server, method_name, None)
        if auth_fn is None:
            continue
        try:
            code, _resp = server.auth(authmethod, auth_fn, initial_response_ok=True)
            if code in (235, 503):
                return
        except smtplib.SMTPAuthenticationError as exc:
            last_auth_exc = exc
            if exc.smtp_code in (534, 535):
                raise
        except smtplib.SMTPServerDisconnected as exc:
            if last_auth_exc is not None:
                raise last_auth_exc from exc
            raise

    if last_auth_exc is not None:
        raise last_auth_exc


def _smtp_connect_and_auth_sync(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_ssl: bool,
    email_addr: str,
    secret: str,
) -> None:
    """使用指定端口和加密模式执行一次同步 SMTP 建连与登录校验。"""
    ctx = ssl.create_default_context()
    local_hostname = get_safe_local_hostname()
    if smtp_ssl:
        with smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            local_hostname=local_hostname,
            timeout=15,
            context=ctx,
        ) as server:
            _smtp_login_preserve_auth_error(server, email_addr, secret)
    else:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            local_hostname=local_hostname,
            timeout=15,
        ) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            _smtp_login_preserve_auth_error(server, email_addr, secret)


def format_mail_auth_error(exc: Exception, provider: str = "") -> str:
    """
    将邮箱服务器返回的英文/bytes 异常翻译为清晰可执行的中文诊断提示。
    """
    raw = str(exc).strip()
    match = BYTES_REPR_PATTERN.match(raw)
    if match:
        raw = match.group(2)
    lower = raw.lower()

    if "application-specific password required" in lower or "185833" in lower:
        return (
            "Gmail 拒绝了普通账户密码登录：请先开启 Google 账号两步验证，前往 "
            "https://myaccount.google.com/apppasswords 生成 16 位「应用专用密码」后填入"
            "（或改用上方「跳转浏览器登录」）。"
        )
    if "basic authentication is disabled" in lower or "logindisabled" in lower:
        return "微软 Outlook 已停用基础密码登录：请切换上方「跳转浏览器登录」使用 Microsoft OAuth2 安全授权。"
    if "web login required" in lower or "webloginrequired" in lower:
        return "邮箱服务器要求先在网页端完成安全验证并开启 IMAP 访问权限。"
    if "unsafe login" in lower:
        return "网易邮箱安全拦截：请登录网页版邮箱开启 IMAP 服务，并使用生成的客户端授权码。"
    if (
        isinstance(exc, smtplib.SMTPAuthenticationError)
        or "username and password not accepted" in lower
        or "invalid credentials" in lower
        or "authenticationfailed" in lower
        or "login error or password error" in lower
        or ("auth" in lower and "fail" in lower)
    ):
        if provider == "gmail":
            return "Gmail 身份校验失败：请核对邮箱地址与 16 位「应用专用密码」是否正确（注意非 Google 登录密码）。"
        if provider in ("qq", "163", "126"):
            return "邮箱认证失败：请确认填写的是网页版生成的「客户端授权码」，而非邮箱网页登录密码。"
        return "邮箱账号或密码/授权码错误，请核对后重试。"
    if (
        "unexpected_eof_while_reading" in lower
        or "eof occurred in violation of protocol" in lower
        or "sslzeroreturnerror" in lower
        or "wrong_version_number" in lower
    ):
        return "TLS/SSL 握手被中断：当前网络或代理可能拦截了该端口（例如 SMTP 465），请尝试切换 587（STARTTLS）端口或检查代理规则。"
    if "timed out" in lower or "timeout" in lower:
        return "连接邮件服务器超时：请检查网络代理或服务器地址、端口及 SSL 设置。"
    return raw or "连接邮件服务器失败，请检查服务器配置与凭据。"


def _decode_mime_text(raw_value: str | None) -> str:
    """安全解码 RFC 2047 编码的邮件头文本（含 GBK/GB2312/UTF-8 兼容）。"""
    if not raw_value:
        return ""
    try:
        return str(make_header(decode_header(raw_value))).strip()
    except Exception:
        return raw_value.strip()


def _parse_address_list(header_values: list[str] | None) -> list[str]:
    """将邮件头收件人/抄送人列表规范化为字符串数组。"""
    if not header_values:
        return []
    parsed: list[str] = []
    for name, addr in getaddresses(header_values):
        decoded_name = _decode_mime_text(name)
        clean_addr = addr.strip()
        if decoded_name and clean_addr:
            parsed.append(f"{decoded_name} <{clean_addr}>")
        elif clean_addr:
            parsed.append(clean_addr)
    return parsed


def _build_snippet(text_body: str, html_body: str) -> str:
    """提取适合左页列表展示的纯文本摘要（最多 160 字）。"""
    source = text_body.strip()
    if not source and html_body:
        stripped = TAG_STRIP_PATTERN.sub(" ", html_body)
        source = html.unescape(stripped)
    collapsed = " ".join(source.split())
    return collapsed[:160]


def _decode_part_payload(part: Message) -> str:
    """按 MIME 字符集与容错回退（utf-8 -> gb18030 -> latin-1）解码正文分片。"""
    payload = part.get_payload(decode=True)
    if not isinstance(payload, (bytes, bytearray)):
        raw = part.get_payload()
        return str(raw) if isinstance(raw, str) else ""

    charset = part.get_content_charset() or "utf-8"
    for enc in (charset, "utf-8", "gb18030", "latin-1"):
        try:
            return bytes(payload).decode(enc, errors="replace")
        except LookupError:
            continue
    return bytes(payload).decode("utf-8", errors="replace")


def _resolve_inline_cid_images(html_body: str, cid_data_uris: dict[str, str]) -> str:
    """将邮件 HTML 正文中的 cid: 内嵌图片引用替换为解析出的 data URI。"""
    if not html_body or not cid_data_uris:
        return html_body

    def _replace_match(match: re.Match[str]) -> str:
        prefix = match.group(1)
        raw_cid = match.group(3)
        cid_key = unquote(raw_cid).strip().strip("<>").strip().lower()
        data_uri = cid_data_uris.get(cid_key)
        if not data_uri:
            return match.group(0)
        return f'{prefix}"{data_uri}"'

    return IMG_CID_SRC_PATTERN.sub(_replace_match, html_body)


def _extract_email_parts(
    msg: Message,
    account_id: int,
    uid_str: str,
    folder: str = "inbox",
) -> tuple[str, str, list[dict[str, Any]]]:
    """提取邮件纯文本正文、HTML 正文、内嵌 cid 图片及附件落盘元数据（非收件箱附件带目录前缀防冲突）。"""
    text_parts: list[str] = []
    html_parts: list[str] = []
    cid_data_uris: dict[str, str] = {}
    attachments_meta: list[dict[str, Any]] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = (part.get_content_type() or "").lower()
            disposition = (part.get("Content-Disposition") or "").lower()
            raw_filename = part.get_filename()
            filename = _decode_mime_text(raw_filename) if raw_filename else ""

            if part.get_content_maintype() == "multipart":
                continue

            # 优先提取带 Content-ID 的内嵌位图（如 QQ 邮箱正文中直接粘贴的图片）
            raw_cid = (part.get("Content-ID") or "").strip()
            cid_key = raw_cid.strip("<>").strip().lower()
            if (
                cid_key
                and content_type.startswith("image/")
                and content_type != "image/svg+xml"
                and "attachment" not in disposition
            ):
                data = part.get_payload(decode=True) or b""
                if 0 < len(data) <= MAX_INLINE_IMAGE_BYTES:
                    mime_type = "image/jpeg" if content_type == "image/jpg" else content_type
                    encoded = base64.b64encode(data).decode("ascii")
                    cid_data_uris[cid_key] = f"data:{mime_type};base64,{encoded}"
                    continue

            if "attachment" in disposition or filename:
                data = part.get_payload(decode=True) or b""
                safe_name = re.sub(r'[\\/:*?"<>|]+', "_", filename or f"attachment_{len(attachments_meta) + 1}")
                target_dir = settings.attachments_dir / str(account_id)
                target_dir.mkdir(parents=True, exist_ok=True)
                # IMAP UID 仅在单文件夹内唯一，非收件箱目录增加 folder 前缀避免同名附件覆盖
                uid_prefix = uid_str if folder == "inbox" else f"{folder}_{uid_str}"
                target_path = target_dir / f"{uid_prefix}_{safe_name}"
                target_path.write_bytes(data)
                attachments_meta.append(
                    {
                        "filename": safe_name,
                        "content_type": content_type or "application/octet-stream",
                        "size_bytes": len(data),
                        "local_path": str(target_path),
                    }
                )
            elif content_type == "text/plain":
                text_parts.append(_decode_part_payload(part))
            elif content_type == "text/html":
                html_parts.append(_decode_part_payload(part))
    else:
        content_type = (msg.get_content_type() or "text/plain").lower()
        body_text = _decode_part_payload(msg)
        if content_type == "text/html":
            html_parts.append(body_text)
        else:
            text_parts.append(body_text)

    text_body = "\n".join(text_parts).strip()
    html_body = _resolve_inline_cid_images("\n".join(html_parts).strip(), cid_data_uris)
    if not html_body and text_body:
        escaped = html.escape(text_body).replace("\n", "<br/>")
        html_body = f'<div class="plain-mail-body">{escaped}</div>'
    return text_body, html_body, attachments_meta


def _should_send_imap_id(provider: str, host: str) -> bool:
    """判断是否需要在认证后发送 RFC 2971 IMAP ID 指令（163 / 126 强制要求）。"""
    lower_host = host.lower()
    return provider in ("163", "126") or "163.com" in lower_host or "126.com" in lower_host or "yeah.net" in lower_host


def _imap_connect_and_auth(
    *,
    host: str,
    port: int,
    use_ssl: bool,
    email_addr: str,
    secret: str,
    auth_type: str,
    provider: str,
) -> IMAPClient:
    """建立并认证 IMAPClient 连接（同步方法，供线程池调用）。"""
    client = IMAPClient(host, port=port, ssl=use_ssl, timeout=20)
    if auth_type == "oauth2":
        client.oauth2_login(email_addr, secret)
    else:
        client.login(email_addr, secret)

    # 关键兼容逻辑：网易 163/126 要求客户端声明 IMAP ID，否则 SELECT INBOX 会被拒绝 Unsafe Login
    if _should_send_imap_id(provider, host):
        try:
            client.id_({"name": "MailHub", "version": "1.0.0", "vendor": "MailHub"})
        except Exception as exc:
            logger.warning("IMAP ID command warning for %s: %s", host, exc)
    return client


def _test_imap_and_smtp_sync(
    *,
    email_addr: str,
    provider: str,
    secret: str,
    imap_host: str,
    imap_port: int,
    imap_ssl: bool,
    smtp_host: str,
    smtp_port: int,
    smtp_ssl: bool,
) -> tuple[bool, bool, str, int, bool]:
    """同步验证 IMAP 收信与 SMTP 发信连通性（支持 465/587 自动回退），返回清晰中文诊断信息。"""
    normalized_secret = normalize_secret(provider, secret, imap_host)
    imap_ok = False
    smtp_ok = False
    resolved_smtp_port = smtp_port
    resolved_smtp_ssl = smtp_ssl
    used_smtp_fallback = False
    errors: list[str] = []

    try:
        imap_client = _imap_connect_and_auth(
            host=imap_host,
            port=imap_port,
            use_ssl=imap_ssl,
            email_addr=email_addr,
            secret=normalized_secret,
            auth_type="password",
            provider=provider,
        )
        imap_client.select_folder("INBOX", readonly=True)
        imap_client.logout()
        imap_ok = True
    except Exception as exc:
        errors.append(f"IMAP 收信失败：{format_mail_auth_error(exc, provider)}")

    smtp_candidates = build_smtp_transport_candidates(
        smtp_port,
        smtp_ssl,
        smtp_host=smtp_host,
        provider=provider,
    )
    last_smtp_exc: Exception | None = None
    for idx, (cand_port, cand_ssl) in enumerate(smtp_candidates):
        try:
            _smtp_connect_and_auth_sync(
                smtp_host=smtp_host,
                smtp_port=cand_port,
                smtp_ssl=cand_ssl,
                email_addr=email_addr,
                secret=normalized_secret,
            )
            smtp_ok = True
            resolved_smtp_port = cand_port
            resolved_smtp_ssl = cand_ssl
            used_smtp_fallback = idx > 0
            break
        except Exception as exc:
            last_smtp_exc = exc
            if _is_smtp_auth_error(exc):
                break
            if idx + 1 < len(smtp_candidates):
                logger.warning(
                    "SMTP %s:%s (ssl=%s) failed (%s), trying fallback transport",
                    smtp_host,
                    cand_port,
                    cand_ssl,
                    exc,
                )

    if not smtp_ok and last_smtp_exc is not None:
        errors.append(f"SMTP 发信失败：{format_mail_auth_error(last_smtp_exc, provider)}")

    if imap_ok and smtp_ok:
        if used_smtp_fallback:
            mode_label = "SSL" if resolved_smtp_ssl else "STARTTLS"
            return (
                True,
                True,
                f"IMAP 收信与 SMTP 发信连接测试均已通过（SMTP 已自动切换至 {resolved_smtp_port} {mode_label}）！",
                resolved_smtp_port,
                resolved_smtp_ssl,
            )
        return True, True, "IMAP 收信与 SMTP 发信连接测试均已通过！", resolved_smtp_port, resolved_smtp_ssl

    # 避免重复显示完全相同的认证错误（IMAP 与 SMTP 同时命中同一个应用专用密码提示时合并展示）
    unique_errors = list(dict.fromkeys(errors))
    return imap_ok, smtp_ok, "；".join(unique_errors), resolved_smtp_port, resolved_smtp_ssl


def _parse_imap_flags(raw_flags: Any) -> tuple[bool, bool]:
    """解析 IMAP FLAGS 元组为 (is_read, is_starred)，兼容 bytes 与 str。"""
    norm_flags = {_decode_imap_text(flag).strip().lower() for flag in (raw_flags or ())}
    return "\\seen" in norm_flags, "\\flagged" in norm_flags


def _extract_envelope_message_id(payload: dict[Any, Any]) -> str:
    """从 IMAP FETCH 返回的 ENVELOPE 结构中安全提取 Message-ID 字符串。"""
    env = payload.get(b"ENVELOPE") if b"ENVELOPE" in payload else payload.get("ENVELOPE")
    if env is None:
        return ""
    raw_mid = env.get("message_id") if isinstance(env, dict) else getattr(env, "message_id", None)
    return _decode_imap_text(raw_mid).strip()


def _extract_raw_message_bytes(payload: dict[Any, Any]) -> bytes | None:
    """从 IMAP FETCH 响应字典中兼容提取原始邮件字节流（兼容 BODY[] 与 RFC822）。"""
    for key in (b"BODY[]", "BODY[]", b"RFC822", "RFC822"):
        raw = payload.get(key)
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
    return None


def _pull_single_remote_folder(
    client: IMAPClient,
    *,
    remote_folder: str,
    sync_days: int,
    limit: int,
    known_uids: set[str],
    fallback_all_when_empty: bool,
    skip_message_ids: set[str] | None = None,
    already_selected: bool = False,
    sync_flags: bool = True,
    collect_skipped_uids: set[str] | None = None,
    peek: bool = False,
) -> tuple[list[tuple[int, bytes, bool, bool]], dict[str, tuple[bool, bool]]]:
    """
    从已登录 IMAPClient 的单个远程文件夹增量拉取邮件：
    1. 针对最近 limit 封仅先拉取 FLAGS 用于同步状态（可选跳过）；
    2. 对 \\All 回退等场景支持通过 ENVELOPE 预过滤已知 Message-ID；
    3. 仅对真正缺失的 UID 拉取完整原文，减少流量与解析开销。
    """
    if not already_selected:
        client.select_folder(remote_folder, readonly=True)
    uids: list[int] = []
    if sync_days > 0:
        since_date = (datetime.now(timezone.utc) - timedelta(days=sync_days)).date()
        try:
            uids = [int(u) for u in client.search(["SINCE", since_date])]
        except Exception as exc:
            logger.warning("IMAP SINCE search failed on %s (%s), falling back to ALL", remote_folder, exc)
            uids = [int(u) for u in client.search(["ALL"])]
        if fallback_all_when_empty and not uids:
            uids = [int(u) for u in client.search(["ALL"])]
    else:
        uids = [int(u) for u in client.search(["ALL"])]

    if not uids:
        return [], {}

    target_uids = sorted(uids)[-limit:]
    folder_flag_updates: dict[str, tuple[bool, bool]] = {}
    if sync_flags:
        flags_payload_map = client.fetch(target_uids, ["FLAGS"])
        for uid in target_uids:
            payload = flags_payload_map.get(uid) or {}
            raw_flags = payload.get(b"FLAGS") if b"FLAGS" in payload else payload.get("FLAGS")
            folder_flag_updates[str(uid)] = _parse_imap_flags(raw_flags)

    new_uids = [uid for uid in target_uids if str(uid) not in known_uids]
    if new_uids and skip_message_ids:
        try:
            env_map = client.fetch(new_uids, ["ENVELOPE"])
            filtered_uids: list[int] = []
            for uid in new_uids:
                env_payload = env_map.get(uid) or {}
                mid = _extract_envelope_message_id(env_payload).lower()
                if mid and mid in skip_message_ids:
                    if collect_skipped_uids is not None:
                        collect_skipped_uids.add(str(uid))
                    continue
                filtered_uids.append(uid)
            new_uids = filtered_uids
        except Exception as exc:
            logger.warning("IMAP ENVELOPE prefilter failed on %s (%s), falling back to full fetch", remote_folder, exc)

    if not new_uids:
        return [], folder_flag_updates

    body_item = "BODY.PEEK[]" if peek else "RFC822"
    fetched = client.fetch(new_uids, [body_item, "FLAGS"])
    new_messages: list[tuple[int, bytes, bool, bool]] = []
    for uid in reversed(new_uids):
        payload = fetched.get(uid) or {}
        raw_bytes = _extract_raw_message_bytes(payload)
        if raw_bytes is None:
            continue
        raw_flags = payload.get(b"FLAGS") if b"FLAGS" in payload else payload.get("FLAGS")
        if raw_flags is not None:
            is_read, is_starred = _parse_imap_flags(raw_flags)
        else:
            is_read, is_starred = folder_flag_updates.get(str(uid), (False, False))
        new_messages.append((int(uid), raw_bytes, is_read, is_starred))
    return new_messages, folder_flag_updates


def _extract_uidnext(select_info: Any) -> int | None:
    """从 IMAP SELECT 响应字典中解析 UIDNEXT 正整数值。"""
    if not isinstance(select_info, dict):
        return None
    raw = select_info.get(b"UIDNEXT") if b"UIDNEXT" in select_info else select_info.get("UIDNEXT")
    if raw is None:
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def _pull_inbox_incremental_on_client(
    client: IMAPClient,
    *,
    known_uids: set[str],
    sync_days: int,
    limit: int = 35,
    select_first: bool = False,
    readonly: bool = False,
    send_noop: bool = False,
    select_info: Any = None,
) -> ImapSyncFetchResult:
    """
    在已认证连接上极速增量检查 INBOX 新邮件：
    1. 支持 SELECT(readonly=False) 与 BODY.PEEK[] 抓包，既确保服务端正常推送 IDLE 事件，又不误修改未读标志；
    2. 利用 SELECT UIDNEXT 短路与 `UID <max+1>:*` 范围检索，跳过 list_folders 与其余文件夹；
    3. 首次空库或 UID 搜索不受支持时安全回退至标准 SINCE 搜索。
    """
    result = ImapSyncFetchResult(synced_folders=["inbox"])
    effective_select_info = select_info
    if select_first:
        effective_select_info = client.select_folder("INBOX", readonly=readonly)
    elif send_noop:
        try:
            client.noop()
        except Exception as exc:
            logger.debug("IMAP NOOP before incremental check warning: %s", exc)

    numeric_known = [int(u) for u in known_uids if u.isdigit()]
    max_known_uid = max(numeric_known) if numeric_known else 0

    if max_known_uid > 0:
        uidnext = _extract_uidnext(effective_select_info)
        # 若服务端返回的 UIDNEXT 恰好为 max_known_uid + 1，说明自上次同步以来无任何新邮件入箱
        if uidnext is not None and uidnext == max_known_uid + 1:
            return result

        # 若 UIDNEXT <= max_known_uid（例如服务器重建邮箱导致 UIDVALIDITY 变更/回绕），降级走普通扫描
        if uidnext is None or uidnext > max_known_uid + 1:
            try:
                raw_uids = client.search(["UID", f"{max_known_uid + 1}:*"])
                # NOTE: RFC 3501 中 a:* 在最大 UID 小于 a 时会被解释为 max_uid:a，故必须再次过滤 u > max_known_uid
                new_uids = [
                    int(u)
                    for u in sorted(int(x) for x in raw_uids)
                    if int(u) > max_known_uid and str(int(u)) not in known_uids
                ][-limit:]
                if not new_uids:
                    return result

                fetched = client.fetch(new_uids, ["BODY.PEEK[]", "FLAGS"])
                for uid in reversed(new_uids):
                    payload = fetched.get(uid) or {}
                    raw_bytes = _extract_raw_message_bytes(payload)
                    if raw_bytes is None:
                        continue
                    raw_flags = payload.get(b"FLAGS") if b"FLAGS" in payload else payload.get("FLAGS")
                    is_read, is_starred = _parse_imap_flags(raw_flags)
                    result.new_messages.append(("inbox", int(uid), raw_bytes, is_read, is_starred))
                return result
            except Exception as exc:
                logger.warning("IMAP UID range search failed on INBOX (%s), falling back to SINCE", exc)

    new_msgs, _ = _pull_single_remote_folder(
        client,
        remote_folder="INBOX",
        sync_days=sync_days,
        limit=limit,
        known_uids=known_uids,
        fallback_all_when_empty=False,
        already_selected=True,
        sync_flags=False,
        peek=True,
    )
    for uid, raw_bytes, is_read, is_starred in new_msgs:
        result.new_messages.append(("inbox", uid, raw_bytes, is_read, is_starred))
    return result


def _fetch_imap_inbox_only(
    *,
    host: str,
    port: int,
    use_ssl: bool,
    email_addr: str,
    secret: str,
    auth_type: str,
    provider: str,
    sync_days: int,
    known_inbox_uids: set[str] | None = None,
    limit: int = 35,
) -> ImapSyncFetchResult:
    """
    轻量单收件箱连接入口：跳过 list_folders 与发件箱/草稿箱/归档/垃圾/回收站，仅增量拉取 INBOX 新邮件。
    """
    client = _imap_connect_and_auth(
        host=host,
        port=port,
        use_ssl=use_ssl,
        email_addr=email_addr,
        secret=secret,
        auth_type=auth_type,
        provider=provider,
    )
    try:
        return _pull_inbox_incremental_on_client(
            client,
            known_uids=known_inbox_uids or set(),
            sync_days=sync_days,
            limit=limit,
            select_first=True,
        )
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _fetch_imap_folder_messages(
    *,
    host: str,
    port: int,
    use_ssl: bool,
    email_addr: str,
    secret: str,
    auth_type: str,
    provider: str,
    sync_days: int,
    existing_uids_by_folder: dict[str, set[str]] | None = None,
    known_message_ids: set[str] | None = None,
    skip_all_mail_uids: set[str] | None = None,
    inbox_limit: int = 35,
    other_limit: int = 25,
    on_inbox_ready: Callable[[list[tuple[int, bytes, bool, bool]], dict[str, tuple[bool, bool]]], None] | None = None,
) -> ImapSyncFetchResult:
    """
    单次连接复用并自动发现同步各邮箱标准文件夹（收件箱、发件箱、草稿箱、归档、垃圾邮件、回收站），
    支持在收件箱拉取完毕后通过 on_inbox_ready 回调提前落库并推给前端，同时兼容 Gmail \\All 归档回退与虚拟星标目录。
    """
    client = _imap_connect_and_auth(
        host=host,
        port=port,
        use_ssl=use_ssl,
        email_addr=email_addr,
        secret=secret,
        auth_type=auth_type,
        provider=provider,
    )
    existing_map = existing_uids_by_folder or {}
    result = ImapSyncFetchResult()
    try:
        starred_remote_folder: str | None = None
        all_mail_remote_folder: str | None = None
        try:
            listed_folders = list(client.list_folders())
            folder_map, starred_remote_folder, all_mail_remote_folder = resolve_imap_folders(listed_folders)
        except Exception as exc:
            logger.warning("IMAP list_folders failed for %s (%s), falling back to INBOX only", email_addr, exc)
            folder_map = {"inbox": "INBOX"}

        for local_folder in SYNC_FOLDER_ORDER:
            remote_folder = folder_map.get(local_folder)
            if not remote_folder:
                continue
            limit = inbox_limit if local_folder == "inbox" else other_limit
            known_uids = existing_map.get(local_folder, set())
            if local_folder == "inbox":
                new_msgs, flag_updates = _pull_single_remote_folder(
                    client,
                    remote_folder=remote_folder,
                    sync_days=sync_days,
                    limit=limit,
                    known_uids=known_uids,
                    fallback_all_when_empty=False,
                )
                result.synced_folders.append(local_folder)
                if on_inbox_ready is not None:
                    # 提前将收件箱新邮件与状态变更落库推送，不等候后续慢速目录完成
                    if new_msgs or flag_updates:
                        on_inbox_ready(new_msgs, flag_updates)
                else:
                    if flag_updates:
                        result.flag_updates[local_folder] = flag_updates
                    for uid, raw_bytes, is_read, is_starred in new_msgs:
                        result.new_messages.append((local_folder, uid, raw_bytes, is_read, is_starred))
            else:
                # 非收件箱单个目录异常不阻断整个账号同步，保证其余目录正常可用
                try:
                    new_msgs, flag_updates = _pull_single_remote_folder(
                        client,
                        remote_folder=remote_folder,
                        sync_days=sync_days,
                        limit=limit,
                        known_uids=known_uids,
                        fallback_all_when_empty=True,
                    )
                    result.synced_folders.append(local_folder)
                    if flag_updates:
                        result.flag_updates[local_folder] = flag_updates
                    for uid, raw_bytes, is_read, is_starred in new_msgs:
                        result.new_messages.append((local_folder, uid, raw_bytes, is_read, is_starred))
                except Exception as exc:
                    logger.warning(
                        "Failed syncing IMAP folder %s (%s) for %s: %s",
                        local_folder,
                        remote_folder,
                        email_addr,
                        exc,
                    )

        # Gmail 等未单独提供 Archive 目录但提供 \All 全部邮件目录时，补全已归档邮件
        if "archive" not in folder_map and all_mail_remote_folder:
            try:
                all_known = set(existing_map.get("archive", set()))
                if skip_all_mail_uids:
                    all_known |= skip_all_mail_uids
                all_msgs, _ = _pull_single_remote_folder(
                    client,
                    remote_folder=all_mail_remote_folder,
                    sync_days=sync_days,
                    limit=other_limit,
                    known_uids=all_known,
                    fallback_all_when_empty=True,
                    skip_message_ids=known_message_ids,
                    sync_flags=False,
                    collect_skipped_uids=result.skipped_all_mail_uids,
                )
                for uid, raw_bytes, is_read, is_starred in all_msgs:
                    result.new_messages.append(("archive_fallback", uid, raw_bytes, is_read, is_starred))
            except Exception as exc:
                logger.warning(
                    "Failed syncing IMAP \\All fallback (%s) for %s: %s",
                    all_mail_remote_folder,
                    email_addr,
                    exc,
                )

        # 若服务器存在虚拟星标目录（如 [Gmail]/Starred），补充对应 Message-ID 星标状态（优先按 sync_days 缩小范围）
        if starred_remote_folder:
            try:
                client.select_folder(starred_remote_folder, readonly=True)
                starred_uids: list[int] = []
                if sync_days > 0:
                    since_date = (datetime.now(timezone.utc) - timedelta(days=sync_days)).date()
                    try:
                        starred_uids = [int(u) for u in client.search(["SINCE", since_date])]
                    except Exception:
                        starred_uids = [int(u) for u in client.search(["ALL"])]
                    if not starred_uids:
                        starred_uids = [int(u) for u in client.search(["ALL"])]
                else:
                    starred_uids = [int(u) for u in client.search(["ALL"])]

                if starred_uids:
                    target_starred_uids = sorted(starred_uids)[-other_limit:]
                    env_fetched = client.fetch(target_starred_uids, ["ENVELOPE"])
                    for uid in target_starred_uids:
                        payload = env_fetched.get(uid) or {}
                        mid = _extract_envelope_message_id(payload)
                        if mid:
                            result.starred_message_ids.add(mid)
            except Exception as exc:
                logger.warning(
                    "Failed reading starred IMAP folder (%s) for %s: %s",
                    starred_remote_folder,
                    email_addr,
                    exc,
                )

        return result
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _fetch_imap_raw_messages(
    *,
    host: str,
    port: int,
    use_ssl: bool,
    email_addr: str,
    secret: str,
    auth_type: str,
    provider: str,
    sync_days: int,
    limit: int = 35,
) -> list[tuple[int, bytes, bool, bool]]:
    """
    向后兼容的单 INBOX 拉取辅助函数：内部复用多文件夹连接逻辑仅返回 INBOX 原始邮件。
    """
    client = _imap_connect_and_auth(
        host=host,
        port=port,
        use_ssl=use_ssl,
        email_addr=email_addr,
        secret=secret,
        auth_type=auth_type,
        provider=provider,
    )
    try:
        new_msgs, _ = _pull_single_remote_folder(
            client,
            remote_folder="INBOX",
            sync_days=sync_days,
            limit=limit,
            known_uids=set(),
            fallback_all_when_empty=False,
        )
        return new_msgs
    finally:
        try:
            client.logout()
        except Exception:
            pass


class ImapSyncService:
    """IMAP 同步、增量入库与测试连接服务。"""

    def __init__(self) -> None:
        # 按事件循环隔离单账号异步互斥锁，避免手动同步、定时全量与 IDLE 推送同时写入产生重复邮件
        self._loop_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[int, asyncio.Lock]] = WeakKeyDictionary()
        # 缓存已在 \All 全部邮件中确认属于其他文件夹的 UID，避免每次 Gmail 全量同步重拉 ENVELOPE
        self._checked_all_mail_uids: dict[int, set[str]] = {}

    def _get_account_lock(self, account_id: int) -> asyncio.Lock:
        """获取当前运行事件循环下对应账号的互斥锁。"""
        loop = asyncio.get_running_loop()
        locks_by_acc = self._loop_locks.get(loop)
        if locks_by_acc is None:
            locks_by_acc = {}
            self._loop_locks[loop] = locks_by_acc
        lock = locks_by_acc.get(account_id)
        if lock is None:
            lock = asyncio.Lock()
            locks_by_acc[account_id] = lock
        return lock

    def _record_checked_all_mail_uids(self, account_id: int, uids: set[str]) -> None:
        """记录无需再拉取 ENVELOPE 的 \\All UID，并限制单账号内存缓存上限为 500。"""
        if not uids:
            return
        cache = self._checked_all_mail_uids.setdefault(account_id, set())
        cache.update(uids)
        if len(cache) > 500:
            numeric = sorted((int(u) for u in cache if u.isdigit()), reverse=True)[:500]
            self._checked_all_mail_uids[account_id] = {str(u) for u in numeric}

    def clear_account_cache(self, account_id: int) -> None:
        """账号删除或重置时清理内存缓存。"""
        self._checked_all_mail_uids.pop(account_id, None)

    def resolve_server_defaults(
        self,
        email_addr: str,
        provider: str,
        imap_host: str,
        smtp_host: str,
    ) -> tuple[str, str, str]:
        """当主机字段留空时，自动结合邮箱域名预设填充 IMAP/SMTP 地址。"""
        preset = get_preset_by_id(provider)
        if provider == "custom" and not imap_host:
            detected = detect_provider_from_email(email_addr)
            if detected.id != "custom":
                preset = detected
        default_imap, default_smtp = resolve_preset_hosts(preset, email_addr)
        resolved_imap = imap_host.strip() or default_imap
        resolved_smtp = smtp_host.strip() or default_smtp
        return preset.id, resolved_imap, resolved_smtp

    async def test_connection(
        self,
        *,
        email_addr: str,
        provider: str,
        secret: str,
        imap_host: str,
        imap_port: int,
        imap_ssl: bool,
        smtp_host: str,
        smtp_port: int,
        smtp_ssl: bool,
    ) -> tuple[bool, bool, bool, str, int, bool]:
        """异步调度连接测试（底层放线程池避免阻塞 FastAPI 主线程）。"""
        resolved_provider, r_imap, r_smtp = self.resolve_server_defaults(
            email_addr, provider, imap_host, smtp_host
        )
        if not r_imap or not r_smtp:
            return (
                False,
                False,
                False,
                "未能自动识别 IMAP/SMTP 服务器地址，请手动填写完整服务器信息。",
                smtp_port,
                smtp_ssl,
            )

        imap_ok, smtp_ok, msg, resolved_smtp_port, resolved_smtp_ssl = await asyncio.to_thread(
            _test_imap_and_smtp_sync,
            email_addr=email_addr,
            provider=resolved_provider,
            secret=secret,
            imap_host=r_imap,
            imap_port=imap_port,
            imap_ssl=imap_ssl,
            smtp_host=r_smtp,
            smtp_port=smtp_port,
            smtp_ssl=smtp_ssl,
        )
        return (imap_ok and smtp_ok), imap_ok, smtp_ok, msg, resolved_smtp_port, resolved_smtp_ssl

    def _persist_fetch_result(
        self,
        db: Session,
        account: Account,
        fetch_result: ImapSyncFetchResult,
        *,
        uid_maps: dict[str, dict[str, Email]] | None = None,
        existing_uids_by_folder: dict[str, set[str]] | None = None,
        sent_msg_id_map: dict[str, Email] | None = None,
        drafts_msg_id_map: dict[str, Email] | None = None,
        all_account_msg_ids: set[str] | None = None,
        mode: str = "full",
        source: str = "manual",
        record_log: bool = True,
        update_account_status: bool = True,
        prior_inserted_by_folder: dict[str, int] | None = None,
    ) -> tuple[bool, int, str]:
        """将拉取结果去重落库、更新状态标志、按策略记录日志并推送 SSE 事件。"""
        if uid_maps is None:
            uid_maps = {
                folder: email_repo.get_uid_map_by_folder(db, account.id, folder)
                for folder in SYNC_FOLDER_ORDER
            }
        if existing_uids_by_folder is None:
            existing_uids_by_folder = {
                folder: set(uid_map.keys()) for folder, uid_map in uid_maps.items()
            }
        if sent_msg_id_map is None:
            sent_msg_id_map = email_repo.get_message_id_map_by_folder(db, account.id, "sent")
        if drafts_msg_id_map is None:
            drafts_msg_id_map = email_repo.get_message_id_map_by_folder(db, account.id, "drafts")
        if all_account_msg_ids is None:
            all_account_msg_ids = email_repo.get_all_message_ids_for_account(db, account.id)

        # 1. 同步已存在邮件的远程已读与星标标志
        flags_updated = 0
        for folder, folder_flags in fetch_result.flag_updates.items():
            folder_uid_map = uid_maps.get(folder, {})
            for uid_str, (remote_read, remote_starred) in folder_flags.items():
                existing_email = folder_uid_map.get(uid_str)
                if existing_email is None:
                    continue
                target_read = True if folder in ("sent", "drafts") else remote_read
                changed = False
                if existing_email.is_read != target_read:
                    existing_email.is_read = target_read
                    changed = True
                if existing_email.is_starred != remote_starred:
                    existing_email.is_starred = remote_starred
                    changed = True
                if changed:
                    email_repo.save(db, existing_email)
                    flags_updated += 1

        # 2. 先入库 6 个标准文件夹新邮件，再处理 Gmail \All 归档回退
        ordered_messages = [
            item for item in fetch_result.new_messages if item[0] != "archive_fallback"
        ] + [
            item for item in fetch_result.new_messages if item[0] == "archive_fallback"
        ]

        inserted = 0
        inbox_inserted = 0
        inserted_by_folder: dict[str, int] = {}
        extra_skipped_all_uids: set[str] = set()
        latest_subject = ""
        latest_sender = ""
        latest_priority = -1
        latest_received_at: datetime | None = None

        for source_folder, uid, raw_bytes, is_read, is_starred in ordered_messages:
            uid_str = str(uid)
            is_archive_fallback = source_folder == "archive_fallback"
            target_folder = "archive" if is_archive_fallback else source_folder

            if uid_str in existing_uids_by_folder.get(target_folder, set()):
                continue

            msg = py_email.message_from_bytes(raw_bytes)
            message_id = (msg.get("Message-ID") or "").strip()
            norm_mid = message_id.lower()

            # \All 归档回退仅收割尚不存在于当前账号任意文件夹中的已归档邮件
            if is_archive_fallback:
                if not norm_mid or norm_mid in all_account_msg_ids:
                    extra_skipped_all_uids.add(uid_str)
                    continue

            # 发件箱/草稿箱按同文件夹 Message-ID 与本地发出/保存记录去重并升级为真实 IMAP UID
            if target_folder in ("sent", "drafts") and norm_mid:
                folder_mid_map = sent_msg_id_map if target_folder == "sent" else drafts_msg_id_map
                dup_email = folder_mid_map.get(norm_mid)
                if dup_email is not None:
                    changed = False
                    if dup_email.message_uid.startswith(("sent-", "draft-")):
                        dup_email.message_uid = uid_str
                        existing_uids_by_folder.setdefault(target_folder, set()).add(uid_str)
                        changed = True
                    if dup_email.is_starred != is_starred:
                        dup_email.is_starred = is_starred
                        changed = True
                    if changed:
                        email_repo.save(db, dup_email)
                        flags_updated += 1
                    continue

            from_list = [
                (name, addr.strip())
                for name, addr in getaddresses([msg.get("From", "")])
                if name.strip() or addr.strip()
            ]
            if from_list:
                sender_name = _decode_mime_text(from_list[0][0]) or from_list[0][1] or "未知发件人"
                sender_email = from_list[0][1] or (
                    account.email if target_folder in ("sent", "drafts") else "unknown@example.com"
                )
            elif target_folder in ("sent", "drafts"):
                sender_name = account.label
                sender_email = account.email
            else:
                sender_name = "未知发件人"
                sender_email = "unknown@example.com"

            subject = _decode_mime_text(msg.get("Subject")) or "(无主题)"
            to_addrs = _parse_address_list(msg.get_all("To", []))
            cc_addrs = _parse_address_list(msg.get_all("Cc", []))

            raw_date = msg.get("Date")
            received_at = datetime.now(timezone.utc)
            if raw_date:
                try:
                    parsed_dt = parsedate_to_datetime(raw_date)
                    if parsed_dt.tzinfo is None:
                        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                    received_at = parsed_dt.astimezone(timezone.utc)
                except Exception:
                    pass

            text_body, html_body, attachments_meta = _extract_email_parts(
                msg, account.id, uid_str, folder=target_folder
            )
            snippet = _build_snippet(text_body, html_body)
            category = classification_service.classify(db, sender_email, sender_name, subject)
            has_remote_images = bool(REMOTE_IMG_PATTERN.search(html_body))
            final_is_read = True if target_folder in ("sent", "drafts") else is_read

            headers_lines = [f"{k}: {_decode_mime_text(v)}" for k, v in list(msg.items())[:25]]
            email_entity = Email(
                account_id=account.id,
                message_uid=uid_str,
                message_id=message_id,
                folder=target_folder,
                category=category,
                sender_name=sender_name,
                sender_email=sender_email,
                sender_avatar_key=sender_email.split("@")[-1].split(".")[0] if "@" in sender_email else "mail",
                to_addresses=to_addrs or [account.email],
                cc_addresses=cc_addrs,
                bcc_addresses=[],
                subject=subject,
                snippet=snippet,
                html_body=html_body,
                text_body=text_body,
                has_remote_images=has_remote_images,
                is_read=final_is_read,
                is_starred=is_starred,
                has_attachments=len(attachments_meta) > 0,
                raw_headers="\n".join(headers_lines),
                received_at=received_at,
            )
            for att in attachments_meta:
                email_entity.attachments.append(
                    Attachment(
                        filename=att["filename"],
                        content_type=att["content_type"],
                        size_bytes=att["size_bytes"],
                        local_path=att["local_path"],
                    )
                )
            email_repo.create(db, email_entity)
            existing_uids_by_folder.setdefault(target_folder, set()).add(uid_str)
            if norm_mid:
                all_account_msg_ids.add(norm_mid)
                if target_folder == "sent":
                    sent_msg_id_map.setdefault(norm_mid, email_entity)
                elif target_folder == "drafts":
                    drafts_msg_id_map.setdefault(norm_mid, email_entity)

            inserted += 1
            inserted_by_folder[target_folder] = inserted_by_folder.get(target_folder, 0) + 1
            if target_folder == "inbox":
                inbox_inserted += 1

            # 优先记录未读收件箱邮件用于桌面/Toast 提醒预览
            priority = 3 if (target_folder == "inbox" and not final_is_read) else (2 if target_folder == "inbox" else 1)
            if priority > latest_priority or (
                priority == latest_priority and (latest_received_at is None or received_at > latest_received_at)
            ):
                latest_priority = priority
                latest_received_at = received_at
                latest_subject = subject
                latest_sender = sender_name

        self._record_checked_all_mail_uids(account.id, fetch_result.skipped_all_mail_uids | extra_skipped_all_uids)

        # 3. 补充虚拟星标目录中的星标标记
        if fetch_result.starred_message_ids:
            flags_updated += email_repo.mark_starred_by_message_ids(db, account.id, fetch_result.starred_message_ids)

        if update_account_status:
            account.last_synced_at = datetime.now(timezone.utc)
            account.sync_status = "idle"
            account.last_error = None
            account_repo.save(db, account)

        # 汇总包含早期 inbox 入库在内的总条数（用于完整 SyncLog 与返回值）
        merged_by_folder = dict(inserted_by_folder)
        prior_total = 0
        if prior_inserted_by_folder:
            for folder_key, cnt in prior_inserted_by_folder.items():
                if cnt > 0:
                    merged_by_folder[folder_key] = merged_by_folder.get(folder_key, 0) + cnt
                    prior_total += cnt
        total_inserted = inserted + prior_total

        if total_inserted > 0:
            detail_parts = [
                f"{FOLDER_LABELS_ZH.get(folder, folder)} {merged_by_folder[folder]}"
                for folder in SYNC_FOLDER_ORDER
                if merged_by_folder.get(folder, 0) > 0
            ]
            detail_suffix = f"（{'、'.join(detail_parts)}）" if detail_parts else ""
            msg_text = f"{account.label} 同步完成，新增 {total_inserted} 封邮件{detail_suffix}"
        else:
            msg_text = f"{account.label} 同步完成，各文件夹均为最新状态"

        # 手动同步始终记录日志；后台自动同步仅在有新邮件时写入，避免空闲轮询刷屏日志表
        if record_log and (source == "manual" or total_inserted > 0):
            account_repo.add_sync_log(db, account.id, "success", total_inserted, msg_text)

        # 仅针对本次新落库/变更广播 SSE，防止早期收件箱已广播后重复推送
        if inserted > 0 or flags_updated > 0:
            mail_event_bus.publish(
                "mail_synced",
                {
                    "account_id": account.id,
                    "account_label": account.label,
                    "notify_enabled": bool(account.notify_enabled),
                    "fetched_count": inserted,
                    "inbox_fetched_count": inbox_inserted,
                    "flags_updated": flags_updated,
                    "mode": mode,
                    "source": source,
                    "latest_subject": latest_subject,
                    "latest_sender": latest_sender,
                },
            )

        return True, total_inserted, msg_text

    async def ingest_fetch_result(
        self,
        account_id: int,
        fetch_result: ImapSyncFetchResult,
        *,
        mode: str = "inbox",
        source: str = "idle",
    ) -> tuple[bool, int, str]:
        """在单账号互斥锁保护下，将后台 IDLE / 快速轮询拉取到的邮件入库并广播 SSE 事件。"""
        async with self._get_account_lock(account_id):
            with SessionLocal() as db:
                account = account_repo.get_by_id(db, account_id)
                if account is None or not account.is_enabled or account.is_demo:
                    return True, 0, "账号不存在或已停用"
                return self._persist_fetch_result(
                    db,
                    account,
                    fetch_result,
                    mode=mode,
                    source=source,
                )

    def mark_realtime_connected(self, account_id: int) -> None:
        """长连接成功就绪后清除残留错误状态并刷新同步时间。"""
        with SessionLocal() as db:
            account = account_repo.get_by_id(db, account_id)
            if account is None or not account.is_enabled or account.is_demo:
                return
            if account.sync_status == "error" or account.last_error is not None:
                account.sync_status = "idle"
                account.last_error = None
                account.last_synced_at = datetime.now(timezone.utc)
                account_repo.save(db, account)

    def record_realtime_error(self, account_id: int, exc: Exception) -> None:
        """记录长连接异常状态（仅当错误文本变化时写入 SyncLog 避免重复刷屏）。"""
        with SessionLocal() as db:
            account = account_repo.get_by_id(db, account_id)
            if account is None or not account.is_enabled or account.is_demo:
                return
            friendly_err = format_mail_auth_error(exc, account.provider)
            changed = account.last_error != friendly_err
            account.sync_status = "error"
            account.last_error = friendly_err
            account_repo.save(db, account)
            if changed:
                account_repo.add_sync_log(
                    db,
                    account.id,
                    "error",
                    0,
                    f"{account.label} 实时收信连接异常：{friendly_err}",
                )

    async def sync_account(
        self,
        db: Session,
        account: Account,
        *,
        inbox_only: bool = False,
        source: str = "manual",
    ) -> tuple[bool, int, str]:
        """
        同步单个邮箱账号的最新邮件至 SQLite。
        支持 `inbox_only=True` 快速通道（仅增量查收件箱），并通过单账号锁避免与实时推送并发重入。
        """
        if account.is_demo:
            account.last_synced_at = datetime.now(timezone.utc)
            account.sync_status = "idle"
            account.last_error = None
            account_repo.save(db, account)
            return True, 0, f"{account.label}（演示邮箱）状态已刷新"

        if not account.is_enabled:
            return True, 0, f"{account.label} 已停用同步"

        async with self._get_account_lock(account.id):
            db.refresh(account)
            if not account.is_enabled:
                return True, 0, f"{account.label} 已停用同步"

            if source == "manual":
                account.sync_status = "syncing"
                account_repo.save(db, account)

            try:
                if account.auth_type == "oauth2":
                    secret = await oauth_service.ensure_valid_access_token(db, account)
                else:
                    raw_secret = crypto_service.decrypt(account.encrypted_secret) or ""
                    secret = normalize_secret(account.provider, raw_secret, account.imap_host)

                if not secret:
                    raise RuntimeError("未找到有效登录凭据，请在设置中重新输入密码或完成浏览器授权。")

                app_settings = setting_repo.get_all(db)
                sync_days = int(app_settings.get("sync_days", 30))

                if inbox_only:
                    known_inbox_uids = email_repo.get_uids_by_folder(db, account.id, "inbox")
                    fetch_result = await asyncio.to_thread(
                        _fetch_imap_inbox_only,
                        host=account.imap_host,
                        port=account.imap_port,
                        use_ssl=account.imap_ssl,
                        email_addr=account.email,
                        secret=secret,
                        auth_type=account.auth_type,
                        provider=account.provider,
                        sync_days=sync_days,
                        known_inbox_uids=known_inbox_uids,
                    )
                    return self._persist_fetch_result(
                        db,
                        account,
                        fetch_result,
                        existing_uids_by_folder={"inbox": known_inbox_uids},
                        uid_maps={},
                        mode="inbox",
                        source=source,
                    )

                # 全量模式：预加载各标准文件夹已有 UID 与去重索引，避免重复下载 RFC822 原文
                uid_maps: dict[str, dict[str, Email]] = {
                    folder: email_repo.get_uid_map_by_folder(db, account.id, folder)
                    for folder in SYNC_FOLDER_ORDER
                }
                existing_uids_by_folder: dict[str, set[str]] = {
                    folder: set(uid_map.keys()) for folder, uid_map in uid_maps.items()
                }
                sent_msg_id_map = email_repo.get_message_id_map_by_folder(db, account.id, "sent")
                drafts_msg_id_map = email_repo.get_message_id_map_by_folder(db, account.id, "drafts")
                all_account_msg_ids = email_repo.get_all_message_ids_for_account(db, account.id)
                skip_all_uids = set(self._checked_all_mail_uids.get(account.id, set()))

                loop = asyncio.get_running_loop()
                early_state: dict[str, int] = {"inbox_inserted": 0}
                early_inbox_source = "manual_early" if source == "manual" else source
                account_id_val = account.id

                async def _persist_early_inbox(
                    early_msgs: list[tuple[int, bytes, bool, bool]],
                    early_flags: dict[str, tuple[bool, bool]],
                ) -> tuple[int, set[str]]:
                    early_fetch = ImapSyncFetchResult(
                        new_messages=[
                            ("inbox", uid, raw_bytes, is_read, is_starred)
                            for uid, raw_bytes, is_read, is_starred in early_msgs
                        ],
                        flag_updates={"inbox": early_flags} if early_flags else {},
                        synced_folders=["inbox"],
                    )
                    with SessionLocal() as early_db:
                        early_acc = account_repo.get_by_id(early_db, account_id_val)
                        if early_acc is None:
                            return 0, set()
                        # 将 UID map 绑定到 early_db 查询对象以便更新 flags
                        early_uid_maps = {
                            "inbox": email_repo.get_uid_map_by_folder(early_db, account_id_val, "inbox")
                        }
                        early_existing = {"inbox": set(early_uid_maps["inbox"].keys())}
                        early_mids = set(all_account_msg_ids)
                        _ok, count, _msg = self._persist_fetch_result(
                            early_db,
                            early_acc,
                            early_fetch,
                            uid_maps=early_uid_maps,
                            existing_uids_by_folder=early_existing,
                            all_account_msg_ids=early_mids,
                            mode="inbox",
                            source=early_inbox_source,
                            record_log=False,
                            update_account_status=False,
                        )
                        newly_added_mids = early_mids - all_account_msg_ids
                        return count, newly_added_mids

                def on_inbox_ready(
                    new_msgs: list[tuple[int, bytes, bool, bool]],
                    flag_updates: dict[str, tuple[bool, bool]],
                ) -> None:
                    fut = asyncio.run_coroutine_threadsafe(
                        _persist_early_inbox(new_msgs, flag_updates),
                        loop,
                    )
                    early_count, new_mids = fut.result(timeout=30.0)
                    early_state["inbox_inserted"] += early_count
                    for uid, _raw, _r, _s in new_msgs:
                        existing_uids_by_folder.setdefault("inbox", set()).add(str(uid))
                    all_account_msg_ids.update(new_mids)

                fetch_result = await asyncio.to_thread(
                    _fetch_imap_folder_messages,
                    host=account.imap_host,
                    port=account.imap_port,
                    use_ssl=account.imap_ssl,
                    email_addr=account.email,
                    secret=secret,
                    auth_type=account.auth_type,
                    provider=account.provider,
                    sync_days=sync_days,
                    existing_uids_by_folder=existing_uids_by_folder,
                    known_message_ids=all_account_msg_ids,
                    skip_all_mail_uids=skip_all_uids,
                    on_inbox_ready=on_inbox_ready,
                )

                db.refresh(account)
                return self._persist_fetch_result(
                    db,
                    account,
                    fetch_result,
                    uid_maps=uid_maps,
                    existing_uids_by_folder=existing_uids_by_folder,
                    sent_msg_id_map=sent_msg_id_map,
                    drafts_msg_id_map=drafts_msg_id_map,
                    all_account_msg_ids=all_account_msg_ids,
                    mode="full",
                    source=source,
                    prior_inserted_by_folder={"inbox": early_state["inbox_inserted"]},
                )
            except Exception as exc:
                logger.exception("Sync failed for account %s", account.email)
                friendly_err = format_mail_auth_error(exc, account.provider)
                prev_error = account.last_error
                account.sync_status = "error"
                account.last_error = friendly_err
                account_repo.save(db, account)
                err_msg = f"{account.label} 同步失败：{friendly_err}"
                if source == "manual" or prev_error != friendly_err:
                    account_repo.add_sync_log(db, account.id, "error", 0, err_msg)
                return False, 0, err_msg


imap_sync_service = ImapSyncService()
