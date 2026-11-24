from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import platform
import re
import secrets
import socket
import sys
import zipfile

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repository.account_repo import account_repo
from app.repository.setting_repo import setting_repo
from app.schema.schemas import (
    DiagnosticsAccountSummary,
    DiagnosticsOut,
    DiagnosticsSettingsSummary,
    DiagnosticsSyncLogSummary,
)
from app.service.system_service import system_service

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
FERNET_TOKEN_PATTERN = re.compile(r"\bgAAAA[A-Za-z0-9_-]{20,}={0,2}\b")
AUTH_HEADER_PATTERN = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*")
SENSITIVE_KV_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|client_secret|access_token|refresh_token|auth_code|authorization|api_key|code)\b"
    r"(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,&;}\]]+)"
)
WIN_USER_PATH_PATTERN = re.compile(r"(?i)[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s:;\"']+")
POSIX_USER_PATH_PATTERN = re.compile(r"/(?:Users|home)/[^/\s:;\"']+")


def mask_email(email_addr: str) -> str:
    """将邮箱地址脱敏为保留首字符与域名（如 a***@qq.com），保护个人身份隐私。"""
    cleaned = email_addr.strip()
    if "@" not in cleaned:
        return "***"
    local, domain = cleaned.rsplit("@", 1)
    prefix = local[0] if local else "*"
    return f"{prefix}***@{domain}"


def sanitize_text(
    text: str,
    *,
    project_root: Path | None = None,
    home_dir: Path | None = None,
    hostname: str | None = None,
) -> str:
    """
    对日志、报错文本与诊断字段执行尽力脱敏：
    遮罩绝对路径、本机用户名、主机名、邮箱前缀、OAuth/Fernet 凭据与敏感参数。
    """
    if not text:
        return ""

    result = text

    root = project_root or settings.project_root
    home = home_dir or Path.home()
    host = hostname if hostname is not None else socket.gethostname()

    # 1. 先替换明确的项目根目录与当前用户主目录（兼容正反斜杠）
    for base_path, token in ((root, "<PROJECT_ROOT>"), (home, "<USER_HOME>")):
        raw_str = str(base_path)
        variants = {
            raw_str,
            raw_str.replace("\\", "/"),
            raw_str.replace("/", "\\"),
        }
        for variant in sorted(variants, key=len, reverse=True):
            if variant:
                result = re.sub(re.escape(variant), token, result, flags=re.IGNORECASE)

    # 2. 泛化残留的用户目录路径（Windows/macOS/Linux）
    result = WIN_USER_PATH_PATTERN.sub("<USER_HOME>", result)
    result = POSIX_USER_PATH_PATTERN.sub("<USER_HOME>", result)

    # 3. 脱敏 Fernet 密文、Authorization 请求头及敏感键值对
    result = FERNET_TOKEN_PATTERN.sub("[REDACTED_FERNET]", result)
    result = AUTH_HEADER_PATTERN.sub(lambda m: f"{m.group(1)} [REDACTED]", result)
    result = SENSITIVE_KV_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", result)

    # 4. 邮箱地址脱敏（保留服务商域名以便排查协议差异）
    result = EMAIL_PATTERN.sub(
        lambda m: f"{m.group(1)[0]}***@{m.group(2)}",
        result,
    )

    # 5. 替换非通用本地主机名
    if host and len(host) >= 3 and host.lower() not in {"localhost", "127.0.0.1"}:
        result = re.sub(
            rf"(?<![A-Za-z0-9_.-]){re.escape(host)}(?![A-Za-z0-9_.-])",
            "<HOST>",
            result,
            flags=re.IGNORECASE,
        )

    return result


