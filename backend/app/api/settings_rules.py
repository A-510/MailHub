from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schema.schemas import (
    AppSettingsOut,
    AppSettingsPatch,
    ClassificationRuleCreate,
    ClassificationRuleOut,
    ClassificationRuleUpdate,
    StorageInfoOut,
    SyncLogOut,
)
from app.service.system_service import system_service

router = APIRouter(tags=["settings-and-system"])


@router.get("/settings", response_model=AppSettingsOut)
def get_settings(db: Session = Depends(get_db)) -> AppSettingsOut:
    """获取当前完整应用设置。"""
    return system_service.get_settings(db)


@router.patch("/settings", response_model=AppSettingsOut)
def patch_settings(payload: AppSettingsPatch, db: Session = Depends(get_db)) -> AppSettingsOut:
    """更新应用设置并持久至 SQLite。"""
    return system_service.patch_settings(db, payload)


@router.post("/settings/mascot/{side}", response_model=AppSettingsOut)
async def upload_mascot(
    side: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AppSettingsOut:
    """上传自定义左右角色立绘 PNG/JPG/WEBP。"""
    content = await file.read()
    try:
        return system_service.save_custom_mascot(db, side, file.filename or "mascot.png", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/settings/mascot/{side}", response_model=AppSettingsOut)
def reset_mascot(side: str, db: Session = Depends(get_db)) -> AppSettingsOut:
    """恢复默认立绘。"""
    try:
        return system_service.reset_custom_mascot(db, side)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/system/mascots/{filename}")
def serve_mascot(filename: str) -> FileResponse:
    """读取用户自定义立绘文件。"""
    try:
        file_path = system_service.get_mascot_file_path(filename)
        return FileResponse(path=str(file_path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/rules", response_model=list[ClassificationRuleOut])
def list_rules(db: Session = Depends(get_db)) -> list[ClassificationRuleOut]:
    """获取智能分类规则列表。"""
    return system_service.list_rules(db)


@router.post("/rules", response_model=ClassificationRuleOut)
def create_rule(payload: ClassificationRuleCreate, db: Session = Depends(get_db)) -> ClassificationRuleOut:
    """创建分类规则。"""
    return system_service.create_rule(db, payload)


@router.patch("/rules/{rule_id}", response_model=ClassificationRuleOut)
def update_rule(
    rule_id: int,
    payload: ClassificationRuleUpdate,
    db: Session = Depends(get_db),
) -> ClassificationRuleOut:
    """更新分类规则。"""
    try:
        return system_service.update_rule(db, rule_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    """删除分类规则。"""
    try:
        system_service.delete_rule(db, rule_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/system/storage", response_model=StorageInfoOut)
def get_storage_info(db: Session = Depends(get_db)) -> StorageInfoOut:
    """查看数据库、附件与演示账号存储统计。"""
    return system_service.get_storage_info(db)


@router.post("/system/clear-cache")
def clear_cache(db: Session = Depends(get_db)) -> dict[str, int]:
    """清理本地附件缓存。"""
    freed = system_service.clear_attachment_cache(db)
    return {"freed_bytes": freed}


@router.get("/system/backup-db")
def backup_db() -> FileResponse:
    """导出 SQLite 数据库备份文件。"""
    try:
        db_path = system_service.get_db_backup_path()
        return FileResponse(
            path=str(db_path),
            filename="mailhub-backup.db",
            media_type="application/octet-stream",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/system/demo/reset")
def reset_demo(db: Session = Depends(get_db)) -> dict[str, bool]:
    """重置内置演示邮箱与示例邮件。"""
    system_service.reset_demo_data(db)
    return {"ok": True}


@router.post("/system/demo/clear")
def clear_demo(db: Session = Depends(get_db)) -> dict[str, int]:
    """一键清除全部演示数据。"""
    removed = system_service.clear_demo_data(db)
    return {"removed_accounts": removed}


@router.get("/notifications", response_model=list[SyncLogOut])
def get_notifications(db: Session = Depends(get_db)) -> list[SyncLogOut]:
    """读取同步与系统提醒日志。"""
    return system_service.list_notifications(db)
