#!/usr/bin/env python3
"""
risk_resolver.py — R0-R3 risk level auto-inference and mixed-risk normalization.

Rules (per Plan §3.2):
    1. Take the HIGHEST risk: R0 > R1 > R2 > R3
    2. R0 veto: any R0 trigger hit → task forced to R0
    3. Path priority over keyword inference
    4. Human can UPGRADE risk but NOT downgrade (especially R0→R1 forbidden)
    5. Auto-inference results recorded to .ai/results/<ID>/risk_resolution.json

Usage:
    from risk_resolver import resolve_risk_level, normalize_mixed_risk, RESOLVE_ORDER
"""

import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class RiskLevel(str, Enum):
    """Risk levels ordered by severity (R0 most severe)."""
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


RESOLVE_ORDER = {RiskLevel.R0: 0, RiskLevel.R1: 1, RiskLevel.R2: 2, RiskLevel.R3: 3}

# ---- R0 detection patterns ----
R0_PATHS = [
    ".env", "token", "webhook", "secrets", "credentials",
    ".env.", "config/secrets", "config/credentials",
]

R0_KEYWORDS = [
    r"自动交易", r"auto.*order", r"send_order",
    r"DROP\s+TABLE", r"rm\s+-rf\s+data",
    r"密钥", r"token\s*=", r"密码", r"secret_key",
    r"api_key\s*=", r"webhook_url\s*=",
]

# ---- R1 detection patterns ----
R1_PATHS = [
    "strategies/", "backtest/", "indicators/", "signals/",
    "risk/", "portfolio/", "engine/",
]

R1_KEYWORDS = [
    r"策略", r"回测", r"\bEMA\b", r"\bMACD\b", r"信号生成",
    r"风控", r"POSITION", r"止损", r"止盈", r"仓位",
    r"杜邦", r"杠杆", r"期权", r"期权定价", r"套利",
    r"DuckDB", r"PostgreSQL", r"数据库",
]

# ---- R2 detection patterns ----
R2_PATHS = [
    "services/", "apps/", "packages/", "scripts/",
    "config/", "src/", "lib/",
]


@dataclass
class RiskResolution:
    """Record of how a risk level was determined."""
    task_id: str
    resolved_level: RiskLevel
    triggers: List[str] = field(default_factory=list)
    explicit: bool = False
    human_override: bool = False
    inference_reason: str = ""


def _matches_any_path(paths: List[str], patterns: List[str]) -> bool:
    """Check if any path/glob matches any pattern."""
    if not paths:
        return False
    for p in paths:
        p_lower = p.lower() if p else ""
        for pattern in patterns:
            if pattern in p_lower:
                return True
    return False


def _matches_any_keyword(text: str, patterns: List[str]) -> bool:
    """Check if any regex pattern matches the text."""
    if not text:
        return False
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def infer_risk_level(
    allowed_paths: Optional[List[str]] = None,
    forbidden_paths: Optional[List[str]] = None,
    body_text: str = "",
) -> RiskLevel:
    """
    Auto-infer risk level from paths and body text.
    Returns the highest triggered risk level.
    """
    all_paths = (allowed_paths or []) + (forbidden_paths or [])
    triggers = []

    # R0 check first (veto)
    if _matches_any_path(all_paths, R0_PATHS) or _matches_any_keyword(body_text, R0_KEYWORDS):
        return RiskLevel.R0

    # R1 check
    if _matches_any_path(all_paths, R1_PATHS) or _matches_any_keyword(body_text, R1_KEYWORDS):
        return RiskLevel.R1

    # R2 check
    if _matches_any_path(all_paths, R2_PATHS):
        return RiskLevel.R2

    # R3 fallback
    return RiskLevel.R3


def resolve_risk_level(
    task_id: str,
    explicit_risk: Optional[str] = None,
    allowed_paths: Optional[List[str]] = None,
    forbidden_paths: Optional[List[str]] = None,
    body_text: str = "",
) -> RiskResolution:
    """
    Full risk resolution pipeline:
    1. If explicit risk provided, validate it
    2. Auto-infer from paths/text
    3. Apply normalization (human can upgrade, can't downgrade; R0 can't be downgraded)
    4. Return RiskResolution record
    """
    inferred = infer_risk_level(allowed_paths, forbidden_paths, body_text)
    triggers = _collect_triggers(allowed_paths or [], forbidden_paths or [], body_text)

    if explicit_risk and explicit_risk in RiskLevel.__members__:
        explicit = RiskLevel(explicit_risk)

        # R0 can't be downgraded
        if inferred == RiskLevel.R0 and explicit != RiskLevel.R0:
            return RiskResolution(
                task_id=task_id,
                resolved_level=RiskLevel.R0,
                triggers=triggers,
                explicit=False,
                human_override=False,
                inference_reason=f"Inferred R0 from paths/text; human override '{explicit.value}' rejected (R0 veto)"
            )

        # Human can upgrade, not downgrade
        if RESOLVE_ORDER[explicit] <= RESOLVE_ORDER[inferred]:
            final = explicit
            is_override = explicit != inferred
        else:
            # Human tried to downgrade — use inferred (higher severity)
            final = inferred
            is_override = False

        return RiskResolution(
            task_id=task_id,
            resolved_level=final,
            triggers=triggers,
            explicit=True,
            human_override=is_override,
            inference_reason=f"Inferred={inferred.value}, explicit={explicit.value}, final={final.value}"
        )

    # No explicit — use inferred
    return RiskResolution(
        task_id=task_id,
        resolved_level=inferred,
        triggers=triggers,
        explicit=False,
        human_override=False,
        inference_reason=f"Inferred {inferred.value} from paths/text"
    )


