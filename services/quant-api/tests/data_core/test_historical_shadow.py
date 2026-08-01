from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.data_core.aggregation import AggregationSession
from app.data_core.historical_migration import (
    LegacyAssetInventory,
    ShadowException,
    build_jm_migration_plan,
    build_jm_shadow_query_set,
    compare_shadow_bars,
)
from app.data_core.historical_apply_gate import HistoricalApplyGateError
from app.data_core import historical_shadow
from app.data_core.historical_shadow import (
    ShadowReadResult,
    expected_shadow_bar_keys,
    run_chunked_historical_shadow_query_set,
)
from app.data_core import cli_service


def _queries():
    return build_jm_shadow_query_set(
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 3, tzinfo=UTC),
    )


def _row(query) -> dict[str, str]:
    contract = "JM.MAIN" if query.dataset_kind == "continuous" else "JM2609"
    return {
        "provider": "rqdata",
        "dataset_kind": query.dataset_kind,
        "symbol": "jm",
        "contract_or_series": contract,
        "frequency": query.frequency,
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
        "bar_end": "2026-07-01T01:01:00+00:00",
        "trading_day": "2026-07-01",
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100",
        "volume": "1",
        "turnover": "100",
        "open_interest": "1",
    }


def _reader(query) -> ShadowReadResult:
    return ShadowReadResult(
        rows=(_row(query),),
        lineage={"source": query.dataset_kind, "frequency": query.frequency},
    )


def test_chunked_shadow_passes_exact_13_query_coverage_and_binds_lineage() -> None:
    result = run_chunked_historical_shadow_query_set(
        _queries(),
        legacy_reader=_reader,
        canonical_reader=_reader,
        expected_keys_reader=lambda _query: (
            "2026-07-01T01:01:00+00:00",
        ),
        expected_actual_contract_by_day={"2026-07-01": "JM2609"},
    )

    assert result["status"] == "passed"
    assert result["query_count"] == result["chunk_count"] == 13
    assert result["blocked_query_count"] == 0
    assert len(result["legacy_source_lineage_digest"]) == 64
    assert len(result["canonical_source_lineage_digest"]) == 64
    assert all(len(item["chunks"]) == 1 for item in result["results"])


def test_chunked_shadow_blocks_mutual_omission_against_expected_coverage() -> None:
    def empty(_query):
        return ShadowReadResult(rows=(), lineage={"source": "empty"})

    result = run_chunked_historical_shadow_query_set(
        _queries(),
        legacy_reader=empty,
        canonical_reader=empty,
        expected_keys_reader=lambda _query: (
            "2026-07-01T01:01:00+00:00",
        ),
        expected_actual_contract_by_day={"2026-07-01": "JM2609"},
    )

    assert result["status"] == "blocked"
    assert result["blocked_query_count"] == 13
    assert all(
        {difference["fields"][0] for difference in item["chunks"][0]["differences"]}
        == {"legacy", "canonical"}
        for item in result["results"]
    )


def test_chunked_shadow_rejects_a_missing_expected_chunk() -> None:
    with pytest.raises(ValueError, match="expected chunk coverage missing"):
        run_chunked_historical_shadow_query_set(
            _queries(),
            legacy_reader=_reader,
            canonical_reader=_reader,
            expected_keys_reader=lambda _query: (),
            expected_actual_contract_by_day={"2026-07-01": "JM2609"},
        )


def test_chunked_shadow_blocks_an_unused_exception_and_binds_digest() -> None:
    result = run_chunked_historical_shadow_query_set(
        _queries(),
        legacy_reader=_reader,
        canonical_reader=_reader,
        expected_keys_reader=lambda _query: (
            "2026-07-01T01:01:00+00:00",
        ),
        allowed_exceptions={
            "continuous:1m": (
                ShadowException(
                    bar_end="2026-07-02T01:01:00+00:00",
                    reason="unused",
                    allow_missing=True,
                ),
            )
        },
        expected_actual_contract_by_day={"2026-07-01": "JM2609"},
    )

    assert result["status"] == "blocked"
    assert result["blocked_query_count"] == 1
    assert result["results"][0]["unused_declared_exception_keys"] == [
        "2026-07-02T01:01:00+00:00"
    ]
    assert len(result["exception_digest"]) == 64