def _read_git_commit_short(project_root: Path) -> str | None:
    """安全读取本地 Git HEAD 短提交哈希，不依赖外部 git 命令。"""
    head_file = project_root / ".git" / "HEAD"
    if not head_file.is_file():
        return None
    try:
        head_content = head_file.read_text(encoding="utf-8", errors="replace").strip()
        if head_content.startswith("ref: "):
            ref_rel = head_content[5:].strip()
            ref_file = project_root / ".git" / ref_rel
            if ref_file.is_file():
                sha = ref_file.read_text(encoding="utf-8", errors="replace").strip()
                return sha[:7] if sha else None
            packed_refs = project_root / ".git" / "packed-refs"
            if packed_refs.is_file():
                for line in packed_refs.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.startswith("#") and line.endswith(f" {ref_rel}"):
                        return line.split(" ", 1)[0][:7]
            return None
        return head_content[:7] if head_content else None
    except OSError:
        return None


def _read_sanitized_log_tail(log_path: Path, max_lines: int) -> list[str]:
    """读取日志文件末尾若干行并逐行脱敏。"""
    if not log_path.is_file():
        return []
    try:
        raw_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    tail = [line for line in raw_lines[-max_lines:] if line.strip()]
    return [sanitize_text(line) for line in tail]


def _format_bytes_human(num_bytes: int) -> str:
    """将字节数格式化为易读体积字符串。"""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


