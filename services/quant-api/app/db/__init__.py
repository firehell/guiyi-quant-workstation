"""数据库基础设施包。

提供 SQLAlchemy ``Base``、会话工厂 ``get_db`` 依赖；URL 规范化与迁移安全校验
见 ``url``、``migration_test_guard`` 子模块。
"""

from app.db.base import Base
from app.db.session import get_db

__all__ = ["Base", "get_db"]
