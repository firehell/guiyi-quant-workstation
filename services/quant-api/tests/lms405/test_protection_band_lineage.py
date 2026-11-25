from lms405_protection_band_lineage import build_updates, selected, timeline
from lms405_right_side_study import US, at


def test_target_only_and_truncated_reuse_never_activate_protection():
    source = {"first": {"published_at": "2026-05-28T10:50:52+08:00"},
              "excerpt": {"published_at": "2026-05-28T10:54:17+08:00"}}
    rows = build_updates("OI2609", "LONG", (
        ("completed", "TARGET", "first", (9739, 9745)),
        ("pending", "REVIEW_PENDING", "excerpt", ()),
    ), source)
    first, second = timeline(rows, "OI2609", "LONG")
    assert first["afterward"]["unresolved"] == "PROTECTION_RANGE_UNAVAILABLE"
    assert second["exact"]["unresolved"] == "PROTECTION_RANGE_UNAVAILABLE"
    assert second["afterward"]["unresolved"] == "PROTECTION_RANGE_REVIEW_PENDING"


def test_late_archive_reading_does_not_supersede_newer_publication():
    sources = {"old": {"published_at": "2026-10-26T17:45:00+08:00"},
               "new": {"published_at": "2026-10-27T17:38:00+08:00"}}
    evidence = {"old": at("2026-10-27T22:51"), "new": at("2026-10-27T22:24")}
    updates = build_updates("SH2701", "SHORT", (
        ("earlier", "PROTECTION", "old", (1516, 1529)),
        ("later", "PROTECTION", "new", (1490, 1501)),
    ), sources)

    assert selected(updates, "SH2701", "SHORT", at("2026-10-27T22:12"), observations=evidence)["revision"] is None
    boundary = evidence["old"] + US
    assert selected(updates, "SH2701", "SHORT", boundary, observations=evidence)["revision"] == "later"
    clocks = timeline(updates, "SH2701", "SHORT", observations=evidence, checkpoints=evidence.values())
    assert [row["afterward"]["revision"] for row in clocks] == ["later", "later"]
