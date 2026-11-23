import json
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.model.entities import AppSetting


DEFAULT_SETTINGS: dict[str, Any] = {
    "theme_mode": "light",
    "show_mascots": True,
    "mascot_opacity": 0.96,
    "custom_mascot_left": None,
    "custom_mascot_right": None,
    "show_particles": True,
    "motion_level": "full",
    "font_size": "md",
    "list_density": "comfortable",
    "default_account_id": None,
    "smart_send_from": True,
    "undo_send_seconds": 5,
    "sync_interval_minutes": 5,
    "sync_days": 30,
    "desktop_notifications": True,
    "block_remote_images": False,
    "oauth_google_client_id": "",
    "oauth_google_client_secret": "",
    "oauth_microsoft_client_id": "",
}


class SettingRepository:
    """应用全局配置仓储层，基于 app_settings 键值表持久化。"""

    def get_all(self, db: Session) -> dict[str, Any]:
        """读取完整配置字典，缺失项自动填充默认值。"""
        merged = dict(DEFAULT_SETTINGS)
        rows = db.scalars(select(AppSetting)).all()
        for row in rows:
            if row.key in merged:
                try:
                    merged[row.key] = json.loads(row.value_json)
                except json.JSONDecodeError:
                    pass
        return merged

    def update_many(self, db: Session, updates: dict[str, Any]) -> dict[str, Any]:
        """批量写入或更新配置键值对，返回最新完整配置。"""
        for key, value in updates.items():
            if key not in DEFAULT_SETTINGS:
                continue
            existing = db.get(AppSetting, key)
            encoded = json.dumps(value, ensure_ascii=False)
            if existing:
                existing.value_json = encoded
            else:
                db.add(AppSetting(key=key, value_json=encoded))
        db.commit()
        return self.get_all(db)


setting_repo = SettingRepository()
