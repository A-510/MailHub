from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.accounts import router as accounts_router
from app.api.emails import router as emails_router
from app.api.oauth import router as oauth_router
from app.api.settings_rules import router as settings_router
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.logging_config import setup_logging
from app.service.demo_seed_service import demo_seed_service
from app.service.scheduler_service import scheduler_service

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期管理：初始化数据库、注入初次演示数据、启停定时同步。"""
    init_db()
    with SessionLocal() as db:
        demo_seed_service.seed_if_empty(db, force=False)
    scheduler_service.start()
    try:
        yield
    finally:
        await scheduler_service.stop()


def create_app() -> FastAPI:
    """构建并返回 FastAPI 应用实例。"""
    application = FastAPI(
        title="MailHub API",
        version=settings.app_version,
        description="MailHub 多邮箱聚合书籍客户端后端服务",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8765",
            "http://127.0.0.1:8765",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/api/v1/health")
    def health_check() -> dict[str, str]:
        """健康检查接口，供启动器检测服务就绪状态。"""
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.app_version,
        }

    application.include_router(accounts_router, prefix="/api/v1")
    application.include_router(emails_router, prefix="/api/v1")
    application.include_router(oauth_router, prefix="/api/v1")
    application.include_router(settings_router, prefix="/api/v1")

    # 挂载 Live2D 模型静态资源，需位于 SPA 通配路由之前
    live2d_dir = settings.live2d_dir
    if live2d_dir.exists():
        application.mount("/live2d", StaticFiles(directory=str(live2d_dir)), name="live2d-assets")

    # 挂载编译后的前端静态资源，实现单进程桌面式启动体验
    dist_dir = settings.frontend_dist_dir
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        assets_dir = dist_dir / "assets"
        if assets_dir.exists():
            application.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

        vendor_dir = dist_dir / "vendor"
        if vendor_dir.exists():
            application.mount("/vendor", StaticFiles(directory=str(vendor_dir)), name="frontend-vendor")

        @application.get("/{full_path:path}", include_in_schema=False)
        def serve_spa(full_path: str) -> FileResponse:
            """托管前端静态文件并回退至 index.html。"""
            candidate: Path = (dist_dir / full_path).resolve()
            if full_path and candidate.is_file() and dist_dir.resolve() in candidate.parents:
                return FileResponse(str(candidate))
            return FileResponse(str(dist_dir / "index.html"))

        logger.info("Mounted built frontend static assets from %s", dist_dir)
    else:
        logger.info("Frontend dist directory not found (%s); running API-only mode.", dist_dir)

    return application


app = create_app()