def test_expected_keys_keep_cross_month_week_in_its_actual_week_end_chunk() -> None:
    sessions = tuple(
        AggregationSession(
            trading_day=trading_day,
            name=f"day-{trading_day.isoformat()}",
            start=datetime(
                trading_day.year,
                trading_day.month,
                trading_day.day,
                1,
                tzinfo=UTC,
            ),
            end=datetime(
                trading_day.year,
                trading_day.month,
                trading_day.day,
                2,
                tzinfo=UTC,
            ),
        )
        for trading_day in (date(2026, 4, 30), date(2026, 5, 1))
    )
    first_month = build_jm_shadow_query_set(
        start=datetime(2026, 4, 1, tzinfo=UTC),
        end=datetime(2026, 5, 1, tzinfo=UTC),
    )[-1]
    second_month = type(first_month)(
        dataset_kind=first_month.dataset_kind,
        contract_or_series=first_month.contract_or_series,
        frequency=first_month.frequency,
        start=datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
        end=datetime(2026, 6, 1, tzinfo=UTC).isoformat(),
    )

    assert first_month.frequency == "1d"
    weekly_first_month = type(first_month)(
        dataset_kind="continuous",
        contract_or_series="JM.MAIN",
        frequency="1w",
        start=first_month.start,
        end=first_month.end,
    )
    weekly_second_month = type(weekly_first_month)(
        dataset_kind="continuous",
        contract_or_series="JM.MAIN",
        frequency="1w",
        start=second_month.start,
        end=second_month.end,
    )

    assert expected_shadow_bar_keys(weekly_first_month, sessions) == (
        "2026-05-01T00:00:00+00:00",
    )
    assert expected_shadow_bar_keys(weekly_second_month, sessions) == ()


def test_shadow_weekly_sessions_exclude_packet_bound_initial_partial_week() -> None:
    query = next(
        item
        for item in build_jm_shadow_query_set(
            start=datetime(2013, 3, 21, 7, tzinfo=UTC),
            end=datetime(2013, 4, 1, tzinfo=UTC),
        )
        if item.dataset_kind == "continuous" and item.frequency == "1w"
    )
    sessions = tuple(
        AggregationSession(
            trading_day=trading_day,
            name=f"day-{trading_day.isoformat()}",
            start=datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC)
            - timedelta(hours=1),
            end=datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC),
        )
        for trading_day in (date(2013, 3, 22), date(2013, 3, 29))
    )

    filtered = historical_shadow.filter_initial_partial_week_sessions(
        sessions,
        first_approved_trading_day=date(2013, 3, 22),
    )

    assert tuple(item.trading_day for item in filtered) == (date(2013, 3, 29),)
    assert expected_shadow_bar_keys(query, filtered) == (
        "2013-03-29T00:00:00+00:00",
    )


