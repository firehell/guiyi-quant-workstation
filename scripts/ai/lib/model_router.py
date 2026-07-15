"""Model Router — WS-V2-006

Maps abstract model profiles (economy/balanced/deep) to concrete model names
via a single configuration file. Enforces degradation recording and prevents
silent degradation for R2/R3 tasks.

Design:
- Only three tiers: economy, balanced, deep.
- Single mapping file: configs/ai/model_routing.json
- Degradation is always logged. R2/R3 tasks must NOT silently degrade below
  their declared profile.
- If a model is unavailable and cannot degrade, raise ModelUnavailableError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import sys
import time


# ── Constants ────────────────────────────────────────────────────────────────

VALID_PROFILES = frozenset({"economy", "balanced", "deep"})

PROFILE_TIER = {
    "economy": 0,
    "balanced": 1,
    "deep": 2,
}

RISK_DEGRADATION_ALLOWED = {
    "R0": True,   # R0: read-only, degradation acceptable
    "R1": True,   # R1: degradation must be logged but acceptable
    "R2": False,  # R2: no silent degradation
    "R3": False,  # R3: no silent degradation
}

DEFAULT_CONFIG_PATH = "configs/ai/model_routing.json"


# ── Types ────────────────────────────────────────────────────────────────────

class ModelUnavailableError(Exception):
    """Raised when required model tier is unavailable and degradation is blocked."""

    def __init__(self, requested: str, available: str, risk_level: str) -> None:
        super().__init__(
            f"Model '{requested}' unavailable, degradation to '{available}' "
            f"blocked for risk={risk_level}"
        )
        self.requested = requested
        self.available = available
        self.risk_level = risk_level


@dataclass
class ModelConfig:
    """Single model entry from routing config."""
    name: str
    provider: str
    reasoning: bool = False
    max_tokens: int = 4096
    fallback: Optional[str] = None


@dataclass
class RoutingConfig:
    """Top-level model routing configuration."""
    profiles: Dict[str, ModelConfig] = field(default_factory=dict)
    default_profile: str = "balanced"
    degradation_log_enabled: bool = True
    degradation_log_dir: str = ".ai/results"


@dataclass
class DegradationRecord:
    """Logged when a model degrades to a lower tier."""
    timestamp: str
    task_id: str
    risk_level: str
    requested_profile: str
    actual_profile: str
    requested_model: str
    actual_model: str
    reason: str


# ── Config Loading ───────────────────────────────────────────────────────────

def load_routing_config(config_path: Optional[str] = None) -> RoutingConfig:
    """Load model routing configuration from JSON file."""
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        # Resolve relative to script directory
        script_dir = Path(__file__).resolve().parent.parent.parent.parent
        cfg_path = script_dir / config_path

    if not cfg_path.is_file():
        raise FileNotFoundError(f"Model routing config not found: {cfg_path}")

    data = json.loads(cfg_path.read_text(encoding="utf-8"))

    profiles: Dict[str, ModelConfig] = {}
    for profile_name, profile_data in data.get("profiles", {}).items():
        if profile_name not in VALID_PROFILES:
            continue
        profiles[profile_name] = ModelConfig(
            name=profile_data.get("name", ""),
            provider=profile_data.get("provider", ""),
            reasoning=profile_data.get("reasoning", False),
            max_tokens=profile_data.get("max_tokens", 4096),
            fallback=profile_data.get("fallback"),
        )

    default_profile = data.get("default_profile", "balanced")
    if default_profile not in VALID_PROFILES:
        default_profile = "balanced"

    return RoutingConfig(
        profiles=profiles,
        default_profile=default_profile,
        degradation_log_enabled=data.get("degradation_log_enabled", True),
        degradation_log_dir=data.get("degradation_log_dir", ".ai/results"),
    )


# ── Profile to Profile Mapping ───────────────────────────────────────────────

def map_task_profile(task_profile: str) -> str:
    """Map legacy task profiles to the three-tier economy/balanced/deep."""
    mapping = {
        "fast": "economy",
        "standard": "balanced",
        "deep": "deep",
        "critical": "deep",
        "economy": "economy",
        "balanced": "balanced",
    }
    return mapping.get(task_profile, "balanced")


# ── Degradation ──────────────────────────────────────────────────────────────

def _check_degradation_allowed(from_profile: str, to_profile: str, risk_level: str) -> None:
    """Raise ModelUnavailableError if degradation is not allowed for the risk level."""
    from_tier = PROFILE_TIER.get(from_profile, 1)
    to_tier = PROFILE_TIER.get(to_profile, 0)
    if to_tier < from_tier:
        risk_level_norm = risk_level.upper()
        if not RISK_DEGRADATION_ALLOWED.get(risk_level_norm, False):
            raise ModelUnavailableError(
                requested=from_profile,
                available=to_profile,
                risk_level=risk_level_norm,
            )


def resolve_with_degradation(
    requested_profile: str,
    risk_level: str,
    config: RoutingConfig,
    *,
    task_id: str = "",
    skip_unavailable: Optional[List[str]] = None,
) -> Tuple[ModelConfig, str]:
    """
    Resolve the best available model for a given profile.

    Returns (ModelConfig, actual_profile).
    Raises ModelUnavailableError if no suitable model and degradation is blocked.
    """
    unavailable = set(skip_unavailable or [])

    # Normalize profile
    profile = requested_profile.lower()
    if profile not in VALID_PROFILES:
        profile = config.default_profile

    requested_tier = PROFILE_TIER.get(profile, 1)

    # Try exact match first
    if profile in config.profiles:
        exact = config.profiles[profile]
        if exact.name and exact.name not in unavailable:
            return exact, profile

    # Iterate fallback chain
    current_profile = profile
    checked: List[str] = []

    while True:
        cfg = config.profiles.get(current_profile)
        if cfg and cfg.name and cfg.name not in unavailable:
            return cfg, current_profile

        if cfg and cfg.fallback:
            if cfg.fallback in checked:
                break  # circular fallback
            # Check degradation before following explicit fallback
            _check_degradation_allowed(current_profile, cfg.fallback, risk_level)
            checked.append(current_profile)
            current_profile = cfg.fallback
            continue

        # No fallback configured — try tier degradation
        break

    # Degrade: try lower tiers
    for degrade_to in ("balanced", "economy"):
        if degrade_to not in config.profiles:
            continue
        if degrade_to in checked:
            continue
        cfg = config.profiles[degrade_to]
        if cfg.name and cfg.name not in unavailable:
            _check_degradation_allowed(requested_profile, degrade_to, risk_level)
            return cfg, degrade_to

    raise ModelUnavailableError(
        requested=requested_profile,
        available="none",
        risk_level=risk_level,
    )


# ── Degradation Logging ──────────────────────────────────────────────────────

def log_degradation(
    record: DegradationRecord,
    config: RoutingConfig,
    repo_root: str = "",
) -> Optional[Path]:
    """Write a degradation event to the degradation log."""
    if not config.degradation_log_enabled:
        return None

    log_dir = Path(repo_root or ".") / config.degradation_log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / "model_degradations.jsonl"
    entry = {
        "timestamp": record.timestamp,
        "task_id": record.task_id,
        "risk_level": record.risk_level,
        "requested_profile": record.requested_profile,
        "actual_profile": record.actual_profile,
        "requested_model": record.requested_model,
        "actual_model": record.actual_model,
        "reason": record.reason,
    }

    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return log_path


# ── Public API ───────────────────────────────────────────────────────────────

def resolve_model(
    profile: str,
    risk_level: str = "R1",
    *,
    task_id: str = "",
    config_path: Optional[str] = None,
    repo_root: str = "",
    skip_unavailable: Optional[List[str]] = None,
) -> Tuple[ModelConfig, str]:
    """
    Public entry point: resolve a model profile to a concrete ModelConfig.

    Args:
        profile: Abstract profile name (economy/balanced/deep).
        risk_level: Task risk level (R0-R3).
        task_id: Task ID for logging.
        config_path: Override routing config path.
        repo_root: Repository root for relative path resolution.
        skip_unavailable: List of model names to treat as unavailable.

    Returns:
        (ModelConfig, actual_profile) tuple.

    Raises:
        ModelUnavailableError: If no model available and degradation blocked.
    """
    config = load_routing_config(config_path)
    mapped_profile = map_task_profile(profile)
    cfg, actual_profile = resolve_with_degradation(
        mapped_profile, risk_level, config,
        task_id=task_id, skip_unavailable=skip_unavailable,
    )

    # Log degradation if it occurred
    if actual_profile != mapped_profile:
        record = DegradationRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            task_id=task_id,
            risk_level=risk_level,
            requested_profile=mapped_profile,
            actual_profile=actual_profile,
            requested_model="",
            actual_model=cfg.name,
            reason=f"degraded from {mapped_profile} to {actual_profile}",
        )
        log_degradation(record, config, repo_root)

    return cfg, actual_profile


# ── CLI Entry ────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Model Router — resolve abstract profile to concrete model"
    )
    parser.add_argument("--profile", required=True, help="Model profile (economy/balanced/deep)")
    parser.add_argument("--risk-level", default="R1", help="Task risk level")
    parser.add_argument("--task-id", default="", help="Task ID for logging")
    parser.add_argument("--config", default=None, help="Config file path override")
    parser.add_argument("--repo-root", default=".", help="Repo root")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--check-degradation", action="store_true",
                        help="Only check if degradation is allowed")

    args = parser.parse_args(argv)

    if args.check_degradation:
        allowed = RISK_DEGRADATION_ALLOWED.get(args.risk_level.upper(), True)
        result = {
            "risk_level": args.risk_level,
            "degradation_allowed": allowed,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("allowed" if allowed else "blocked")
        return 0

    try:
        cfg, actual = resolve_model(
            profile=args.profile,
            risk_level=args.risk_level,
            task_id=args.task_id,
            config_path=args.config,
            repo_root=args.repo_root,
        )
        result = {
            "requested": args.profile,
            "actual_profile": actual,
            "model": cfg.name,
            "provider": cfg.provider,
            "reasoning": cfg.reasoning,
            "max_tokens": cfg.max_tokens,
            "degraded": actual != map_task_profile(args.profile),
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"model={cfg.name} provider={cfg.provider} profile={actual}")

        return 0
    except ModelUnavailableError as e:
        if args.json:
            print(json.dumps({"error": str(e), "code": "MODEL_UNAVAILABLE"}, ensure_ascii=False))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
