#!/usr/bin/env python3
"""
status_machine.py — 17-state status machine with transitions, permissions, and validation.

States (per Plan §3.1):
    Work states: DRAFT, EXECUTING, TESTING, REVIEWING, REPLAN
    Gate states: REQUIREMENT_READY, PLAN_READY, APPROVED, DELIVERY_READY, GATE_PASSED
    Terminal: CLOSED, CANCELLED, SKIPPED_NOT_APPLICABLE, SKIPPED_WITH_REASON
    Interrupt: BLOCKED, BLOCKED_BY_DEPENDENCY, FAILED

Usage:
    from status_machine import Status, is_valid_transition, allowed_stages, STATUS_ORDER
"""

from enum import Enum
from typing import Set, Dict, List, Optional


class Status(str, Enum):
    """17-state status enum."""
    DRAFT = "DRAFT"
    REQUIREMENT_READY = "REQUIREMENT_READY"
    PLAN_READY = "PLAN_READY"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    DELIVERY_READY = "DELIVERY_READY"
    GATE_PASSED = "GATE_PASSED"
    CLOSED = "CLOSED"
    BLOCKED = "BLOCKED"
    BLOCKED_BY_DEPENDENCY = "BLOCKED_BY_DEPENDENCY"
    FAILED = "FAILED"
    REPLAN = "REPLAN"
    CANCELLED = "CANCELLED"
    SKIPPED_NOT_APPLICABLE = "SKIPPED_NOT_APPLICABLE"
    SKIPPED_WITH_REASON = "SKIPPED_WITH_REASON"


# Terminal states — no further transitions allowed
TERMINAL_STATES: Set[Status] = {
    Status.CLOSED,
    Status.CANCELLED,
    Status.SKIPPED_NOT_APPLICABLE,
    Status.SKIPPED_WITH_REASON,
}

# Interrupt states — can be entered from many states, can recover
INTERRUPT_STATES: Set[Status] = {
    Status.BLOCKED,
    Status.BLOCKED_BY_DEPENDENCY,
    Status.FAILED,
}

# Gate states — require human approval to progress
GATE_STATES: Set[Status] = {
    Status.REQUIREMENT_READY,
    Status.PLAN_READY,
    Status.APPROVED,
    Status.DELIVERY_READY,
    Status.GATE_PASSED,
}

# ---- Valid transitions ----

VALID_TRANSITIONS: Dict[Status, Set[Status]] = {
    # Forward main line
    Status.DRAFT: {
        Status.REQUIREMENT_READY, Status.PLAN_READY,
        Status.SKIPPED_NOT_APPLICABLE, Status.SKIPPED_WITH_REASON,
        Status.CANCELLED,
    },
    Status.REQUIREMENT_READY: {
        Status.PLAN_READY, Status.DRAFT,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.CANCELLED,
    },
    Status.PLAN_READY: {
        Status.APPROVED, Status.DRAFT,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.CANCELLED,
    },
    Status.APPROVED: {
        Status.EXECUTING, Status.DRAFT,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.CANCELLED,
    },
    Status.EXECUTING: {
        Status.TESTING, Status.REVIEWING,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.FAILED, Status.CANCELLED,
    },
    Status.TESTING: {
        Status.REVIEWING, Status.EXECUTING,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.FAILED, Status.CANCELLED,
    },
    Status.REVIEWING: {
        Status.DELIVERY_READY, Status.GATE_PASSED, Status.EXECUTING,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.FAILED, Status.CANCELLED,
    },
    Status.DELIVERY_READY: {
        Status.CLOSED,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.CANCELLED,
    },
    Status.GATE_PASSED: {
        Status.DELIVERY_READY, Status.CLOSED,
        Status.CANCELLED,
    },

    # Interrupt recoveries
    Status.BLOCKED: {
        # Can recover to previous state (caller should specify exact target)
        Status.DRAFT, Status.REQUIREMENT_READY, Status.PLAN_READY,
        Status.APPROVED, Status.EXECUTING, Status.TESTING, Status.REVIEWING,
        Status.DELIVERY_READY,
        Status.CANCELLED, Status.FAILED,
    },
    Status.BLOCKED_BY_DEPENDENCY: {
        # Auto-recover to previous state when deps resolve
        Status.DRAFT, Status.REQUIREMENT_READY, Status.PLAN_READY,
        Status.APPROVED, Status.EXECUTING, Status.TESTING, Status.REVIEWING,
        Status.DELIVERY_READY,
        Status.CANCELLED,
    },
    Status.FAILED: {
        Status.REPLAN, Status.DRAFT,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.CANCELLED,
    },
    Status.REPLAN: {
        Status.PLAN_READY, Status.DRAFT,
        Status.BLOCKED, Status.BLOCKED_BY_DEPENDENCY,
        Status.CANCELLED,
    },

    # Terminal — outgoing
    Status.CLOSED: set(),
    Status.CANCELLED: set(),
    Status.SKIPPED_NOT_APPLICABLE: set(),
    Status.SKIPPED_WITH_REASON: set(),
}


