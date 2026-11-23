import base64
from datetime import datetime, timedelta, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import smtplib
import socket
import ssl
import aiosmtplib
from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.core.database import SessionLocal, configure_database, init_db
from app.main import create_app
from app.model.entities import Account
from app.repository.account_repo import account_repo
from app.service.crypto_service import CryptoService
from app.service.demo_seed_service import demo_seed_service
from app.service.imap_sync_service import (
    _extract_email_parts,
    _should_send_imap_id,
    _smtp_login_preserve_auth_error,
    build_smtp_transport_candidates,
    format_mail_auth_error,
    normalize_secret,
    resolve_imap_folders,
)
from app.service.oauth_service import OAuthService
from app.service.provider_preset_service import detect_provider_from_email
from app.service.smtp_send_service import smtp_send_service


@pytest.fixture()
def client(tmp_path: Path):
    """为每个测试创建独立的临时 SQLite 数据库与 FastAPI 测试客户端。"""
    db_file = tmp_path / "test_mailhub.db"
    eng = configure_database(f"sqlite:///{db_file}")
    init_db(eng)
    with SessionLocal() as db:
        demo_seed_service.seed_if_empty(db, force=False)

    app = create_app()
    with TestClient(app) as tc:
        yield tc


def test_crypto_roundtrip(tmp_path: Path) -> None:
    """验证 Fernet 加密与解密往返一致性。"""
    crypto = CryptoService(key_file=tmp_path / ".secret.key")
    secret = "my_16_char_auth_code_1234"
    encrypted = crypto.encrypt(secret)
    assert encrypted is not None and encrypted != secret
    assert crypto.decrypt(encrypted) == secret
    assert crypto.encrypt(None) is None


def test_provider_detection_and_163_imap_id() -> None:
    """验证主流邮箱后缀自动识别与 163/126 IMAP ID 触发策略。"""
    assert detect_provider_from_email("user@qq.com").id == "qq"
    assert detect_provider_from_email("user@163.com").id == "163"
    assert detect_provider_from_email("user@gmail.com").id == "gmail"
    assert detect_provider_from_email("user@outlook.com").id == "outlook"
    assert detect_provider_from_email("stu@pku.edu.cn").id == "school"

    assert _should_send_imap_id("163", "imap.163.com") is True
    assert _should_send_imap_id("126", "imap.126.com") is True
    assert _should_send_imap_id("qq", "imap.qq.com") is False


def test_pkce_pair_generation() -> None:
    """验证 OAuth2 PKCE verifier 与 challenge 生成合法。"""
    verifier, challenge = OAuthService.build_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43
    assert verifier != challenge
    assert "=" not in challenge


