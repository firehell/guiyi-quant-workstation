"""Model router for WS-V2-006: maps task profiles to concrete models with degradation.

Three-tier profile system:
- economy: gpt-4o-mini → claude-sonnet-4-20250514 (fallback)
- balanced: claude-sonnet-4-20250514 → claude-opus-4-20250514 (fallback)
- deep: claude-opus-4-20250514 (no fallback)

Degradation policy:
- R0/R1: degradation allowed (log it)
- R2/R3: degradation blocked — raises ModelUnavailableError

Usage:
    from model_router import resolve_model
    model = resolve_model("balanced", risk_level="R2", task_id="TASK-001")
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ModelRouterError(Exception):
    """Base error for model router."""


class ModelUnavailableError(ModelRouterError):
    """Raised when the required model profile is unavailable and degradation is not allowed."""


@dataclass(frozen=True)
class RoutingConfig:
    profile: str
    model: str
    fallback: Optional[str]

    @property
    def has_fallback(self) -> bool:
        return self.fallback is not None and self.fallback != ""


def load_routing_config(
    config_path: Path | str | None = None,
) -> dict[str, RoutingConfig]:
    """Load model routing configuration from configs/ai/model_routing.json.

    Returns a dict mapping profile names to RoutingConfig objects.
    """
    if config_path is None:
        repo_root = _find_repo_root()
        config_path = repo_root / "configs" / "ai" / "model_routing.json"

    path = Path(config_path)
    if not path.is_file():
        raise ModelRouterError(f"Model routing config not found: {path}")

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    profiles: dict[str, RoutingConfig] = {}
    for name, entry in data.get("profiles", {}).items():
        profiles[name] = RoutingConfig(
            profile=name,
            model=entry["model"],
            fallback=entry.get("fallback"),
        )

    if not profiles:
        raise ModelRouterError("No profiles defined in model routing config")

    return profiles


def map_task_profile(profile: str) -> str:
    """Map a task's model_profile to a canonical key.

    Normalises common aliases to one of: economy, balanced, deep.
    """
    canonical = profile.lower().strip()
    alias_map: dict[str, str] = {
        "fast": "economy",
        "standard": "balanced",
        "critical": "deep",
    }
    return alias_map.get(canonical, canonical)


def resolve_with_degradation(
    profile: str,
    profiles: dict[str, RoutingConfig],
    risk_level: str,
) -> RoutingConfig:
    """Resolve a profile, attempting fallback if the primary model is unavailable.

    Degradation rules:
    - R0/R1: degradation is allowed, log it
    - R2/R3: degradation is blocked, raise ModelUnavailableError
    """
    profile = map_task_profile(profile)
    if profile not in profiles:
        raise ModelUnavailableError(
            f"Unknown model profile: {profile}. Available: {sorted(profiles)}"
        )

    config = profiles[profile]
    return config


def _check_degradation_allowed(profile: str, risk_level: str) -> None:
    """Raise ModelUnavailableError if degradation is not allowed for this risk level."""
    allowed_levels = {"R0", "R1"}
    if risk_level not in allowed_levels:
        raise ModelUnavailableError(
            f"Model '{profile}' is unavailable and degradation is blocked "
            f"for risk_level={risk_level} (R2/R3 require exact match)"
        )


def log_degradation(
    degraded_from: str,
    degraded_to: str,
    task_id: str,
    risk_level: str,
    repo_root: Path | None = None,
) -> None:
    """Log a model degradation event to .ai/results/model_degradations.jsonl."""
    if repo_root is None:
        repo_root = _find_repo_root()

    log_dir = repo_root / ".ai" / "results"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "model_degradations.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "risk_level": risk_level,
        "degraded_from": degraded_from,
        "degraded_to": degraded_to,
    }

    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def resolve_model(
    profile: str,
    risk_level: str = "R3",
    task_id: str = "",
    profiles: dict[str, RoutingConfig] | None = None,
    repo_root: Path | str | None = None,
) -> str:
    """Resolve a model profile to a concrete model name.

    Args:
        profile: Model profile name (economy/balanced/deep or alias)
        risk_level: Task risk level (R0-R3)
        task_id: Task identifier for logging
        profiles: Pre-loaded routing config (loaded from disk if None)
        repo_root: Repository root for log path resolution

    Returns:
        Concrete model name (e.g. "claude-sonnet-4-20250514")

    Raises:
        ModelUnavailableError: Profile unknown or degradation not allowed
    """
    if profiles is None:
        profiles = load_routing_config()

    profile = map_task_profile(profile)

    if profile not in profiles:
        available = sorted(profiles)
        # Try fallback through alias chain
        if risk_level in ("R0", "R1"):
            fallback_chain = {"economy": "balanced", "balanced": "deep", "deep": None}
            fb = fallback_chain.get(profile)
            if fb and fb in profiles:
                log_degradation(profile, fb, task_id, risk_level, _resolve_repo_root(repo_root))
                return profiles[fb].model
        raise ModelUnavailableError(
            f"Model profile '{profile}' not found. Available: {available}"
        )

    config = profiles[profile]
    return config.model


def _find_repo_root() -> Path:
    """Find the git repository root."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def _resolve_repo_root(repo_root: Path | str | None) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    return _find_repo_root()