def _collect_triggers(
    allowed_paths: List[str],
    forbidden_paths: List[str],
    body_text: str,
) -> List[str]:
    """Collect which patterns triggered the risk detection."""
    all_paths = allowed_paths + forbidden_paths
    triggers = []

    for pattern in R0_PATHS:
        if any(pattern in (p or "").lower() for p in all_paths):
            triggers.append(f"R0_path:{pattern}")
    for pattern in R0_KEYWORDS:
        if re.search(pattern, body_text, re.IGNORECASE):
            triggers.append(f"R0_keyword:{pattern}")

    for pattern in R1_PATHS:
        if any(pattern in (p or "").lower() for p in all_paths):
            triggers.append(f"R1_path:{pattern}")
    for pattern in R1_KEYWORDS:
        if re.search(pattern, body_text, re.IGNORECASE):
            triggers.append(f"R1_keyword:{pattern}")

    for pattern in R2_PATHS:
        if any(pattern in (p or "").lower() for p in all_paths):
            triggers.append(f"R2_path:{pattern}")

    if not triggers:
        triggers.append("R3:no_triggers")

    return triggers


def normalize_mixed_risk(resolutions: List[RiskResolution]) -> RiskResolution:
    """
    Normalize multiple risk resolutions for mixed-risk tasks.
    Rule: take the highest (most severe) risk level.
    """
    if not resolutions:
        raise ValueError("At least one RiskResolution required")

    # R0=0, R1=1, R2=2, R3=3 — lower number = higher severity
    highest = min(resolutions, key=lambda r: (RESOLVE_ORDER[r.resolved_level], 0))

    # Merge triggers from all resolutions
    all_triggers = []
    for r in resolutions:
        all_triggers.extend(r.triggers)

    return RiskResolution(
        task_id=highest.task_id,
        resolved_level=highest.resolved_level,
        triggers=list(set(all_triggers)),
        explicit=highest.explicit,
        human_override=highest.human_override,
        inference_reason=f"Normalized from {len(resolutions)} resolutions, highest={highest.resolved_level.value}"
    )


def write_risk_resolution(resolution: RiskResolution, results_dir: Path):
    """Write RiskResolution to .ai/results/<ID>/risk_resolution.json."""
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / "risk_resolution.json"

    record = {
        "task_id": resolution.task_id,
        "resolved_level": resolution.resolved_level.value,
        "triggers": resolution.triggers,
        "explicit": resolution.explicit,
        "human_override": resolution.human_override,
        "inference_reason": resolution.inference_reason,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    return output_path


# ---- CLI ----
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Resolve risk level for a task")
    parser.add_argument("--task-id", required=True, help="Task ID")
    parser.add_argument("--explicit-risk", help="Explicitly declared risk level (R0-R3)")
    parser.add_argument("--allowed-paths", nargs="*", default=[], help="Allowed file paths")
    parser.add_argument("--forbidden-paths", nargs="*", default=[], help="Forbidden file paths")
    parser.add_argument("--body", default="", help="Task body text for keyword scanning")
    parser.add_argument("--output-dir", help="Output directory for risk_resolution.json")
    args = parser.parse_args()

    resolution = resolve_risk_level(
        task_id=args.task_id,
        explicit_risk=args.explicit_risk,
        allowed_paths=args.allowed_paths if args.allowed_paths else None,
        forbidden_paths=args.forbidden_paths if args.forbidden_paths else None,
        body_text=args.body,
    )

    print(f"Risk Resolution: {resolution.resolved_level.value}")
    print(f"  Triggers: {resolution.triggers}")
    print(f"  Reason: {resolution.inference_reason}")
    print(f"  Explicit: {resolution.explicit}")
    print(f"  Human Override: {resolution.human_override}")

    if args.output_dir:
        path = write_risk_resolution(resolution, Path(args.output_dir))
        print(f"  Written to: {path}")


if __name__ == "__main__":
    main()
