from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    BarsResult,
    DataGapError,
    DatasetAmbiguousError,
    DatasetOrigin,
    DatasetKey,
    DatasetKind,
    ManifestLineage,
    ManifestMismatchError,
)


START = datetime(2026, 7, 29, 13, 0, tzinfo=UTC)
END = datetime(2026, 7, 29, 14, 0, tzinfo=UTC)


def _key(**overrides: object) -> DatasetKey:
    values: dict[str, object] = {
        "provider": "rqdata",
        "dataset_kind": DatasetKind.ACTUAL_DOMINANT,
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": BarFrequency.M1,
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    values.update(overrides)
    return DatasetKey(**values)  # type: ignore[arg-type]


def _bar(**overrides: object) -> CanonicalBar:
    values: dict[str, object] = {
        "provider": "rqdata",
        "dataset_kind": DatasetKind.ACTUAL_DOMINANT,
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": BarFrequency.M1,
        "bar_end": START + timedelta(minutes=1),
        "trading_day": date(2026, 7, 29),
        "open": Decimal("100"),
        "high": Decimal("102"),
        "low": Decimal("99"),
        "close": Decimal("101"),
        "volume": Decimal("1"),
        "turnover": None,
        "open_interest": None,
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    values.update(overrides)
    return CanonicalBar(**values)  # type: ignore[arg-type]


def test_enum_values_freeze_supported_dataset_kinds_and_frequencies() -> None:
    assert tuple(DatasetKind) == (
        DatasetKind.CONTINUOUS,
        DatasetKind.ACTUAL_DOMINANT,
    )
    assert [frequency.value for frequency in BarFrequency] == [
        "1m",
        "5m",
        "15m",
        "30m",
        "60m",
        "1d",
        "1w",
    ]


def test_dataset_key_normalizes_identity_and_is_frozen() -> None:
    key = _key(
        provider=" RQDATA ",
        dataset_kind="actual_dominant",
        symbol=" JM ",
        contract_or_series=" jm2609 ",
        frequency="1m",
        adjustment=" NONE ",
        schema_version=" canonical-bar-v1 ",
    )

    assert key == _key()
    with pytest.raises(FrozenInstanceError):
        key.symbol = "i"  # type: ignore[misc]


def test_dataset_key_keeps_continuous_and_actual_dominant_distinct() -> None:
    actual = _key()
    continuous = _key(
        dataset_kind=DatasetKind.CONTINUOUS,
        contract_or_series="JM.MAIN",
    )

    assert actual != continuous
    assert {actual, continuous} == {actual, continuous}


@pytest.mark.parametrize("frequency", tuple(BarFrequency))
def test_dataset_key_accepts_all_persisted_frequencies(
    frequency: BarFrequency,
) -> None:
    overrides: dict[str, object] = {"frequency": frequency}
    if frequency is BarFrequency.W1:
        overrides.update(
            dataset_kind=DatasetKind.CONTINUOUS,
            contract_or_series="JM.MAIN",
        )
    assert _key(**overrides).frequency is frequency


def test_direct_frequency_matrix_keeps_weekly_continuous_only() -> None:
    assert _key(
        dataset_kind=DatasetKind.CONTINUOUS,
        contract_or_series="JM.MAIN",
        frequency=BarFrequency.W1,
    ).frequency is BarFrequency.W1

    with pytest.raises(ValueError) as error:
        _key(frequency=BarFrequency.W1)

    assert error.value.facts == {
        "field": "frequency",
        "reason": "actual_dominant_weekly_not_supported",
        "value": "1w",
    }


@pytest.mark.parametrize(
    ("dataset_kind", "contract_or_series", "reason"),
    [
        (DatasetKind.CONTINUOUS, "JM2609", "continuous_series_required"),
        (DatasetKind.CONTINUOUS, "I.MAIN", "continuous_series_symbol_mismatch"),
        (DatasetKind.ACTUAL_DOMINANT, "JM.MAIN", "concrete_contract_required"),
        (DatasetKind.ACTUAL_DOMINANT, "I2609", "concrete_contract_symbol_mismatch"),
    ],
)
def test_dataset_key_rejects_semantically_incompatible_contract_identity(
    dataset_kind: DatasetKind,
    contract_or_series: str,
    reason: str,
) -> None:
    with pytest.raises(ValueError) as error:
        _key(dataset_kind=dataset_kind, contract_or_series=contract_or_series)

    assert error.value.facts == {
        "field": "contract_or_series",
        "reason": reason,
    }


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"provider": "local_parquet"}, "provider"),
        ({"frequency": "2m"}, "frequency"),
        ({"symbol": " "}, "symbol"),
        ({"contract_or_series": ""}, "contract_or_series"),
        ({"adjustment": "\t"}, "adjustment"),
        ({"schema_version": ""}, "schema_version"),
    ],
)
def test_dataset_key_rejects_noncanonical_identity(
    overrides: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(ValueError) as error:
        _key(**overrides)

    assert getattr(error.value, "facts")["field"] == reason


def test_manifest_lineage_accepts_exact_direct_and_aggregate_shapes() -> None:
    direct = ManifestLineage(origin=DatasetOrigin.PROVIDER_DIRECT)
    aggregate = ManifestLineage(
        origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
        source_frequency=BarFrequency.M1,
        legacy_source_checksum="a" * 64,
        quality_evidence_digest="b" * 64,
    )

    direct.validate_dataset(_key(frequency=BarFrequency.D1))
    aggregate.validate_dataset(_key(frequency=BarFrequency.M15))
    assert direct.as_payload() == {"origin": "provider_direct"}
    assert aggregate.as_payload() == {
        "origin": "preaggregated_from_1m",
        "source_frequency": "1m",
        "legacy_source_checksum": "a" * 64,
        "quality_evidence_digest": "b" * 64,
    }


@pytest.mark.parametrize(
    ("lineage", "frequency", "reason"),
    [
        (
            ManifestLineage(origin=DatasetOrigin.PROVIDER_DIRECT),
            BarFrequency.M5,
            "provider_direct_frequency_invalid",
        ),
        (
            ManifestLineage(
                origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
                source_frequency=BarFrequency.M1,
                legacy_source_checksum="a" * 64,
                quality_evidence_digest="b" * 64,
            ),
            BarFrequency.D1,
            "preaggregated_target_frequency_invalid",
        ),
    ],
)
def test_manifest_lineage_rejects_origin_frequency_mismatch_and_derived_daily(
    lineage: ManifestLineage,
    frequency: BarFrequency,
    reason: str,
) -> None:
    with pytest.raises(ValueError) as error:
        lineage.validate_dataset(_key(frequency=frequency))

    assert error.value.facts == {
        "field": "lineage",
        "reason": reason,
        "frequency": frequency.value,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_frequency": BarFrequency.M1},
        {"legacy_source_checksum": "a" * 64},
        {"quality_evidence_digest": "b" * 64},
    ],
)
def test_direct_lineage_rejects_fabricated_aggregate_fields(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ManifestLineage(
            origin=DatasetOrigin.PROVIDER_DIRECT,
            **overrides,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_frequency": None},
        {"source_frequency": BarFrequency.M5},
        {"legacy_source_checksum": None},
        {"legacy_source_checksum": "A" * 64},
        {"quality_evidence_digest": None},
        {"quality_evidence_digest": "short"},
    ],
)
def test_aggregate_lineage_requires_exact_m1_digest_bound_evidence(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "origin": DatasetOrigin.PREAGGREGATED_FROM_1M,
        "source_frequency": BarFrequency.M1,
        "legacy_source_checksum": "a" * 64,
        "quality_evidence_digest": "b" * 64,
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        ManifestLineage(**values)  # type: ignore[arg-type]


def test_bar_query_normalizes_identity_and_window_to_utc() -> None:
    shanghai = timezone(timedelta(hours=8))
    query = BarQuery(
        dataset_kind="continuous",  # type: ignore[arg-type]
        symbol=" JM ",
        contract_or_series=" jm.main ",
        frequency="15m",  # type: ignore[arg-type]
        start=datetime(2026, 7, 29, 21, 0, tzinfo=shanghai),
        end=datetime(2026, 7, 29, 22, 0, tzinfo=shanghai),
        strict=True,
    )

    assert query.dataset_kind is DatasetKind.CONTINUOUS
    assert query.symbol == "jm"
    assert query.contract_or_series == "JM.MAIN"
    assert query.frequency is BarFrequency.M15
    assert query.start == START
    assert query.end == END


@pytest.mark.parametrize(
    ("dataset_kind", "contract_or_series", "reason"),
    [
        (DatasetKind.CONTINUOUS, None, "continuous_series_required"),
        (DatasetKind.CONTINUOUS, "JM2609", "continuous_series_required"),
        (DatasetKind.ACTUAL_DOMINANT, "JM.MAIN", "concrete_contract_required"),
    ],
)
def test_bar_query_rejects_semantically_incompatible_contract_identity(
    dataset_kind: DatasetKind,
    contract_or_series: str | None,
    reason: str,
) -> None:
    with pytest.raises(ValueError) as error:
        BarQuery(
            dataset_kind=dataset_kind,
            symbol="jm",
            contract_or_series=contract_or_series,
            frequency=BarFrequency.M1,
            start=START,
            end=END,
        )

    assert error.value.facts == {
        "field": "contract_or_series",
        "reason": reason,
    }


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START.replace(tzinfo=None), END),
        (START, END.replace(tzinfo=None)),
        (END, START),
        (START, START),
    ],
)
def test_bar_query_rejects_naive_or_nonascending_window(
    start: datetime,
    end: datetime,
) -> None:
    with pytest.raises(ValueError) as error:
        BarQuery(
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol="jm",
            contract_or_series="JM2609",
            frequency=BarFrequency.M1,
            start=start,
            end=end,
        )

    assert getattr(error.value, "facts")["field"] == "window"


