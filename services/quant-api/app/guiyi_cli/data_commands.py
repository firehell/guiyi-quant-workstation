from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import json

from app.core.env import PROJECT_ROOT
from app.market_data.domain import DatasetKey
from app.market_data.maintenance import (
    AuditRequest,
    BootstrapRequest,
    ExactRepairItem,
    HistoricalDataManager,
    RepairRequest,
    UpdateRequest,
)


def build_request(args: argparse.Namespace):
    if args.data_command == "update":
        _validate_candidate_update_args(args)
        return UpdateRequest(
            products=_products(args.symbol, args.universe),
            since=_day(args.since),
            through=_day(args.through),
            apply=bool(args.apply),
        )
    if args.data_command == "bootstrap":
        return BootstrapRequest(
            products=_active_products(),
            through=_day(args.through),
            apply=bool(args.apply),
        )
    if args.data_command == "repair":
        return RepairRequest(_repair_items(args.plan), bool(args.apply))
    if args.data_command == "audit":
        return AuditRequest(_active_products())
    raise ValueError("CLI_DATA_COMMAND_INVALID")


def _validate_candidate_update_args(args: argparse.Namespace) -> None:
    root = getattr(args, "candidate_root", None)
    mode = getattr(args, "candidate_mode", None)
    if root is None and mode is None:
        return
    if root is None or mode is None or args.through is None:
        raise ValueError("CLI_CANDIDATE_ARGUMENT_INVALID")


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


def _repair_items(path) -> tuple[ExactRepairItem, ...]:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError("REPAIR_PLAN_INVALID")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        raw_items = payload["items"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("REPAIR_PLAN_INVALID") from exc
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("REPAIR_PLAN_INVALID")
    items = []
    for raw in raw_items:
        try:
            dataset = DatasetKey(**raw["dataset"])
            items.append(
                ExactRepairItem(
                    dataset=dataset,
                    year=int(raw["year"]),
                    month=int(raw["month"]),
                    start=_instant(raw["start"]),
                    end=_instant(raw["end"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("REPAIR_PLAN_INVALID") from exc
    return tuple(items)


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("REPAIR_PLAN_TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)
