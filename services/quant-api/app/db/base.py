"""SQLAlchemy Declarative Base 定义。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类；八表实体均继承此类。"""

    pass
