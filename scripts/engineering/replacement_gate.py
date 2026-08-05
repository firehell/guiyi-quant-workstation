#!/usr/bin/env python3
"""Replacement gate: deletion is allowed only after tests/references/validations pass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Sequence

_ENGINEERING_DIR = Path(__file__).resolve().parent
if str(_ENGINEERING_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINEERING_DIR))

from script_disposition import (  # noqa: E402
    DispositionAssignment,
    assert_protected_excluded,
    is_protected_resource,
    repository_deletion_plan,
)


@dataclass(frozen=True, slots=True)
class ReplacementGateInput:
    replacement_tests_passed: bool
    active_non_historical_references: int
    required_validations_passed: bool
    has_forwarding_shim: bool = False
    has_profile_alias: bool = False
    has_phase_numbered_alias: bool = False


@dataclass(frozen=True, slots=True)
class ReplacementGateResult:
    deletion_permitted: bool
    reasons: tuple[str, ...]


def evaluate_replacement_gate(payload: ReplacementGateInput) -> ReplacementGateResult:
    reasons: list[str] = []
    if not payload.replacement_tests_passed:
        reasons.append("replacement_tests_failed")
    if payload.active_non_historical_references != 0:
        reasons.append("active_references_remain")
    if not payload.required_validations_passed:
        reasons.append("required_validations_failed")
    if payload.has_forwarding_shim:
        reasons.append("forwarding_shim_present")
    if payload.has_profile_alias:
        reasons.append("profile_alias_present")
    if payload.has_phase_numbered_alias:
        reasons.append("phase_numbered_alias_present")
    return ReplacementGateResult(
        deletion_permitted=not reasons,
        reasons=tuple(reasons),
    )


def gated_deletion_plan(
    assignments: Sequence[DispositionAssignment],
    gate: ReplacementGateInput,
) -> tuple[str, ...]:
    decision = evaluate_replacement_gate(gate)
    if not decision.deletion_permitted:
        return ()
    plan = repository_deletion_plan(assignments)
    assert_protected_excluded(plan)
    return tuple(path for path in plan if not is_protected_resource(path))
