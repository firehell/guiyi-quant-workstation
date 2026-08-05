from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_core.catalog import HistoricalCatalog
from app.db.session import get_db
from app.models.watchlist import Watchlist
from app.services.watchlists import ensure_default_watchlists


router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


@router.get("")
def list_watchlists(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    ensure_default_watchlists(session)
    session.commit()
    rows = session.scalars(
        select(Watchlist)
        .where(Watchlist.is_active.is_(True))
        .order_by(Watchlist.code)
    )
    return [
        {
            "code": row.code,
            "name": row.name,
            "category": row.category,
            "description": row.description,
            "item_count": len([item for item in row.items if item.is_active]),
        }
        for row in rows
    ]


@router.get("/{code}/items")
def list_watchlist_items(
    code: str, session: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    ensure_default_watchlists(session)
    session.commit()
    watchlist = session.scalar(
        select(Watchlist).where(
            Watchlist.code == code, Watchlist.is_active.is_(True)
        )
    )
    if watchlist is None:
        raise HTTPException(status_code=404, detail="watchlist not found")
    return [
        {
            "symbol": item.symbol,
            "name": item.name,
            "exchange_code": item.exchange_code,
            "default_contract": item.default_contract,
            "available_periods": sorted(
                {
                    row.frequency
                    for row in HistoricalCatalog(session).list_datasets(
                        symbol=item.symbol
                    )
                }
            ),
        }
        for item in sorted(
            [item for item in watchlist.items if item.is_active],
            key=lambda row: (row.sort_order, row.symbol),
        )
    ]
