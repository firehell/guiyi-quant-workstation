"""Current-status contract for the Lean Matrix Phase 3 pilot."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md"
PLANNED_BRANCH = "research/AI-TEAM-003-phase3-status-consistency-pilot"


def _design() -> str:
    return DESIGN.read_text(encoding="utf-8")


def _section(markdown: str, heading: str) -> str:
    body = markdown.split(f"## {heading}\n", 1)[1]
    return body.split("\n## ", 1)[0]


def test_phase_status_records_the_merged_phase_two_and_active_phase_three_pilot() -> None:
    """A stale pending-PR status must not hide Phase 2's merged evidence."""
    design = _design()
    phased_implementation = _section(design, "19. 分阶段实施")

    assert "Phase 2 merged through PR #101 at `develop@7a668eeb`" in design
    assert "remains pending Draft PR exact-head review, CI, and merge" not in design
    assert "Issue #102" in design
    assert PLANNED_BRANCH in design
    assert "Phase 3 is active under Issue #102 and is not merged" in design
    assert "implemented on its task branch only after tracked evidence exists" in design
    assert "PR #100 不能追认为该试运行" in phased_implementation


def test_current_phase_status_retains_the_no_new_authority_boundary() -> None:
    """A Phase 3 status correction must not grant higher-risk delivery authority."""
    design = _design()

    assert (
        "This does not authorize Phase 4 or Phase 5, `main`, Runtime, data writes, "
        "notifications, release, or deployment."
    ) in design
