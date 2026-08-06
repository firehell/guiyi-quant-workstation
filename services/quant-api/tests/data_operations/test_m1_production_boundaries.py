"""M1 production-boundary regressions use only fakes and temporary data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.data_core.aggregation import AggregationSession
from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import BarFrequency, BarsResult, DatasetKey, DatasetKind
from app.services.data_operations.aggregate import AggregateApplicationService
from app.services.data_operations.contracts import (
    AggregateRequest,
    CommandStatus,
    DataTarget,
    DownloadRequest,
)
from app.services.data_operations.download import DownloadApplicationService


START = datetime(2026, 8, 3, 1, tzinfo=UTC)
END = START + timedelta(minutes=5)


def _target(frequency: BarFrequency) -> DataTarget:
    return DataTarget(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=frequency,
        adjustment="none",
        schema_version="canonical-bar-v1",
        start=START,
        end=END,
    )


def _source_key() -> DatasetKey:
    target = _target(BarFrequency.M1)
    return DatasetKey(
        provider=target.provider,
        dataset_kind=target.dataset_kind,
        symbol=target.symbol,
        contract_or_series=target.contract_or_series,
        frequency=target.frequency,
        adjustment=target.adjustment,
        schema_version=target.schema_version,
    )


def _bars() -> tuple[CanonicalBar, ...]:
    return tuple(
        CanonicalBar(
            provider="rqdata",
            symbol="jm",
            contract_or_series="JM.MAIN",
            dataset_kind=DatasetKind.CONTINUOUS,
            frequency=BarFrequency.M1,
            bar_end=START + timedelta(minutes=index + 1),
            trading_day=date(2026, 8, 3),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("10"),
            turnover=None,
            open_interest=Decimal("20"),
            adjustment="none",
            schema_version="canonical-bar-v1",
        )
        for index in range(5)
    )


def test_aggregate_apply_without_typed_publisher_fails_closed() -> None:
    source = BarsResult(
        bars=_bars(),
        source_datasets=(_source_key(),),
        manifest_digests=("1" * 64,),
        requested_window=(START, END),
        data_type=DatasetKind.CONTINUOUS,
        derived_frequency=None,
        source_data_versions=("rqdata-test",),
    )
    service = AggregateApplicationService(
        market_data=SimpleNamespace(get_bars=lambda _query: source),
        session_provider=lambda *_args: (
            AggregationSession(
                trading_day=date(2026, 8, 3), name="day", start=START, end=END
            ),
        ),
    )

    result = service.run(AggregateRequest(targets=(_target(BarFrequency.M5),), apply=True))

    assert result.status is CommandStatus.ERROR
    assert result.targets[0].error is not None
    assert result.targets[0].error.code == "AGGREGATE_PUBLISHER_UNAVAILABLE"
    assert result.effects.writes_canonical is False


def test_download_apply_noop_does_not_construct_provider_synchronizer() -> None:
    calls: list[str] = []
    target = _target(BarFrequency.M1)
    service = DownloadApplicationService(
        synchronizer_factory=lambda: calls.append("sync") or object(),  # type: ignore[arg-type]
        covered_windows=lambda _key: ((START, END),),
    )

    result = service.run(DownloadRequest(targets=(target,), apply=True))

    assert calls == []
    assert result.status is CommandStatus.PASSED
    assert result.effects.calls_rqdata is False
    assert result.targets[0].detail["action"] == "no_op"


def test_typed_derived_publisher_uses_real_sessions_and_deterministic_lineage() -> None:
    from app.services.data_operations.publisher import DerivedCanonicalPublisher

    staged = SimpleNamespace(
        file_checksum="a" * 64,
        canonical_logical_fingerprint="b" * 64,
    )
    captured: list[object] = []

    class Store:
        def stage(self, batch):
            captured.append(batch)
            return staged

        def publish(self, _staged, expected):
            captured.append(expected)
            return SimpleNamespace()

    source = BarsResult(
        bars=_bars(),
        source_datasets=(_source_key(),),
        manifest_digests=("1" * 64,),
        requested_window=(START, END),
        data_type=DatasetKind.CONTINUOUS,
        derived_frequency=None,
        source_data_versions=("rqdata-test",),
    )
    target = _target(BarFrequency.M5)
    target_key = DatasetKey(
        provider=target.provider,
        dataset_kind=target.dataset_kind,
        symbol=target.symbol,
        contract_or_series=target.contract_or_series,
        frequency=target.frequency,
        adjustment=target.adjustment,
        schema_version=target.schema_version,
    )
    sessions = (
        AggregationSession(
            trading_day=date(2026, 8, 3), name="day", start=START, end=END
        ),
    )

    DerivedCanonicalPublisher(Store())(
        _bars(),
        dataset=target_key,
        source=source,
        aggregation_sessions=sessions,
    )

    batch, expectation = captured
    assert batch.request.sessions[0].expected_bar_ends == (END,)  # type: ignore[union-attr]
    assert expectation.lineage.legacy_source_checksum != "0" * 64  # type: ignore[union-attr]
    assert expectation.lineage.quality_evidence_digest != "0" * 64  # type: ignore[union-attr]
    assert expectation.data_version.startswith("aggregate-canonical-aggregate-v1-")  # type: ignore[union-attr]
