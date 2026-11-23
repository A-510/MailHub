import json
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schema.schemas import (
    DraftSaveRequest,
    EmailBatchRequest,
    EmailDetailOut,
    EmailListResponse,
    EmailPatchRequest,
)
from app.service.email_service import email_service
from app.service.system_service import system_service

router = APIRouter(tags=["emails"])


@router.get("/emails", response_model=EmailListResponse)
def list_emails(
    folder: str = Query(default="inbox"),
    category: str = Query(default="all"),
    account_id: int | None = Query(default=None),
    account_ids: str | None = Query(default=None, description="逗号分隔的账号 ID 列表"),
    q: str = Query(default=""),
    unread_only: bool = Query(default=False),
    has_attachments: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=50),
    db: Session = Depends(get_db),
) -> EmailListResponse:
    """分页查询邮件列表与文件夹计数（支持聚合视图、单邮箱与 FTS5 全文搜索）。"""
    parsed_ids: list[int] | None = None
    if account_ids is not None:
        if account_ids.strip() == "":
            parsed_ids = []
        else:
            try:
                parsed_ids = [int(part.strip()) for part in account_ids.split(",") if part.strip()]
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="account_ids 格式无效") from exc

    return email_service.list_emails(
        db,
        folder=folder,
        category=category,
        account_id=account_id,
        account_ids=parsed_ids,
        query=q,
        unread_only=unread_only,
        has_attachments=has_attachments,
        page=page,
        page_size=page_size,
    )


@router.get("/emails/{email_id}", response_model=EmailDetailOut)
def get_email(email_id: int, db: Session = Depends(get_db)) -> EmailDetailOut:
    """获取单封邮件详细信息及附件列表。"""
    try:
        return email_service.get_email(db, email_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/emails/{email_id}", response_model=EmailDetailOut)
def patch_email(
    email_id: int,
    payload: EmailPatchRequest,
    db: Session = Depends(get_db),
) -> EmailDetailOut:
    """更新邮件已读、星标、文件夹或分类。"""
    try:
        return email_service.patch_email(db, email_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/emails/batch")
def batch_emails(payload: EmailBatchRequest, db: Session = Depends(get_db)) -> dict[str, int]:
    """批量修改或删除多封邮件。"""
    affected = email_service.batch_action(db, payload.email_ids, payload.action)
    return {"affected": affected}


@router.delete("/emails/{email_id}")
def delete_email(email_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    """彻底删除单封邮件。"""
    try:
        email_service.delete_email(db, email_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/emails/drafts", response_model=EmailDetailOut)
def save_draft(payload: DraftSaveRequest, db: Session = Depends(get_db)) -> EmailDetailOut:
    """保存或更新草稿。"""
    try:
        return email_service.save_draft(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/emails/send", response_model=EmailDetailOut)
async def send_email(
    account_id: int = Form(...),
    to_addresses: str = Form(..., description="JSON 数组或逗号分隔邮箱"),
    cc_addresses: str = Form(default="[]"),
    bcc_addresses: str = Form(default="[]"),
    subject: str = Form(default=""),
    html_body: str = Form(default=""),
    text_body: str = Form(default=""),
    in_reply_to: str = Form(default=""),
    draft_id: int | None = Form(default=None),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
) -> EmailDetailOut:
    """发送新邮件或回复/转发邮件（支持多附件上传）。"""

    def _parse_addrs(raw: str) -> list[str]:
        raw_s = raw.strip()
        if not raw_s:
            return []
        if raw_s.startswith("["):
            try:
                loaded = json.loads(raw_s)
                return [str(x).strip() for x in loaded if str(x).strip()]
            except json.JSONDecodeError:
                pass
        return [item.strip() for item in raw_s.replace(";", ",").split(",") if item.strip()]

    uploaded_payload: list[tuple[str, str, bytes]] = []
    for upload in files:
        content = await upload.read()
        uploaded_payload.append((upload.filename or "attachment", upload.content_type or "application/octet-stream", content))

    try:
        return await email_service.send_email(
            db,
            account_id=account_id,
            to_addresses=_parse_addrs(to_addresses),
            cc_addresses=_parse_addrs(cc_addresses),
            bcc_addresses=_parse_addrs(bcc_addresses),
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            in_reply_to=in_reply_to,
            draft_id=draft_id,
            uploaded_files=uploaded_payload,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)) -> Response:
    """下载邮件附件文件。"""
    try:
        filename, content_type, file_path, raw_bytes = system_service.get_attachment_download_info(db, attachment_id)
        if file_path is not None:
            return FileResponse(path=str(file_path), filename=filename, media_type=content_type)
        return Response(
            content=raw_bytes or b"",
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
