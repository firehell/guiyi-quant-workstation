"""Plan and publish immutable RQData member-rank research snapshots."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import re
import shutil
from typing import Literal, Protocol, cast
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from app.market_data.catalog import MainMapFact
from app.market_data.member_rank_snapshot import (
    MEMBER_RANK_SCHEMA,
    MEMBER_RANK_ADMITTED_PRODUCTS,
    RANK_BY_VALUES,
    ContractValidityVerifier,
    MemberRankRow,
    MemberRankSnapshotError,
    MemberRankSnapshotRepository,
    TradingCalendarVerifier,
    member_rank_contract_product,
)


_DATASET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class MemberRankSnapshotBuildError(RuntimeError):
    """Stable fail-closed error for snapshot planning and publication."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MemberRankSnapshotRequest:
    dataset_id: str
    products: tuple[str, ...]
    since: date
    through: date
    apply: bool = False


@dataclass(frozen=True, slots=True)
class MemberRankFetch:
    symbol: str
    physical_contract: str
    since: date
    through: date
    rank_by: Literal["volume", "long", "short"]


class MemberRankProvider(Protocol):
    def fetch(self, request: MemberRankFetch) -> tuple[MemberRankRow, ...]: ...


class MemberRankPlanningSource(Protocol):
    def rank1_map(
        self, symbol: str, since: date, through: date
    ) -> tuple[MainMapFact, ...]: ...

    def trading_days(self, symbol: str, since: date, through: date) -> tuple[date, ...]: ...


@dataclass(frozen=True, slots=True)
class MemberRankSnapshotPlan:
    request: MemberRankSnapshotRequest
    fetches: tuple[MemberRankFetch, ...]
    contract_days: tuple[tuple[str, date], ...]
    partitions: tuple[tuple[str, int], ...]

    def as_result(
        self,
        *,
        status: Literal["planned", "published"],
        provider_calls: int,
        partition_count: int,
    ) -> MemberRankSnapshotResult:
        return MemberRankSnapshotResult(
            status=status,
            dataset_id=self.request.dataset_id,
            products=self.request.products,
            contract_count=len({contract for contract, _ in self.contract_days}),
            provider_calls=provider_calls,
            partition_count=partition_count,
        )


@dataclass(frozen=True, slots=True)
class MemberRankSnapshotResult:
    status: Literal["planned", "published"]
    dataset_id: str
    products: tuple[str, ...]
    contract_count: int
    provider_calls: int
    partition_count: int

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "data.member-rank.snapshot",
            "status": self.status,
            "dataset_id": self.dataset_id,
            "products": list(self.products),
            "contract_count": self.contract_count,
            "provider_calls": self.provider_calls,
            "partition_count": self.partition_count,
            "readonly": self.status == "planned",
        }


