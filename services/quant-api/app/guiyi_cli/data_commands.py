from __future__ import annotations

import argparse
from datetime import date

from app.core.env import PROJECT_ROOT
from app.market_data.maintenance import (
    AuditRequest,
    HistoricalDataManager,
    RefreshRequest,
    UpdateRequest,
)


def build_request(args: argparse.Namespace):
    if args.data_command == "update":
        return UpdateRequest(
            products=_products(args.symbol, args.universe),
            since=_day(args.since),
            through=_day(args.through),
            apply=bool(args.apply),
        )
    if args.data_command == "audit":
        return AuditRequest(_active_products())
    if args.data_command == "refresh":
        since = _day(args.since)
        through = _day(args.through)
        assert since is not None and through is not None
        return RefreshRequest(
            symbol=_products(args.symbol, None)[0],
            since=since,
            through=through,
            apply=bool(args.apply),
        )
    raise ValueError("CLI_DATA_COMMAND_INVALID")


def run_data_command(args: argparse.Namespace, manager: HistoricalDataManager):
    request = build_request(args)
    action = getattr(manager, args.data_command)
    return action(request)


def _products(symbol: str | None, universe: str | None) -> tuple[str, ...]:
    if universe == "active":
        return _active_products()
    normalized = str(symbol or "").strip().lower()
    if not normalized:
        raise ValueError("CLI_SYMBOL_REQUIRED")
    return (normalized,)


def _active_products() -> tuple[str, ...]:
    path = PROJECT_ROOT / "data/universe/active_products.txt"
    products = tuple(
        item.strip().lower()
        for item in path.read_text(encoding="utf-8").splitlines()
        if item.strip()
    )
    if len(products) != 69 or len(set(products)) != 69:
        raise ValueError("ACTIVE_UNIVERSE_INVALID")
    return products


def _day(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("CLI_DATE_INVALID") from exc
