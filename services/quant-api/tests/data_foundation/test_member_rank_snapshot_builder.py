from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.market_data.catalog import MainMapFact
from app.market_data.member_rank_snapshot import MemberRankSnapshotRepository
from app.market_data.member_rank_snapshot_builder import (
    MemberRankFetch,
    MemberRankSnapshotBuildError,
    MemberRankSnapshotBuilder,
    MemberRankSnapshotRequest,
)
from app.market_data.rqdata_adapter import RQDataMemberRankProvider


_DAY = date(2026, 8, 20)
_NEXT_DAY = date(2026, 8, 21)


class _MapFacts:
    def __init__(self, facts: tuple[MainMapFact, ...]) -> None:
        self.facts = facts

    def rank1_map(
        self, symbol: str, since: date, through: date
    ) -> tuple[MainMapFact, ...]:
        return tuple(
            fact
            for fact in self.facts
            if fact.symbol == symbol and since <= fact.trade_date <= through
        )

    def trading_days(
        self, symbol: str, since: date, through: date
    ) -> tuple[date, ...]:
        return tuple(
            fact.trade_date
            for fact in self.facts
            if fact.symbol == symbol and since <= fact.trade_date <= through
        )


class _Calendar:
    def is_trading_day(self, symbol: str, trade_date: date) -> bool:
        return symbol == "jm" and trade_date in {_DAY, _NEXT_DAY}


class _ContractValidity:
    def is_contract_valid(self, physical_contract: str, trade_date: date) -> bool:
        return physical_contract == "JM2609" and trade_date in {_DAY, _NEXT_DAY}


class _FailingIfCalledProvider:
    def fetch(self, request: MemberRankFetch):
        raise AssertionError(f"provider must not run: {request}")


class _RowsProvider:
    def __init__(self, rows: tuple) -> None:
        self.rows = rows
        self.calls: list[MemberRankFetch] = []

    def fetch(self, request: MemberRankFetch):
        self.calls.append(request)
        return tuple(
            row
            for row in self.rows
            if row.physical_contract == request.physical_contract
            and request.since <= row.trade_date <= request.through
            and row.rank_by == request.rank_by
        )


def _builder(
    root: Path,
    *,
    provider: object | None = None,
    facts: tuple[MainMapFact, ...] | None = None,
) -> MemberRankSnapshotBuilder:
    return MemberRankSnapshotBuilder(
        root,
        rank1_source=_MapFacts(
            facts
            if facts is not None
            else (
                MainMapFact("jm", _DAY, "JM2609"),
                MainMapFact("jm", _NEXT_DAY, "JM2609"),
            )
        ),
        trading_calendar=_Calendar(),
        contract_validity=_ContractValidity(),
        provider_factory=lambda: provider or _FailingIfCalledProvider(),
        provider_client_version="test-client",
    )


def _request(*, apply: bool = False) -> MemberRankSnapshotRequest:
    return MemberRankSnapshotRequest(
        dataset_id="mfm-member-20260821",
        products=("jm",),
        since=_DAY,
        through=_NEXT_DAY,
        apply=apply,
    )


def _complete_rows() -> tuple:
    from app.market_data.member_rank_snapshot import MemberRankRow

    return tuple(
        MemberRankRow(
            physical_contract="JM2609",
            trade_date=trading_day,
            rank_by=rank_by,
            rank=rank,
            member_name=f"{rank_by}-{rank}",
            value=Decimal(rank),
            change=Decimal(rank - 10),
        )
        for trading_day in (_DAY, _NEXT_DAY)
        for rank_by in ("volume", "long", "short")
        for rank in range(1, 21)
    )


def test_member_rank_snapshot_defaults_to_plan_without_provider_or_write(tmp_path: Path) -> None:
    result = _builder(tmp_path, provider=_FailingIfCalledProvider()).snapshot(_request())

    assert result.status == "planned"
    assert result.provider_calls == 0
    assert result.as_payload()["readonly"] is True
    assert not (tmp_path / "main_force_member_rank_v1").exists()


def test_plan_uses_exact_contiguous_rank1_contract_windows(tmp_path: Path) -> None:
    result = _builder(tmp_path).plan(_request())

    assert [(item.physical_contract, item.since, item.through, item.rank_by) for item in result.fetches] == [
        ("JM2609", _DAY, _NEXT_DAY, "volume"),
        ("JM2609", _DAY, _NEXT_DAY, "long"),
        ("JM2609", _DAY, _NEXT_DAY, "short"),
    ]


