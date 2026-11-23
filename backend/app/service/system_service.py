import logging
from pathlib import Path
import shutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.model.entities import Account, Attachment, ClassificationRule, Email
from app.repository.account_repo import account_repo
from app.repository.email_repo import email_repo
from app.repository.rule_repo import rule_repo
from app.repository.setting_repo import setting_repo
from app.schema.schemas import (
    AppSettingsOut,
    AppSettingsPatch,
    ClassificationRuleCreate,
    ClassificationRuleOut,
    ClassificationRuleUpdate,
    StorageInfoOut,
    SyncLogOut,
)
from app.service.demo_seed_service import demo_seed_service

logger = logging.getLogger(__name__)


class SystemService:
    """设置、规则、立绘上传、附件下载与本地存储管理服务层。"""

    def get_settings(self, db: Session) -> AppSettingsOut:
        """读取全局设置。"""
        data = setting_repo.get_all(db)
        return AppSettingsOut(**data)

    def patch_settings(self, db: Session, payload: AppSettingsPatch) -> AppSettingsOut:
        """局部更新全局设置。"""
        updates = payload.model_dump(exclude_unset=True)
        merged = setting_repo.update_many(db, updates)
        return AppSettingsOut(**merged)

    def save_custom_mascot(self, db: Session, side: str, filename: str, content: bytes) -> AppSettingsOut:
        """保存用户上传的自定义角色立绘并更新设置中的访问 URL。"""
        if side not in ("left", "right"):
            raise ValueError("立绘方位仅支持 left 或 right。")
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("单张立绘文件不能超过 8 MB。")

        ext = Path(filename).suffix.lower()
        if ext not in (".png", ".webp", ".jpg", ".jpeg"):
            raise ValueError("立绘文件仅支持 PNG、WEBP 或 JPG 格式。")

        target_name = f"custom_{side}{ext}"
        # 清理旧格式文件
        for old in settings.mascots_dir.glob(f"custom_{side}.*"):
            old.unlink(missing_ok=True)

        target_path = settings.mascots_dir / target_name
        target_path.write_bytes(content)

        url = f"/api/v1/system/mascots/{target_name}?t={int(target_path.stat().st_mtime)}"
        key = "custom_mascot_left" if side == "left" else "custom_mascot_right"
        merged = setting_repo.update_many(db, {key: url})
        return AppSettingsOut(**merged)

    def reset_custom_mascot(self, db: Session, side: str) -> AppSettingsOut:
        """恢复默认内置立绘。"""
        if side not in ("left", "right"):
            raise ValueError("立绘方位仅支持 left 或 right。")
        for old in settings.mascots_dir.glob(f"custom_{side}.*"):
            old.unlink(missing_ok=True)
        key = "custom_mascot_left" if side == "left" else "custom_mascot_right"
        merged = setting_repo.update_many(db, {key: None})
        return AppSettingsOut(**merged)

    def get_mascot_file_path(self, filename: str) -> Path:
        """安全解析自定义立绘路径，防止路径穿越。"""
        safe_name = Path(filename).name
        target = (settings.mascots_dir / safe_name).resolve()
        if target.parent != settings.mascots_dir.resolve() or not target.exists():
            raise FileNotFoundError("自定义立绘不存在。")
        return target

    def list_rules(self, db: Session) -> list[ClassificationRuleOut]:
        """列出全部智能分类规则。"""
        rules = rule_repo.list_all(db)
        return [
            ClassificationRuleOut(
                id=r.id,
                name=r.name,
                field=r.field,
                pattern=r.pattern,
                target_category=r.target_category,
                is_enabled=r.is_enabled,
            )
            for r in rules
        ]

    def create_rule(self, db: Session, payload: ClassificationRuleCreate) -> ClassificationRuleOut:
        """新增分类规则。"""
        rule = ClassificationRule(
            name=payload.name.strip(),
            field=payload.field,
            pattern=payload.pattern.strip(),
            target_category=payload.target_category,
            is_enabled=payload.is_enabled,
        )
        saved = rule_repo.create(db, rule)
        return ClassificationRuleOut(
            id=saved.id,
            name=saved.name,
            field=saved.field,
            pattern=saved.pattern,
            target_category=saved.target_category,
            is_enabled=saved.is_enabled,
        )

    def update_rule(self, db: Session, rule_id: int, payload: ClassificationRuleUpdate) -> ClassificationRuleOut:
        """修改分类规则。"""
        rule = rule_repo.get_by_id(db, rule_id)
        if not rule:
            raise ValueError("分类规则不存在。")
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(rule, k, v.strip() if isinstance(v, str) else v)
        saved = rule_repo.save(db, rule)
        return ClassificationRuleOut(
            id=saved.id,
            name=saved.name,
            field=saved.field,
            pattern=saved.pattern,
            target_category=saved.target_category,
            is_enabled=saved.is_enabled,
        )

    def delete_rule(self, db: Session, rule_id: int) -> None:
        """删除分类规则。"""
        rule = rule_repo.get_by_id(db, rule_id)
        if not rule:
            raise ValueError("分类规则不存在。")
        rule_repo.delete(db, rule)

    def get_attachment_download_info(self, db: Session, attachment_id: int) -> tuple[str, str, Path | None, bytes | None]:
        """获取附件文件下载信息；演示附件直接返回内置示例内容。"""
        att = email_repo.get_attachment(db, attachment_id)
        if not att:
            raise FileNotFoundError("附件不存在。")
        if att.local_path:
            file_path = Path(att.local_path)
            if file_path.exists():
                return att.filename, att.content_type, file_path, None

        # 演示附件提供友好可读的示例文件下载
        demo_content = (
            "# MailHub Issue 摘要报告（演示附件）\n\n"
            "- #124 功能建议：增加多账号切换支持\n"
            "- #123 登录页动画优化\n"
            "- #122 修复：邮件同步偶尔失败\n"
        ).encode("utf-8")
        return att.filename, att.content_type, None, demo_content

    def get_storage_info(self, db: Session) -> StorageInfoOut:
        """统计数据库与附件缓存空间占用。"""
        db_size = settings.db_path.stat().st_size if settings.db_path.exists() else 0
        att_bytes = 0
        if settings.attachments_dir.exists():
            for p in settings.attachments_dir.rglob("*"):
                if p.is_file():
                    att_bytes += p.stat().st_size

        att_count = int(db.scalar(select(func.count(Attachment.id))) or 0)
        emails_count = int(db.scalar(select(func.count(Email.id))) or 0)
        accounts_count = int(db.scalar(select(func.count(Account.id))) or 0)
        demo_count = int(db.scalar(select(func.count(Account.id)).where(Account.is_demo.is_(True))) or 0)
        return StorageInfoOut(
            db_size_bytes=db_size,
            attachments_size_bytes=att_bytes,
            attachments_count=att_count,
            emails_count=emails_count,
            accounts_count=accounts_count,
            demo_accounts_count=demo_count,
        )

    def get_db_backup_path(self) -> Path:
        """返回 SQLite 主数据库备份路径。"""
        if not settings.db_path.exists():
            raise FileNotFoundError("数据库文件尚未生成")
        return settings.db_path

    def clear_attachment_cache(self, db: Session) -> int:
        """清理磁盘附件缓存文件并返回释放字节数。"""
        freed = 0
        if settings.attachments_dir.exists():
            for p in settings.attachments_dir.rglob("*"):
                if p.is_file():
                    freed += p.stat().st_size
            shutil.rmtree(settings.attachments_dir, ignore_errors=True)
            settings.attachments_dir.mkdir(parents=True, exist_ok=True)

        # 清空附件记录中的本地路径避免死链
        for att in db.scalars(select(Attachment)).all():
            att.local_path = ""
        db.commit()
        logger.info("Cleared attachment cache (%d bytes freed).", freed)
        return freed

    def list_notifications(self, db: Session) -> list[SyncLogOut]:
        """获取同步日志与系统提醒列表。"""
        logs = account_repo.list_sync_logs(db, limit=30)
        return [
            SyncLogOut(
                id=log.id,
                account_id=log.account_id,
                status=log.status,
                fetched_count=log.fetched_count,
                message=log.message,
                created_at=log.created_at,
            )
            for log in logs
        ]

    def reset_demo_data(self, db: Session) -> None:
        """重置内置演示邮箱与示例邮件。"""
        demo_seed_service.seed_if_empty(db, force=True)

    def clear_demo_data(self, db: Session) -> int:
        """清空全部演示邮箱及演示邮件（保留用户真实绑定的邮箱）。"""
        return demo_seed_service.clear_demo_data(db)


system_service = SystemService()