# ---- Stage permissions ----

STAGE_PERMISSIONS: Dict[Status, Set[str]] = {
    Status.DRAFT:                    {"plan"},
    Status.REQUIREMENT_READY:        {"plan"},
    Status.PLAN_READY:               {"plan"},
    Status.APPROVED:                 {"dev", "fix"},
    Status.EXECUTING:                {"dev", "fix"},
    Status.TESTING:                  {"test", "fix"},
    Status.REVIEWING:                {"review", "fix"},
    Status.DELIVERY_READY:           {"result"},
    Status.GATE_PASSED:              {"result"},
    Status.CLOSED:                   set(),
    Status.BLOCKED:                  {"plan", "review"},
    Status.BLOCKED_BY_DEPENDENCY:    {"plan", "review"},
    Status.FAILED:                   {"fix"},
    Status.REPLAN:                   {"plan"},
    Status.CANCELLED:                set(),
    Status.SKIPPED_NOT_APPLICABLE:   set(),
    Status.SKIPPED_WITH_REASON:      set(),
}


# ---- Legacy status mapping (Plan §3.1.3) ----

LEGACY_TO_V2: Dict[str, Status] = {
    "IDEA": Status.DRAFT,
    "REQUIREMENT_READY": Status.REQUIREMENT_READY,
    "PLAN_READY": Status.PLAN_READY,
    "APPROVED_DEV": Status.APPROVED,
    "CODING": Status.EXECUTING,
    "TESTING": Status.TESTING,
    "DELIVERY_READY": Status.DELIVERY_READY,
    "CLOSED": Status.CLOSED,
    "PAUSED": Status.BLOCKED,
    "FAILED": Status.FAILED,
    "REPLAN": Status.REPLAN,
    "CANCELLED": Status.CANCELLED,
}

V2_TO_LEGACY: Dict[Status, str] = {v: k for k, v in LEGACY_TO_V2.items()}


# ---- Functions ----

def is_valid_transition(from_status: Status, to_status: Status) -> bool:
    """Check if a status transition is valid."""
    if from_status == to_status:
        return True  # No-op is always valid
    if from_status in TERMINAL_STATES:
        return False
    return to_status in VALID_TRANSITIONS.get(from_status, set())


def is_terminal(status: Status) -> bool:
    """Check if this status is terminal (no further transitions)."""
    return status in TERMINAL_STATES


def is_interrupt(status: Status) -> bool:
    """Check if this status is an interrupt (blocked/failed)."""
    return status in INTERRUPT_STATES


def is_gate(status: Status) -> bool:
    """Check if this status requires human approval."""
    return status in GATE_STATES


def allowed_stages(status: Status) -> Set[str]:
    """Return set of allowed stage names for a given status."""
    return STAGE_PERMISSIONS.get(status, set())


def can_execute_stage(status: Status, stage: str) -> bool:
    """Check if a specific stage is allowed for a given status."""
    return stage in STAGE_PERMISSIONS.get(status, set())


