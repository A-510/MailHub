from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schema.schemas import (
    AccountCreate,
    AccountOut,
    AccountReorderRequest,
    AccountTestRequest,
    AccountTestResult,
    AccountUpdate,
    ProviderPresetOut,
)
from app.service.account_service import account_service
from app.service.provider_preset_service import (
    detect_provider_from_email,
    list_provider_presets,
    resolve_preset_hosts,
)

router = APIRouter(tags=["accounts"])


@router.get("/providers", response_model=list[ProviderPresetOut])
def get_provider_presets() -> list[ProviderPresetOut]:
    """获取内置主流邮箱服务器配置预设列表。"""
    return [ProviderPresetOut(**item) for item in list_provider_presets()]


@router.get("/providers/detect", response_model=ProviderPresetOut)
def detect_provider(email: str = Query(..., min_length=3)) -> ProviderPresetOut:
    """根据用户输入邮箱后缀自动匹配推荐的 IMAP/SMTP 配置。"""
    preset = detect_provider_from_email(email)
    imap_host, smtp_host = resolve_preset_hosts(preset, email)
    return ProviderPresetOut(
        id=preset.id,
        name=preset.name,
        domains=list(preset.domains),
        imap_host=imap_host,
        imap_port=preset.imap_port,
        imap_ssl=preset.imap_ssl,
        smtp_host=smtp_host,
        smtp_port=preset.smtp_port,
        smtp_ssl=preset.smtp_ssl,
        supports_oauth=preset.supports_oauth,
        requires_imap_id=preset.requires_imap_id,
        badge_color=preset.badge_color,
        auth_guide_url=preset.auth_guide_url,
        auth_guide_tip=preset.auth_guide_tip,
    )


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)) -> list[AccountOut]:
    """获取全部绑定邮箱账号及未读统计。"""
    return account_service.list_accounts(db)


@router.post("/accounts/test", response_model=AccountTestResult)
async def test_account_connection(payload: AccountTestRequest) -> AccountTestResult:
    """实时测试账号 IMAP 收信与 SMTP 发信连通性。"""
    return await account_service.test_connection(payload)


@router.post("/accounts", response_model=AccountOut)
async def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> AccountOut:
    """新增邮箱渠道账号。"""
    try:
        return await account_service.create_account(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/accounts/reorder", response_model=list[AccountOut])
def reorder_accounts(payload: AccountReorderRequest, db: Session = Depends(get_db)) -> list[AccountOut]:
    """调整右侧栏邮箱显示顺序。"""
    return account_service.reorder_accounts(db, payload.ordered_ids)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: int, payload: AccountUpdate, db: Session = Depends(get_db)) -> AccountOut:
    """修改邮箱别名、授权码、签名或开关设置。"""
    try:
        return account_service.update_account(db, account_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    """删除邮箱账号及其关联本地邮件。"""
    try:
        account_service.delete_account(db, account_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/accounts/sync-all")
async def sync_all_accounts(
    inbox_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """手动触发全部已启用邮箱立即同步（支持 inbox_only 快速查新）。"""
    return await account_service.sync_all_accounts(db, inbox_only=inbox_only, source="manual")


@router.post("/accounts/quick-check")
async def quick_check_accounts(
    account_id: int | None = Query(default=None),
) -> dict[str, object]:
    """唤醒实时长连接或轻量增量检查收件箱新邮件。"""
    return await account_service.quick_check_accounts(account_id=account_id)


@router.post("/accounts/{account_id}/sync")
async def sync_single_account(
    account_id: int,
    inbox_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """手动触发指定邮箱立即同步。"""
    try:
        return await account_service.sync_single_account(
            db,
            account_id,
            inbox_only=inbox_only,
            source="manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
