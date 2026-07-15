"""Model Router tests — WS-V2-006 M6."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add lib to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ai" / "lib"))

from model_router import (
    ModelConfig,
    ModelUnavailableError,
    RoutingConfig,
    DegradationRecord,
    load_routing_config,
    map_task_profile,
    resolve_model,
    resolve_with_degradation,
    VALID_PROFILES,
    PROFILE_TIER,
    RISK_DEGRADATION_ALLOWED,
)


# ── Profile Mapping ──────────────────────────────────────────────────────────

class TestProfileMapping:
    """Map legacy profiles to three-tier economy/balanced/deep."""

    def test_fast_maps_to_economy(self):
        assert map_task_profile("fast") == "economy"

    def test_standard_maps_to_balanced(self):
        assert map_task_profile("standard") == "balanced"

    def test_deep_maps_to_deep(self):
        assert map_task_profile("deep") == "deep"

    def test_critical_maps_to_deep(self):
        assert map_task_profile("critical") == "deep"

    def test_economy_passthrough(self):
        assert map_task_profile("economy") == "economy"

    def test_balanced_passthrough(self):
        assert map_task_profile("balanced") == "balanced"

    def test_unknown_maps_to_balanced(self):
        assert map_task_profile("garbage") == "balanced"


# ── Config Loading ───────────────────────────────────────────────────────────

class TestConfigLoading:
    """Load and validate model_routing.json."""

    def test_load_real_config(self):
        """The real config file should load and have all three profiles."""
        config_path = Path(__file__).resolve().parents[2] / "configs" / "ai" / "model_routing.json"
        config = load_routing_config(str(config_path))

        assert "economy" in config.profiles
        assert "balanced" in config.profiles
        assert "deep" in config.profiles
        assert config.default_profile == "balanced"
        assert config.degradation_log_enabled is True

    def test_economy_profile_has_fallback(self):
        config_path = Path(__file__).resolve().parents[2] / "configs" / "ai" / "model_routing.json"
        config = load_routing_config(str(config_path))
        economy = config.profiles["economy"]
        assert economy.fallback is not None

    def test_deep_profile_no_fallback(self):
        config_path = Path(__file__).resolve().parents[2] / "configs" / "ai" / "model_routing.json"
        config = load_routing_config(str(config_path))
        deep = config.profiles["deep"]
        assert deep.fallback is None

    def test_temp_config(self, tmp_path):
        """Load a custom config file from temp path."""
        config_data = {
            "default_profile": "economy",
            "degradation_log_enabled": False,
            "profiles": {
                "economy": {
                    "name": "test-model",
                    "provider": "test",
                    "fallback": None,
                },
                "balanced": {
                    "name": "test-model-2",
                    "provider": "test",
                    "fallback": "economy",
                },
                "deep": {
                    "name": "test-model-3",
                    "provider": "test",
                    "fallback": None,
                },
            },
        }
        config_path = tmp_path / "model_routing.json"
        config_path.write_text(json.dumps(config_data))

        config = load_routing_config(str(config_path))
        assert config.default_profile == "economy"
        assert config.degradation_log_enabled is False
        assert config.profiles["economy"].name == "test-model"


# ── Resolution ───────────────────────────────────────────────────────────────

class TestResolution:
    """Resolve models from profiles."""

    def test_exact_match(self):
        config = RoutingConfig(profiles={
            "economy": ModelConfig(name="gpt-mini", provider="openai"),
            "balanced": ModelConfig(name="claude-sonnet", provider="anthropic"),
            "deep": ModelConfig(name="claude-opus", provider="anthropic"),
        })
        cfg, profile = resolve_with_degradation("balanced", "R1", config)
        assert profile == "balanced"
        assert cfg.name == "claude-sonnet"

    def test_fallback_chain(self):
        config = RoutingConfig(profiles={
            "balanced": ModelConfig(name="claude-sonnet", provider="anthropic", fallback="economy"),
            "economy": ModelConfig(name="gpt-mini", provider="openai"),
        })
        # balanced is available — use it
        cfg, profile = resolve_with_degradation("balanced", "R1", config)
        assert profile == "balanced"
        assert cfg.name == "claude-sonnet"

    def test_skip_unavailable(self):
        config = RoutingConfig(profiles={
            "balanced": ModelConfig(name="claude-sonnet", provider="anthropic", fallback="economy"),
            "economy": ModelConfig(name="gpt-mini", provider="openai"),
        })
        cfg, profile = resolve_with_degradation(
            "balanced", "R1", config,
            skip_unavailable=["claude-sonnet"],
        )
        # should fallback to economy
        assert profile == "economy"
        assert cfg.name == "gpt-mini"


# ── Degradation ──────────────────────────────────────────────────────────────

class TestDegradation:
    """Degradation behavior by risk level."""

    def test_r0_allows_degradation(self):
        config = RoutingConfig(profiles={
            "deep": ModelConfig(name="deep-model", provider="test", fallback="economy"),
            "economy": ModelConfig(name="cheap-model", provider="test"),
        })
        cfg, profile = resolve_with_degradation(
            "deep", "R0", config,
            skip_unavailable=["deep-model"],
        )
        assert profile == "economy"

    def test_r1_allows_degradation(self):
        config = RoutingConfig(profiles={
            "deep": ModelConfig(name="deep-model", provider="test", fallback="economy"),
            "economy": ModelConfig(name="cheap-model", provider="test"),
        })
        cfg, profile = resolve_with_degradation(
            "deep", "R1", config,
            skip_unavailable=["deep-model"],
        )
        assert profile == "economy"

    def test_r2_blocks_silent_degradation(self):
        """R2 tasks cannot silently degrade from deep."""
        config = RoutingConfig(profiles={
            "deep": ModelConfig(name="deep-model", provider="test", fallback="economy"),
            "economy": ModelConfig(name="cheap-model", provider="test"),
        })
        with pytest.raises(ModelUnavailableError) as excinfo:
            resolve_with_degradation(
                "deep", "R2", config,
                skip_unavailable=["deep-model"],
            )
        assert "R2" in str(excinfo.value)

    def test_r3_blocks_silent_degradation(self):
        """R3 tasks cannot silently degrade from deep."""
        config = RoutingConfig(profiles={
            "deep": ModelConfig(name="deep-model", provider="test", fallback="economy"),
            "economy": ModelConfig(name="cheap-model", provider="test"),
        })
        with pytest.raises(ModelUnavailableError) as excinfo:
            resolve_with_degradation(
                "deep", "R3", config,
                skip_unavailable=["deep-model"],
            )
        assert "R3" in str(excinfo.value)

    def test_all_unavailable_raises(self):
        """When all profiles are unavailable, raises ModelUnavailableError."""
        config = RoutingConfig(profiles={
            "economy": ModelConfig(name="only-model", provider="test"),
        })
        with pytest.raises(ModelUnavailableError):
            resolve_with_degradation(
                "economy", "R1", config,
                skip_unavailable=["only-model"],
            )


# ── Degradation Risk Table ───────────────────────────────────────────────────

class TestRiskDegradationTable:
    """Verify the risk degradation matrix."""

    def test_r0_degradation_allowed(self):
        assert RISK_DEGRADATION_ALLOWED["R0"] is True

    def test_r1_degradation_allowed(self):
        assert RISK_DEGRADATION_ALLOWED["R1"] is True

    def test_r2_degradation_blocked(self):
        assert RISK_DEGRADATION_ALLOWED["R2"] is False

    def test_r3_degradation_blocked(self):
        assert RISK_DEGRADATION_ALLOWED["R3"] is False


# ── Profile Tiers ────────────────────────────────────────────────────────────

class TestProfileTiers:
    """Profile tier ordering."""

    def test_economy_lowest(self):
        assert PROFILE_TIER["economy"] == 0

    def test_balanced_middle(self):
        assert PROFILE_TIER["balanced"] == 1

    def test_deep_highest(self):
        assert PROFILE_TIER["deep"] == 2

    def test_valid_profiles_set(self):
        assert VALID_PROFILES == {"economy", "balanced", "deep"}


# ── Degradation Logging ──────────────────────────────────────────────────────

class TestDegradationLogging:
    """Degradation events are logged to file."""

    def test_log_degradation_writes_file(self, tmp_path):
        from model_router import log_degradation

        config = RoutingConfig(
            degradation_log_enabled=True,
            degradation_log_dir=str(tmp_path),
        )
        record = DegradationRecord(
            timestamp="2026-07-13T00:00:00Z",
            task_id="TEST-001",
            risk_level="R1",
            requested_profile="deep",
            actual_profile="economy",
            requested_model="deep-model",
            actual_model="cheap-model",
            reason="deep-model unavailable",
        )

        log_path = log_degradation(record, config, repo_root=str(tmp_path))
        assert log_path is not None
        assert log_path.is_file()

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["task_id"] == "TEST-001"
        assert entry["requested_profile"] == "deep"
        assert entry["actual_profile"] == "economy"

    def test_log_disabled_skips(self, tmp_path):
        from model_router import log_degradation

        config = RoutingConfig(
            degradation_log_enabled=False,
            degradation_log_dir=str(tmp_path),
        )
        record = DegradationRecord(
            timestamp="2026-07-13T00:00:00Z",
            task_id="TEST-002",
            risk_level="R1",
            requested_profile="deep",
            actual_profile="economy",
            requested_model="deep-model",
            actual_model="cheap-model",
            reason="test",
        )

        log_path = log_degradation(record, config, repo_root=str(tmp_path))
        assert log_path is None


# ── resolve_model Public API ─────────────────────────────────────────────────

class TestResolveModel:
    """Public resolve_model API with real config."""

    def test_resolve_model_with_real_config(self):
        """resolve_model should work with the real config file."""
        config_path = Path(__file__).resolve().parents[2] / "configs" / "ai" / "model_routing.json"

        cfg, profile = resolve_model(
            "balanced", "R1",
            config_path=str(config_path),
        )
        assert profile == "balanced"
        assert cfg.name != ""
        assert cfg.provider != ""

    def test_resolve_model_degradation_r1_ok(self):
        """R1 can degrade from deep to balanced."""
        config_path = Path(__file__).resolve().parents[2] / "configs" / "ai" / "model_routing.json"
        # Skip the real deep model to force degradation
        deep_model = "claude-opus-4-20250514"

        cfg, profile = resolve_model(
            "deep", "R1",
            config_path=str(config_path),
            skip_unavailable=[deep_model],
        )
        # Should degrade to balanced (which has fallback=economy)
        # or directly to balanced since it's the next in tier
        assert profile in ("balanced", "economy")

    def test_resolve_model_degradation_r2_blocked(self):
        """R2 cannot silently degrade from deep."""
        config_path = Path(__file__).resolve().parents[2] / "configs" / "ai" / "model_routing.json"
        deep_model = "claude-opus-4-20250514"

        with pytest.raises(ModelUnavailableError):
            resolve_model(
                "deep", "R2",
                config_path=str(config_path),
                skip_unavailable=[deep_model],
            )


# ── Demo Gates ───────────────────────────────────────────────────────────────

class TestModelRouterDemoGates:
    """Security boundary demonstrations for model routing."""

    def test_demo_r2_silent_degradation_blocked(self):
        """Demo: R2 task attempting silent degradation is blocked."""
        config = RoutingConfig(profiles={
            "deep": ModelConfig(name="claude-opus", provider="anthropic", fallback="economy"),
            "economy": ModelConfig(name="gpt-mini", provider="openai"),
        })

        # R2 with deep model unavailable → must raise
        with pytest.raises(ModelUnavailableError) as excinfo:
            resolve_with_degradation(
                "deep", "R2", config,
                skip_unavailable=["claude-opus"],
                task_id="DEMO-R2-DEGRADE-TEST",
            )
        assert "R2" in str(excinfo.value) or "unavailable" in str(excinfo.value).lower()

    def test_demo_r0_degradation_allowed(self):
        """Demo: R0 (read-only) task can safely degrade."""
        config = RoutingConfig(profiles={
            "deep": ModelConfig(name="claude-opus", provider="anthropic", fallback="economy"),
            "economy": ModelConfig(name="gpt-mini", provider="openai"),
        })

        cfg, profile = resolve_with_degradation(
            "deep", "R0", config,
            skip_unavailable=["claude-opus"],
            task_id="DEMO-R0",
        )
        assert profile == "economy"

    def test_demo_profile_mapping_legacy_compat(self):
        """Demo: Legacy 'critical' tasks map to 'deep' with no data loss."""
        assert map_task_profile("critical") == "deep"
        assert map_task_profile("standard") == "balanced"
        assert map_task_profile("fast") == "economy"
