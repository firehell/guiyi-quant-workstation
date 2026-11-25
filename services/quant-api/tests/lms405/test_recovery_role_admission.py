from datetime import datetime, timedelta, timezone

import pytest

from lms405_recovery_role_admission import EXPLICIT_NEAR, terminal_candidate


@pytest.mark.parametrize(
    ("modes", "role", "publication_offset", "retrospective", "expected"),
    [
        (["NEAR"], EXPLICIT_NEAR, -1, False, "CONDITIONAL_PRICE_CANDIDATE_ONLY"),
        (["NEAR"], EXPLICIT_NEAR, 0, False, "SOURCE_NOT_STRICTLY_BEFORE_CANDIDATE"),
        (["NEAR"], EXPLICIT_NEAR, 1, False, "SOURCE_NOT_STRICTLY_BEFORE_CANDIDATE"),
        (["NEAR"], EXPLICIT_NEAR, None, False, "SOURCE_NOT_STRICTLY_BEFORE_CANDIDATE"),
        (["NEAR"], EXPLICIT_NEAR, 10, True, "RETROSPECTIVE_PRICE_CANDIDATE"),
        (["NEAR"], "STRONG_TARGET", -1, False, "NO_EXPLICIT_NEAR_RECOVERY_ROLE"),
        (["FAR"], EXPLICIT_NEAR, -1, False, "NEAR_PRICE_NOT_CONFIRMED"),
    ],
)
def test_near_edge_needs_recovery_role_visible_before_shape(modes, role, publication_offset, retrospective, expected):
    start = datetime(2026, 10, 27, 6, 10, tzinfo=timezone.utc)
    event = dict(modes=modes, shape_end=start + timedelta(minutes=5), shape_minutes=5)
    published = start + timedelta(minutes=publication_offset) if publication_offset is not None else None

    assert terminal_candidate(
        event, role=role, published_minute_end=published, retrospective=retrospective,
    ) == expected
