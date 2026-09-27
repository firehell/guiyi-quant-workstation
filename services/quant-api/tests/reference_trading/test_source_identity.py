import pytest
from datetime import date

from app.reference_trading.query import QueryConflict
from app.reference_trading.source_identity import verify_saved_input_prefix


def test_bounded_page_can_use_saved_prefix_but_rejects_revised_fact() -> None:
    saved = {
        "reader": "newow_product_reader_v1",
        "input_fingerprints": ["first", "second", "third"],
        "calendar_session_effective_fingerprints": ["calendar-1", "calendar-2"],
        "boundaries": ["boundary-1", "boundary-2"],
        "lifecycle_owners": [["RB2610", "owner-1"]],
        "rank1": [["RB2610", "2026-09-01", "2026-09-30"]],
    }
    current = {
        "reader": "newow_product_reader_v1",
        "input_fingerprints": ["first", "second"],
        "calendar_session_effective_fingerprints": ["calendar-1"],
        "boundaries": ["boundary-1"],
        "lifecycle_owners": [["RB2610", "owner-1"]],
        "rank1": [["RB2610", "2026-09-01", "2026-09-30"]],
    }
    owners = frozenset({("RB2610", "owner-1")})
    verify_saved_input_prefix(saved, current, date(2026, 9, 30), owners)
    with pytest.raises(QueryConflict, match="SOURCE_IDENTITY_UNVERIFIED"):
        verify_saved_input_prefix(
            saved,
            {**current, "input_fingerprints": ["first", "revised"]},
            date(2026, 9, 30),
            owners,
        )
    with pytest.raises(QueryConflict, match="SOURCE_IDENTITY_UNVERIFIED"):
        verify_saved_input_prefix(
            saved,
            {**current, "lifecycle_owners": [["RB2610", "revised-owner"]]},
            date(2026, 9, 30),
            owners,
        )
    with pytest.raises(QueryConflict, match="SOURCE_IDENTITY_UNVERIFIED"):
        verify_saved_input_prefix(
            saved, {**current, "lifecycle_owners": []}, date(2026, 9, 30), owners
        )


def test_compact_intraday_source_proof_requires_exact_content_and_scope():
    saved = {
        "reader": "newow_product_reader_intraday_v3",
        "source_evidence_sha256": "a" * 64,
        "input_sha256": "b" * 64,
        "input_count": 870825,
    }
    current = dict(saved)
    verify_saved_input_prefix(saved, current, date(2026, 9, 24))
    for key, value in (("source_evidence_sha256", "c" * 64), ("input_count", 1)):
        changed = {**current, key: value}
        with pytest.raises(QueryConflict, match="SOURCE_IDENTITY_UNVERIFIED"):
            verify_saved_input_prefix(saved, changed, date(2026, 9, 24))
    with pytest.raises(QueryConflict, match="SOURCE_IDENTITY_UNVERIFIED"):
        verify_saved_input_prefix(saved, {}, date(2026, 9, 24))