class MemberRankSnapshotBuilder:
    """Build only explicitly requested immutable snapshots from catalog rank-1 facts."""

    def __init__(
        self,
        root: Path,
        *,
        rank1_source: MemberRankPlanningSource,
        trading_calendar: TradingCalendarVerifier,
        contract_validity: ContractValidityVerifier,
        provider_factory: Callable[[], MemberRankProvider],
        provider_client_version: str = "unknown",
    ) -> None:
        if not isinstance(root, Path):
            raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_ROOT_INVALID")
        self._root = root.resolve()
        self._rank1_source = rank1_source
        self._trading_calendar = trading_calendar
        self._contract_validity = contract_validity
        self._provider_factory = provider_factory
        self._provider_client_version = provider_client_version.strip() or "unknown"

    def plan(self, request: MemberRankSnapshotRequest) -> MemberRankSnapshotPlan:
        _validate_request(request)
        fetches: list[MemberRankFetch] = []
        contract_days: list[tuple[str, date]] = []
        for product in request.products:
            expected_days = self._trading_days(product, request.since, request.through)
            maps = self._rank1_map(product, request.since, request.through)
            if tuple(fact.trade_date for fact in maps) != expected_days:
                raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_MAIN_MAP_MISSING")
            for contract, since, through in _contract_windows(maps, expected_days):
                fetches.extend(
                    MemberRankFetch(
                        product,
                        contract,
                        since,
                        through,
                        cast(Literal["volume", "long", "short"], rank_by),
                    )
                    for rank_by in RANK_BY_VALUES
                )
            contract_days.extend(
                (fact.contract.strip().upper(), fact.trade_date) for fact in maps
            )
        partitions = tuple(
            sorted({(contract, trading_day.year) for contract, trading_day in contract_days})
        )
        return MemberRankSnapshotPlan(request, tuple(fetches), tuple(contract_days), partitions)

    def snapshot(self, request: MemberRankSnapshotRequest) -> MemberRankSnapshotResult:
        plan = self.plan(request)
        if not request.apply:
            return plan.as_result(
                status="planned", provider_calls=0, partition_count=0
            )
        final = self._final_path(request.dataset_id)
        if final.exists():
            raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_ALREADY_EXISTS")
        staging = self._staging_path(request.dataset_id)
        try:
            provider = self._provider_factory()
            rows = tuple(
                row for fetch in plan.fetches for row in provider.fetch(fetch)
            )
            self._write_and_read_back(staging, request, plan, rows, provider)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(
                staging / "main_force_member_rank_v1" / request.dataset_id,
                final,
            )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        self._clean_published_staging_wrapper(staging)
        return plan.as_result(
            status="published",
            provider_calls=len(plan.fetches),
            partition_count=len(plan.partitions),
        )

    @staticmethod
    def _clean_published_staging_wrapper(staging: Path) -> None:
        """Best-effort cleanup after publish; never turn a successful rename into failure."""
        try:
            (staging / "main_force_member_rank_v1").rmdir()
            staging.rmdir()
        except OSError:
            return

    def _trading_days(self, product: str, since: date, through: date) -> tuple[date, ...]:
        try:
            values = self._rank1_source.trading_days(product, since, through)
        except Exception as exc:
            raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_CALENDAR_UNAVAILABLE") from exc
        if not values or tuple(sorted(set(values))) != values:
            raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_CALENDAR_UNAVAILABLE")
        return values

    def _rank1_map(self, product: str, since: date, through: date) -> tuple[MainMapFact, ...]:
        try:
            values = self._rank1_source.rank1_map(product, since, through)
        except Exception as exc:
            raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_MAIN_MAP_MISSING") from exc
        try:
            invalid = any(
                fact.symbol != product
                or not isinstance(fact.trade_date, date)
                or not isinstance(fact.contract, str)
                or not fact.contract.strip()
                or member_rank_contract_product(fact.contract) != product
                for fact in values
            )
        except MemberRankSnapshotError:
            invalid = True
        if invalid:
            raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_MAIN_MAP_INVALID")
        return values

    def _final_path(self, dataset_id: str) -> Path:
        return self._root / "main_force_member_rank_v1" / dataset_id

    def _staging_path(self, dataset_id: str) -> Path:
        return self._root / f".member-rank-{dataset_id}.staging-{uuid4().hex}"

    def _write_and_read_back(
        self,
        staging: Path,
        request: MemberRankSnapshotRequest,
        plan: MemberRankSnapshotPlan,
        rows: tuple[MemberRankRow, ...],
        provider: MemberRankProvider,
    ) -> None:
        allowed_days = set(plan.contract_days)
        if any((row.physical_contract, row.trade_date) not in allowed_days for row in rows):
            raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_PROVIDER_ROW_OUT_OF_SCOPE")
        snapshot_root = staging / "main_force_member_rank_v1" / request.dataset_id
        snapshot_root.mkdir(parents=True, exist_ok=False)
        grouped: dict[tuple[str, int], list[MemberRankRow]] = defaultdict(list)
        for row in rows:
            grouped[(row.physical_contract, row.trade_date.year)].append(row)
        descriptors = []
        for contract, year in plan.partitions:
            partition_rows = grouped.get((contract, year), [])
            if not partition_rows:
                raise MemberRankSnapshotBuildError("MEMBER_CONTRACT_DAY_INCOMPLETE")
            relative_uri = f"contract={contract}/year={year}/member_rank.parquet"
            destination = snapshot_root / relative_uri
            destination.parent.mkdir(parents=True, exist_ok=False)
            records = [
                {
                    "physical_contract": row.physical_contract,
                    "trade_date": row.trade_date,
                    "rank_by": row.rank_by,
                    "rank": row.rank,
                    "member_name": row.member_name,
                    "value": row.value,
                    "change": row.change,
                    "provider": "rqdata",
                    "dataset_id": request.dataset_id,
                }
                for row in partition_rows
            ]
            try:
                pq.write_table(pa.Table.from_pylist(records, schema=MEMBER_RANK_SCHEMA), destination)
            except (pa.ArrowException, ValueError, TypeError) as exc:
                raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_PARQUET_INVALID") from exc
            days = [row.trade_date for row in partition_rows]
            descriptors.append(
                {
                    "relative_uri": relative_uri,
                    "row_count": len(partition_rows),
                    "coverage_start": min(days).isoformat(),
                    "coverage_end": max(days).isoformat(),
                    "quality_status": "passed",
                }
            )
        payload = {
            "schema_version": 1,
            "dataset_id": request.dataset_id,
            "provider": "rqdata",
            "provider_client_version": str(
                getattr(provider, "client_version", self._provider_client_version)
            ).strip()
            or self._provider_client_version,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "requested_since": request.since.isoformat(),
            "requested_through": request.through.isoformat(),
            "requested_products": list(request.products),
            "admitted_products": list(request.products),
            "physical_contracts": sorted({contract for contract, _ in plan.contract_days}),
            "partitions": descriptors,
        }
        (snapshot_root / "snapshot.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        repository = MemberRankSnapshotRepository(
            staging,
            request.dataset_id,
            trading_calendar=self._trading_calendar,
            contract_validity=self._contract_validity,
        )
        for contract, trading_day in plan.contract_days:
            try:
                if repository.day(contract, trading_day) is None:
                    raise MemberRankSnapshotBuildError("MEMBER_CONTRACT_DAY_INCOMPLETE")
            except MemberRankSnapshotError as exc:
                raise MemberRankSnapshotBuildError(exc.code) from None


