from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.watchlist import Watchlist, WatchlistItem


WATCHLIST_DEFINITIONS = {
    "black": {
        "name": "黑色池",
        "description": "黑色系趋势/波段研究品种",
        "items": [
            ("rb", "螺纹", "SHFE", "rb.MAIN"),
            ("hc", "热卷", "SHFE", "hc.MAIN"),
            ("i", "铁矿", "DCE", "i.MAIN"),
            ("jm", "焦煤", "DCE", "jm.MAIN"),
            ("j", "焦炭", "DCE", "j.MAIN"),
        ],
    },
    "chemical": {
        "name": "化工池",
        "description": "化工系趋势/波段研究品种",
        "items": [
            ("TA", "PTA", "CZCE", "TA.MAIN"),
            ("MA", "甲醇", "CZCE", "MA.MAIN"),
            ("l", "塑料", "DCE", "l.MAIN"),
            ("pp", "PP", "DCE", "pp.MAIN"),
            ("v", "PVC", "DCE", "v.MAIN"),
            ("SA", "纯碱", "CZCE", "SA.MAIN"),
            ("FG", "玻璃", "CZCE", "FG.MAIN"),
        ],
    },
    "energy": {
        "name": "能源池",
        "description": "能源系趋势/波段研究品种",
        "items": [
            ("sc", "原油", "INE", "sc.MAIN"),
            ("fu", "燃油", "SHFE", "fu.MAIN"),
            ("bu", "沥青", "SHFE", "bu.MAIN"),
            ("pg", "LPG", "DCE", "pg.MAIN"),
        ],
    },
}


def ensure_default_watchlists(session: Session) -> None:
    existing_codes = set(session.scalars(select(Watchlist.code)))
    for code, definition in WATCHLIST_DEFINITIONS.items():
        if code not in existing_codes:
            session.add(
                Watchlist(
                    code=code,
                    name=definition["name"],
                    category="futures",
                    description=definition["description"],
                    is_active=True,
                )
            )
    session.flush()

    existing_items = {
        (item.watchlist_code, item.symbol)
        for item in session.scalars(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_code.in_(WATCHLIST_DEFINITIONS)
            )
        )
    }
    for code, definition in WATCHLIST_DEFINITIONS.items():
        for index, (symbol, name, exchange, contract) in enumerate(
            definition["items"], start=1
        ):
            if (code, symbol) not in existing_items:
                session.add(
                    WatchlistItem(
                        watchlist_code=code,
                        symbol=symbol,
                        name=name,
                        exchange_code=exchange,
                        default_contract=contract,
                        sort_order=index * 10,
                        is_active=True,
                        extra={},
                    )
                )
