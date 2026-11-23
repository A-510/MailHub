from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    MailHub 全局应用配置。
    所有路径均以项目根目录为基准自动解析，支持环境变量覆盖。
    """

    model_config = SettingsConfigDict(
        env_prefix="MAILHUB_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "MailHub"
    host: str = "127.0.0.1"
    port: int = 8765
    secret_key: str | None = None
    project_root: Path = Path(__file__).resolve().parents[3]

    @property
    def data_dir(self) -> Path:
        """返回运行时数据目录，确保目录存在。"""
        path = self.project_root / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        """返回 SQLite 数据库文件路径。"""
        return self.data_dir / "mailhub.db"

    @property
    def attachments_dir(self) -> Path:
        """返回附件缓存目录。"""
        path = self.data_dir / "attachments"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def mascots_dir(self) -> Path:
        """返回用户自定义立绘上传目录。"""
        path = self.data_dir / "mascots"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def live2d_dir(self) -> Path:
        """返回 Live2D 模型静态资源目录。"""
        return self.project_root / "live2d"

    @property
    def secret_key_file(self) -> Path:
        """返回本地加密主密钥持久化文件。"""
        return self.data_dir / ".secret.key"

    @property
    def frontend_dist_dir(self) -> Path:
        """返回构建后的前端静态资源目录。"""
        return self.project_root / "frontend" / "dist"


settings = Settings()
