from __future__ import annotations

from collections.abc import Mapping

from app.data_core.consumer_identity import CanonicalConsumerInput
from app.data_core.contracts import DataCoreError
from app.schemas.signal import FORMAL_SIGNAL_AUXILIARY_PERIOD


def parse_formal_auxiliary_identities(
    primary: CanonicalConsumerInput,
    snapshots: object,
) -> dict[str, CanonicalConsumerInput]:
    primary_period = primary.request.frequency.value
    if primary_period != "1d" and primary_period not in FORMAL_SIGNAL_AUXILIARY_PERIOD:
        raise ValueError("SIGNAL_FORMAL_AUXILIARY_IDENTITY_INVALID")
    expected_period = FORMAL_SIGNAL_AUXILIARY_PERIOD.get(primary_period)
    expected_periods = set() if expected_period is None else {expected_period}
    if not isinstance(snapshots, Mapping) or set(snapshots) != expected_periods:
        raise ValueError("SIGNAL_FORMAL_AUXILIARY_IDENTITY_INVALID")
    try:
        identities = {
            str(period): CanonicalConsumerInput.from_snapshot(snapshot)
            for period, snapshot in snapshots.items()
            if isinstance(period, str) and isinstance(snapshot, Mapping)
        }
    except (DataCoreError, TypeError, ValueError) as exc:
        raise ValueError("SIGNAL_FORMAL_AUXILIARY_IDENTITY_INVALID") from exc
    if len(identities) != len(snapshots):
        raise ValueError("SIGNAL_FORMAL_AUXILIARY_IDENTITY_INVALID")
    for period, auxiliary in identities.items():
        if not _auxiliary_matches_primary(
            primary,
            auxiliary,
            expected_period=period,
        ):
            raise ValueError("SIGNAL_FORMAL_AUXILIARY_IDENTITY_INVALID")
    return identities


def _auxiliary_matches_primary(
    primary: CanonicalConsumerInput,
    auxiliary: CanonicalConsumerInput,
    *,
    expected_period: str,
) -> bool:
    primary_request = primary.request
    auxiliary_request = auxiliary.request
    same_derived_source = (
        primary.derived_frequency is not None
        and auxiliary.derived_frequency is not None
    )
    return (
        auxiliary_request.frequency.value == expected_period
        and auxiliary_request.dataset_kind is primary_request.dataset_kind
        and auxiliary_request.symbol == primary_request.symbol
        and auxiliary_request.contract_or_series
        == primary_request.contract_or_series
        and auxiliary_request.start == primary_request.start
        and auxiliary_request.end == primary_request.end
        and auxiliary_request.strict is primary_request.strict
        and auxiliary.strategy_input_version == primary.strategy_input_version
        and (
            not same_derived_source
            or (
                auxiliary.source_datasets == primary.source_datasets
                and auxiliary.manifest_digests == primary.manifest_digests
                and auxiliary.source_data_versions == primary.source_data_versions
            )
        )
    )