def test_accounts_crud_and_secret_masking(client: TestClient) -> None:
    """验证邮箱增删改与响应绝不泄漏明文密码。"""
    resp = client.get("/api/v1/accounts")
    assert resp.status_code == 200
    accounts = resp.json()
    assert len(accounts) == 5

    create_resp = client.post(
        "/api/v1/accounts",
        json={
            "label": "测试网易",
            "email": "tester@163.com",
            "provider": "163",
            "auth_type": "password",
            "secret": "SUPER_SECRET_AUTH",
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["imap_host"] == "imap.163.com"
    assert "SUPER_SECRET_AUTH" not in create_resp.text
    assert "encrypted_secret" not in created

    # 删除新账号
    del_resp = client.delete(f"/api/v1/accounts/{created['id']}")
    assert del_resp.status_code == 200


def test_emails_fts_search_and_batch_flow(client: TestClient) -> None:
    """验证 FTS5 全文搜索、详情、草稿、发送与批量操作。"""
    search_resp = client.get("/api/v1/emails", params={"q": "Issue"})
    assert search_resp.status_code == 200
    data = search_resp.json()
    assert data["total"] >= 1
    first_id = data["items"][0]["id"]

    # 标记星标与已读
    patch_resp = client.patch(f"/api/v1/emails/{first_id}", json={"is_read": True, "is_starred": True})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_starred"] is True

    # 发送演示邮件（自动入库发件箱）
    accounts = client.get("/api/v1/accounts").json()
    send_resp = client.post(
        "/api/v1/emails/send",
        data={
            "account_id": str(accounts[0]["id"]),
            "to_addresses": "friend@example.com",
            "subject": "Pytest 发送验证邮件",
            "text_body": "你好，这是自动测试发出的邮件内容。",
        },
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["folder"] == "sent"


def test_settings_and_rules_persistence(client: TestClient) -> None:
    """验证明暗主题与设置持久化、分类规则 CRUD 与演示清理。"""
    patch_res = client.patch(
        "/api/v1/settings",
        json={"theme_mode": "dark", "show_mascots": False, "undo_send_seconds": 10},
    )
    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["theme_mode"] == "dark"
    assert body["show_mascots"] is False
    assert body["undo_send_seconds"] == 10

    rule_res = client.post(
        "/api/v1/rules",
        json={"name": "测试规则", "field": "subject", "pattern": "周报", "target_category": "work"},
    )
    assert rule_res.status_code == 200
    rule_id = rule_res.json()["id"]
    assert client.delete(f"/api/v1/rules/{rule_id}").status_code == 200

    # 清空并重置演示数据
    clear_res = client.post("/api/v1/system/demo/clear")
    assert clear_res.status_code == 200
    assert clear_res.json()["removed_accounts"] == 5
    reset_res = client.post("/api/v1/system/demo/reset")
    assert reset_res.status_code == 200
    assert len(client.get("/api/v1/accounts").json()) == 5


def test_gmail_secret_normalization_and_error_translation() -> None:
    """验证 Gmail 16 位应用专用密码空格清理及常见授权报错中文翻译。"""
    assert normalize_secret("gmail", "  abcd efgh ijkl mnop  ") == "abcdefghijklmnop"
    assert normalize_secret("gmail", "regular-password with space") == "regular-password with space"
    assert normalize_secret("qq", "abcd efgh ijkl mnop") == "abcd efgh ijkl mnop"

    raw_err = Exception(
        "b'[ALERT] Application-specific password required: https://support.google.com/accounts/answer/185833 (Failure)'"
    )
    msg = format_mail_auth_error(raw_err, "gmail")
    assert "应用专用密码" in msg
    assert "apppasswords" in msg
    assert not msg.startswith("b'")


def test_create_account_with_verify_rejects_invalid_gmail_password(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证开启 verify_connection 后，IMAP 登录失败会拦截创建且不产生假成功账号。"""
    import app.service.imap_sync_service as sync_mod

    def fake_connect_fail(**_kwargs: object) -> object:
        raise RuntimeError(
            "b'[ALERT] Application-specific password required: https://support.google.com/accounts/answer/185833 (Failure)'"
        )

    monkeypatch.setattr(sync_mod, "_imap_connect_and_auth", fake_connect_fail)

    before_count = len(client.get("/api/v1/accounts").json())
    res = client.post(
        "/api/v1/accounts",
        json={
            "label": "测试 Gmail",
            "email": "mytest@gmail.com",
            "provider": "gmail",
            "auth_type": "password",
            "secret": "normal_login_password",
            "verify_connection": True,
        },
    )
    assert res.status_code == 400
    assert "应用专用密码" in res.json()["detail"]
    after_count = len(client.get("/api/v1/accounts").json())
    assert after_count == before_count


def test_default_settings_do_not_block_remote_images(client: TestClient) -> None:
    """验证默认配置下不拦截邮件外链图片，避免新用户打开邮件全是裂图占位框。"""
    res = client.get("/api/v1/settings")
    assert res.status_code == 200
    assert res.json()["block_remote_images"] is False


def test_extract_email_parts_resolves_qq_cid_inline_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证包含 Content-ID 的内嵌图片（无文件名与 inline+文件名）可解析为 data URI 且不生成多余附件。"""
    monkeypatch.setattr(settings, "project_root", tmp_path)

    png_bytes_1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    png_bytes_2 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEklEQVR42mP8z8BQzwAEjDAGACbeAwM9u+6KAAAAAElFTkSuQmCC"
    )

    msg = MIMEMultipart("related")
    html_part = MIMEText(
        '<div><img src="cid:qqimg01@qq.com"><img src="cid:qqimg02%40qq.com"></div>',
        "html",
        "utf-8",
    )
    msg.attach(html_part)

    # 场景 1：无 filename 的内嵌图片
    img_no_name = MIMEImage(png_bytes_1, _subtype="png")
    img_no_name.add_header("Content-ID", "<qqimg01@qq.com>")
    msg.attach(img_no_name)

    # 场景 2：带 inline disposition 与 filename 的 QQ 内嵌图片
    img_inline_named = MIMEImage(png_bytes_2, _subtype="png", name="paste.png")
    img_inline_named.add_header("Content-ID", "<qqimg02@qq.com>")
    img_inline_named.add_header("Content-Disposition", "inline", filename="paste.png")
    msg.attach(img_inline_named)

    # 场景 3：正常普通附件应保留在 attachments_meta 中
    real_att = MIMEText("hello attachment", "plain", "utf-8")
    real_att.add_header("Content-Disposition", "attachment", filename="readme.txt")
    msg.attach(real_att)

    text_body, html_body, attachments_meta = _extract_email_parts(msg, account_id=9, uid_str="1001")
    assert text_body == ""
    assert f"data:image/png;base64,{base64.b64encode(png_bytes_1).decode('ascii')}" in html_body
    assert f"data:image/png;base64,{base64.b64encode(png_bytes_2).decode('ascii')}" in html_body
    assert "cid:" not in html_body
    assert [att["filename"] for att in attachments_meta] == ["readme.txt"]


def test_smtp_transport_candidates_and_ssl_eof_error_translation() -> None:
    """验证 SMTP 465/587 回退序列，以及 SSLEOFError 与 SMTP 535 认证异常的中文诊断翻译。"""
    assert build_smtp_transport_candidates(465, True) == [(465, True), (587, False)]
    assert build_smtp_transport_candidates(587, False) == [(587, False), (465, True)]
    assert build_smtp_transport_candidates(587, True) == [(587, True), (587, False), (465, True)]
    assert build_smtp_transport_candidates(465, False) == [(465, False), (465, True), (587, False)]
    assert build_smtp_transport_candidates(2525, False) == [(2525, False)]

    eof_exc = ssl.SSLEOFError(
        8,
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)",
    )
    eof_msg = format_mail_auth_error(eof_exc, "gmail")
    assert "TLS/SSL 握手被中断" in eof_msg
    assert "587" in eof_msg

    smtp_auth_exc = smtplib.SMTPAuthenticationError(
        535,
        b"5.7.8 Username and Password not accepted. For more information, go to https://support.google.com/mail/?p=BadCredentials",
    )
    auth_msg = format_mail_auth_error(smtp_auth_exc, "gmail")
    assert "Gmail 身份校验失败" in auth_msg
    assert "应用专用密码" in auth_msg


def test_account_test_falls_back_from_465_ssl_eof_to_587_starttls(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 465 SSL 遭遇 UNEXPECTED_EOF_WHILE_READING 时自动回退 587 STARTTLS 并落库有效配置。"""
    import app.service.imap_sync_service as sync_mod

    class FakeImapClient:
        def select_folder(self, _folder: str, readonly: bool = True) -> None:
            return None

        def logout(self) -> None:
            return None

    smtp_attempts: list[tuple[int, bool]] = []

    def fake_imap_connect(**_kwargs: object) -> FakeImapClient:
        return FakeImapClient()

    def fake_smtp_connect_and_auth(**kwargs: object) -> None:
        port = int(kwargs["smtp_port"])
        use_ssl = bool(kwargs["smtp_ssl"])
        smtp_attempts.append((port, use_ssl))
        if port == 465 and use_ssl:
            raise ssl.SSLEOFError(
                8,
                "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)",
            )
        if port == 587 and not use_ssl:
            return None
        raise AssertionError(f"Unexpected SMTP attempt: {(port, use_ssl)}")

    monkeypatch.setattr(sync_mod, "_imap_connect_and_auth", fake_imap_connect)
    monkeypatch.setattr(sync_mod, "_smtp_connect_and_auth_sync", fake_smtp_connect_and_auth)

    test_resp = client.post(
        "/api/v1/accounts/test",
        json={
            "email": "fallback@gmail.com",
            "provider": "gmail",
            "secret": "abcd efgh ijkl mnop",
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "imap_ssl": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 465,
            "smtp_ssl": True,
        },
    )
    assert test_resp.status_code == 200
    body = test_resp.json()
    assert body["ok"] is True
    assert body["imap_ok"] is True
    assert body["smtp_ok"] is True
    assert body["resolved_smtp_port"] == 587
    assert body["resolved_smtp_ssl"] is False
    assert "587 STARTTLS" in body["message"]
    assert smtp_attempts == [(465, True), (587, False)]

    create_resp = client.post(
        "/api/v1/accounts",
        json={
            "label": "Gmail 测试",
            "email": "fallback@gmail.com",
            "provider": "gmail",
            "auth_type": "password",
            "secret": "abcd efgh ijkl mnop",
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "imap_ssl": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 465,
            "smtp_ssl": True,
            "verify_connection": True,
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["smtp_port"] == 587
    assert created["smtp_ssl"] is False


def test_account_test_does_not_fallback_on_smtp_auth_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证遇明确 SMTP 535 凭据拒绝时不无意义重连另一端口，直接给出中文提示。"""
    import app.service.imap_sync_service as sync_mod

    class FakeImapClient:
        def select_folder(self, _folder: str, readonly: bool = True) -> None:
            return None

        def logout(self) -> None:
            return None

    smtp_attempts: list[tuple[int, bool]] = []

    monkeypatch.setattr(sync_mod, "_imap_connect_and_auth", lambda **_kw: FakeImapClient())

    def fake_smtp_auth_fail(**kwargs: object) -> None:
        smtp_attempts.append((int(kwargs["smtp_port"]), bool(kwargs["smtp_ssl"])))
        raise smtplib.SMTPAuthenticationError(
            535,
            b"5.7.8 Username and Password not accepted",
        )

    monkeypatch.setattr(sync_mod, "_smtp_connect_and_auth_sync", fake_smtp_auth_fail)

    resp = client.post(
        "/api/v1/accounts/test",
        json={
            "email": "badpass@gmail.com",
            "provider": "gmail",
            "secret": "aaaa bbbb cccc dddd",
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "imap_ssl": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 465,
            "smtp_ssl": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["imap_ok"] is True
    assert data["smtp_ok"] is False
    assert smtp_attempts == [(465, True)]
    assert "Gmail 身份校验失败" in data["message"]


@pytest.mark.anyio
async def test_smtp_send_service_fallback_and_ascii_local_hostname(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证中文主机名下自动使用 ASCII local_hostname，并在 465 失败时回退 587 且持久化。"""
    monkeypatch.setattr(socket, "getfqdn", lambda: "测试主机小屋")

    recorded_calls: list[dict[str, object]] = []

    async def fake_aiosmtp_send(_msg: object, **kwargs: object) -> tuple[dict[str, object], str]:
        recorded_calls.append(dict(kwargs))
        if kwargs["port"] == 465:
            raise aiosmtplib.SMTPConnectError("Error connecting to smtp.gmail.com on port 465")
        return ({}, "250 2.0.0 OK")

    monkeypatch.setattr(aiosmtplib, "send", fake_aiosmtp_send)

    with SessionLocal() as db:
        acc = Account(
            label="Gmail 发送测试",
            email="sender@gmail.com",
            provider="gmail",
            auth_type="password",
            encrypted_secret=CryptoService(key_file=settings.secret_key_file).encrypt("abcdefghijklmnop"),
            imap_host="imap.gmail.com",
            imap_port=993,
            imap_ssl=True,
            smtp_host="smtp.gmail.com",
            smtp_port=465,
            smtp_ssl=True,
            is_demo=False,
        )
        acc = account_repo.create(db, acc)

        sent = await smtp_send_service.send_email(
            db,
            account=acc,
            to_addresses=["to@example.com"],
            cc_addresses=[],
            bcc_addresses=[],
            subject="回退发信验证",
            html_body="<p>hello</p>",
            text_body="hello",
        )
        assert sent.folder == "sent"
        refreshed = account_repo.get_by_id(db, acc.id)
        assert refreshed is not None
        assert refreshed.smtp_port == 587
        assert refreshed.smtp_ssl is False

    assert len(recorded_calls) == 2
    assert recorded_calls[0]["local_hostname"] == "localhost"
    assert recorded_calls[0]["port"] == 465
    assert recorded_calls[0]["use_tls"] is True
    assert recorded_calls[0]["start_tls"] is False
    assert recorded_calls[1]["local_hostname"] == "localhost"
    assert recorded_calls[1]["port"] == 587
    assert recorded_calls[1]["use_tls"] is False
    assert recorded_calls[1]["start_tls"] is True


def test_smtp_login_preserves_535_auth_error_without_second_auth_disconnect() -> None:
    """验证遇 535 凭据拒绝时立即抛出 SMTPAuthenticationError，不再发第二次 AUTH 导致断连覆盖错误。"""

    class FakeSmtpServer(smtplib.SMTP):
        def __init__(self) -> None:
            super().__init__()
            self.esmtp_features = {"auth": "LOGIN PLAIN"}
            self.auth_calls: list[str] = []

        def ehlo_or_helo_if_needed(self) -> None:
            return None

        def auth(self, mechanism: str, authobject: object, *, initial_response_ok: bool = True) -> tuple[int, bytes]:
            self.auth_calls.append(mechanism)
            if len(self.auth_calls) == 1:
                raise smtplib.SMTPAuthenticationError(
                    535,
                    b"5.7.8 Username and Password not accepted",
                )
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    fake_server = FakeSmtpServer()
    with pytest.raises(smtplib.SMTPAuthenticationError) as exc_info:
        _smtp_login_preserve_auth_error(fake_server, "user@gmail.com", "aaaabbbbccccdddd")

    assert exc_info.value.smtp_code == 535
    assert fake_server.auth_calls == ["PLAIN"]


def test_email_and_log_timestamps_serialize_with_utc_timezone(client: TestClient) -> None:
    """验证邮件、账号同步与通知日志时间从 SQLite 读出后带 UTC 时区后缀，并保持正确的倒序排序。"""
    from app.model.entities import Email, SyncLog

    with SessionLocal() as db:
        acc = account_repo.list_all(db)[0]
        # 写入一条带 +08:00 偏移与一条更晚的 UTC 时间，检验统一转换存盘与 ORDER BY 排序
        dt_beijing_earlier = datetime(2026, 11, 22, 21, 10, 47, tzinfo=timezone(timedelta(hours=8)))
        dt_utc_later = datetime(2026, 11, 22, 13, 13, 51, tzinfo=timezone.utc)
        db.add(
            Email(
                account_id=acc.id,
                message_uid="tz-test-1",
                folder="inbox",
                category="work",
                sender_name="TZ Earlier",
                sender_email="tz1@example.com",
                subject="时区排序测试-较早",
                snippet="earlier",
                received_at=dt_beijing_earlier,
            )
        )
        db.add(
            Email(
                account_id=acc.id,
                message_uid="tz-test-2",
                folder="inbox",
                category="work",
                sender_name="TZ Later",
                sender_email="tz2@example.com",
                subject="时区排序测试-较晚",
                snippet="later",
                received_at=dt_utc_later,
            )
        )
        db.add(SyncLog(account_id=acc.id, status="success", fetched_count=1, message="时区日志验证"))
        db.commit()

    def _has_utc_suffix(ts: str) -> bool:
        return ts.endswith("Z") or ts.endswith("+00:00")

    accounts_res = client.get("/api/v1/accounts")
    assert accounts_res.status_code == 200
    for acc_item in accounts_res.json():
        if acc_item["last_synced_at"] is not None:
            assert _has_utc_suffix(acc_item["last_synced_at"])

    list_res = client.get("/api/v1/emails", params={"q": "时区排序测试"})
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert [it["subject"] for it in items] == ["时区排序测试-较晚", "时区排序测试-较早"]
    assert _has_utc_suffix(items[0]["received_at"])
    assert _has_utc_suffix(items[1]["received_at"])
    assert items[0]["received_at"].startswith("2026-11-22T13:13:51")
    assert items[1]["received_at"].startswith("2026-11-22T13:10:47")

    detail_res = client.get(f"/api/v1/emails/{items[0]['id']}")
    assert detail_res.status_code == 200
    assert _has_utc_suffix(detail_res.json()["received_at"])

    logs_res = client.get("/api/v1/notifications")
    assert logs_res.status_code == 200
    logs = logs_res.json()
    assert len(logs) >= 1
    assert _has_utc_suffix(logs[0]["created_at"])


def _build_rfc822_email(
    *,
    sender: str,
    to: str,
    subject: str,
    body: str,
    message_id: str = "",
    attachment: tuple[str, bytes] | None = None,
) -> bytes:
    """构造测试用 RFC822 邮件字节流。"""
    if attachment is not None:
        msg = MIMEMultipart()
        if body:
            msg.attach(MIMEText(body, "plain", "utf-8"))
        att_name, att_bytes = attachment
        att_part = MIMEText(att_bytes.decode("utf-8"), "plain", "utf-8")
        att_part.add_header("Content-Disposition", "attachment", filename=att_name)
        msg.attach(att_part)
    else:
        msg = MIMEText(body, "plain", "utf-8")

    if sender:
        msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = "Sun, 22 Nov 2026 12:00:00 +0000"
    if message_id:
        msg["Message-ID"] = message_id
    return msg.as_bytes()


def test_resolve_imap_folders_across_providers() -> None:
    """验证 QQ、163、Gmail、Outlook 与学校邮箱（含 \\Noselect / \\All / \\Flagged）目录解析正确。"""
    # 1. QQ 邮箱风格（部分目录无 special-use flag，依赖名称匹配）
    qq_map, qq_starred, qq_all = resolve_imap_folders(
        [
            ((b"\\HasNoChildren",), b"/", "INBOX"),
            ((b"\\HasNoChildren",), b"/", "Sent Messages"),
            ((b"\\HasNoChildren",), b"/", "Drafts"),
            ((b"\\HasNoChildren",), b"/", "Deleted Messages"),
            ((b"\\HasNoChildren",), b"/", "Junk"),
            ((b"\\Noselect", b"\\HasChildren"), b"/", "其他文件夹"),
            ((b"\\HasNoChildren",), b"/", "其他文件夹/QQ邮件订阅"),
        ]
    )
    assert qq_map == {
        "inbox": "INBOX",
        "sent": "Sent Messages",
        "drafts": "Drafts",
        "trash": "Deleted Messages",
        "spam": "Junk",
    }
    assert qq_starred is None
    assert qq_all is None

    # 2. 网易 163 邮箱中文目录
    netease_map, _, _ = resolve_imap_folders(
        [
            ((), b"/", "INBOX"),
            ((), b"/", "已发送"),
            ((), b"/", "草稿箱"),
            ((), b"/", "已删除"),
            ((), b"/", "垃圾邮件"),
            ((), b"/", "广告邮件"),
        ]
    )
    assert netease_map == {
        "inbox": "INBOX",
        "sent": "已发送",
        "drafts": "草稿箱",
        "trash": "已删除",
        "spam": "垃圾邮件",
    }

    # 3. Gmail（RFC 6154 Special-Use Flags + \Noselect + \All + \Flagged）
    gmail_map, gmail_starred, gmail_all = resolve_imap_folders(
        [
            ((b"\\HasNoChildren",), b"/", "INBOX"),
            ((b"\\Noselect", b"\\HasChildren"), b"/", "[Gmail]"),
            ((b"\\All", b"\\HasNoChildren"), b"/", "[Gmail]/All Mail"),
            ((b"\\Sent", b"\\HasNoChildren"), b"/", "[Gmail]/Sent Mail"),
            ((b"\\Drafts", b"\\HasNoChildren"), b"/", "[Gmail]/Drafts"),
            ((b"\\Junk", b"\\HasNoChildren"), b"/", "[Gmail]/Spam"),
            ((b"\\Trash", b"\\HasNoChildren"), b"/", "[Gmail]/Trash"),
            ((b"\\Flagged", b"\\HasNoChildren"), b"/", "[Gmail]/Starred"),
        ]
    )
    assert gmail_map == {
        "inbox": "INBOX",
        "sent": "[Gmail]/Sent Mail",
        "drafts": "[Gmail]/Drafts",
        "spam": "[Gmail]/Spam",
        "trash": "[Gmail]/Trash",
    }
    assert gmail_starred == "[Gmail]/Starred"
    assert gmail_all == "[Gmail]/All Mail"

    # 4. Outlook 风格
    outlook_map, _, _ = resolve_imap_folders(
        [
            ((b"\\HasNoChildren",), b"/", "Inbox"),
            ((b"\\Sent",), b"/", "Sent"),
            ((b"\\Drafts",), b"/", "Drafts"),
            ((b"\\Archive",), b"/", "Archive"),
            ((b"\\Junk",), b"/", "Junk"),
            ((b"\\Trash",), b"/", "Deleted"),
        ]
    )
    assert outlook_map == {
        "inbox": "Inbox",
        "sent": "Sent",
        "drafts": "Drafts",
        "archive": "Archive",
        "spam": "Junk",
        "trash": "Deleted",
    }

    # 5. 学校 Coremail / Dovecot 点分隔层级目录
    school_map, _, _ = resolve_imap_folders(
        [
            ((), b".", "INBOX"),
            ((), b".", "INBOX.Sent"),
            ((), b".", "INBOX.Drafts"),
            ((), b".", "INBOX.Archive"),
            ((), b".", "INBOX.Spam"),
            ((), b".", "INBOX.Trash"),
        ]
    )
    assert school_map == {
        "inbox": "INBOX",
        "sent": "INBOX.Sent",
        "drafts": "INBOX.Drafts",
        "archive": "INBOX.Archive",
        "spam": "INBOX.Spam",
        "trash": "INBOX.Trash",
    }


def test_sync_account_syncs_all_folders_and_isolates_by_account(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证多邮箱同步时全部标准文件夹入库，且单邮箱视图严格隔离、聚合视图正确汇总。"""
    import app.service.imap_sync_service as sync_mod

    # 清理预置演示数据以便精确验证真实多邮箱隔离与计数
    clear_res = client.post("/api/v1/system/demo/clear")
    assert clear_res.status_code == 200

    mailboxes_by_email: dict[str, dict[str, object]] = {
        "qq_user@qq.com": {
            "folders": [
                ((), b"/", "INBOX"),
                ((), b"/", "Sent Messages"),
                ((), b"/", "Drafts"),
                ((), b"/", "Archive"),
                ((), b"/", "Junk"),
                ((), b"/", "Deleted Messages"),
            ],
            "messages": {
                "INBOX": {
                    1: (
                        _build_rfc822_email(
                            sender="Friend <friend@qq.com>",
                            to="qq_user@qq.com",
                            subject="QQ 收件箱星标邮件",
                            body="QQ 收件箱内容",
                            message_id="<qq-inbox-1@qq.com>",
                        ),
                        (b"\\Flagged",),
                    ),
                },
                "Sent Messages": {
                    2: (
                        _build_rfc822_email(
                            sender="QQ用户 <qq_user@qq.com>",
                            to="other@example.com",
                            subject="QQ 已发送邮件",
                            body="我从 QQ 发出的内容",
                            message_id="<qq-sent-2@qq.com>",
                        ),
                        (b"\\Seen",),
                    ),
                },
                "Drafts": {
                    3: (
                        _build_rfc822_email(
                            sender="",
                            to="target@example.com",
                            subject="QQ 草稿箱邮件",
                            body="QQ 草稿正文",
                            message_id="<qq-draft-3@qq.com>",
                        ),
                        (),
                    ),
                },
                "Archive": {
                    4: (
                        _build_rfc822_email(
                            sender="QQ Team <team@qq.com>",
                            to="qq_user@qq.com",
                            subject="QQ 归档邮件",
                            body="QQ 归档正文",
                            message_id="<qq-archive-4@qq.com>",
                        ),
                        (b"\\Seen",),
                    ),
                },
                "Junk": {
                    5: (
                        _build_rfc822_email(
                            sender="Spammer <spam@bad.invalid>",
                            to="qq_user@qq.com",
                            subject="QQ 专属垃圾邮件",
                            body="QQ 垃圾邮件正文",
                            message_id="<qq-spam-5@bad.invalid>",
                        ),
                        (),
                    ),
                },
                "Deleted Messages": {
                    6: (
                        _build_rfc822_email(
                            sender="Old <old@qq.com>",
                            to="qq_user@qq.com",
                            subject="QQ 回收站邮件",
                            body="QQ 回收站正文",
                            message_id="<qq-trash-6@qq.com>",
                        ),
                        (b"\\Seen",),
                    ),
                },
            },
        },
        "netease_user@163.com": {
            "folders": [
                ((), b"/", "INBOX"),
                ((), b"/", "已发送"),
                ((), b"/", "草稿箱"),
                ((), b"/", "垃圾邮件"),
                ((), b"/", "已删除"),
            ],
            "messages": {
                "INBOX": {
                    11: (
                        _build_rfc822_email(
                            sender="NetEase <notice@163.com>",
                            to="netease_user@163.com",
                            subject="163 收件箱邮件",
                            body="163 收件箱内容",
                            message_id="<163-inbox-11@163.com>",
                        ),
                        (b"\\Seen",),
                    ),
                },
                "已发送": {
                    12: (
                        _build_rfc822_email(
                            sender="网易用户 <netease_user@163.com>",
                            to="partner@163.com",
                            subject="163 已发送邮件",
                            body="163 发件箱内容",
                            message_id="<163-sent-12@163.com>",
                        ),
                        (b"\\Seen",),
                    ),
                },
                "草稿箱": {
                    13: (
                        _build_rfc822_email(
                            sender="网易用户 <netease_user@163.com>",
                            to="draft@163.com",
                            subject="163 草稿邮件",
                            body="163 草稿内容",
                            message_id="<163-draft-13@163.com>",
                        ),
                        (),
                    ),
                },
                "垃圾邮件": {
                    14: (
                        _build_rfc822_email(
                            sender="Ads <ads@163spam.invalid>",
                            to="netease_user@163.com",
                            subject="163 专属垃圾邮件",
                            body="163 垃圾邮件正文",
                            message_id="<163-spam-14@163spam.invalid>",
                        ),
                        (),
                    ),
                },
                "已删除": {
                    15: (
                        _build_rfc822_email(
                            sender="Old163 <old@163.com>",
                            to="netease_user@163.com",
                            subject="163 回收站邮件",
                            body="163 回收站正文",
                            message_id="<163-trash-15@163.com>",
                        ),
                        (b"\\Seen",),
                    ),
                },
            },
        },
    }

    class FakeImapClient:
        def __init__(self, mailbox: dict[str, object]) -> None:
            self.mailbox = mailbox
            self.current_folder = "INBOX"

        def list_folders(self) -> list[tuple[object, object, object]]:
            return self.mailbox["folders"]  # type: ignore[return-value]

        def select_folder(self, folder: str, readonly: bool = True) -> None:
            self.current_folder = folder

        def search(self, _criteria: list[object]) -> list[int]:
            msgs: dict[int, tuple[bytes, tuple[bytes, ...]]] = self.mailbox["messages"].get(self.current_folder, {})  # type: ignore[union-attr]
            return sorted(msgs.keys())

        def fetch(self, uids: list[int], parts: list[str]) -> dict[int, dict[bytes, object]]:
            msgs: dict[int, tuple[bytes, tuple[bytes, ...]]] = self.mailbox["messages"].get(self.current_folder, {})  # type: ignore[union-attr]
            out: dict[int, dict[bytes, object]] = {}
            for uid in uids:
                if uid not in msgs:
                    continue
                raw_bytes, flags = msgs[uid]
                row: dict[bytes, object] = {b"FLAGS": flags}
                if "RFC822" in parts:
                    row[b"RFC822"] = raw_bytes
                out[uid] = row
            return out

        def logout(self) -> None:
            return None

    def fake_imap_connect(**kwargs: object) -> FakeImapClient:
        addr = str(kwargs["email_addr"])
        return FakeImapClient(mailboxes_by_email[addr])

    monkeypatch.setattr(sync_mod, "_imap_connect_and_auth", fake_imap_connect)

    qq_acc = client.post(
        "/api/v1/accounts",
        json={
            "label": "我的QQ邮箱",
            "email": "qq_user@qq.com",
            "provider": "qq",
            "auth_type": "password",
            "secret": "qq_auth_code",
        },
    ).json()
    netease_acc = client.post(
        "/api/v1/accounts",
        json={
            "label": "我的163邮箱",
            "email": "netease_user@163.com",
            "provider": "163",
            "auth_type": "password",
            "secret": "163_auth_code",
        },
    ).json()

    qq_sync = client.post(f"/api/v1/accounts/{qq_acc['id']}/sync").json()
    assert qq_sync["ok"] is True
    assert qq_sync["fetched"] == 6
    assert "垃圾邮件 1" in qq_sync["message"]

    netease_sync = client.post(f"/api/v1/accounts/{netease_acc['id']}/sync").json()
    assert netease_sync["ok"] is True
    assert netease_sync["fetched"] == 5

    # 验证单邮箱视图下各文件夹严格只返回该邮箱自己的邮件
    qq_expected_subjects = {
        "inbox": ["QQ 收件箱星标邮件"],
        "starred": ["QQ 收件箱星标邮件"],
        "sent": ["QQ 已发送邮件"],
        "drafts": ["QQ 草稿箱邮件"],
        "archive": ["QQ 归档邮件"],
        "spam": ["QQ 专属垃圾邮件"],
        "trash": ["QQ 回收站邮件"],
    }
    for folder, expected in qq_expected_subjects.items():
        res = client.get("/api/v1/emails", params={"account_id": qq_acc["id"], "folder": folder})
        assert res.status_code == 200
        data = res.json()
        assert [it["subject"] for it in data["items"]] == expected
        assert all(it["account_id"] == qq_acc["id"] for it in data["items"])
        assert data["folder_counts"] == {
            "inbox": 1,
            "inbox_unread": 1,
            "unread": 1,
            "starred": 1,
            "sent": 1,
            "drafts": 1,
            "archive": 1,
            "spam": 1,
            "trash": 1,
        }

    # QQ 草稿无 From 头时应回退为自身账号名称与邮箱
    qq_draft = client.get("/api/v1/emails", params={"account_id": qq_acc["id"], "folder": "drafts"}).json()["items"][0]
    assert qq_draft["sender_name"] == "我的QQ邮箱"
    assert qq_draft["sender_email"] == "qq_user@qq.com"

    # 验证 163 垃圾邮件仅包含 163 账号的垃圾邮件，不包含 QQ 的垃圾邮件
    netease_spam = client.get(
        "/api/v1/emails",
        params={"account_id": netease_acc["id"], "folder": "spam"},
    ).json()
    assert [it["subject"] for it in netease_spam["items"]] == ["163 专属垃圾邮件"]
    assert netease_spam["folder_counts"]["archive"] == 0
    assert netease_spam["folder_counts"]["spam"] == 1

    # 验证全部聚合视图正确汇总两者
    agg_spam = client.get(
        "/api/v1/emails",
        params={
            "folder": "spam",
            "account_ids": f"{qq_acc['id']},{netease_acc['id']}",
        },
    ).json()
    assert sorted(it["subject"] for it in agg_spam["items"]) == ["163 专属垃圾邮件", "QQ 专属垃圾邮件"]
    assert agg_spam["folder_counts"]["spam"] == 2
    assert agg_spam["folder_counts"]["trash"] == 2
    assert agg_spam["folder_counts"]["sent"] == 2


def test_sync_account_incremental_flags_dedup_and_partial_folder_failure(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证增量不重拉 RFC822、标志刷新、本地 Sent 去重、\\All 归档回退、虚拟星标、附件防覆盖与单目录容错。"""
    import app.service.imap_sync_service as sync_mod
    from imapclient.response_types import Envelope
    from app.model.entities import Email

    monkeypatch.setattr(settings, "project_root", tmp_path)
    client.post("/api/v1/system/demo/clear")

    gmail_acc = client.post(
        "/api/v1/accounts",
        json={
            "label": "我的Gmail",
            "email": "gmail_user@gmail.com",
            "provider": "gmail",
            "auth_type": "password",
            "secret": "aaaa bbbb cccc dddd",
        },
    ).json()

    # 预先在本地发件箱写入一条 sent-* 本地发信记录，验证后续同步远程 Sent 时按 Message-ID 去重并升级 UID
    with SessionLocal() as db:
        db.add(
            Email(
                account_id=gmail_acc["id"],
                message_uid="sent-local-abc123",
                message_id="<local-sent-dup@gmail.com>",
                folder="sent",
                category="work",
                sender_name="我的Gmail",
                sender_email="gmail_user@gmail.com",
                subject="本地已发出邮件",
                snippet="hello",
                is_read=True,
                is_starred=False,
            )
        )
        db.commit()

    rfc822_fetch_calls: list[tuple[str, list[int]]] = []
    phase = {"step": 1, "broken_trash": True}

    inbox_msg_10 = _build_rfc822_email(
        sender="Alice <alice@example.com>",
        to="gmail_user@gmail.com",
        subject="收件箱带附件邮件",
        body="来自收件箱",
        message_id="<msg-inbox-10@example.com>",
        attachment=("report.txt", b"INBOX_ATTACHMENT_DATA"),
    )
    inbox_msg_11 = _build_rfc822_email(
        sender="Bob <bob@example.com>",
        to="gmail_user@gmail.com",
        subject="第二次同步新邮件",
        body="增量新邮件",
        message_id="<msg-inbox-11@example.com>",
    )
    sent_msg_20 = _build_rfc822_email(
        sender="我的Gmail <gmail_user@gmail.com>",
        to="client@example.com",
        subject="本地已发出邮件",
        body="hello",
        message_id="<local-sent-dup@gmail.com>",
    )
    spam_msg_10 = _build_rfc822_email(
        sender="Spam <spam@bad.invalid>",
        to="gmail_user@gmail.com",
        subject="同UID附件垃圾邮件",
        body="来自垃圾箱",
        message_id="<msg-spam-10@bad.invalid>",
        attachment=("report.txt", b"SPAM_ATTACHMENT_DATA"),
    )
    archived_msg_30 = _build_rfc822_email(
        sender="ArchiveSender <arch@example.com>",
        to="gmail_user@gmail.com",
        subject="仅在 All Mail 中的已归档邮件",
        body="归档正文",
        message_id="<msg-archived-30@example.com>",
    )

    class IncrementalFakeImap:
        def __init__(self) -> None:
            self.current_folder = "INBOX"

        def list_folders(self) -> list[tuple[object, object, object]]:
            return [
                ((b"\\HasNoChildren",), b"/", "INBOX"),
                ((b"\\Sent",), b"/", "[Gmail]/Sent Mail"),
                ((b"\\Junk",), b"/", "[Gmail]/Spam"),
                ((b"\\Trash",), b"/", "[Gmail]/Trash"),
                ((b"\\All",), b"/", "[Gmail]/All Mail"),
                ((b"\\Flagged",), b"/", "[Gmail]/Starred"),
            ]

        def select_folder(self, folder: str, readonly: bool = True) -> None:
            if folder == "[Gmail]/Trash" and phase["broken_trash"]:
                raise RuntimeError("READ-ONLY folder unavailable")
            self.current_folder = folder

        def search(self, _criteria: list[object]) -> list[int]:
            if self.current_folder == "INBOX":
                return [10] if phase["step"] == 1 else [10, 11]
            if self.current_folder == "[Gmail]/Sent Mail":
                return [20]
            if self.current_folder == "[Gmail]/Spam":
                return [10]
            if self.current_folder == "[Gmail]/All Mail":
                return [100, 101]
            if self.current_folder == "[Gmail]/Starred":
                return [200]
            return []

        def fetch(self, uids: list[int], parts: list[str]) -> dict[int, dict[bytes, object]]:
            if "RFC822" in parts:
                rfc822_fetch_calls.append((self.current_folder, list(uids)))

            if self.current_folder == "[Gmail]/Starred" and "ENVELOPE" in parts:
                env = Envelope(
                    date=None,
                    subject=b"starred",
                    from_=None,
                    sender=None,
                    reply_to=None,
                    to=None,
                    cc=None,
                    bcc=None,
                    in_reply_to=b"",
                    message_id=b"<msg-archived-30@example.com>",
                )
                return {200: {b"ENVELOPE": env}}

            if self.current_folder == "[Gmail]/All Mail" and "ENVELOPE" in parts:
                env_map = {
                    100: b"<msg-inbox-10@example.com>",
                    101: b"<msg-archived-30@example.com>",
                }
                return {
                    uid: {
                        b"ENVELOPE": Envelope(
                            date=None,
                            subject=b"all-mail",
                            from_=None,
                            sender=None,
                            reply_to=None,
                            to=None,
                            cc=None,
                            bcc=None,
                            in_reply_to=b"",
                            message_id=env_map[uid],
                        )
                    }
                    for uid in uids
                    if uid in env_map
                }

            data_map: dict[str, dict[int, tuple[bytes, tuple[bytes, ...]]]] = {
                "INBOX": {
                    10: (inbox_msg_10, () if phase["step"] == 1 else (b"\\Seen", b"\\Flagged")),
                    11: (inbox_msg_11, ()),
                },
                "[Gmail]/Sent Mail": {
                    20: (sent_msg_20, (b"\\Seen", b"\\Flagged")),
                },
                "[Gmail]/Spam": {
                    10: (spam_msg_10, ()),
                },
                "[Gmail]/All Mail": {
                    100: (inbox_msg_10, (b"\\Seen",)),  # 与 INBOX 重复，应跳过
                    101: (archived_msg_30, (b"\\Seen",)),  # 仅存在于 All Mail，应归入 archive
                },
            }
            folder_msgs = data_map.get(self.current_folder, {})
            out: dict[int, dict[bytes, object]] = {}
            for uid in uids:
                if uid not in folder_msgs:
                    continue
                raw_bytes, flags = folder_msgs[uid]
                row: dict[bytes, object] = {b"FLAGS": flags}
                if "RFC822" in parts:
                    row[b"RFC822"] = raw_bytes
                out[uid] = row
            return out

        def logout(self) -> None:
            return None

    monkeypatch.setattr(sync_mod, "_imap_connect_and_auth", lambda **_kw: IncrementalFakeImap())

    # 第一次同步（Trash 报错应被容错跳过，其余正常同步）
    sync1 = client.post(f"/api/v1/accounts/{gmail_acc['id']}/sync").json()
    assert sync1["ok"] is True
    # 新增：INBOX(10) + Spam(10) + Archive(101) = 3；Sent(20) 命中本地 sent-local-abc123 去重
    assert sync1["fetched"] == 3

    # 验证本地 Sent 去重：依然只有 1 封发件箱邮件，UID 已升级为 "20"，且同步了星标
    sent_items = client.get(
        "/api/v1/emails", params={"account_id": gmail_acc["id"], "folder": "sent"}
    ).json()["items"]
    assert len(sent_items) == 1
    assert sent_items[0]["is_starred"] is True
    with SessionLocal() as db:
        from sqlalchemy import select
        sent_row = db.scalar(select(Email).where(Email.id == sent_items[0]["id"]))
        assert sent_row is not None
        assert sent_row.message_uid == "20"

    # 验证 \All 归档回退去重 + 虚拟星标目录补充星标
    archive_items = client.get(
        "/api/v1/emails", params={"account_id": gmail_acc["id"], "folder": "archive"}
    ).json()["items"]
    assert [it["subject"] for it in archive_items] == ["仅在 All Mail 中的已归档邮件"]
    assert archive_items[0]["is_starred"] is True

    # 验证跨文件夹同 UID 10 附件未互相覆盖
    inbox_item = client.get(
        "/api/v1/emails", params={"account_id": gmail_acc["id"], "folder": "inbox"}
    ).json()["items"][0]
    spam_item = client.get(
        "/api/v1/emails", params={"account_id": gmail_acc["id"], "folder": "spam"}
    ).json()["items"][0]
    inbox_detail = client.get(f"/api/v1/emails/{inbox_item['id']}").json()
    spam_detail = client.get(f"/api/v1/emails/{spam_item['id']}").json()
    assert inbox_item["is_read"] is False
    assert inbox_item["is_starred"] is False
    inbox_dl = client.get(f"/api/v1/attachments/{inbox_detail['attachments'][0]['id']}/download")
    spam_dl = client.get(f"/api/v1/attachments/{spam_detail['attachments'][0]['id']}/download")
    assert inbox_dl.content == b"INBOX_ATTACHMENT_DATA"
    assert spam_dl.content == b"SPAM_ATTACHMENT_DATA"

    # 第二次同步：INBOX UID 10 仅更新 FLAGS，仅拉取新邮件 UID 11 的 RFC822
    rfc822_fetch_calls.clear()
    phase["step"] = 2
    sync2 = client.post(f"/api/v1/accounts/{gmail_acc['id']}/sync").json()
    assert sync2["ok"] is True
    assert sync2["fetched"] == 1
    assert rfc822_fetch_calls == [("INBOX", [11])]

    # 验证 UID 10 在本地已同步远程的已读与星标标志
    refreshed_inbox = client.get(f"/api/v1/emails/{inbox_item['id']}").json()
    assert refreshed_inbox["is_read"] is True
    assert refreshed_inbox["is_starred"] is True


def test_netease_994_fallback_auth_translations_and_all_providers_creation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证网易 163/126/yeah 994 SSL 回退、Outlook/163 中文错误翻译，以及全部 8 类邮箱均能成功创建。"""
    import app.service.imap_sync_service as sync_mod

    # 1. 验证 163 / 126 / yeah.net 候选端口包含 (994, True)
    assert build_smtp_transport_candidates(465, True, smtp_host="smtp.163.com", provider="163") == [
        (465, True),
        (994, True),
        (587, False),
    ]
    assert build_smtp_transport_candidates(465, True, smtp_host="smtp.yeah.net", provider="163") == [
        (465, True),
        (994, True),
        (587, False),
    ]

    # 2. 验证 yeah.net 自动识别到独立服务器主机
    yeah_detect = client.get("/api/v1/providers/detect", params={"email": "user@yeah.net"})
    assert yeah_detect.status_code == 200
    assert yeah_detect.json()["imap_host"] == "imap.yeah.net"
    assert yeah_detect.json()["smtp_host"] == "smtp.yeah.net"

    # 3. 验证 163 与 Outlook 原始英文报错翻译为清晰中文
    assert "客户端授权码" in format_mail_auth_error(RuntimeError("LOGIN Login error or password error"), "163")
    assert "OAuth2" in format_mail_auth_error(RuntimeError("b'Basic authentication is disabled.'"), "outlook")

    class FakeImapClient:
        def select_folder(self, _folder: str, readonly: bool = True) -> None:
            return None

        def logout(self) -> None:
            return None

    smtp_attempts: list[tuple[str, int, bool]] = []

    def fake_imap_connect(**_kwargs: object) -> FakeImapClient:
        return FakeImapClient()

    def fake_smtp_connect_and_auth(**kwargs: object) -> None:
        host = str(kwargs["smtp_host"])
        port = int(kwargs["smtp_port"])
        use_ssl = bool(kwargs["smtp_ssl"])
        smtp_attempts.append((host, port, use_ssl))
        if port == 465 and use_ssl:
            raise ssl.SSLEOFError(8, "[SSL: UNEXPECTED_EOF_WHILE_READING]")
        if host in ("smtp.163.com", "smtp.126.com", "smtp.yeah.net") and port == 994 and use_ssl:
            return None
        if port == 587 and not use_ssl:
            return None
        raise RuntimeError(f"Unsupported SMTP attempt {(host, port, use_ssl)}")

    monkeypatch.setattr(sync_mod, "_imap_connect_and_auth", fake_imap_connect)
    monkeypatch.setattr(sync_mod, "_smtp_connect_and_auth_sync", fake_smtp_connect_and_auth)

    client.post("/api/v1/system/demo/clear")

    # 4. 逐一验证全部 8 类邮箱渠道（含学校/自定义与 163/126 994 回退）创建成功
    providers_payloads = [
        {"label": "QQ", "email": "u_qq@qq.com", "provider": "qq", "secret": "qq_code", "smtp_port": 465, "smtp_ssl": True},
        {"label": "163", "email": "u_163@163.com", "provider": "163", "secret": "163_code", "smtp_port": 465, "smtp_ssl": True},
        {"label": "126", "email": "u_126@126.com", "provider": "126", "secret": "126_code", "smtp_port": 465, "smtp_ssl": True},
        {"label": "Gmail", "email": "u_gmail@gmail.com", "provider": "gmail", "secret": "abcd efgh ijkl mnop", "smtp_port": 587, "smtp_ssl": False},
        {"label": "iCloud", "email": "u_icloud@icloud.com", "provider": "icloud", "secret": "app-pass", "smtp_port": 587, "smtp_ssl": False},
        {
            "label": "学校邮箱",
            "email": "u_stu@pku.edu.cn",
            "provider": "school",
            "secret": "stu_pass",
            "imap_host": "mail.pku.edu.cn",
            "imap_port": 993,
            "imap_ssl": True,
            "smtp_host": "mail.pku.edu.cn",
            "smtp_port": 465,
            "smtp_ssl": True,
        },
        {
            "label": "企业自定义",
            "email": "u_corp@corp.example",
            "provider": "custom",
            "secret": "corp_pass",
            "imap_host": "imap.corp.example",
            "imap_port": 993,
            "imap_ssl": True,
            "smtp_host": "smtp.corp.example",
            "smtp_port": 587,
            "smtp_ssl": False,
        },
    ]

    created_by_provider: dict[str, dict[str, object]] = {}
    for item in providers_payloads:
        res = client.post(
            "/api/v1/accounts",
            json={**item, "auth_type": "password", "verify_connection": True},
        )
        assert res.status_code == 200, f"Failed creating {item['provider']}: {res.text}"
        created_by_provider[str(item["provider"])] = res.json()

    assert created_by_provider["163"]["smtp_port"] == 994
    assert created_by_provider["163"]["smtp_ssl"] is True
    assert created_by_provider["126"]["smtp_port"] == 994
    assert created_by_provider["126"]["smtp_ssl"] is True
    assert created_by_provider["qq"]["smtp_port"] == 587
    assert created_by_provider["qq"]["smtp_ssl"] is False
    assert ("smtp.163.com", 994, True) in smtp_attempts
    assert ("smtp.126.com", 994, True) in smtp_attempts


@pytest.mark.anyio
async def test_oauth_callback_resolves_outlook_preferred_username_and_replaces_demo_hosts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Outlook OAuth2 回调兼容 preferred_username，并在覆盖演示账号时同步修正 *.demo 主机。"""
    import httpx
    from app.service.oauth_service import oauth_service

    client.patch("/api/v1/settings", json={"oauth_microsoft_client_id": "ms-client-id-123"})

    class FakeResp:
        def __init__(self, status_code: int, data: dict[str, object]) -> None:
            self.status_code = status_code
            self._data = data

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError("HTTP error")

        def json(self) -> dict[str, object]:
            return self._data

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, _url: str, data: dict[str, str] | None = None) -> FakeResp:
            return FakeResp(200, {"access_token": "ms-access", "refresh_token": "ms-refresh", "expires_in": 3600})

        async def get(self, _url: str, headers: dict[str, str] | None = None) -> FakeResp:
            # 模拟 Microsoft OIDC 仅返回 preferred_username，匹配演示账号 demo@company.com
            return FakeResp(200, {"preferred_username": "demo@company.com"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with SessionLocal() as db:
        state, _auth_url, _opened = oauth_service.start_flow(
            db, provider="outlook", label="我的 Outlook", email_hint="", open_browser=False
        )
        ok, _msg, saved = await oauth_service.handle_callback(db, state=state, code="auth-code-123")
        assert ok is True
        assert saved is not None
        assert saved.email == "demo@company.com"
        assert saved.auth_type == "oauth2"
        assert saved.is_demo is False
        assert saved.imap_host == "outlook.office365.com"
        assert saved.smtp_host == "smtp.office365.com"
        assert saved.smtp_port == 587
        assert saved.smtp_ssl is False


def test_diagnostics_sanitization_and_bundle_export(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证诊断报告与诊断包导出接口能彻底脱敏路径、邮箱前缀与凭据，绝不泄露隐私数据。"""
    import io
    import json
    import zipfile
    from app.service.diagnostics_service import mask_email, sanitize_text

    assert mask_email("alice.wang@qq.com") == "a***@qq.com"
    assert mask_email("u@163.com") == "u***@163.com"

    fake_root = tmp_path / "repo_root"
    fake_home = Path(r"C:\Users\SecretTester")
    raw_text = (
        f"Failed at {fake_root}\\backend\\app\\main.py from C:\\Users\\SecretTester\\Desktop "
        "for user secret_user@163.com Bearer my_jwt_token_123 "
        "password=super_secret_pw client_secret='oauth_sec_999' "
        "token=gAAAAABn1234567890abcdefghijklmnopqrstuvwxyz1234567890 on WORKSTATION-PC"
    )
    sanitized = sanitize_text(
        raw_text,
        project_root=fake_root,
        home_dir=fake_home,
        hostname="WORKSTATION-PC",
    )
    assert "SecretTester" not in sanitized
    assert str(fake_root) not in sanitized
    assert "secret_user@" not in sanitized
    assert "s***@163.com" in sanitized
    assert "my_jwt_token_123" not in sanitized
    assert "super_secret_pw" not in sanitized
    assert "oauth_sec_999" not in sanitized
    assert "gAAAAABn" not in sanitized
    assert "WORKSTATION-PC" not in sanitized
    assert "<PROJECT_ROOT>" in sanitized
    assert "<USER_HOME>" in sanitized
    assert "<HOST>" in sanitized

    # 模拟存在测试账号、OAuth 配置与包含敏感字符串的日志
    client.patch(
        "/api/v1/settings",
        json={
            "oauth_google_client_id": "secret-google-client-id.apps.googleusercontent.com",
            "oauth_google_client_secret": "super-secret-google-client-secret",
        },
    )
    with SessionLocal() as db:
        acc = Account(
            label="私人主邮箱",
            email="private.owner@163.com",
            provider="163",
            auth_type="password",
            encrypted_secret="gAAAAABnSecretCipherTextValueShouldNeverLeak1234567890",
            imap_host="imap.163.com",
            imap_port=993,
            imap_ssl=True,
            smtp_host="smtp.163.com",
            smtp_port=465,
            smtp_ssl=True,
            sync_status="error",
            last_error="Auth fail for private.owner@163.com token=secret_abc_123",
            is_demo=False,
        )
        account_repo.create(db, acc)
        account_repo.add_sync_log(
            db,
            account_id=acc.id,
            status="error",
            fetched_count=0,
            message=r"连接 C:\Users\Alice\mail 失败: password=my_auth_code_99",
        )

    backend_log = tmp_path / "backend.log"
    launcher_log = tmp_path / "launcher.log"
    backend_log.write_text(
        "2026-11-23 15:00:00 | ERROR | app.sync | login private.owner@163.com code=xyz987\n",
        encoding="utf-8",
    )
    launcher_log.write_text(
        "2026-11-23 15:00:01 | INFO | launcher | started from /Users/alice/MailHub\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(type(settings), "backend_log_path", property(lambda _self: backend_log))
    monkeypatch.setattr(type(settings), "launcher_log_path", property(lambda _self: launcher_log))

    health_resp = client.get("/api/v1/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["version"] == settings.app_version

    diag_resp = client.get("/api/v1/system/diagnostics")
    assert diag_resp.status_code == 200
    diag = diag_resp.json()
    assert diag["event_id"].startswith("MH-")
    assert diag["app_version"] == settings.app_version
    assert diag["settings_summary"]["oauth_google_configured"] is True
    assert diag["settings_summary"]["oauth_microsoft_configured"] is False

    report_md = diag["markdown_report"]
    assert "private.owner@" not in report_md
    assert "p***@163.com" in report_md
    assert "secret-google-client-id" not in report_md
    assert "super-secret-google-client-secret" not in report_md
    assert "secret_abc_123" not in report_md
    assert "my_auth_code_99" not in report_md
    assert "xyz987" not in report_md
    assert "<USER_HOME>" in report_md

    bundle_resp = client.get(f"/api/v1/system/diagnostics/bundle?event_id={diag['event_id']}")
    assert bundle_resp.status_code == 200
    assert bundle_resp.headers["content-type"] == "application/zip"
    assert f"mailhub-diagnostics-{diag['event_id']}.zip" in bundle_resp.headers.get("content-disposition", "")

    # 恶意/非法 event_id 参数不应渗透到文件名或报告中
    bad_bundle_resp = client.get("/api/v1/system/diagnostics/bundle?event_id=../../evil")
    assert bad_bundle_resp.status_code == 200
    assert "evil" not in bad_bundle_resp.headers.get("content-disposition", "")

    with zipfile.ZipFile(io.BytesIO(bundle_resp.content), "r") as zf:
        names = set(zf.namelist())
        assert {
            "README-PRIVACY.txt",
            "diagnostic-report.md",
            "diagnostics.json",
            "backend.log.txt",
            "launcher.log.txt",
        }.issubset(names)
        assert "mailhub.db" not in names
        assert ".secret.key" not in names

        parsed_json = json.loads(zf.read("diagnostics.json").decode("utf-8"))
        assert parsed_json["event_id"] == diag["event_id"]
        for member in names:
            content = zf.read(member).decode("utf-8")
            assert "private.owner@" not in content
            assert "my_auth_code_99" not in content
            assert "super-secret-google-client-secret" not in content



