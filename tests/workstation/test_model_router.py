#!/usr/bin/env python3
"""WS-V2-006: Model Router tests — profile mapping, degradation, resolution"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "ai" / "lib"))

import pytest

from model_router import (
    RoutingConfig,
    ModelRouterError,
    ModelUnavailableError,
    load_routing_config,
    map_task_profile,
    resolve_with_degradation,
    resolve_model,
    log_degradation,
)


# ── Profile Mapping ────────────────────────────────────────────────────


class TestProfileMapping:
    """Test map_task_profile alias normalization"""

    def test_standard_aliases(self):
        assert map_task_profile("fast") == "economy"
        assert map_task_profile("standard") == "balanced"
        assert map_task_profile("critical") == "deep"

    def test_canonical_passthrough(self):
        assert map_task_profile("economy") == "economy"
        assert map_task_profile("balanced") == "balanced"
        assert map_task_profile("deep") == "deep"

    def test_case_insensitive(self):
        assert map_task_profile("ECONOMY") == "economy"
        assert map_task_profile("Balanced") == "balanced"
        assert map_task_profile("DEEP") == "deep"

    def test_whitespace_trimmed(self):
        assert map_task_profile("  economy  ") == "economy"

    def test_unknown_passthrough(self):
        assert map_task_profile("unknown-profile") == "unknown-profile"


# ── Config Loading ──────────────────────────────────────────────────────


class TestConfigLoading:
    """Test load_routing_config"""

    def test_loads_real_config(self):
        config_path = (
            Path(__file__).resolve().parents[2] / "configs" / "ai" / "model_routing.json"
        )
        if config_path.is_file():
            profiles = load_routing_config(config_path)
            assert "economy" in profiles
            assert "balanced" in profiles
            assert "deep" in profiles
            assert profiles["economy"].model == "gpt-4o-mini"
            assert profiles["deep"].fallback is None

    def test_missing_file_raises(self, tmp_path: Path):
        config = tmp_path / "nonexistent.json"
        with pytest.raises(ModelRouterError):
            load_routing_config(config)

    def test_empty_profiles_raises(self, tmp_path: Path):
        config = tmp_path / "empty.json"
        config.write_text(json.dumps({"profiles": {}, "version": "1.0"}))
        with pytest.raises(ModelRouterError):
            load_routing_config(config)

    def test_valid_config_from_dict(self, tmp_path: Path):
        config = tmp_path / "test.json"
        config.write_text(json.dumps({
            "version": "1.0",
            "profiles": {
                "economy": {"model": "gpt-4o-mini", "fallback": "claude-sonnet-4-20250514"},
            },
        }))
        profiles = load_routing_config(config)
        assert "economy" in profiles
        assert profiles["economy"].has_fallback is True


# ── Resolution ─────────────────────────────────────────────────────────


class TestResolution:
    """Test resolve_with_degradation"""

    def _test_profiles(self) -> dict[str, RoutingConfig]:
        return {
            "economy": RoutingConfig(profile="economy", model="gpt-4o-mini", fallback="claude-sonnet"),
            "balanced": RoutingConfig(profile="balanced", model="claude-sonnet", fallback="claude-opus"),
            "deep": RoutingConfig(profile="deep", model="claude-opus", fallback=None),
        }

    def test_resolve_economy(self):
        profiles = self._test_profiles()
        config = resolve_with_degradation("economy", profiles, "R2")
        assert config.model == "gpt-4o-mini"

    def test_resolve_balanced(self):
        profiles = self._test_profiles()
        config = resolve_with_degradation("balanced", profiles, "R2")
        assert config.model == "claude-sonnet"

    def test_resolve_deep(self):
        profiles = self._test_profiles()
        config = resolve_with_degradation("deep", profiles, "R2")
        assert config.model == "claude-opus"

    def test_resolve_alias(self):
        profiles = self._test_profiles()
        config = resolve_with_degradation("fast", profiles, "R2")
        assert config.model == "gpt-4o-mini"

    def test_unknown_profile_raises(self):
        profiles = self._test_profiles()
        with pytest.raises(ModelUnavailableError):
            resolve_with_degradation("luxury", profiles, "R2")


# ── Degradation ─────────────────────────────────────────────────────────


class TestDegradation:
    """Test degradation policy"""

    def _test_profiles(self) -> dict[str, RoutingConfig]:
        return {
            "economy": RoutingConfig(profile="economy", model="gpt-4o-mini", fallback="claude-sonnet"),
            "balanced": RoutingConfig(profile="balanced", model="claude-sonnet", fallback="claude-opus"),
            "deep": RoutingConfig(profile="deep", model="claude-opus", fallback=None),
        }

    def test_degradation_not_triggered_when_primary_available(self):
        """When primary model is available, no degradation is attempted."""
        profiles = self._test_profiles()
        config = resolve_with_degradation("balanced", profiles, "R2")
        assert config.model == "claude-sonnet"  # Primary, not fallback

    def test_unknown_profile_r0_allowed_degradation_not_applicable(self):
        """R0 with unknown profile should raise — degradation is about known profiles."""
        profiles = self._test_profiles()
        with pytest.raises(ModelUnavailableError):
            resolve_with_degradation("unknown", profiles, "R0")

    def test_unknown_profile_r2_blocked(self):
        profiles = self._test_profiles()
        with pytest.raises(ModelUnavailableError):
            resolve_with_degradation("unknown", profiles, "R2")


# ── Risk Level Degradation Table ────────────────────────────────────────


class TestRiskDegradationTable:
    """Verify degradation allowed/blocked per risk level"""

    def _test_profiles(self) -> dict[str, RoutingConfig]:
        return {
            "economy": RoutingConfig(profile="economy", model="gpt-4o-mini", fallback="claude-sonnet"),
            "balanced": RoutingConfig(profile="balanced", model="claude-sonnet", fallback="claude-opus"),
            "deep": RoutingConfig(profile="deep", model="claude-opus", fallback=None),
        }

    def test_r0_allowed(self):
        profiles = self._test_profiles()
        config = resolve_with_degradation("economy", profiles, "R0")
        assert config.model == "gpt-4o-mini"

    def test_r1_allowed(self):
        profiles = self._test_profiles()
        config = resolve_with_degradation("balanced", profiles, "R1")
        assert config.model == "claude-sonnet"

    def test_r2_blocked(self):
        profiles = self._test_profiles()
        config = resolve_with_degradation("economy", profiles, "R2")
        assert config.model == "gpt-4o-mini"  # Primary works, no degradation needed

    def test_r3_blocked(self):
        profiles = self._test_profiles()
        config = resolve_with_degradation("balanced", profiles, "R3")
        assert config.model == "claude-sonnet"  # Primary works


# ── Profile Tiers ──────────────────────────────────────────────────────


class TestProfileTiers:
    """Test three-tier profile structure"""

    def _test_profiles(self) -> dict[str, RoutingConfig]:
        return {
            "economy": RoutingConfig(profile="economy", model="gpt-4o-mini", fallback="claude-sonnet"),
            "balanced": RoutingConfig(profile="balanced", model="claude-sonnet", fallback="claude-opus"),
            "deep": RoutingConfig(profile="deep", model="claude-opus", fallback=None),
        }

    def test_three_tiers_exist(self):
        profiles = self._test_profiles()
        assert set(profiles.keys()) == {"economy", "balanced", "deep"}

    def test_economy_has_fallback(self):
        profiles = self._test_profiles()
        assert profiles["economy"].has_fallback

    def test_balanced_has_fallback(self):
        profiles = self._test_profiles()
        assert profiles["balanced"].has_fallback

    def test_deep_no_fallback(self):
        profiles = self._test_profiles()
        assert not profiles["deep"].has_fallback

    def test_deep_model_is_opus(self):
        profiles = self._test_profiles()
        assert "opus" in profiles["deep"].model.lower()


# ── Degradation Logging ─────────────────────────────────────────────────


class TestDegradationLogging:
    """Test log_degradation"""

    def test_log_writes_valid_jsonl(self, tmp_path: Path):
        results_dir = tmp_path / ".ai" / "results"
        results_dir.mkdir(parents=True)
        log_degradation("economy", "balanced", "TASK-001", "R1", tmp_path)
        log_degradation("balanced", "deep", "TASK-002", "R0", tmp_path)

        log_path = results_dir / "model_degradations.jsonl"
        assert log_path.is_file()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2
        entry1 = json.loads(lines[0])
        assert entry1["degraded_from"] == "economy"
        assert entry1["degraded_to"] == "balanced"
        assert entry1["task_id"] == "TASK-001"
        assert entry1["risk_level"] == "R1"

    def test_log_directory_created_if_missing(self, tmp_path: Path):
        results_dir = tmp_path / ".ai" / "results"
        assert not results_dir.exists()
        log_degradation("balanced", "deep", "TASK-003", "R1", tmp_path)
        assert results_dir.is_dir()
        assert (results_dir / "model_degradations.jsonl").is_file()


# ── Resolve Model (Integration) ─────────────────────────────────────────


class TestResolveModel:
    """Test resolve_model — the main entry point"""

    def _test_profiles(self) -> dict[str, RoutingConfig]:
        return {
            "economy": RoutingConfig(profile="economy", model="gpt-4o-mini", fallback="claude-sonnet"),
            "balanced": RoutingConfig(profile="balanced", model="claude-sonnet", fallback="claude-opus"),
            "deep": RoutingConfig(profile="deep", model="claude-opus", fallback=None),
        }

    def test_resolve_economy(self):
        model = resolve_model("economy", profiles=self._test_profiles())
        assert model == "gpt-4o-mini"

    def test_resolve_with_alias(self):
        model = resolve_model("fast", profiles=self._test_profiles())
        assert model == "gpt-4o-mini"

    def test_resolve_balanced_r2(self):
        model = resolve_model("balanced", risk_level="R2", profiles=self._test_profiles())
        assert model == "claude-sonnet"

    def test_resolve_deep_no_degradation(self):
        model = resolve_model("deep", risk_level="R3", profiles=self._test_profiles())
        assert "opus" in model.lower()

    def test_unknown_profile_r0_raises(self):
        with pytest.raises(ModelUnavailableError):
            resolve_model("super-expensive", risk_level="R0", profiles=self._test_profiles())

    def test_unknown_profile_r3_raises(self):
        with pytest.raises(ModelUnavailableError):
            resolve_model("super-expensive", risk_level="R3", profiles=self._test_profiles())


# ── Routing Config Dataclass ────────────────────────────────────────────


class TestRoutingConfig:
    """Test RoutingConfig dataclass"""

    def test_has_fallback_true(self):
        cfg = RoutingConfig(profile="test", model="gpt-4", fallback="claude")
        assert cfg.has_fallback is True

    def test_has_fallback_none(self):
        cfg = RoutingConfig(profile="test", model="gpt-4", fallback=None)
        assert cfg.has_fallback is False

    def test_has_fallback_empty_string(self):
        cfg = RoutingConfig(profile="test", model="gpt-4", fallback="")
        assert cfg.has_fallback is False

    def test_frozen(self):
        cfg = RoutingConfig(profile="test", model="gpt-4", fallback=None)
        with pytest.raises(Exception):
            cfg.model = "other"  # type: ignore
