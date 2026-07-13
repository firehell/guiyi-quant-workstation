#!/usr/bin/env python3
"""WS-V2-008: Runtime Gate Ledger tests — init, collect, daily-close, finalize, fail-closed."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile

import pytest

# Add lib to path for direct imports in tests
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ai" / "lib"))

from runtime_gate_ledger import (
    ALL_EVIDENCE_KEYS,
    CRITICAL_EVIDENCE,
    FINAL_DEGRADED,
    FINAL_FAILED,
    FINAL_LONG_RUNNING_READY,
    GATE_STATUS_DEGRADED,
    GATE_STATUS_FAILED,
    GATE_STATUS_OK,
    DailyRecord,
    DailyRecordValidator,
    FinalReport,
    GateConfig,
    collect_daily_status,
    compute_idempotency_key,
    finalize_gate,
    generate_final_report,
    init_gate_dir,
    is_idempotent,
    load_gate_config,
    validate_daily_completeness,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic_5day"


# ── Helpers ────────────────────────────────────────────────────────────


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_tmp_gate_dir() -> Path:
    d = Path(tempfile.mkdtemp(prefix="guiyi_gate_"))
    return d


def _setup_five_day_gate(gate_dir: Path) -> Path:
    """Set up a complete 5-day gate with all fixtures."""
    gate_dir.mkdir(parents=True, exist_ok=True)
    gate_id = "FIVE_DAY_SYNTHETIC"
    # Copy gate config
    shutil.copy2(FIXTURES / "gate_five_day.yaml", gate_dir / "gate.yaml")
    # Copy daily records
    daily_dir = gate_dir / "daily"
    daily_dir.mkdir(parents=True)
    for day in ["T+0", "T+1", "T+2", "T+3", "T+4"]:
        shutil.copy2(FIXTURES / f"{day}.json", daily_dir / f"{day}.json")
    # Create incident
    incidents_dir = gate_dir / "incidents"
    incidents_dir.mkdir(parents=True)
    incident = {
        "incident_id": "incident-001",
        "incident_type": "heartbeat_missed",
        "component": "scheduler",
        "details": "Scheduler heartbeat missed for 3 minutes",
        "duration_seconds": 180,
        "recorded_at": "2026-07-16T12:33:00Z",
        "recovered": True,
        "recovery_id": "recovery-001",
        "recovery_at": "2026-07-16T12:35:00Z",
    }
    (incidents_dir / "incident-001.json").write_text(
        json.dumps(incident, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Create recovery test
    recovery_dir = gate_dir / "recovery-tests"
    recovery_dir.mkdir(parents=True)
    (recovery_dir / "recovery-001.md").write_text(
        "# Recovery Test: recovery-001\n\n"
        "- **Incident:** incident-001\n"
        "- **Result:** PASSED\n"
        "- **Notes:** scheduler auto-restart verified\n\n"
        "✅ Recovery successful\n",
        encoding="utf-8",
    )
    return gate_dir


def _setup_three_day_gate(gate_dir: Path) -> Path:
    """Set up a 3-day gate (should fail on finalize)."""
    gate_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURES / "gate_missing_day.yaml", gate_dir / "gate.yaml")
    daily_dir = gate_dir / "daily"
    daily_dir.mkdir(parents=True)
    for day in ["T+0", "T+1", "T+2"]:
        shutil.copy2(FIXTURES / f"{day}.json", daily_dir / f"{day}.json")
    (gate_dir / "incidents").mkdir(parents=True)
    (gate_dir / "recovery-tests").mkdir(parents=True)
    return gate_dir


def _setup_partial_gate(gate_dir: Path) -> Path:
    """Set up a gate with one day having missing critical evidence."""
    gate_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURES / "gate_five_day.yaml", gate_dir / "gate.yaml")
    daily_dir = gate_dir / "daily"
    daily_dir.mkdir(parents=True)
    # T+0 is partial (missing heartbeats + checkpoints)
    shutil.copy2(FIXTURES / "T+0_partial.json", daily_dir / "T+0.json")
    # T+1..T+4 are complete
    for day in ["T+1", "T+2", "T+3", "T+4"]:
        shutil.copy2(FIXTURES / f"{day}.json", daily_dir / f"{day}.json")
    (gate_dir / "incidents").mkdir(parents=True)
    (gate_dir / "recovery-tests").mkdir(parents=True)
    return gate_dir


# ── Tests: GateConfig ──────────────────────────────────────────────────


class TestGateConfig:
    """Gate configuration loading and defaults."""

    def test_default_config_has_five_days(self):
        cfg = GateConfig(gate_id="TEST")
        assert cfg.min_trading_days == 5
        assert cfg.total_days == 5
        assert cfg.trading_days == ["T+0", "T+1", "T+2", "T+3", "T+4"]

    def test_default_critical_evidence(self):
        cfg = GateConfig(gate_id="TEST")
        assert "heartbeats" in cfg.critical_evidence
        assert "checkpoints" in cfg.critical_evidence
        assert "git" in cfg.critical_evidence
        assert "health" in cfg.critical_evidence

    def test_config_to_dict(self):
        cfg = GateConfig(gate_id="TEST", title="My Gate")
        d = cfg.to_dict()
        assert d["gate_id"] == "TEST"
        assert d["title"] == "My Gate"

    def test_load_gate_config_from_yaml(self, tmp_path: Path):
        yaml_path = tmp_path / "gate.yaml"
        yaml_path.write_text(
            "gate_id: MY_GATE\ntitle: \"Test Gate\"\nmin_trading_days: 5\n",
            encoding="utf-8",
        )
        cfg = load_gate_config(tmp_path)
        assert cfg.gate_id == "MY_GATE"
        assert cfg.title == "Test Gate"

    def test_load_gate_config_fallback(self, tmp_path: Path):
        """No gate.yaml → use defaults with directory name."""
        cfg = load_gate_config(tmp_path, gate_id="FALLBACK")
        assert cfg.gate_id == "FALLBACK"
        assert cfg.min_trading_days == 5

    def test_load_five_day_fixture_config(self):
        cfg = load_gate_config(FIXTURES / "gate_five_day.yaml")
        assert cfg.gate_id == "FIVE_DAY_SYNTHETIC"
        assert cfg.min_trading_days == 5

    def test_load_yaml_with_list_fields(self):
        cfg = load_gate_config(FIXTURES / "gate_five_day.yaml")
        assert "T+0" in cfg.trading_days
        assert "heartbeat_missed" in cfg.required_incident_types
        assert "scheduler_restart" in cfg.required_recovery_tests


# ── Tests: DailyRecord ─────────────────────────────────────────────────


class TestDailyRecord:
    """DailyRecord creation, serialization, and loading."""

    def test_from_fixture(self):
        data = _load_fixture("T+0.json")
        record = DailyRecord.from_dict(data)
        assert record.trading_day == "T+0"
        assert record.status == GATE_STATUS_OK
        assert len(record.heartbeats) == 3
        assert len(record.checkpoints) == 2
        assert record.git is not None
        assert record.git["commit"] == "abcT0f"

    def test_partial_fixture_missing_heartbeats(self):
        data = _load_fixture("T+0_partial.json")
        record = DailyRecord.from_dict(data)
        assert record.heartbeats == []

    def test_to_json_roundtrip(self):
        data = _load_fixture("T+0.json")
        record = DailyRecord.from_dict(data)
        json_str = record.to_json()
        record2 = DailyRecord.from_dict(json.loads(json_str))
        assert record2.trading_day == "T+0"
        assert record2.status == GATE_STATUS_OK


# ── Tests: Validator ───────────────────────────────────────────────────


class TestValidator:
    """DailyRecordValidator fail-closed behavior."""

    def test_complete_record_passes(self):
        cfg = GateConfig(gate_id="TEST")
        data = _load_fixture("T+0.json")
        record = DailyRecord.from_dict(data)
        validator = DailyRecordValidator(cfg)
        result = validator.validate(record)
        assert result.status == GATE_STATUS_OK
        assert result.missing_evidence == []

    def test_missing_heartbeats_fails(self):
        cfg = GateConfig(gate_id="TEST")
        data = _load_fixture("T+0_partial.json")
        record = DailyRecord.from_dict(data)
        validator = DailyRecordValidator(cfg)
        result = validator.validate(record)
        assert result.status == GATE_STATUS_FAILED
        assert "heartbeats" in result.missing_evidence
        assert "checkpoints" in result.missing_evidence

    def test_missing_git_fails(self):
        cfg = GateConfig(gate_id="TEST")
        data = _load_fixture("T+0.json")
        data["git"] = None
        record = DailyRecord.from_dict(data)
        validator = DailyRecordValidator(cfg)
        result = validator.validate(record)
        assert result.status == GATE_STATUS_FAILED
        assert "git" in result.missing_evidence

    def test_missing_dedup_degrades(self):
        """dedup is non-critical → DEGRADED not FAILED."""
        cfg = GateConfig(gate_id="TEST")
        data = _load_fixture("T+0.json")
        data["dedup"] = None
        record = DailyRecord.from_dict(data)
        validator = DailyRecordValidator(cfg)
        result = validator.validate(record)
        assert result.status == GATE_STATUS_DEGRADED
        assert "dedup" in result.missing_evidence


# ── Tests: Init ────────────────────────────────────────────────────────


class TestInit:
    """Gate directory initialization."""

    def test_init_creates_structure(self, tmp_path: Path):
        gate_root = tmp_path / ".ai" / "runtime-gates"
        gate_dir = init_gate_dir(gate_root, "TEST_GATE")
        assert gate_dir.is_dir()
        assert (gate_dir / "gate.yaml").is_file()
        assert (gate_dir / "daily").is_dir()
        assert (gate_dir / "incidents").is_dir()
        assert (gate_dir / "recovery-tests").is_dir()

    def test_init_writes_valid_yaml(self, tmp_path: Path):
        gate_root = tmp_path / ".ai" / "runtime-gates"
        gate_dir = init_gate_dir(gate_root, "TEST_GATE")
        cfg = load_gate_config(gate_dir)
        assert cfg.gate_id == "TEST_GATE"
        assert cfg.min_trading_days == 5

    def test_init_idempotent(self, tmp_path: Path):
        gate_root = tmp_path / ".ai" / "runtime-gates"
        gate_dir = init_gate_dir(gate_root, "TEST_GATE")
        yaml_text1 = (gate_dir / "gate.yaml").read_text()
        # Second init should not overwrite
        init_gate_dir(gate_root, "TEST_GATE")
        yaml_text2 = (gate_dir / "gate.yaml").read_text()
        assert yaml_text1 == yaml_text2


# ── Tests: Collect ─────────────────────────────────────────────────────


class TestCollect:
    """Synthetic data collection."""

    def test_collect_with_synthetic_data(self, tmp_path: Path):
        gate_dir = tmp_path
        daily_dir = gate_dir / "daily"
        daily_dir.mkdir(parents=True)

        synth = _load_fixture("T+0.json")
        record = collect_daily_status(
            gate_dir, "T+0", "2026-07-14", synthetic_data=synth,
            git_commit="abc123", service_version="v1.0"
        )
        assert record.trading_day == "T+0"
        assert record.git["commit"] == "abcT0f"  # from synthetic, overridden by git_commit? No, synthetic takes priority
        # Actually synthetic_data takes priority over explicit params

    def test_collect_synthetic_preserves_heartbeats(self, tmp_path: Path):
        gate_dir = tmp_path
        daily_dir = gate_dir / "daily"
        daily_dir.mkdir(parents=True)

        synth = _load_fixture("T+0.json")
        record = collect_daily_status(
            gate_dir, "T+0", "2026-07-14", synthetic_data=synth
        )
        assert len(record.heartbeats) == 3

    def test_collect_sets_idempotency_key(self, tmp_path: Path):
        gate_dir = tmp_path
        daily_dir = gate_dir / "daily"
        daily_dir.mkdir(parents=True)

        synth = _load_fixture("T+0.json")
        record = collect_daily_status(
            gate_dir, "T+0", "2026-07-14", synthetic_data=synth
        )
        assert len(record.idempotency_key) == 16  # SHA256 truncated


# ── Tests: Idempotency ─────────────────────────────────────────────────


class TestIdempotency:
    """Duplicate detection for daily records."""

    def test_same_day_same_date_same_key(self):
        key1 = compute_idempotency_key("T+0", "2026-07-14")
        key2 = compute_idempotency_key("T+0", "2026-07-14")
        assert key1 == key2

    def test_different_day_different_key(self):
        key1 = compute_idempotency_key("T+0", "2026-07-14")
        key2 = compute_idempotency_key("T+1", "2026-07-15")
        assert key1 != key2

    def test_is_idempotent_matches(self, tmp_path: Path):
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir(parents=True)
        key = compute_idempotency_key("T+0", "2026-07-14")
        (daily_dir / "T+0.json").write_text(
            json.dumps({"trading_day": "T+0", "idempotency_key": key}),
            encoding="utf-8",
        )
        assert is_idempotent(daily_dir, "T+0", key)

    def test_is_idempotent_no_existing_file(self, tmp_path: Path):
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir(parents=True)
        key = compute_idempotency_key("T+0", "2026-07-14")
        assert not is_idempotent(daily_dir, "T+0", key)


# ── Tests: Fail-Closed ─────────────────────────────────────────────────


class TestFailClosed:
    """Fail-closed behavior on missing evidence."""

    def test_partial_record_fail_closed(self):
        cfg = GateConfig(gate_id="TEST")
        data = _load_fixture("T+0_partial.json")
        record = DailyRecord.from_dict(data)
        result = validate_daily_completeness(record, cfg)
        assert result.status == GATE_STATUS_FAILED
        assert len(result.missing_evidence) >= 2

    def test_complete_record_passes_validation(self):
        cfg = GateConfig(gate_id="TEST")
        data = _load_fixture("T+0.json")
        record = DailyRecord.from_dict(data)
        result = validate_daily_completeness(record, cfg)
        assert result.status == GATE_STATUS_OK


# ── Tests: Finalize ────────────────────────────────────────────────────


class TestFinalize:
    """Gate finalization with full 5-day vs partial scenarios."""

    def test_five_day_complete_passes(self, tmp_path: Path):
        gate_dir = _setup_five_day_gate(tmp_path / "gate")
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        assert report.final_status == FINAL_LONG_RUNNING_READY
        assert report.days_present == 5
        assert report.days_failed == 0
        assert report.incidents_missing == []
        assert report.recovery_tests_passed == 1

    def test_missing_day_fails(self, tmp_path: Path):
        gate_dir = _setup_three_day_gate(tmp_path / "gate")
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        assert report.final_status == FINAL_FAILED
        assert report.days_present == 3
        assert report.days_required == 5
        assert len(report.missing_days) > 0

    def test_partial_evidence_day_fails_finalize(self, tmp_path: Path):
        gate_dir = _setup_partial_gate(tmp_path / "gate")
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        assert report.final_status == FINAL_FAILED
        assert report.days_failed >= 1

    def test_no_incidents_degrades(self, tmp_path: Path):
        """Gate with no incidents triggered but required ones → DEGRADED."""
        gate_dir = tmp_path / "gate"
        gate_dir.mkdir(parents=True)
        shutil.copy2(FIXTURES / "gate_no_incidents.yaml", gate_dir / "gate.yaml")
        daily_dir = gate_dir / "daily"
        daily_dir.mkdir(parents=True)
        for day in ["T+0", "T+1", "T+2", "T+3", "T+4"]:
            shutil.copy2(FIXTURES / f"{day}.json", daily_dir / f"{day}.json")
        (gate_dir / "incidents").mkdir(parents=True)
        (gate_dir / "recovery-tests").mkdir(parents=True)

        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        assert report.final_status != FINAL_LONG_RUNNING_READY
        # Should be DEGRADED because checkpoint_stale incident is missing
        assert report.incidents_missing == ["checkpoint_stale"]


# ── Tests: Final Report ────────────────────────────────────────────────


class TestFinalReport:
    """Markdown final report generation."""

    def test_report_contains_gate_id(self, tmp_path: Path):
        gate_dir = _setup_five_day_gate(tmp_path / "gate")
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        md = generate_final_report(report)
        assert "FIVE_DAY_SYNTHETIC" in md or "five_day_synthetic" in md
        assert "LONG_RUNNING_READY" in md

    def test_failed_report_mentions_missing_days(self, tmp_path: Path):
        gate_dir = _setup_three_day_gate(tmp_path / "gate")
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        md = generate_final_report(report)
        assert "FAILED" in md
        assert "Missing" in md or "missing" in md

    def test_report_has_daily_detail_table(self, tmp_path: Path):
        gate_dir = _setup_five_day_gate(tmp_path / "gate")
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        md = generate_final_report(report)
        assert "Daily Detail" in md
        assert "T+0" in md
        assert "T+4" in md

    def test_report_has_summary_table(self, tmp_path: Path):
        gate_dir = _setup_five_day_gate(tmp_path / "gate")
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        md = generate_final_report(report)
        assert "Summary" in md
        assert "Days Present" in md


# ── Tests: CLI ─────────────────────────────────────────────────────────


class TestCLI:
    """Test the runtime_gate_ledger.py CLI entry point."""

    def _run_cli(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        ledger_py = REPO_ROOT / "scripts" / "ai" / "lib" / "runtime_gate_ledger.py"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "scripts" / "ai" / "lib")
        return subprocess.run(
            [sys.executable, str(ledger_py), *args],
            capture_output=True, text=True, cwd=cwd, env=env,
        )

    def test_init_creates_gate(self, tmp_path: Path):
        gate_root = tmp_path / ".ai" / "runtime-gates"
        result = self._run_cli("init", str(gate_root), "CLI_TEST", cwd=tmp_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "initialized"
        assert (gate_root / "CLI_TEST" / "gate.yaml").is_file()

    def test_collect_and_validate(self, tmp_path: Path):
        # Init
        gate_root = tmp_path / ".ai" / "runtime-gates"
        self._run_cli("init", str(gate_root), "CLI_COLLECT", cwd=tmp_path)

        # Collect with synthetic data
        synth_path = FIXTURES / "T+0.json"
        result = self._run_cli(
            "collect", str(gate_root / "CLI_COLLECT"),
            "T+0", "2026-07-14", str(synth_path), "abc123", "v1.0",
            cwd=tmp_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"

        # Validate
        result = self._run_cli(
            "validate", str(gate_root / "CLI_COLLECT"), "T+0", cwd=tmp_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"

    def test_finalize_complete_gate(self, tmp_path: Path):
        # Set up complete 5-day gate
        gate_dir = _setup_five_day_gate(tmp_path / "gate")
        result = self._run_cli("finalize", str(gate_dir), cwd=tmp_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["final_status"] == FINAL_LONG_RUNNING_READY
        assert (gate_dir / "final-report.md").is_file()

    def test_report_generates_markdown(self, tmp_path: Path):
        gate_dir = _setup_five_day_gate(tmp_path / "gate")
        result = self._run_cli("report", str(gate_dir), cwd=tmp_path)
        assert result.returncode == 0
        assert "LONG_RUNNING_READY" in result.stdout
        assert "Daily Detail" in result.stdout


# ── Tests: Five-Day Full Simulation ────────────────────────────────────


class TestFiveDaySimulation:
    """End-to-end 5-day long-running gate simulation."""

    def test_full_five_day_simulation(self, tmp_path: Path):
        """Simulate complete 5-day run and verify final report."""
        gate_root = tmp_path / ".ai" / "runtime-gates"
        gate_id = "SIM_FULL"

        # Step 1: Init
        gate_dir = init_gate_dir(gate_root, gate_id)
        config = load_gate_config(gate_dir)

        # Step 2: Collect all 5 days
        dates = ["2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17", "2026-07-18"]
        for i, (day, date) in enumerate(zip(["T+0", "T+1", "T+2", "T+3", "T+4"], dates)):
            synth = _load_fixture(f"{day}.json")
            record = collect_daily_status(
                gate_dir, day, date, synthetic_data=synth, git_commit="abc123", service_version="v1.0"
            )
            record = validate_daily_completeness(record, config)
            (gate_dir / "daily" / f"{day}.json").write_text(record.to_json(), encoding="utf-8")
            assert record.status in (GATE_STATUS_OK, GATE_STATUS_DEGRADED)

        # Step 3: Record incident
        incidents_dir = gate_dir / "incidents"
        incidents_dir.mkdir(exist_ok=True)
        incident = {
            "incident_id": "incident-001",
            "incident_type": "heartbeat_missed",
            "component": "scheduler",
            "details": "Heartbeat missed on T+2",
            "duration_seconds": 180,
            "recorded_at": "2026-07-16T12:33:00Z",
            "recovered": True,
            "recovery_id": "recovery-001",
            "recovery_at": "2026-07-16T12:35:00Z",
        }
        (incidents_dir / "incident-001.json").write_text(
            json.dumps(incident, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Step 4: Record recovery test
        recovery_dir = gate_dir / "recovery-tests"
        recovery_dir.mkdir(exist_ok=True)
        (recovery_dir / "recovery-001.md").write_text(
            "# Recovery Test\n\n✅ PASSED\n", encoding="utf-8"
        )

        # Step 5: Finalize
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        assert report.final_status == FINAL_LONG_RUNNING_READY
        assert report.days_present == 5
        assert report.days_ok == 5

        # Step 6: Generate report
        md = generate_final_report(report)
        (gate_dir / "final-report.md").write_text(md, encoding="utf-8")
        assert "LONG_RUNNING_READY" in md
        assert "✅" in md

    def test_fail_closed_when_day_missing(self, tmp_path: Path):
        """Only 3 days collected → LONG_RUNNING_READY must NOT be set."""
        gate_root = tmp_path / ".ai" / "runtime-gates"
        gate_id = "SIM_FAIL"

        gate_dir = init_gate_dir(gate_root, gate_id)

        # Only collect 3 days
        dates = ["2026-07-14", "2026-07-15", "2026-07-16"]
        for i, (day, date) in enumerate(zip(["T+0", "T+1", "T+2"], dates)):
            synth = _load_fixture(f"{day}.json")
            record = collect_daily_status(
                gate_dir, day, date, synthetic_data=synth, git_commit="abc123", service_version="v1.0"
            )
            config_3day = load_gate_config(gate_dir)
            record = validate_daily_completeness(record, config_3day)
            (gate_dir / "daily" / f"{day}.json").write_text(record.to_json(), encoding="utf-8")

        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        assert report.final_status != FINAL_LONG_RUNNING_READY
        assert report.final_status == FINAL_FAILED
        assert len(report.missing_days) >= 2

    def test_five_day_simulation_no_incidents_long_running_fails(self, tmp_path: Path):
        """Even with 5 complete days, missing required incidents → not LONG_RUNNING_READY."""
        gate_root = tmp_path / ".ai" / "runtime-gates"

        # Use NO_INCIDENTS_TEST config (requires checkpoint_stale incident)
        gate_dir = gate_root / "NO_INC"
        gate_dir.mkdir(parents=True)
        shutil.copy2(FIXTURES / "gate_no_incidents.yaml", gate_dir / "gate.yaml")
        daily_dir = gate_dir / "daily"
        daily_dir.mkdir(parents=True)
        for day in ["T+0", "T+1", "T+2", "T+3", "T+4"]:
            shutil.copy2(FIXTURES / f"{day}.json", daily_dir / f"{day}.json")
        (gate_dir / "incidents").mkdir(parents=True)
        (gate_dir / "recovery-tests").mkdir(parents=True)

        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        assert report.final_status != FINAL_LONG_RUNNING_READY


# ── Tests: Annotation System ───────────────────────────────────────────


class TestAnnotations:
    """Human annotations preserve original machine evidence."""

    def test_annotations_file_separate(self, tmp_path: Path):
        """Annotations stored separately, daily records untouched."""
        gate_dir = tmp_path / "gate"
        gate_dir.mkdir(parents=True)
        daily_dir = gate_dir / "daily"
        daily_dir.mkdir(parents=True)

        # Write a daily record
        synth = _load_fixture("T+0.json")
        record = collect_daily_status(
            gate_dir, "T+0", "2026-07-14", synthetic_data=synth,
            git_commit="abc", service_version="v1"
        )
        daily_path = daily_dir / "T+0.json"
        daily_path.write_text(record.to_json(), encoding="utf-8")

        # Write annotations separately
        annotations_path = gate_dir / "annotations.json"
        annotations = {"T+0": {"human_notes": "Scheduler restart was manual, not auto", "reviewer": "ops-team"}}
        annotations_path.write_text(json.dumps(annotations, indent=2, ensure_ascii=False), encoding="utf-8")

        # Verify daily record is unchanged
        record2 = DailyRecord.from_json_file(daily_path)
        assert record2.status == GATE_STATUS_OK  # Annotations don't change machine status

        # Verify annotations exist
        annotations_data = json.loads(annotations_path.read_text(encoding="utf-8"))
        assert "T+0" in annotations_data
        assert "Scheduler restart" in annotations_data["T+0"]["human_notes"]


# ── Edge Cases ─────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_gate_dir_finalize_fails(self, tmp_path: Path):
        gate_dir = tmp_path / "gate"
        gate_dir.mkdir(parents=True)
        (gate_dir / "gate.yaml").write_text("gate_id: EMPTY\nmin_trading_days: 5\n")
        cfg = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, cfg)
        assert report.final_status == FINAL_FAILED
        assert report.days_present == 0

    def test_non_critical_missing_does_not_fail(self):
        """Missing archive (non-critical) → DEGRADED, not FAILED."""
        cfg = GateConfig(gate_id="TEST")
        data = _load_fixture("T+0.json")
        data["archive"] = None
        record = DailyRecord.from_dict(data)
        result = validate_daily_completeness(record, cfg)
        assert result.status == GATE_STATUS_DEGRADED
