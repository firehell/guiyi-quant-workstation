#!/usr/bin/env python3
"""Tests for risk_resolver.py — R0-R3 risk level auto-inference and normalization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "ai" / "lib"))

import pytest
from risk_resolver import (
    RiskLevel,
    RiskResolution,
    resolve_risk_level,
    infer_risk_level,
    normalize_mixed_risk,
    RESOLVE_ORDER,
)


# ---- Inference tests ----

def test_infer_R0_from_env_path():
    """Paths containing .env should trigger R0."""
    result = infer_risk_level(allowed_paths=["config/.env"])
    assert result == RiskLevel.R0


def test_infer_R0_from_token_path():
    """Paths containing token should trigger R0."""
    result = infer_risk_level(allowed_paths=["scripts/token.sh"])
    assert result == RiskLevel.R0


def test_infer_R0_from_keyword():
    """Body text with 自动交易 should trigger R0."""
    result = infer_risk_level(body_text="实现自动交易功能")
    assert result == RiskLevel.R0


def test_infer_R1_from_strategies_path():
    """Paths in strategies/ should trigger R1."""
    result = infer_risk_level(allowed_paths=["strategies/ema_cross.py"])
    assert result == RiskLevel.R1


def test_infer_R1_from_keyword():
    """Body text with 策略 should trigger R1."""
    result = infer_risk_level(body_text="优化MACD策略参数")
    assert result == RiskLevel.R1


def test_infer_R2_from_services_path():
    """Paths in services/ should trigger R2."""
    result = infer_risk_level(allowed_paths=["services/api/app.py"])
    assert result == RiskLevel.R2


def test_infer_R3_default():
    """Pure docs paths should default to R3."""
    result = infer_risk_level(allowed_paths=["docs/README.md"])
    assert result == RiskLevel.R3


def test_infer_R3_empty():
    """No paths, no body should default to R3."""
    result = infer_risk_level()
    assert result == RiskLevel.R3


# ---- Mixed risk normalization ----

def test_mixed_takes_highest():
    """R1 + R2 paths should resolve to R1 (higher severity)."""
    result = infer_risk_level(allowed_paths=["strategies/ema.py", "services/api.py"])
    assert result == RiskLevel.R1


def test_R0_trumps_all():
    """R0 + R1 + R2 should resolve to R0."""
    result = infer_risk_level(
        allowed_paths=[".env", "strategies/", "services/"],
        body_text="自动交易",
    )
    assert result == RiskLevel.R0


# ---- resolve_risk_level with explicit ----

def test_explicit_upgrade():
    """Human can upgrade risk from R2 to R1."""
    result = resolve_risk_level(
        task_id="TEST-001",
        explicit_risk="R1",
        allowed_paths=["services/api.py"],  # Would infer R2
    )
    assert result.resolved_level == RiskLevel.R1
    assert result.human_override is True


def test_explicit_downgrade_rejected():
    """Human cannot downgrade from R0 to R2 (R0 veto)."""
    result = resolve_risk_level(
        task_id="TEST-001",
        explicit_risk="R2",
        allowed_paths=[".env"],  # Infers R0
    )
    assert result.resolved_level == RiskLevel.R0
    assert result.human_override is False


def test_explicit_match():
    """Explicit risk matching inferred should be accepted."""
    result = resolve_risk_level(
        task_id="TEST-001",
        explicit_risk="R3",
        allowed_paths=["docs/readme.md"],
    )
    assert result.resolved_level == RiskLevel.R3
    assert result.explicit is True


# ---- normalize_mixed_risk ----

def test_normalize_mixed():
    resolutions = [
        RiskResolution(task_id="T1", resolved_level=RiskLevel.R3, triggers=["R3:default"]),
        RiskResolution(task_id="T2", resolved_level=RiskLevel.R1, triggers=["R1_path:strategies/"]),
        RiskResolution(task_id="T3", resolved_level=RiskLevel.R2, triggers=["R2_path:services/"]),
    ]
    result = normalize_mixed_risk(resolutions)
    assert result.resolved_level == RiskLevel.R1


def test_normalize_single():
    resolutions = [
        RiskResolution(task_id="T1", resolved_level=RiskLevel.R3, triggers=["R3:default"]),
    ]
    result = normalize_mixed_risk(resolutions)
    assert result.resolved_level == RiskLevel.R3


def test_normalize_empty_raises():
    with pytest.raises(ValueError):
        normalize_mixed_risk([])


# ---- RESOLVE_ORDER ----

def test_resolve_order():
    assert RESOLVE_ORDER[RiskLevel.R0] < RESOLVE_ORDER[RiskLevel.R1]
    assert RESOLVE_ORDER[RiskLevel.R1] < RESOLVE_ORDER[RiskLevel.R2]
    assert RESOLVE_ORDER[RiskLevel.R2] < RESOLVE_ORDER[RiskLevel.R3]