def test_shadow_production_weekly_reader_excludes_initial_partial_week(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    start = datetime(2013, 3, 21, 7, tzinfo=UTC)
    end = datetime(2013, 4, 1, tzinfo=UTC)
    sessions = tuple(
        AggregationSession(
            trading_day=trading_day,
            name=f"day-{trading_day.isoformat()}",
            start=datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC)
            - timedelta(hours=1),
            end=datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC),
        )
        for trading_day in (date(2013, 3, 22), date(2013, 3, 29))
    )
    receipt_path = (tmp_path / "receipt.json").resolve()
    canonical_root = (tmp_path / "canonical").resolve()
    canonical_root.mkdir()
    packet = {
        "packet_hash": "packet-hash",
        "bound_facts": {
            "task_head": "task-head",
            "plan_digest": "plan-digest",
            "scope": {
                "window": {"start": start.isoformat(), "end": end.isoformat()}
            },
            "write_set": {
                "partial_apply_receipt": str(receipt_path),
                "canonical_root": str(canonical_root),
            },
        },
    }
    current_state = {
        "state_digest": "state-digest",
        "mapping_complete": True,
        "mapping_digest": "mapping-digest",
        "mapping_rows": [
            {"trading_day": "2013-03-22", "actual_contract": "JM1307"},
            {"trading_day": "2013-03-29", "actual_contract": "JM1309"},
        ],
    }

    monkeypatch.setattr(cli_service, "_require_loaded_source_checkout", lambda _root: None)
    monkeypatch.setattr(cli_service, "_require_data_core_revision", lambda _session: None)
    monkeypatch.setattr(cli_service, "load_apply_approval_packet", lambda *_a, **_k: packet)
    monkeypatch.setattr(
        cli_service,
        "_git_state",
        lambda _root: {"clean": True, "head": "task-head"},
    )
    monkeypatch.setattr(cli_service, "approval_basis_digest", lambda _facts: "basis")
    monkeypatch.setattr(
        cli_service,
        "PartialApplyReceiptStore",
        lambda *_a, **_k: SimpleNamespace(
            snapshot=lambda: {
                "status": "passed",
                "receipt_digest": "receipt-digest",
                "progress_state_digest": "state-digest",
            }
        ),
    )
    monkeypatch.setattr(cli_service, "build_jm_current_state", lambda *_a, **_k: current_state)
    monkeypatch.setattr(cli_service, "HistoricalCatalog", lambda _session: object())
    monkeypatch.setattr(cli_service, "inventory_jm_legacy_assets", lambda *_a, **_k: ())
    monkeypatch.setattr(
        cli_service,
        "_require_shadow_legacy_plan",
        lambda *_a, **_k: {"plan_digest": "plan-digest", "shadow_assets": [{}]},
    )
    monkeypatch.setattr(cli_service, "MarketDataReader", lambda *_a, **_k: object())
    monkeypatch.setattr(
        cli_service,
        "_freeze_shadow_legacy_assets",
        lambda *_a, **_k: ({"market_data_file_id": 1},),
    )
    monkeypatch.setattr(cli_service, "jm_sessions", lambda *_a, **_k: sessions)

    class FakeCanonicalReader:
        def __init__(self, *, session_provider, **_kwargs):
            self.session_provider = session_provider

        def get_bars(self, query):
            selected = self.session_provider("jm", query.start, query.end)
            assert tuple(item.trading_day for item in selected) == (date(2013, 3, 29),)
            return SimpleNamespace(
                bars=(),
                source_datasets=(),
                manifest_digests=(),
                source_data_versions=(),
            )

    monkeypatch.setattr(cli_service, "CanonicalHistoricalReader", FakeCanonicalReader)

    class DiagnosticComplete(RuntimeError):
        pass

    def verify_production_readers(
        queries,
        *,
        canonical_reader,
        expected_keys_reader,
        **_kwargs,
    ):
        weekly = next(
            item
            for item in queries
            if item.dataset_kind == "continuous" and item.frequency == "1w"
        )
        canonical_reader(weekly)
        assert expected_keys_reader(weekly) == ("2013-03-29T00:00:00+00:00",)
        raise DiagnosticComplete

    monkeypatch.setattr(
        cli_service,
        "run_chunked_historical_shadow_query_set",
        verify_production_readers,
    )
    args = SimpleNamespace(
        project_root=tmp_path.resolve(),
        legacy_root=tmp_path.resolve(),
        canonical_root=canonical_root,
        start=start.isoformat(),
        end=end.isoformat(),
        exception_json=None,
        approval_packet=(tmp_path / "packet.json").resolve(),
        approval_hash="packet-hash",
        apply_receipt=receipt_path,
        apply_receipt_hash="receipt-digest",
    )

    with pytest.raises(DiagnosticComplete):
        cli_service._run_jm_historical_shadow(object(), args)