def map_legacy_status(legacy_status: str) -> Status:
    """Map a legacy status string to V2 Status enum."""
    if legacy_status in LEGACY_TO_V2:
        return LEGACY_TO_V2[legacy_status]
    # Try direct match
    try:
        return Status(legacy_status)
    except ValueError:
        raise ValueError(f"Unknown legacy status: '{legacy_status}'. Valid values: {list(LEGACY_TO_V2.keys())}")


def map_to_legacy(v2_status: Status) -> str:
    """Map V2 Status to legacy string (for backward compatibility)."""
    return V2_TO_LEGACY.get(v2_status, v2_status.value)


def valid_targets(from_status: Status) -> Set[Status]:
    """Return set of valid target statuses from a given status."""
    return VALID_TRANSITIONS.get(from_status, set())


# ---- Requirement-level Gate checks ----

def check_approval_scope_for_dev(
    risk_level: str,
    approval_scope: List[str],
    requested_stage: str,
) -> Optional[str]:
    """
    Check if approval_scope is sufficient for the requested stage.
    Returns None if OK, or an error message string.
    """
    # Map approval scopes to required scope per risk
    required_scopes = {
        "R0": {"dev": "code", "test": "code", "review": "external_review", "result": "production_write"},
        "R1": {"dev": "code", "test": "code", "review": "code"},
        "R2": {"dev": "code", "test": "code"},
        "R3": {},
    }

    reqs = required_scopes.get(risk_level, {})
    required = reqs.get(requested_stage)

    if required and required not in approval_scope:
        return f"Stage '{requested_stage}' requires approval_scope to include '{required}' (risk={risk_level}, current scope={approval_scope})"

    return None


# ---- CLI ----
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Status machine operations")
    parser.add_argument("command", choices=["check", "stages", "map", "list"])
    parser.add_argument("--from", dest="from_status", help="Source status")
    parser.add_argument("--to", dest="to_status", help="Target status")
    parser.add_argument("--stage", help="Stage to check permissions for")
    parser.add_argument("--legacy", help="Map legacy status to V2")
    args = parser.parse_args()

    if args.command == "check":
        if not args.from_status or not args.to_status:
            print("ERROR: --from and --to required for check", file=sys.stderr)
            sys.exit(1)
        try:
            frm = Status(args.from_status)
            to = Status(args.to_status)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

        if is_valid_transition(frm, to):
            print(f"✓ Valid: {frm.value} → {to.value}")
            sys.exit(0)
        else:
            print(f"✗ Invalid: {frm.value} → {to.value}")
            print(f"  Valid targets: {[s.value for s in valid_targets(frm)]}")
            sys.exit(1)

    elif args.command == "stages":
        if not args.from_status:
            print("ERROR: --from required for stages", file=sys.stderr)
            sys.exit(1)
        try:
            status = Status(args.from_status)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

        stages = allowed_stages(status)
        if args.stage:
            if args.stage in stages:
                print(f"✓ Stage '{args.stage}' allowed for {status.value}")
                sys.exit(0)
            else:
                print(f"✗ Stage '{args.stage}' NOT allowed for {status.value}")
                print(f"  Allowed: {stages}")
                sys.exit(1)
        else:
            print(f"Allowed stages for {status.value}: {stages}")

    elif args.command == "map":
        if not args.legacy:
            print("ERROR: --legacy required for map", file=sys.stderr)
            sys.exit(1)
        try:
            v2 = map_legacy_status(args.legacy)
            print(f"{args.legacy} → {v2.value}")
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        print("All 17 statuses:")
        for s in Status:
            terminal = " [TERMINAL]" if is_terminal(s) else ""
            interrupt = " [INTERRUPT]" if is_interrupt(s) else ""
            gate = " [GATE]" if is_gate(s) else ""
            stages = ", ".join(sorted(allowed_stages(s))) if allowed_stages(s) else "(none)"
            print(f"  {s.value}{terminal}{interrupt}{gate}")
            print(f"    Stages: {stages}")


if __name__ == "__main__":
    import sys
    main()