@pytest.mark.parametrize("strict", [0, 1, "true", None])
def test_bar_query_requires_an_explicit_bool(strict: object) -> None:
    with pytest.raises(ValueError) as error:
        BarQuery(
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol="jm",
            contract_or_series="JM2609",
            frequency=BarFrequency.M1,
            start=START,
            end=END,
            strict=strict,  # type: ignore[arg-type]
        )

    assert getattr(error.value, "facts")["field"] == "strict"


def test_bars_result_freezes_sequences_and_normalizes_window() -> None:
    source = _key()
    bar = _bar(frequency=BarFrequency.M15)
    shanghai = timezone(timedelta(hours=8))
    result = BarsResult(
        bars=[bar],
        source_datasets=[source],
        manifest_digests=["a" * 64],
        requested_window=(
            datetime(2026, 7, 29, 21, 0, tzinfo=shanghai),
            datetime(2026, 7, 29, 22, 0, tzinfo=shanghai),
        ),
        data_type="actual_dominant",  # type: ignore[arg-type]
        derived_frequency="15m",  # type: ignore[arg-type]
    )

    assert result.bars == (bar,)
    assert result.source_datasets == (source,)
    assert result.manifest_digests == ("a" * 64,)
    assert result.requested_window == (START, END)
    assert result.data_type is DatasetKind.ACTUAL_DOMINANT
    assert result.derived_frequency is BarFrequency.M15


