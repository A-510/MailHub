import html
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schema.schemas import OAuthStartRequest, OAuthStartResponse, OAuthStatusResponse
from app.service.account_service import account_service
from app.service.oauth_service import oauth_service

router = APIRouter(tags=["oauth"])


@router.post("/oauth/start", response_model=OAuthStartResponse)
def start_oauth(payload: OAuthStartRequest, db: Session = Depends(get_db)) -> OAuthStartResponse:
    """发起浏览器 OAuth2 PKCE 授权登录。"""
    try:
        state, auth_url, browser_opened = oauth_service.start_flow(
            db,
            provider=payload.provider,
            label=payload.label,
            email_hint=payload.email_hint,
        )
        return OAuthStartResponse(state=state, auth_url=auth_url, browser_opened=browser_opened)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/oauth/status/{state}", response_model=OAuthStatusResponse)
def get_oauth_status(state: str, db: Session = Depends(get_db)) -> OAuthStatusResponse:
    """前端轮询 OAuth2 授权进度与已绑定账号结果。"""
    session = oauth_service.get_status(state)
    if session is None:
        return OAuthStatusResponse(state=state, status="expired", message="授权会话已过期")

    acc_out = None
    if session.status == "completed" and session.account_id is not None:
        try:
            acc_out = account_service.get_account_out(db, session.account_id)
        except ValueError:
            acc_out = None

    return OAuthStatusResponse(
        state=state,
        status=session.status,  # type: ignore[arg-type]
        message=session.message,
        account=acc_out,
    )


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """接收 OAuth2 浏览器重定向回调，换取令牌并展示结果页。"""
    ok, message, _ = await oauth_service.handle_callback(db, state=state, code=code, error=error)
    title = "邮箱授权成功" if ok else "邮箱授权未完成"
    accent = "#8B6CE8" if ok else "#E11D48"
    safe_msg = html.escape(message)
    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{title} - MailHub</title>
  <style>
    body {{
      margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
      font-family: "Microsoft YaHei UI", system-ui, sans-serif;
      background: linear-gradient(135deg, #fde8f2, #ede7fb);
      color: #3a2d46;
    }}
    .card {{
      max-width: 420px; padding: 32px; border-radius: 22px; text-align: center;
      background: rgba(255,255,255,0.92); box-shadow: 0 20px 50px rgba(100,70,130,0.18);
      border: 1px solid rgba(255,255,255,0.8);
    }}
    h1 {{ font-size: 20px; color: {accent}; margin: 0 0 12px; }}
    p {{ font-size: 14px; line-height: 1.6; color: #6f5e7e; margin: 0 0 20px; }}
    button {{
      padding: 10px 24px; border-radius: 999px; border: none; cursor: pointer;
      background: linear-gradient(135deg, #8B6CE8, #A986F7); color: #fff; font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p>{safe_msg}</p>
    <button onclick="window.close()">关闭此标签页并返回 MailHub</button>
  </div>
</body>
</html>"""
    return HTMLResponse(content=body, status_code=200 if ok else 400)
