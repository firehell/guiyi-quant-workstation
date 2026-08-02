"""Deterministic Lane and specialist routing."""

from __future__ import annotations

from typing import Any


DOMAIN_SPECIALISTS = {
    "product-interaction": "product-interaction-specialist",
    "frontend": "frontend-specialist",
    "data-database": "data-database-specialist",
    "quant-research": "quant-research-specialist",
    "backtest-audit": "backtest-audit-specialist",
    "research-ai": "research-ai-specialist",
    "runtime-sre": "runtime-sre-specialist",
    "security": "security-specialist",
}
BASE_ROLES = ["ai-project-lead", "technical-lead", "implementer", "independent-quality-reviewer"]
LANE_DISPATCH = {
    1: ("Terra", "medium", "direct-or-short-plan", 2),
    2: ("Terra", "medium", "plan-then-execute", 3),
    3: ("Sol", "high", "plan-only-start", 4),
}


def dispatch_charter(charter: dict[str, Any]) -> dict[str, Any]:
    """Return the frozen schema-v1 legacy Charter dispatch payload."""
    model, reasoning_effort, mode, base_sessions = LANE_DISPATCH[charter["lane"]]
    independence = ["implementer and independent-quality-reviewer use separate contexts"]
    if {"quant-research", "backtest-audit"}.issubset(charter["domains"]):
        independence.append("quant-research-specialist and backtest-audit-specialist use separate contexts")
    return {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "mode": mode,
        "session_count": base_sessions + len(charter["specialists"]),
        "roles": BASE_ROLES,
        "specialists": charter["specialists"],
        "independence_requirements": independence,
    }