def test_bars_result_preserves_strictly_increasing_bar_order() -> None:
    bars = (
        _bar(bar_end=START + timedelta(minutes=1)),
        _bar(bar_end=START + timedelta(minutes=2)),
    )

    result = BarsResult(
        bars=bars,
        source_datasets=(_key(),),
        manifest_digests=("a" * 64,),
        requested_window=(START, END),
        data_type=DatasetKind.ACTUAL_DOMINANT,
        derived_frequency=None,
    )

    assert result.bars == bars


@pytest.mark.parametrize(
    "bars",
    [
        (
            _bar(bar_end=START + timedelta(minutes=2)),
            _bar(bar_end=START + timedelta(minutes=1)),
        ),
        (
            _bar(bar_end=START + timedelta(minutes=1)),
            _bar(bar_end=START + timedelta(minutes=1)),
        ),
    ],
)
def test_bars_result_rejects_reversed_or_duplicate_bar_end(
    bars: tuple[CanonicalBar, CanonicalBar],
) -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=bars,
            source_datasets=(_key(),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(error.value, "facts") == {
        "field": "bars",
        "reason": "bar_end_not_strictly_increasing",
    }


@pytest.mark.parametrize(
    "bar_end",
    [
        START,
        END + timedelta(microseconds=1),
    ],
)
def test_bars_result_requires_each_bar_in_requested_open_closed_window(
    bar_end: datetime,
) -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(_bar(bar_end=bar_end),),
            source_datasets=(_key(),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(error.value, "facts") == {
        "field": "bars",
        "reason": "bar_outside_requested_window",
        "bar_end": bar_end.isoformat(),
    }


def test_bars_result_allows_bar_at_requested_window_end() -> None:
    bar = _bar(bar_end=END)

    result = BarsResult(
        bars=(bar,),
        source_datasets=(_key(),),
        manifest_digests=("a" * 64,),
        requested_window=(START, END),
        data_type=DatasetKind.ACTUAL_DOMINANT,
        derived_frequency=None,
    )

    assert result.bars == (bar,)


def test_bars_result_rejects_noncanonical_bar_items() -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(object(),),
            source_datasets=(_key(),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(error.value, "facts") == {
        "field": "bars",
        "reason": "invalid_item",
    }


@pytest.mark.parametrize(
    "source",
    [
        _key(symbol="i", contract_or_series="I2609"),
        _key(contract_or_series="JM2605"),
        _key(adjustment="pre"),
        _key(schema_version="canonical-bar-v2"),
    ],
)
def test_bars_result_requires_bar_identity_to_match_a_source_dataset(
    source: DatasetKey,
) -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(_bar(),),
            source_datasets=(source,),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(error.value, "facts") == {
        "field": "bars",
        "reason": "source_dataset_identity_mismatch",
        "bar_end": (START + timedelta(minutes=1)).isoformat(),
    }


@pytest.mark.parametrize(
    "derived_frequency",
    [BarFrequency.M1, BarFrequency.D1, BarFrequency.W1],
)
def test_bars_result_rejects_non_derived_frequency(
    derived_frequency: BarFrequency,
) -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(),
            source_datasets=(_key(),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=derived_frequency,
        )

    assert getattr(error.value, "facts")["field"] == "derived_frequency"


def test_bars_result_requires_derived_bars_to_match_frequency_and_m1_source() -> None:
    with pytest.raises(ValueError) as bar_error:
        BarsResult(
            bars=(_bar(frequency=BarFrequency.M5),),
            source_datasets=(_key(),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=BarFrequency.M15,
        )

    assert getattr(bar_error.value, "facts") == {
        "field": "bars",
        "reason": "derived_bar_frequency_mismatch",
        "expected": "15m",
        "actual": "5m",
    }

    with pytest.raises(ValueError) as source_error:
        BarsResult(
            bars=(_bar(frequency=BarFrequency.M5),),
            source_datasets=(_key(frequency=BarFrequency.D1),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=BarFrequency.M5,
        )

    assert getattr(source_error.value, "facts") == {
        "field": "source_datasets",
        "reason": "derived_source_frequency_must_be_1m",
    }


def test_bars_result_requires_direct_bar_frequency_to_match_source() -> None:
    with pytest.raises(ValueError) as non_direct_error:
        BarsResult(
            bars=(_bar(frequency=BarFrequency.M5),),
            source_datasets=(_key(),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(non_direct_error.value, "facts") == {
        "field": "bars",
        "reason": "direct_bar_frequency_required",
        "actual": "5m",
    }

    with pytest.raises(ValueError) as mismatch_error:
        BarsResult(
            bars=(_bar(frequency=BarFrequency.D1),),
            source_datasets=(_key(frequency=BarFrequency.M1),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(mismatch_error.value, "facts") == {
        "field": "bars",
        "reason": "direct_source_frequency_mismatch",
        "bar_end": (START + timedelta(minutes=1)).isoformat(),
    }


def test_bars_result_requires_nonempty_source_datasets() -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(),
            source_datasets=(),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(error.value, "facts") == {
        "field": "source_datasets",
        "reason": "empty",
    }


def test_bars_result_rejects_derived_result_with_non_m1_source_when_empty() -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(),
            source_datasets=(_key(frequency=BarFrequency.D1),),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=BarFrequency.M15,
        )

    assert getattr(error.value, "facts") == {
        "field": "source_datasets",
        "reason": "derived_source_frequency_must_be_1m",
    }


@pytest.mark.parametrize(
    "sources",
    [
        (
            _key(frequency=BarFrequency.M1),
            _key(frequency=BarFrequency.D1),
        ),
        (
            _key(),
            _key(symbol="i", contract_or_series="I2609"),
        ),
        (
            _key(),
            _key(schema_version="canonical-bar-v2"),
        ),
        (
            _key(),
            _key(adjustment="pre"),
        ),
    ],
)
def test_bars_result_rejects_mixed_source_family(
    sources: tuple[DatasetKey, DatasetKey],
) -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(),
            source_datasets=sources,
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(error.value, "facts") == {
        "field": "source_datasets",
        "reason": "source_family_mismatch",
    }


def test_contract_rejects_a_second_noncanonical_continuous_series() -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(),
            source_datasets=(
                _key(
                    dataset_kind=DatasetKind.CONTINUOUS,
                    contract_or_series="JM.MAIN",
                ),
                _key(
                    dataset_kind=DatasetKind.CONTINUOUS,
                    contract_or_series="JM889",
                ),
            ),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.CONTINUOUS,
            derived_frequency=None,
        )

    assert getattr(error.value, "facts") == {
        "field": "contract_or_series",
        "reason": "continuous_series_required",
    }


def test_bars_result_allows_actual_family_with_multiple_contracts() -> None:
    first = _bar(
        contract_or_series="JM2605",
        bar_end=START + timedelta(minutes=1),
    )
    second = _bar(
        contract_or_series="JM2609",
        bar_end=START + timedelta(minutes=2),
    )

    result = BarsResult(
        bars=(first, second),
        source_datasets=(
            _key(contract_or_series="JM2609"),
            _key(contract_or_series="JM2605"),
        ),
        manifest_digests=("a" * 64,),
        requested_window=(START, END),
        data_type=DatasetKind.ACTUAL_DOMINANT,
        derived_frequency=None,
    )

    assert result.bars == (first, second)
    assert tuple(
        source.contract_or_series for source in result.source_datasets
    ) == ("JM2605", "JM2609")


def test_bars_result_rejects_source_dataset_kind_mismatch() -> None:
    with pytest.raises(ValueError) as error:
        BarsResult(
            bars=(),
            source_datasets=(
                _key(
                    dataset_kind=DatasetKind.CONTINUOUS,
                    contract_or_series="JM.MAIN",
                ),
            ),
            manifest_digests=("a" * 64,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert getattr(error.value, "facts") == {
        "field": "data_type",
        "reason": "source_dataset_kind_mismatch",
    }


def test_bars_result_canonicalizes_independent_lineage_sets() -> None:
    source_a = _key(contract_or_series="JM2609")
    source_b = _key(contract_or_series="JM2605")
    values = {
        "bars": (_bar(),),
        "requested_window": (START, END),
        "data_type": DatasetKind.ACTUAL_DOMINANT,
        "derived_frequency": None,
    }

    first = BarsResult(
        source_datasets=(source_a, source_b, source_a),
        manifest_digests=(" " + "B" * 64 + " ", "a" * 64, "B" * 64),
        **values,
    )
    second = BarsResult(
        source_datasets=(source_b, source_a),
        manifest_digests=("a" * 64, "b" * 64),
        **values,
    )

    assert first == second
    assert first.source_datasets == (source_b, source_a)
    assert first.manifest_digests == ("a" * 64, "b" * 64)


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "a" * 63,
        "a" * 65,
        "g" * 64,
        "ab-cd" * 13,
    ],
)
def test_bars_result_rejects_invalid_manifest_digest(digest: str) -> None:
    with pytest.raises(ManifestMismatchError) as error:
        BarsResult(
            bars=(),
            source_datasets=(_key(),),
            manifest_digests=(digest,),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert error.value.code == "MANIFEST_MISMATCH"
    assert error.value.facts == {"reason": "invalid_manifest_digest"}


def test_bars_result_rejects_empty_manifest_digest_set() -> None:
    with pytest.raises(ManifestMismatchError) as error:
        BarsResult(
            bars=(),
            source_datasets=(_key(),),
            manifest_digests=(),
            requested_window=(START, END),
            data_type=DatasetKind.ACTUAL_DOMINANT,
            derived_frequency=None,
        )

    assert error.value.code == "MANIFEST_MISMATCH"
    assert error.value.facts == {"reason": "manifest_digests_empty"}


def test_manifest_digest_error_facts_do_not_depend_on_input_order() -> None:
    valid = "a" * 64
    invalid = "g" * 64
    diagnostics: list[dict[str, object]] = []

    for digests in ((valid, invalid), (invalid, valid)):
        with pytest.raises(ManifestMismatchError) as error:
            BarsResult(
                bars=(),
                source_datasets=(_key(),),
                manifest_digests=digests,
                requested_window=(START, END),
                data_type=DatasetKind.ACTUAL_DOMINANT,
                derived_frequency=None,
            )
        diagnostics.append(dict(error.value.facts))

    assert diagnostics == [
        {"reason": "invalid_manifest_digest"},
        {"reason": "invalid_manifest_digest"},
    ]


def test_non_string_manifest_digest_has_stable_facts() -> None:
    valid = "a" * 64
    diagnostics: list[dict[str, object]] = []

    for digests in ((valid, 123), (123, valid)):
        with pytest.raises(ManifestMismatchError) as error:
            BarsResult(
                bars=(),
                source_datasets=(_key(),),
                manifest_digests=digests,  # type: ignore[arg-type]
                requested_window=(START, END),
                data_type=DatasetKind.ACTUAL_DOMINANT,
                derived_frequency=None,
            )
        diagnostics.append(dict(error.value.facts))

    assert diagnostics == [
        {"reason": "invalid_manifest_digest"},
        {"reason": "invalid_manifest_digest"},
    ]


@pytest.mark.parametrize(
    ("error_type", "code"),
    [
        (DataGapError, "DATA_GAP"),
        (DatasetAmbiguousError, "DATASET_AMBIGUOUS"),
        (ManifestMismatchError, "MANIFEST_MISMATCH"),
    ],
)
def test_contract_errors_expose_stable_code_and_structured_facts(
    error_type: type[ValueError],
    code: str,
) -> None:
    error = error_type(facts={"symbol": "jm", "reason": "synthetic"})  # type: ignore[call-arg]

    assert getattr(error, "code") == code
    assert dict(getattr(error, "facts")) == {
        "symbol": "jm",
        "reason": "synthetic",
    }
    assert str(error) == code
    with pytest.raises(TypeError):
        getattr(error, "facts")["symbol"] = "i"