def test_expected_derived_keys_are_independent_session_bucket_ends() -> None:
    query = build_jm_shadow_query_set(
        start=datetime(2026, 7, 1, 1, tzinfo=UTC),
        end=datetime(2026, 7, 1, 1, 12, tzinfo=UTC),
    )[2]
    session = AggregationSession(
        trading_day=date(2026, 7, 1),
        name="day",
        start=datetime(2026, 7, 1, 1, tzinfo=UTC),
        end=datetime(2026, 7, 1, 1, 12, tzinfo=UTC),
    )

    assert query.frequency == "15m"
    assert expected_shadow_bar_keys(query, (session,)) == (
        "2026-07-01T01:12:00+00:00",
    )


def _legacy_asset(tmp_path: Path) -> LegacyAssetInventory:
    path = tmp_path / "jm_1m.parquet"
    path.write_bytes(b"approved legacy bytes")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    return LegacyAssetInventory(
        market_data_file_id=1,
        provider="rqdata",
        dataset_kind="continuous",
        symbol="jm",
        contract_or_series="JM88",
        period="1m",
        coverage_start="2026-07-01T00:00:00+00:00",
        coverage_end="2026-07-02T00:00:00+00:00",
        row_count=1,
        data_version="legacy-v1",
        data_role="primary",
        quality_status="passed",
        file_path=str(path),
        physical_exists=True,
        checksum_declared=checksum,
        checksum_actual=checksum,
        checksum_status="matched",
        source_intervals=("1m",),
        reader_symbol="jm",
        reader_contract="JM88",
        reader_period="1m",
    )


def test_shadow_legacy_plan_rejects_new_db_asset_even_when_excluded(
    tmp_path: Path,
) -> None:
    approved = _legacy_asset(tmp_path)
    approved_digest = build_jm_migration_plan((approved,))["plan_digest"]
    added = replace(
        approved,
        market_data_file_id=2,
        provider="local_parquet",
    )

    with pytest.raises(HistoricalApplyGateError, match="legacy_plan_mismatch"):
        cli_service._require_shadow_legacy_plan(
            (approved, added),
            approved_plan_digest=approved_digest,
        )


def test_shadow_plan_keeps_passed_primary_baseline_separate_from_direct_reuse(
    tmp_path: Path,
) -> None:
    baseline = replace(
        _legacy_asset(tmp_path),
        source_intervals=(),
    )

    plan = build_jm_migration_plan((baseline,))

    assert plan["eligible_assets"] == []
    assert plan["eligible_market_data_file_ids"] == []
    assert plan["shadow_assets"] == [asdict(baseline)]
    assert plan["shadow_market_data_file_ids"] == [baseline.market_data_file_id]


def test_shadow_baseline_accepts_only_plan_bound_source_intervals() -> None:
    assert cli_service._shadow_source_interval_compatible("1d", "1d", ())
    assert cli_service._shadow_source_interval_compatible("1m", "1d", ("1m",))
    assert not cli_service._shadow_source_interval_compatible((), "1d", ())
    assert not cli_service._shadow_source_interval_compatible(
        "5m",
        "1d",
        ("1m",),
    )


def test_shadow_freezes_exact_legacy_reader_identity_separately(
    tmp_path: Path,
) -> None:
    baseline = replace(
        _legacy_asset(tmp_path),
        contract_or_series="JM.MAIN",
        reader_contract="jm.MAIN",
    )
    evidence = {
        "market_data_file_id": baseline.market_data_file_id,
        "provider": baseline.provider,
        "data_role": baseline.data_role,
        "quality_status": baseline.quality_status,
        "data_version": baseline.data_version,
        "checksum": baseline.checksum_declared,
        "source_interval": "1m",
    }
    row = SimpleNamespace(
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="1m",
    )

    class FakeSession:
        def get(self, *_args, **_kwargs):
            return row

    class FakeLegacy:
        @staticmethod
        def asset_evidence(_row):
            return evidence

    frozen = cli_service._freeze_shadow_legacy_assets(
        FakeSession(),
        legacy=FakeLegacy(),
        shadow_assets=[asdict(baseline)],
    )

    assert cli_service._frozen_shadow_reader_identity(frozen) == (
        "jm",
        "jm.MAIN",
        "1m",
    )
    assert frozen[0]["contract_or_series"] == "JM.MAIN"
    with pytest.raises(
        HistoricalApplyGateError,
        match="legacy_reader_identity_ambiguous",
    ):
        cli_service._frozen_shadow_reader_identity(
            frozen + ({"market_data_file_id": 2},),
        )


