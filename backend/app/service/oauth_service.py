import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode
import webbrowser
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.model.entities import Account
from app.repository.account_repo import account_repo
from app.repository.setting_repo import setting_repo
from app.service.crypto_service import crypto_service
from app.service.provider_preset_service import get_preset_by_id

logger = logging.getLogger(__name__)

# 支持本地回环授权的 OAuth2 提供商端点配置
OAUTH_PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "gmail": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile https://mail.google.com/",
    },
    "outlook": {
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile offline_access https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send",
    },
}


@dataclass
class OAuthPendingSession:
    """单次 OAuth2 PKCE 授权会话上下文。"""

    state: str
    provider: str
    label: str
    email_hint: str
    code_verifier: str
    redirect_uri: str
    created_at: float
    status: str = "pending"
    message: str = "等待用户在浏览器完成登录授权..."
    account_id: int | None = None


class OAuthService:
    """
    OAuth2 PKCE（S256）+ Localhost Loopback 浏览器登录服务。
    支持 Google Gmail 与 Microsoft Outlook 的免密安全授权及刷新令牌机制。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, OAuthPendingSession] = {}

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired_keys = [k for k, v in self._sessions.items() if now - v.created_at > 600]
        for key in expired_keys:
            self._sessions.pop(key, None)

    @staticmethod
    def build_pkce_pair() -> tuple[str, str]:
        """生成符合 RFC 7636 的 code_verifier 与 S256 code_challenge。"""
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return verifier, challenge

    def start_flow(
        self,
        db: Session,
        provider: str,
        label: str = "",
        email_hint: str = "",
        open_browser: bool = True,
    ) -> tuple[str, str, bool]:
        """
        生成授权跳转链接并尝试唤起系统默认浏览器。
        返回 (state, auth_url, browser_opened)。
        """
        self._cleanup_expired()
        if provider not in OAUTH_PROVIDER_CONFIGS:
            raise ValueError(f"Unsupported OAuth provider: {provider}")

        app_settings = setting_repo.get_all(db)
        if provider == "gmail":
            client_id = str(app_settings.get("oauth_google_client_id", "")).strip()
        else:
            client_id = str(app_settings.get("oauth_microsoft_client_id", "")).strip()

        if not client_id:
            raise ValueError(
                f"请先在「设置 -> 邮箱渠道 -> OAuth2 客户端配置」中填写 {provider.upper()} Client ID。"
            )

        state = secrets.token_urlsafe(24)
        verifier, challenge = self.build_pkce_pair()
        redirect_uri = f"http://{settings.host}:{settings.port}/api/v1/oauth/callback"

        cfg = OAUTH_PROVIDER_CONFIGS[provider]
        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": cfg["scope"],
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        if provider == "outlook":
            params.pop("access_type", None)
            params["response_mode"] = "query"
        if email_hint.strip():
            params["login_hint"] = email_hint.strip()

        auth_url = f"{cfg['auth_url']}?{urlencode(params)}"
        self._sessions[state] = OAuthPendingSession(
            state=state,
            provider=provider,
            label=label.strip() or ("Gmail" if provider == "gmail" else "Outlook"),
            email_hint=email_hint.strip(),
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            created_at=time.time(),
        )

        browser_opened = False
        if open_browser:
            try:
                browser_opened = webbrowser.open(auth_url)
            except Exception as exc:
                logger.warning("Failed to launch system browser for OAuth2: %s", exc)
        return state, auth_url, browser_opened

    def get_status(self, state: str) -> OAuthPendingSession | None:
        """查询某次授权会话当前状态。"""
        self._cleanup_expired()
        return self._sessions.get(state)

    async def handle_callback(
        self,
        db: Session,
        *,
        state: str,
        code: str | None = None,
        error: str | None = None,
    ) -> tuple[bool, str, Account | None]:
        """
        处理浏览器 OAuth2 回调：校验 state、换取 token、提取邮箱身份并加密写入 SQLite。
        """
        session = self._sessions.get(state)
        if session is None:
            return False, "授权会话已过期或无效，请回到 MailHub 重新发起登录。", None

        if error:
            session.status = "failed"
            session.message = f"授权被取消或拒绝：{error}"
            return False, session.message, None

        if not code:
            session.status = "failed"
            session.message = "回调缺少授权码 code 参数。"
            return False, session.message, None

        app_settings = setting_repo.get_all(db)
        cfg = OAUTH_PROVIDER_CONFIGS[session.provider]
        if session.provider == "gmail":
            client_id = str(app_settings.get("oauth_google_client_id", "")).strip()
            client_secret = str(app_settings.get("oauth_google_client_secret", "")).strip()
        else:
            client_id = str(app_settings.get("oauth_microsoft_client_id", "")).strip()
            client_secret = ""

        token_payload: dict[str, str] = {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": session.redirect_uri,
            "code_verifier": session.code_verifier,
        }
        if client_secret:
            token_payload["client_secret"] = client_secret

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                token_resp = await client.post(cfg["token_url"], data=token_payload)
                token_resp.raise_for_status()
                token_data = token_resp.json()

                access_token = str(token_data.get("access_token", ""))
                refresh_token = str(token_data.get("refresh_token", ""))
                expires_in = int(token_data.get("expires_in", 3600))
                if not access_token:
                    raise ValueError("Token response did not contain access_token.")

                # 读取用户邮箱地址
                resolved_email = session.email_hint
                try:
                    info_resp = await client.get(
                        cfg["userinfo_url"],
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if info_resp.status_code == 200:
                        info_json = info_resp.json()
                        resolved_email = str(
                            info_json.get("email")
                            or info_json.get("preferred_username")
                            or info_json.get("mail")
                            or info_json.get("upn")
                            or resolved_email
                        )
                except Exception as exc:
                    logger.warning("Failed to query OAuth userinfo endpoint: %s", exc)

            if not resolved_email:
                raise ValueError("无法识别授权账号的邮箱地址，请在发起登录前填写邮箱提示。")

            preset = get_preset_by_id(session.provider)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in - 60))

            existing = account_repo.get_by_email(db, resolved_email)
            if existing:
                existing.provider = session.provider
                existing.auth_type = "oauth2"
                existing.encrypted_secret = crypto_service.encrypt(access_token)
                if refresh_token:
                    existing.encrypted_refresh_token = crypto_service.encrypt(refresh_token)
                existing.token_expires_at = expires_at
                # 若曾为演示账号（*.demo），同步更新为真实服务商主机与端口
                existing.imap_host = preset.imap_host
                existing.imap_port = preset.imap_port
                existing.imap_ssl = preset.imap_ssl
                existing.smtp_host = preset.smtp_host
                existing.smtp_port = preset.smtp_port
                existing.smtp_ssl = preset.smtp_ssl
                existing.is_enabled = True
                existing.is_demo = False
                existing.sync_status = "idle"
                existing.last_error = None
                saved = account_repo.save(db, existing)
            else:
                next_order = account_repo.get_max_sort_order(db) + 1
                new_acc = Account(
                    label=session.label,
                    email=resolved_email,
                    provider=session.provider,
                    auth_type="oauth2",
                    encrypted_secret=crypto_service.encrypt(access_token),
                    encrypted_refresh_token=crypto_service.encrypt(refresh_token) if refresh_token else None,
                    token_expires_at=expires_at,
                    imap_host=preset.imap_host,
                    imap_port=preset.imap_port,
                    imap_ssl=preset.imap_ssl,
                    smtp_host=preset.smtp_host,
                    smtp_port=preset.smtp_port,
                    smtp_ssl=preset.smtp_ssl,
                    badge_color=preset.badge_color,
                    sort_order=next_order,
                    is_demo=False,
                )
                saved = account_repo.create(db, new_acc)

            session.status = "completed"
            session.message = f"账号 {saved.email} 授权成功！"
            session.account_id = saved.id
            from app.service.scheduler_service import scheduler_service

            scheduler_service.notify_accounts_changed(force_restart_account_id=saved.id)
            return True, session.message, saved
        except Exception as exc:
            logger.exception("OAuth2 callback exchange failed")
            session.status = "failed"
            session.message = f"换取授权令牌失败：{exc}"
            return False, session.message, None

    async def ensure_valid_access_token(self, db: Session, account: Account) -> str:
        """
        对 OAuth2 账号校验并按需自动刷新 access_token。
        """
        current_token = crypto_service.decrypt(account.encrypted_secret) or ""
        if account.auth_type != "oauth2":
            return current_token

        now = datetime.now(timezone.utc)
        expires = account.token_expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if current_token and expires is not None and expires > now + timedelta(seconds=60):
            return current_token

        refresh_token = crypto_service.decrypt(account.encrypted_refresh_token)
        if not refresh_token:
            return current_token

        cfg = OAUTH_PROVIDER_CONFIGS.get(account.provider)
        if not cfg:
            return current_token

        app_settings = setting_repo.get_all(db)
        if account.provider == "gmail":
            client_id = str(app_settings.get("oauth_google_client_id", "")).strip()
            client_secret = str(app_settings.get("oauth_google_client_secret", "")).strip()
        else:
            client_id = str(app_settings.get("oauth_microsoft_client_id", "")).strip()
            client_secret = ""

        if not client_id:
            return current_token

        payload: dict[str, str] = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if client_secret:
            payload["client_secret"] = client_secret

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(cfg["token_url"], data=payload)
            resp.raise_for_status()
            data = resp.json()

        new_access = str(data.get("access_token", ""))
        if not new_access:
            raise RuntimeError("OAuth2 token refresh did not return a new access_token.")

        expires_in = int(data.get("expires_in", 3600))
        account.encrypted_secret = crypto_service.encrypt(new_access)
        if data.get("refresh_token"):
            account.encrypted_refresh_token = crypto_service.encrypt(str(data["refresh_token"]))
        account.token_expires_at = now + timedelta(seconds=max(60, expires_in - 60))
        account_repo.save(db, account)
        return new_access


oauth_service = OAuthService()