def test_snapshot_rejects_unadmitted_product_including_sc(tmp_path: Path) -> None:
    request = MemberRankSnapshotRequest(
        dataset_id="mfm-member-20260821",
        products=("sc",),
        since=_DAY,
        through=_NEXT_DAY,
    )

    with pytest.raises(MemberRankSnapshotBuildError, match="MEMBER_SNAPSHOT_PRODUCT_NOT_ADMITTED"):
        _builder(tmp_path).snapshot(request)


def test_apply_rejects_one_missing_rank_without_publishing(tmp_path: Path) -> None:
    provider = _RowsProvider(_complete_rows()[:-1])

    with pytest.raises(MemberRankSnapshotBuildError, match="MEMBER_CONTRACT_DAY_INCOMPLETE"):
        _builder(tmp_path, provider=provider).snapshot(_request(apply=True))

    assert not (tmp_path / "main_force_member_rank_v1" / "mfm-member-20260821").exists()


def test_apply_publishes_immutable_descriptor_after_reader_readback(tmp_path: Path) -> None:
    provider = _RowsProvider(_complete_rows())
    result = _builder(tmp_path, provider=provider).snapshot(_request(apply=True))

    assert result.status == "published"
    assert result.provider_calls == 3
    assert result.partition_count == 1
    repository = MemberRankSnapshotRepository(
        tmp_path,
        "mfm-member-20260821",
        trading_calendar=_Calendar(),
        contract_validity=_ContractValidity(),
    )
    assert repository.day("JM2609", _DAY) is not None
    with pytest.raises(MemberRankSnapshotBuildError, match="MEMBER_SNAPSHOT_ALREADY_EXISTS"):
        _builder(tmp_path, provider=provider).snapshot(_request(apply=True))


@pytest.mark.parametrize("rank_by", ("volume", "long", "short"))
def test_rqdata_provider_normalizes_each_supported_member_rank_shape(rank_by: str) -> None:
    frame = _rank_frame(rank_by)
    provider = RQDataMemberRankProvider(_FrameClient(frame), client_version="fake-1")

    rows = provider.fetch(
        MemberRankFetch("jm", "JM2609", _DAY, _DAY, rank_by)  # type: ignore[arg-type]
    )

    assert len(rows) == 20
    assert {row.rank_by for row in rows} == {rank_by}
    assert {row.physical_contract for row in rows} == {"JM2609"}
    assert all(isinstance(row.value, Decimal) for row in rows)


def test_rqdata_provider_rejects_empty_duplicate_nonfinite_and_provider_failures() -> None:
    request = MemberRankFetch("jm", "JM2609", _DAY, _DAY, "volume")
    for frame, code in (
        (pd.DataFrame(), "RQDATA_MEMBER_RANK_EMPTY"),
        (_rank_frame("volume", duplicate_rank=True), "RQDATA_MEMBER_RANK_DUPLICATE"),
        (_rank_frame("volume", nonfinite=True), "RQDATA_MEMBER_RANK_NONFINITE"),
    ):
        with pytest.raises(MemberRankSnapshotBuildError, match=code):
            RQDataMemberRankProvider(_FrameClient(frame), client_version="fake-1").fetch(request)
    with pytest.raises(MemberRankSnapshotBuildError, match="RQDATA_MEMBER_RANK_UNAVAILABLE"):
        RQDataMemberRankProvider(_BrokenClient(), client_version="fake-1").fetch(request)


class _FrameClient:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def member_rank(self, order_book_id: str, start: date, end: date, rank_by: str):
        assert (order_book_id, start, end) == ("JM2609", _DAY, _DAY)
        return self.frame


class _BrokenClient:
    def member_rank(self, *_args, **_kwargs):
        raise RuntimeError("provider unavailable")


def _rank_frame(
    rank_by: str, *, duplicate_rank: bool = False, nonfinite: bool = False
) -> pd.DataFrame:
    value_column = {"volume": "volume", "long": "long_position", "short": "short_position"}[rank_by]
    change_column = {
        "volume": "volume_change",
        "long": "long_position_change",
        "short": "short_position_change",
    }[rank_by]
    records = [
        {
            "rank": rank,
            "member_name": f"member-{rank}",
            value_column: rank,
            change_column: float("inf") if nonfinite and rank == 1 else rank - 10,
        }
        for rank in range(1, 21)
    ]
    if duplicate_rank:
        records[-1]["rank"] = 1
    index = pd.MultiIndex.from_arrays(
        [[_DAY] * 20, list(range(1, 21))], names=["trade_date", "sequence"]
    )
    return pd.DataFrame(records, index=index)
