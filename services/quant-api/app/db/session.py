"""SQLAlchemy 引擎与会话工厂。

应用启动时加载 .env、规范化 DATABASE_URL 并创建连接池；``get_db`` 供 FastAPI
Depends 注入，请求结束自动关闭会话。
"""

from collections.abc import Generator
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.env import PROJECT_ROOT as CORE_PROJECT_ROOT, load_project_env
from app.db.url import normalize_database_url

PROJECT_ROOT = CORE_PROJECT_ROOT

load_project_env()

DATABASE_URL = normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://guiyi@127.0.0.1:5432/guiyi_quant",
    )
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session]:
    """FastAPI 依赖：为每个请求提供 DB 会话并在结束后释放。"""
    with SessionLocal() as session:
        yield session
