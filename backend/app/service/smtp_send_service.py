from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
import html
import logging
from pathlib import Path
import re
import uuid

import aiosmtplib
from sqlalchemy.orm import Session

from app.core.config import settings
from app.model.entities import Account, Attachment, Email
from app.repository.account_repo import account_repo
from app.repository.email_repo import email_repo
from app.service.crypto_service import crypto_service
from app.service.imap_sync_service import (
    build_smtp_transport_candidates,
    get_safe_local_hostname,
)
from app.service.oauth_service import oauth_service

logger = logging.getLogger(__name__)
HTML_TAG_RE = re.compile(r"<[^>]+>")


class SmtpSendService:
    """异步 SMTP 发信、回复与本地发件箱落库服务。"""

    async def send_email(
        self,
        db: Session,
        *,
        account: Account,
        to_addresses: list[str],
        cc_addresses: list[str],
        bcc_addresses: list[str],
        subject: str,
        html_body: str,
        text_body: str,
        in_reply_to: str = "",
        draft_id: int | None = None,
        uploaded_files: list[tuple[str, str, bytes]] | None = None,
    ) -> Email:
        """
        发送邮件（支持真实 SMTP 与演示模式发件箱入库），并保留附件落盘记录。
        """
        if not to_addresses:
            raise ValueError("至少需要填写一个收件人邮箱地址。")

        # 自动附加账号签名（如正文未包含）
        final_html = html_body.strip()
        final_text = text_body.strip()
        if not final_text and final_html:
            final_text = " ".join(HTML_TAG_RE.sub(" ", final_html).split())
        if not final_html and final_text:
            final_html = f"<div>{html.escape(final_text).replace(chr(10), '<br/>')}</div>"

        if account.signature.strip() and account.signature.strip() not in final_text:
            sig_html = html.escape(account.signature.strip()).replace("\n", "<br/>")
            final_html = f"{final_html}<br/><div class='mail-signature' style='margin-top:16px;padding-top:12px;border-top:1px dashed #d8cce6;color:#7a6b8a;font-size:13px'>{sig_html}</div>"
            final_text = f"{final_text}\n\n--\n{account.signature.strip()}"

        msg_id = make_msgid(domain=account.email.split("@")[-1])
        saved_attachments: list[Attachment] = []

        # 如为真实绑定账号，走 aiosmtplib 真实发信
        if not account.is_demo:
            msg = EmailMessage()
            msg["From"] = f"{account.label} <{account.email}>"
            msg["To"] = ", ".join(to_addresses)
            if cc_addresses:
                msg["Cc"] = ", ".join(cc_addresses)
            if bcc_addresses:
                msg["Bcc"] = ", ".join(bcc_addresses)
            msg["Subject"] = subject or "(无主题)"
            msg["Message-ID"] = msg_id
            if in_reply_to:
                msg["In-Reply-To"] = in_reply_to
                msg["References"] = in_reply_to

            msg.set_content(final_text or " ")
            msg.add_alternative(final_html or "<div></div>", subtype="html")

            for filename, content_type, data in uploaded_files or []:
                maintype, _, subtype = (content_type or "application/octet-stream").partition("/")
                msg.add_attachment(
                    data,
                    maintype=maintype or "application",
                    subtype=subtype or "octet-stream",
                    filename=filename,
                )

            send_kwargs: dict[str, object] = {
                "hostname": account.smtp_host,
                "port": account.smtp_port,
                "username": account.email,
                "local_hostname": get_safe_local_hostname(),
                "use_tls": account.smtp_ssl,
                "start_tls": not account.smtp_ssl,
                "timeout": 25,
            }
            if account.auth_type == "oauth2":
                token = await oauth_service.ensure_valid_access_token(db, account)

                async def _token_gen() -> str:
                    return token

                send_kwargs["oauth_token_generator"] = _token_gen
            else:
                secret = crypto_service.decrypt(account.encrypted_secret) or ""
                if not secret:
                    raise RuntimeError("该账号缺少发送密码或授权码，请先在设置中完善。")
                send_kwargs["password"] = secret

            candidates = build_smtp_transport_candidates(
                account.smtp_port,
                account.smtp_ssl,
                smtp_host=account.smtp_host,
                provider=account.provider,
            )
            last_exc: Exception | None = None
            for idx, (cand_port, cand_ssl) in enumerate(candidates):
                attempt_kwargs = {
                    **send_kwargs,
                    "port": cand_port,
                    "use_tls": cand_ssl,
                    "start_tls": not cand_ssl,
                }
                try:
                    await aiosmtplib.send(msg, **attempt_kwargs)  # type: ignore[arg-type]
                    if cand_port != account.smtp_port or cand_ssl != account.smtp_ssl:
                        account.smtp_port = cand_port
                        account.smtp_ssl = cand_ssl
                        account_repo.save(db, account)
                        logger.info(
                            "Updated SMTP transport for %s to %s (ssl=%s) after fallback.",
                            account.email,
                            cand_port,
                            cand_ssl,
                        )
                    last_exc = None
                    break
                except aiosmtplib.SMTPAuthenticationError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    if idx + 1 < len(candidates):
                        logger.warning(
                            "aiosmtplib send via %s:%s (ssl=%s) failed (%s), trying fallback",
                            account.smtp_host,
                            cand_port,
                            cand_ssl,
                            exc,
                        )
            if last_exc is not None:
                raise last_exc

        # 保存附件文件到本地并构建发件箱记录
        for idx, (filename, content_type, data) in enumerate(uploaded_files or [], start=1):
            target_dir = settings.attachments_dir / str(account.id)
            target_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[\\/:*?"<>|]+', "_", filename or f"file_{idx}")
            local_path = target_dir / f"sent_{uuid.uuid4().hex[:8]}_{safe_name}"
            local_path.write_bytes(data)
            saved_attachments.append(
                Attachment(
                    filename=safe_name,
                    content_type=content_type or "application/octet-stream",
                    size_bytes=len(data),
                    local_path=str(local_path),
                )
            )

        snippet = " ".join((final_text or "").split())[:160]
        sent_email = Email(
            account_id=account.id,
            message_uid=f"sent-{uuid.uuid4().hex[:12]}",
            message_id=msg_id,
            folder="sent",
            category="work",
            sender_name=account.label,
            sender_email=account.email,
            sender_avatar_key=account.provider,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            bcc_addresses=bcc_addresses,
            subject=subject or "(无主题)",
            snippet=snippet,
            html_body=final_html,
            text_body=final_text,
            has_remote_images=False,
            is_read=True,
            is_starred=False,
            has_attachments=len(saved_attachments) > 0,
            raw_headers=f"From: {account.label} <{account.email}>\nTo: {', '.join(to_addresses)}\nSubject: {subject}",
            received_at=datetime.now(timezone.utc),
        )
        sent_email.attachments.extend(saved_attachments)
        created = email_repo.create(db, sent_email)

        # 若是从草稿箱发出，删除对应草稿
        if draft_id is not None:
            draft_obj = email_repo.get_by_id(db, draft_id)
            if draft_obj and draft_obj.folder == "drafts":
                email_repo.delete(db, draft_obj)

        logger.info("Sent email %s via account %s (demo=%s).", created.id, account.email, account.is_demo)
        return created


smtp_send_service = SmtpSendService()