class DiagnosticsService:
    """面向 Issue 精准排查的应用运行态采集、脱敏报告与诊断包导出服务。"""

    _EVENT_ID_RE = re.compile(r"^MH-\d{8}-[A-F0-9]{6}$")

    def _resolve_event_id(self, event_id: str | None) -> str:
        """校验前端传入的 Event ID，若未提供或格式不合法则生成新的诊断编号。"""
        if event_id and self._EVENT_ID_RE.match(event_id.strip()):
            return event_id.strip()
        now = datetime.now(timezone.utc)
        return f"MH-{now.strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

    def collect_diagnostics(self, db: Session, event_id: str | None = None) -> DiagnosticsOut:
        """采集当前实例脱敏运行态信息并生成可粘贴的 Markdown 诊断报告。"""
        now = datetime.now(timezone.utc)
        resolved_event_id = self._resolve_event_id(event_id)

        storage = system_service.get_storage_info(db)
        raw_settings = setting_repo.get_all(db)
        accounts = account_repo.list_all(db)
        sync_logs = account_repo.list_sync_logs(db, limit=20)

        if settings.secret_key:
            secret_mode = "env"
        elif settings.secret_key_file.is_file():
            secret_mode = "file"
        else:
            secret_mode = "missing"

        settings_summary = DiagnosticsSettingsSummary(
            theme_mode=str(raw_settings.get("theme_mode", "light")),
            motion_level=str(raw_settings.get("motion_level", "full")),
            sync_interval_minutes=int(raw_settings.get("sync_interval_minutes", 5)),
            sync_days=int(raw_settings.get("sync_days", 30)),
            realtime_push=bool(raw_settings.get("realtime_push", True)),
            undo_send_seconds=int(raw_settings.get("undo_send_seconds", 5)),
            block_remote_images=bool(raw_settings.get("block_remote_images", False)),
            oauth_google_configured=bool(str(raw_settings.get("oauth_google_client_id", "")).strip()),
            oauth_microsoft_configured=bool(str(raw_settings.get("oauth_microsoft_client_id", "")).strip()),
        )

        account_summaries = [
            DiagnosticsAccountSummary(
                id=acc.id,
                provider=acc.provider,
                auth_type=acc.auth_type,
                masked_email=mask_email(acc.email),
                imap_host=acc.imap_host,
                imap_port=acc.imap_port,
                imap_ssl=acc.imap_ssl,
                smtp_host=acc.smtp_host,
                smtp_port=acc.smtp_port,
                smtp_ssl=acc.smtp_ssl,
                is_enabled=acc.is_enabled,
                is_demo=acc.is_demo,
                sync_status=acc.sync_status,
                last_synced_at=acc.last_synced_at,
                last_error=sanitize_text(acc.last_error) if acc.last_error else None,
            )
            for acc in accounts
        ]

        sync_log_summaries = [
            DiagnosticsSyncLogSummary(
                status=item.status,
                fetched_count=item.fetched_count,
                message=sanitize_text(item.message),
                created_at=item.created_at,
            )
            for item in sync_logs
        ]

        backend_lines = _read_sanitized_log_tail(settings.backend_log_path, max_lines=60)
        launcher_lines = _read_sanitized_log_tail(settings.launcher_log_path, max_lines=60)

        git_commit = _read_git_commit_short(settings.project_root)
        frontend_dist_ready = (settings.frontend_dist_dir / "index.html").is_file()
        os_info = f"{platform.system()} {platform.release()} ({platform.version()})"
        python_version = platform.python_version()
        arch = platform.machine() or "unknown"

        markdown_report = self._build_markdown_report(
            event_id=resolved_event_id,
            generated_at=now,
            git_commit=git_commit,
            os_info=os_info,
            python_version=python_version,
            arch=arch,
            frontend_dist_ready=frontend_dist_ready,
            secret_mode=secret_mode,
            storage=storage,
            settings_summary=settings_summary,
            accounts=account_summaries,
            sync_logs=sync_log_summaries,
            backend_lines=backend_lines,
            launcher_lines=launcher_lines,
        )

        return DiagnosticsOut(
            event_id=resolved_event_id,
            generated_at=now,
            app_name=settings.app_name,
            app_version=settings.app_version,
            git_commit=git_commit,
            os_info=os_info,
            python_version=python_version,
            arch=arch,
            host=settings.host,
            port=settings.port,
            frontend_dist_ready=frontend_dist_ready,
            secret_key_mode=secret_mode,  # type: ignore[arg-type]
            storage=storage,
            settings_summary=settings_summary,
            accounts=account_summaries,
            recent_sync_logs=sync_log_summaries,
            backend_log_lines=backend_lines,
            launcher_log_lines=launcher_lines,
            markdown_report=markdown_report,
        )

    def _build_markdown_report(
        self,
        *,
        event_id: str,
        generated_at: datetime,
        git_commit: str | None,
        os_info: str,
        python_version: str,
        arch: str,
        frontend_dist_ready: bool,
        secret_mode: str,
        storage: object,
        settings_summary: DiagnosticsSettingsSummary,
        accounts: list[DiagnosticsAccountSummary],
        sync_logs: list[DiagnosticsSyncLogSummary],
        backend_lines: list[str],
        launcher_lines: list[str],
    ) -> str:
        """构造适合直接粘贴到 GitHub Issue 正文的脱敏 Markdown 报告。"""
        version_str = f"v{settings.app_version}" + (f" ({git_commit})" if git_commit else "")
        lines: list[str] = [
            f"### MailHub 脱敏诊断报告（`{event_id}`）",
            "",
            f"- **生成时间 (UTC)**: `{generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}`",
            f"- **应用版本**: `{version_str}`",
            f"- **操作系统**: `{os_info}` (`{arch}`)",
            f"- **Python 运行时**: `{python_version}`",
            f"- **本地服务地址**: `{settings.host}:{settings.port}` · 前端静态包就绪: `{'是' if frontend_dist_ready else '否'}`",
            f"- **主密钥模式**: `{secret_mode}`",
            (
                f"- **存储概况**: 数据库 `{_format_bytes_human(storage.db_size_bytes)}`"  # type: ignore[attr-defined]
                f" · 附件缓存 `{_format_bytes_human(storage.attachments_size_bytes)}`"  # type: ignore[attr-defined]
                f" · 邮件 `{storage.emails_count}` 封 · 账号 `{storage.accounts_count}` 个（演示 `{storage.demo_accounts_count}`）"  # type: ignore[attr-defined]
            ),
            (
                f"- **关键设置**: 主题=`{settings_summary.theme_mode}`, 动效=`{settings_summary.motion_level}`, "
                f"同步间隔=`{settings_summary.sync_interval_minutes}m`, 拉取范围=`{settings_summary.sync_days}d`, "
                f"实时推送=`{settings_summary.realtime_push}`, "
                f"外链拦截=`{settings_summary.block_remote_images}`, "
                f"OAuth2(Google=`{settings_summary.oauth_google_configured}`, Microsoft=`{settings_summary.oauth_microsoft_configured}`)"
            ),
            "",
            "#### 邮箱渠道状态（已脱敏）",
        ]

        if not accounts:
            lines.append("- 暂无已配置账号")
        else:
            for acc in accounts:
                tag = "演示" if acc.is_demo else acc.auth_type
                err_part = f" | 最近错误: `{acc.last_error}`" if acc.last_error else ""
                lines.append(
                    f"- `#{acc.id}` [{acc.provider}/{tag}] `{acc.masked_email}` "
                    f"IMAP=`{acc.imap_host}:{acc.imap_port}`(SSL={acc.imap_ssl}) "
                    f"SMTP=`{acc.smtp_host}:{acc.smtp_port}`(SSL={acc.smtp_ssl}) "
                    f"状态=`{acc.sync_status}`{err_part}"
                )

        if sync_logs:
            lines.extend([
                "",
                "<details>",
                f"<summary>最近同步记录（{len(sync_logs)} 条，已脱敏）</summary>",
                "",
                "```text",
            ])
            for log in sync_logs[:15]:
                ts = log.created_at.strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"[{ts}] [{log.status}] (+{log.fetched_count}) {log.message}")
            lines.extend(["```", "</details>"])

        if backend_lines:
            lines.extend([
                "",
                "<details>",
                f"<summary>后端最近运行日志（{len(backend_lines)} 行，已脱敏）</summary>",
                "",
                "```text",
                *backend_lines[-40:],
                "```",
                "</details>",
            ])

        if launcher_lines:
            lines.extend([
                "",
                "<details>",
                f"<summary>启动器最近运行日志（{len(launcher_lines)} 行，已脱敏）</summary>",
                "",
                "```text",
                *launcher_lines[-40:],
                "```",
                "</details>",
            ])

        return "\n".join(lines)

    def build_diagnostic_bundle_zip(self, db: Session, event_id: str | None = None) -> tuple[str, bytes]:
        """构建脱敏后的可下载诊断压缩包（绝不包含数据库、密钥文件与邮件正文）。"""
        diag = self.collect_diagnostics(db, event_id=event_id)

        backend_full = _read_sanitized_log_tail(settings.backend_log_path, max_lines=300)
        launcher_full = _read_sanitized_log_tail(settings.launcher_log_path, max_lines=300)

        payload_dict = diag.model_dump(mode="json", exclude={"markdown_report"})
        privacy_readme = (
            "MailHub 脱敏诊断包说明\n"
            "========================\n"
            f"Event ID: {diag.event_id}\n"
            f"Platform: {sys.platform}\n\n"
            "本压缩包仅包含运行环境元数据、账号协议参数摘要与脱敏后的最近日志，\n"
            "不包含 mailhub.db、.secret.key、授权码/OAuth 令牌、邮件正文或附件内容。\n"
            "在上传至公开 GitHub Issue 前，请再次打开检查其中的文件名、错误信息或日志内容，\n"
            "确保无不应公开的私密信息。\n"
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README-PRIVACY.txt", privacy_readme)
            zf.writestr("diagnostic-report.md", diag.markdown_report)
            zf.writestr(
                "diagnostics.json",
                json.dumps(payload_dict, ensure_ascii=False, indent=2),
            )
            zf.writestr(
                "backend.log.txt",
                "\n".join(backend_full) if backend_full else "(暂无 backend.log 日志文件)",
            )
            zf.writestr(
                "launcher.log.txt",
                "\n".join(launcher_full) if launcher_full else "(暂无 launcher.log 日志文件)",
            )

        filename = f"mailhub-diagnostics-{diag.event_id}.zip"
        logger.info("Generated sanitized diagnostic bundle %s", filename)
        return filename, buf.getvalue()


diagnostics_service = DiagnosticsService()
