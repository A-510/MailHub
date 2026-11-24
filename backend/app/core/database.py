from collections.abc import Generator
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy ORM 模型基类。"""


def _create_sqlite_engine(db_url: str) -> Engine:
    """
    创建 SQLite 引擎并启用外键约束与 WAL 并发模式。
    """
    eng = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=10000;")
        cursor.close()

    return eng


engine: Engine = _create_sqlite_engine(f"sqlite:///{settings.db_path}")
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def configure_database(db_url: str) -> Engine:
    """
    在测试或自定义场景重新绑定数据库引擎，同时更新全局 SessionLocal 绑定。
    """
    global engine
    engine = _create_sqlite_engine(db_url)
    SessionLocal.configure(bind=engine)
    return engine


def init_db(target_engine: Engine | None = None) -> None:
    """
    初始化数据库表结构及 SQLite FTS5 全文检索虚拟表与同步触发器。
    """
    # 确保模型全部加载注册
    import app.model.entities  # noqa: F401

    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)

    # 创建 FTS5 全文搜索虚拟表（支持中英文邮件主题、发件人、摘要与正文检索）
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
                    subject,
                    sender_name,
                    sender_email,
                    snippet,
                    text_body,
                    content='emails',
                    content_rowid='id'
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS emails_ai AFTER INSERT ON emails BEGIN
                    INSERT INTO emails_fts(rowid, subject, sender_name, sender_email, snippet, text_body)
                    VALUES (new.id, new.subject, new.sender_name, new.sender_email, new.snippet, new.text_body);
                END;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS emails_ad AFTER DELETE ON emails BEGIN
                    INSERT INTO emails_fts(emails_fts, rowid, subject, sender_name, sender_email, snippet, text_body)
                    VALUES ('delete', old.id, old.subject, old.sender_name, old.sender_email, old.snippet, old.text_body);
                END;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS emails_au AFTER UPDATE ON emails BEGIN
                    INSERT INTO emails_fts(emails_fts, rowid, subject, sender_name, sender_email, snippet, text_body)
                    VALUES ('delete', old.id, old.subject, old.sender_name, old.sender_email, old.snippet, old.text_body);
                    INSERT INTO emails_fts(rowid, subject, sender_name, sender_email, snippet, text_body)
                    VALUES (new.id, new.subject, new.sender_name, new.sender_email, new.snippet, new.text_body);
                END;
                """
            )
        )
    logger.info("SQLite database and FTS5 index initialized successfully.")


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入使用的数据库会话生成器。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