def test_shadow_reader_identity_changes_the_approval_plan_digest(
    tmp_path: Path,
) -> None:
    baseline = replace(
        _legacy_asset(tmp_path),
        contract_or_series="JM.MAIN",
        reader_contract="jm.MAIN",
    )
    drifted = replace(baseline, reader_contract="JM.MAIN")

    assert (
        build_jm_migration_plan((baseline,))["plan_digest"]
        != build_jm_migration_plan((drifted,))["plan_digest"]
    )


def test_shadow_legacy_physical_checksum_is_rechecked_after_freeze(
    tmp_path: Path,
) -> None:
    approved = _legacy_asset(tmp_path)
    frozen = (
        {
            "file_path": approved.file_path,
            "checksum_actual": approved.checksum_actual,
        },
    )

    cli_service._verify_frozen_shadow_asset_checksums(frozen)
    Path(approved.file_path).write_bytes(b"drifted")

    with pytest.raises(
        HistoricalApplyGateError,
        match="legacy_physical_checksum_mismatch",
    ):
        cli_service._verify_frozen_shadow_asset_checksums(frozen)


def test_shadow_same_value_duplicate_is_allowed_but_conflict_is_rejected() -> None:
    query = _queries()[0]
    row = _row(query)

    same = compare_shadow_bars((row, dict(row)), (row,))

    assert same["status"] == "passed"
    with pytest.raises(ValueError, match="same-key conflict"):
        compare_shadow_bars(
            (row, {**row, "close": "999"}),
            (row,),
        )


def test_shadow_frozen_asset_rejects_db_file_path_drift(tmp_path: Path) -> None:
    original = tmp_path / "approved.parquet"
    replacement = tmp_path / "replacement.parquet"
    original.write_bytes(b"same bytes")
    replacement.write_bytes(b"same bytes")
    checksum = hashlib.sha256(original.read_bytes()).hexdigest()
    evidence = {"market_data_file_id": 1, "provider": "rqdata"}
    row = SimpleNamespace(
        file_path=str(replacement),
        instrument_symbol="jm",
        contract_code="JM88",
        period="1m",
    )

    class FakeSession:
        def get(self, *_args, **_kwargs):
            return row

    class FakeLegacy:
        project_root = tmp_path

        @staticmethod
        def asset_evidence(_row):
            return evidence

    frozen = (
        {
            "market_data_file_id": 1,
            "file_path": str(original),
            "checksum_actual": checksum,
            "db_evidence": evidence,
            "plan_evidence": {
                "symbol": "jm",
                "contract_or_series": "JM88",
                "period": "1m",
            },
        },
    )

    with pytest.raises(
        HistoricalApplyGateError,
        match="legacy_asset_evidence_mismatch",
    ):
        cli_service._verify_frozen_shadow_assets_current(
            FakeSession(),
            legacy=FakeLegacy(),
            assets=frozen,
        )


def test_shadow_final_state_rejects_mid_run_catalog_or_mapping_drift() -> None:
    with pytest.raises(HistoricalApplyGateError, match="apply_state_changed"):
        cli_service._require_shadow_final_state(
            initial_state={"state_digest": "a" * 64},
            final_state={"state_digest": "b" * 64},
            apply_receipt={"progress_state_digest": "a" * 64},
        )