def _validate_request(request: MemberRankSnapshotRequest) -> None:
    if not isinstance(request.dataset_id, str) or _DATASET_ID.fullmatch(request.dataset_id) is None:
        raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_DATASET_ID_INVALID")
    if not isinstance(request.products, tuple) or not request.products:
        raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_PRODUCTS_INVALID")
    if (
        any(not isinstance(product, str) or product != product.strip().lower() or not product.isalpha() for product in request.products)
        or len(set(request.products)) != len(request.products)
    ):
        raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_PRODUCTS_INVALID")
    if any(product not in MEMBER_RANK_ADMITTED_PRODUCTS for product in request.products):
        raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_PRODUCT_NOT_ADMITTED")
    if (
        not isinstance(request.since, date)
        or not isinstance(request.through, date)
        or request.since > request.through
        or type(request.apply) is not bool
    ):
        raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_REQUEST_INVALID")


def _contract_windows(
    maps: tuple[MainMapFact, ...], expected_days: tuple[date, ...]
) -> tuple[tuple[str, date, date], ...]:
    if not maps:
        raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_MAIN_MAP_MISSING")
    windows: list[tuple[str, date, date]] = []
    contract = maps[0].contract.strip().upper()
    since = expected_days[0]
    previous = expected_days[0]
    for fact, trading_day in zip(maps[1:], expected_days[1:], strict=True):
        candidate = fact.contract.strip().upper()
        if candidate != contract:
            windows.append((contract, since, previous))
            contract = candidate
            since = trading_day
        previous = trading_day
    windows.append((contract, since, previous))
    return tuple(windows)
