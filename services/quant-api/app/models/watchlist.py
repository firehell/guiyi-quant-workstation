from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.data_center import TimestampMixin


class Watchlist(Base, TimestampMixin):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    items: Mapped[list["WatchlistItem"]] = relationship(back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_code", "symbol", name="uq_watchlist_item_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_code: Mapped[str] = mapped_column(ForeignKey("watchlists.code", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(64))
    exchange_code: Mapped[str | None] = mapped_column(String(16), index=True)
    default_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    watchlist: Mapped["Watchlist"] = relationship(back_populates="items")
