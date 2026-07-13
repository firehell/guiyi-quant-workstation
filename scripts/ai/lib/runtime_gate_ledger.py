#!/usr/bin/env python3
"""WS-V2-008: Runtime Gate Ledger — long-running stability gate recording.

Core module providing:
  - GateConfig / load_gate_config():  gate configuration
  - DailyRecord / DailyRecordValidator:  per-day data model and validation
  - collect_daily_status():  record one trading day's evidence
  - validate_daily_completeness():  fail-closed completeness check
  - finalize_gate():  aggregate 5 days → LONG_RUNNING_READY / DEGRADED / FAILED
  - generate_final_report():  Markdown final report
  - is_idempotent() / compute_idempotency_key():  duplicate detection
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

GATE_STATUS_OK = "ok"
GATE_STATUS_DEGRADED = "degraded"
GATE_STATUS_FAILED = "failed"

FINAL_LONG_RUNNING_READY = "LONG_RUNNING_READY"
FINAL_DEGRADED = "DEGRADED"
FINAL_FAILED = "FAILED"

EVIDENCE_GIT = "git"
EVIDENCE_SERVICE_VERSION = "service_version"
EVIDENCE_HEARTBEATS = "heartbeats"
EVIDENCE_CHECKPOINTS = "checkpoints"
EVIDENCE_DEDUP = "dedup"
EVIDENCE_ARCHIVE = "archive"
EVIDENCE_HEALTH = "health"

ALL_EVIDENCE_KEYS = [
    EVIDENCE_GIT,
    EVIDENCE_SERVICE_VERSION,
    EVIDENCE_HEARTBEATS,
    EVIDENCE_CHECKPOINTS,
    EVIDENCE_DEDUP,
    EVIDENCE_ARCHIVE,
    EVIDENCE_HEALTH,
]

CRITICAL_EVIDENCE = [
    EVIDENCE_GIT,
    EVIDENCE_HEARTBEATS,
    EVIDENCE_CHECKPOINTS,
    EVIDENCE_HEALTH,
]


# ═══════════════════════════════════════════════════════════════════════
# 1. Gate Configuration
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class GateConfig:
    """Configuration for a runtime gate, loaded from gate.yaml."""

    gate_id: str
    title: str = ""
    description: str = ""
    trading_days: list[str] = field(default_factory=lambda: ["T+0", "T+1", "T+2", "T+3", "T+4"])
    trading_dates: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=lambda: list(ALL_EVIDENCE_KEYS))
    critical_evidence: list[str] = field(default_factory=lambda: list(CRITICAL_EVIDENCE))
    required_incident_types: list[str] = field(default_factory=list)
    # Example: ["heartbeat_missed", "checkpoint_stale", "rq_worker_down"]
    required_recovery_tests: list[str] = field(default_factory=list)
    min_trading_days: int = 5
    schema_version: str = "1.0"

    @property
    def total_days(self) -> int:
        return len(self.trading_days)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_gate_config(gate_dir: Path, gate_id: str | None = None) -> GateConfig:
    """Load gate.yaml from a gate directory, falling back to defaults.

    If gate_dir points directly to a YAML file, it is used as the config.
    Otherwise, looks for gate_dir/gate.yaml.
    """
    if gate_dir.is_file() and gate_dir.suffix in (".yaml", ".yml"):
        # Direct file path
        yaml_path = gate_dir
        gate_dir = yaml_path.parent
    else:
        yaml_path = gate_dir / "gate.yaml"
        if not yaml_path.is_file():
            if gate_id:
                return GateConfig(gate_id=gate_id)
            inferred = gate_dir.name
            return GateConfig(gate_id=inferred)

    text = yaml_path.read_text(encoding="utf-8")
    data = _parse_simple_yaml(text)

    cfg = GateConfig(
        gate_id=gate_id or data.get("gate_id", gate_dir.parent.name if gate_dir.name == "daily" else gate_dir.name),
        title=data.get("title", ""),
        description=data.get("description", ""),
        trading_days=data.get("trading_days", ["T+0", "T+1", "T+2", "T+3", "T+4"]),
        trading_dates=data.get("trading_dates", []),
        required_evidence=data.get("required_evidence", list(ALL_EVIDENCE_KEYS)),
        critical_evidence=data.get("critical_evidence", list(CRITICAL_EVIDENCE)),
        required_incident_types=data.get("required_incident_types", []),
        required_recovery_tests=data.get("required_recovery_tests", []),
        min_trading_days=data.get("min_trading_days", 5),
        schema_version=data.get("schema_version", "1.0"),
    )
    return cfg


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML parser for flat and list-only structures.
    Avoids external dependency; sufficient for gate.yaml format.
    """
    result: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item under a key
        if stripped.startswith("- ") and current_key is not None:
            current_list.append(stripped[2:].strip().strip("\"'"))
            continue

        # New key: value
        if ":" in stripped and not stripped.startswith("-"):
            # Flush previous list
            if current_key is not None and current_list:
                result[current_key] = current_list
                current_list = []

            key, _, value = stripped.partition(":")
            current_key = key.strip()
            val = value.strip().strip("\"'")

            if val:
                # Scalar value
                result[current_key] = val
                current_key = None
            else:
                # List follows on subsequent lines
                current_list = []
        elif stripped and current_key is not None and not stripped.startswith("-"):
            # Continuation without dash (for edge cases)
            pass

    # Flush final list
    if current_key is not None and current_list:
        result[current_key] = current_list

    # Type coercion
    for k in ("min_trading_days",):
        if k in result and isinstance(result[k], str):
            try:
                result[k] = int(result[k])
            except ValueError:
                pass

    return result


# ═══════════════════════════════════════════════════════════════════════
# 2. Daily Record
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class HeartbeatRecord:
    component: str  # scheduler, worker_signal, worker_backtest
    count: int = 0
    last_seen_at: str | None = None
    status: str = "missing"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckpointRecord:
    component: str  # live_ingest, live_aggregation
    latest_success_at: str | None = None
    status: str = "missing"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnomalyEntry:
    type: str
    component: str
    at: str
    duration_seconds: int = 0
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceFileEntry:
    path: str
    command: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyRecord:
    """A single trading day's runtime gate evidence."""

    trading_day: str
    trading_date: str = ""
    collected_at: str = ""
    status: str = GATE_STATUS_OK
    idempotency_key: str = ""
    git: dict[str, Any] | None = None
    service_version: str = ""
    heartbeats: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    dedup: dict[str, Any] | None = None
    archive: dict[str, Any] | None = None
    health: dict[str, Any] | None = None
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    incidents_triggered: list[str] = field(default_factory=list)
    evidence_files: list[dict[str, Any]] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    human_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyRecord:
        return cls(
            trading_day=data.get("trading_day", "?"),
            trading_date=data.get("trading_date", ""),
            collected_at=data.get("collected_at", ""),
            status=data.get("status", GATE_STATUS_OK),
            idempotency_key=data.get("idempotency_key", ""),
            git=data.get("git"),
            service_version=data.get("service_version", ""),
            heartbeats=data.get("heartbeats", []),
            checkpoints=data.get("checkpoints", []),
            dedup=data.get("dedup"),
            archive=data.get("archive"),
            health=data.get("health"),
            anomalies=data.get("anomalies", []),
            incidents_triggered=data.get("incidents_triggered", []),
            evidence_files=data.get("evidence_files", []),
            missing_evidence=data.get("missing_evidence", []),
            human_notes=data.get("human_notes"),
        )

    @classmethod
    def from_json_file(cls, path: Path) -> DailyRecord:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


# ═══════════════════════════════════════════════════════════════════════
# 3. Daily Record Validator (Fail-Closed)
# ═══════════════════════════════════════════════════════════════════════

class DailyRecordValidator:
    """Validates a DailyRecord against required evidence from GateConfig.

    Fail-closed: any missing critical evidence → status = FAILED.
    Missing non-critical → DEGRADED.
    All present → OK.
    """

    def __init__(self, config: GateConfig) -> None:
        self.config = config

    def validate(self, record: DailyRecord) -> DailyRecord:
        """Validate a daily record and compute missing_evidence + status."""
        missing: list[str] = []

        for evidence_key in self.config.required_evidence:
            if not self._evidence_present(record, evidence_key):
                missing.append(evidence_key)

        record.missing_evidence = missing

        # Fail-closed logic
        critical_missing = [k for k in missing if k in self.config.critical_evidence]
        non_critical_missing = [k for k in missing if k not in self.config.critical_evidence]

        if critical_missing:
            record.status = GATE_STATUS_FAILED
        elif non_critical_missing:
            record.status = GATE_STATUS_DEGRADED
        else:
            record.status = GATE_STATUS_OK

        return record

    def _evidence_present(self, record: DailyRecord, key: str) -> bool:
        if key == EVIDENCE_GIT:
            return bool(record.git and record.git.get("commit"))
        if key == EVIDENCE_SERVICE_VERSION:
            return bool(record.service_version)
        if key == EVIDENCE_HEARTBEATS:
            return len(record.heartbeats) > 0
        if key == EVIDENCE_CHECKPOINTS:
            return len(record.checkpoints) > 0
        if key == EVIDENCE_DEDUP:
            return bool(record.dedup)
        if key == EVIDENCE_ARCHIVE:
            return bool(record.archive)
        if key == EVIDENCE_HEALTH:
            return bool(record.health)
        return False


# ═══════════════════════════════════════════════════════════════════════
# 4. Collect Daily Status
# ═══════════════════════════════════════════════════════════════════════

def collect_daily_status(
    gate_dir: Path,
    trading_day: str,
    trading_date: str,
    *,
    synthetic_data: dict[str, Any] | None = None,
    git_commit: str = "",
    service_version: str = "",
) -> DailyRecord:
    """Collect one trading day's status.

    When synthetic_data is provided, it is used directly (no real services).
    Otherwise, a best-effort collection from the filesystem is attempted.

    Returns a DailyRecord; caller should then call validate_daily_completeness().
    """
    now = datetime.now(UTC).isoformat()

    if synthetic_data:
        record = DailyRecord.from_dict(synthetic_data)
        record.trading_day = trading_day
        record.trading_date = trading_date
        record.collected_at = now
        record.idempotency_key = compute_idempotency_key(trading_day, trading_date)
        return record

    # Real collection from filesystem (best-effort)
    record = DailyRecord(
        trading_day=trading_day,
        trading_date=trading_date,
        collected_at=now,
        idempotency_key=compute_idempotency_key(trading_day, trading_date),
        git=_collect_git_info(gate_dir, git_commit),
        service_version=service_version,
        heartbeats=[],
        checkpoints=[],
        dedup=None,
        archive=None,
        health=None,
        evidence_files=[],
    )
    return record


def _collect_git_info(gate_dir: Path, explicit_commit: str) -> dict[str, Any]:
    if explicit_commit:
        return {"commit": explicit_commit, "branch": "", "dirty": False}
    try:
        import subprocess
        repo_root = _find_repo_root(gate_dir)
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        dirty_result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--quiet"],
            capture_output=True,
        )
        dirty = dirty_result.returncode != 0
        return {"commit": commit, "branch": branch, "dirty": dirty}
    except Exception:
        return {"commit": "", "branch": "", "dirty": True}


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / ".git").exists():
            return parent
    return start


# ═══════════════════════════════════════════════════════════════════════
# 5. Validate Daily Completeness (Fail-Closed)
# ═══════════════════════════════════════════════════════════════════════

def validate_daily_completeness(record: DailyRecord, config: GateConfig) -> DailyRecord:
    """Validate a daily record against gate config. Fail-closed.

    After validation, the record's status and missing_evidence are updated.
    Returns the (potentially degraded/failed) record.
    """
    validator = DailyRecordValidator(config)
    return validator.validate(record)


# ═══════════════════════════════════════════════════════════════════════
# 6. Finalize Gate
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class FinalReport:
    gate_id: str
    final_status: str  # LONG_RUNNING_READY / DEGRADED / FAILED
    days_present: int
    days_required: int
    days_ok: int
    days_degraded: int
    days_failed: int
    missing_days: list[str]
    incidents_covered: list[str]
    incidents_required: list[str]
    incidents_missing: list[str]
    recovery_tests_passed: int
    recovery_tests_required: int
    daily_summaries: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def finalize_gate(gate_dir: Path, config: GateConfig) -> FinalReport:
    """Read all daily records, incident records, and recovery tests.
    Determine final gate status using fail-closed logic.

    LONG_RUNNING_READY requires:
      - All required trading days present
      - All days have status == OK
      - All required incident types triggered AND recovered
      - All required recovery tests present
    """
    daily_dir = gate_dir / "daily"
    incidents_dir = gate_dir / "incidents"
    recovery_dir = gate_dir / "recovery-tests"
    notes: list[str] = []

    # --- Expected trading days ---
    expected_days = config.trading_days  # From gate.yaml
    required_count = config.min_trading_days

    # --- Load daily records ---
    daily_records: dict[str, DailyRecord] = {}
    missing_days: list[str] = []

    for td in expected_days:
        path = daily_dir / f"{td}.json"
        if path.is_file():
            daily_records[td] = DailyRecord.from_json_file(path)
        else:
            missing_days.append(td)

    # If expected days < required, note the implicit missing days
    if len(expected_days) < required_count:
        for n in range(len(expected_days), required_count):
            missing_days.append(f"T+{n}")

    # --- Validate each day against config ---
    ok_count = 0
    degraded_count = 0
    failed_count = 0
    daily_summaries: list[dict[str, Any]] = []

    for td in config.trading_days:
        if td in daily_records:
            record = validate_daily_completeness(daily_records[td], config)
            daily_summaries.append({
                "trading_day": td,
                "status": record.status,
                "missing_evidence": record.missing_evidence,
                "anomalies_count": len(record.anomalies),
                "incidents_triggered": record.incidents_triggered,
            })
            if record.status == GATE_STATUS_OK:
                ok_count += 1
            elif record.status == GATE_STATUS_DEGRADED:
                degraded_count += 1
            else:
                failed_count += 1
        else:
            daily_summaries.append({
                "trading_day": td,
                "status": "missing",
                "missing_evidence": ["ALL"],
                "anomalies_count": 0,
                "incidents_triggered": [],
            })
            failed_count += 1

    # --- Check incident coverage ---
    triggered_incidents = _collect_incident_types(incidents_dir)
    incidents_missing = [
        it for it in config.required_incident_types
        if it not in triggered_incidents
    ]

    # --- Check recovery tests ---
    recovery_count = _count_recovery_tests(recovery_dir)

    # --- Final status determination ---
    final_status = _determine_final_status(
        missing_days=missing_days,
        failed_count=failed_count,
        degraded_count=degraded_count,
        config=config,
        incidents_missing=incidents_missing,
        recovery_count=recovery_count,
        notes=notes,
    )

    return FinalReport(
        gate_id=config.gate_id,
        final_status=final_status,
        days_present=len(daily_records),
        days_required=config.min_trading_days,
        days_ok=ok_count,
        days_degraded=degraded_count,
        days_failed=failed_count,
        missing_days=missing_days,
        incidents_covered=list(triggered_incidents),
        incidents_required=config.required_incident_types,
        incidents_missing=incidents_missing,
        recovery_tests_passed=recovery_count,
        recovery_tests_required=len(config.required_recovery_tests),
        daily_summaries=daily_summaries,
        generated_at=datetime.now(UTC).isoformat(),
        notes=notes,
    )


def _determine_final_status(
    missing_days: list[str],
    failed_count: int,
    degraded_count: int,
    config: GateConfig,
    incidents_missing: list[str],
    recovery_count: int,
    notes: list[str],
) -> str:
    """Fail-closed final status determination."""
    if missing_days:
        notes.append(f"MISSING trading days: {', '.join(missing_days)}")
        return FINAL_FAILED

    if failed_count > 0:
        notes.append(f"{failed_count} day(s) in FAILED status")
        return FINAL_FAILED

    if incidents_missing:
        notes.append(f"Missing required incidents: {', '.join(incidents_missing)}")
        return FINAL_DEGRADED

    if recovery_count < len(config.required_recovery_tests):
        notes.append(
            f"Recovery tests: {recovery_count} passed, "
            f"{len(config.required_recovery_tests)} required"
        )
        return FINAL_DEGRADED

    if degraded_count > 0:
        notes.append(f"{degraded_count} day(s) in DEGRADED status (non-critical evidence missing)")
        return FINAL_DEGRADED

    return FINAL_LONG_RUNNING_READY


def _collect_incident_types(incidents_dir: Path) -> set[str]:
    types: set[str] = set()
    if not incidents_dir.is_dir():
        return types
    for f in incidents_dir.glob("incident-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            itype = data.get("incident_type") or data.get("type", "")
            if itype:
                types.add(itype)
            # Also check recovery status
            if data.get("recovered") is True:
                types.add(itype + "_recovered")
        except (json.JSONDecodeError, OSError):
            continue
    return types


def _count_recovery_tests(recovery_dir: Path) -> int:
    if not recovery_dir.is_dir():
        return 0
    count = 0
    for f in recovery_dir.glob("recovery-*.md"):
        text = f.read_text(encoding="utf-8")
        if "PASSED" in text or "passed" in text or "✅" in text:
            count += 1
    return count


# ═══════════════════════════════════════════════════════════════════════
# 7. Final Report Generation
# ═══════════════════════════════════════════════════════════════════════

def generate_final_report(report: FinalReport) -> str:
    """Generate a Markdown final report."""

    status_emoji = {
        FINAL_LONG_RUNNING_READY: "✅",
        FINAL_DEGRADED: "⚠️",
        FINAL_FAILED: "❌",
    }

    lines = [
        f"# Runtime Gate Final Report: {report.gate_id}",
        "",
        f"**Final Status:** {status_emoji.get(report.final_status, '❓')} **{report.final_status}**",
        f"**Generated At:** {report.generated_at}",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Days Present | {report.days_present} / {report.days_required} |",
        f"| Days OK | {report.days_ok} |",
        f"| Days Degraded | {report.days_degraded} |",
        f"| Days Failed | {report.days_failed} |",
        f"| Days Missing | {', '.join(report.missing_days) if report.missing_days else 'None'} |",
        f"| Incidents Covered | {len(report.incidents_covered)} / {len(report.incidents_required)} |",
        f"| Recovery Tests | {report.recovery_tests_passed} / {report.recovery_tests_required} |",
        "",
    ]

    if report.notes:
        lines.append("## Notes")
        lines.append("")
        for note in report.notes:
            lines.append(f"- {note}")
        lines.append("")

    if report.missing_days:
        lines.append("## ⚠️ Missing Days")
        lines.append("")
        lines.append("The following trading days are **missing** and must be collected before finalization:")
        lines.append("")
        for d in report.missing_days:
            lines.append(f"- **{d}**")
        lines.append("")

    if report.incidents_missing:
        lines.append("## ⚠️ Missing Incidents")
        lines.append("")
        for it in report.incidents_missing:
            lines.append(f"- **{it}**")
        lines.append("")

    # Daily detail table
    lines.append("## Daily Detail")
    lines.append("")
    lines.append("| Day | Date | Status | Anomalies | Missing Evidence |")
    lines.append("|-----|------|--------|-----------|------------------|")
    for s in report.daily_summaries:
        day = s["trading_day"]
        status = s["status"]
        anomalies = s.get("anomalies_count", 0)
        missing = ", ".join(s.get("missing_evidence", [])) or "None"
        lines.append(f"| {day} | - | {status} | {anomalies} | {missing} |")
    lines.append("")

    if report.final_status == FINAL_LONG_RUNNING_READY:
        lines.append("## ✅ Gate Passed")
        lines.append("")
        lines.append("All required evidence collected. The system is ready for long-running operation.")
    elif report.final_status == FINAL_DEGRADED:
        lines.append("## ⚠️ Gate Degraded")
        lines.append("")
        lines.append("Some non-critical evidence is missing or incidents are not fully covered.")
        lines.append("Review the notes above and address the gaps before proceeding.")
    else:
        lines.append("## ❌ Gate Failed")
        lines.append("")
        lines.append("Critical evidence is missing. The long-running gate cannot be passed.")
        lines.append("Collect the missing data and re-finalize.")

    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 8. Idempotency
# ═══════════════════════════════════════════════════════════════════════

def compute_idempotency_key(trading_day: str, trading_date: str) -> str:
    """Compute a SHA256-based idempotency key for a trading day."""
    raw = f"{trading_day}|{trading_date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_idempotent(daily_dir: Path, trading_day: str, new_key: str) -> bool:
    """Check if a daily record already exists with the same idempotency key."""
    existing = daily_dir / f"{trading_day}.json"
    if not existing.is_file():
        return False
    try:
        data = json.loads(existing.read_text(encoding="utf-8"))
        return data.get("idempotency_key") == new_key
    except (json.JSONDecodeError, OSError):
        return False


# ═══════════════════════════════════════════════════════════════════════
# 9. Gate Initialization
# ═══════════════════════════════════════════════════════════════════════

def init_gate_dir(gate_root: Path, gate_id: str, *, config: GateConfig | None = None) -> Path:
    """Initialize a gate directory structure.

    Creates:
      .ai/runtime-gates/<gate_id>/
        gate.yaml
        daily/          (empty)
        incidents/      (empty)
        recovery-tests/ (empty)
    """
    gate_dir = gate_root / gate_id
    gate_dir.mkdir(parents=True, exist_ok=True)

    for sub in ("daily", "incidents", "recovery-tests"):
        (gate_dir / sub).mkdir(exist_ok=True)

    cfg = config or GateConfig(gate_id=gate_id)
    _write_gate_yaml(gate_dir, cfg)

    return gate_dir


def _write_gate_yaml(gate_dir: Path, config: GateConfig) -> None:
    yaml_path = gate_dir / "gate.yaml"
    if yaml_path.exists():
        return  # Never overwrite existing config

    lines = [
        f"# Runtime Gate Configuration: {config.gate_id}",
        f"gate_id: {config.gate_id}",
        f"title: \"{config.title or config.gate_id}\"",
        f"description: \"{config.description}\"",
        f"schema_version: {config.schema_version}",
        f"min_trading_days: {config.min_trading_days}",
        "",
        "# Trading day labels (T+0 through T+N)",
        "trading_days:",
    ]
    for td in config.trading_days:
        lines.append(f"  - {td}")

    lines.append("")
    lines.append("# Trading dates (YYYY-MM-DD format, optional)")
    lines.append("trading_dates:")
    if config.trading_dates:
        for d in config.trading_dates:
            lines.append(f"  - {d}")
    else:
        lines.append("  - \"2026-07-14\"")
        lines.append("  - \"2026-07-15\"")
        lines.append("  - \"2026-07-16\"")
        lines.append("  - \"2026-07-17\"")
        lines.append("  - \"2026-07-18\"")

    lines.append("")
    lines.append("# Required evidence keys (all must be present for OK status)")
    lines.append("required_evidence:")
    for ev in config.required_evidence:
        lines.append(f"  - {ev}")

    lines.append("")
    lines.append("# Critical evidence (missing → FAILED, not just DEGRADED)")
    lines.append("critical_evidence:")
    for ev in config.critical_evidence:
        lines.append(f"  - {ev}")

    lines.append("")
    lines.append("# Required incident types that must be triggered during the run")
    lines.append("required_incident_types:")
    if config.required_incident_types:
        for it in config.required_incident_types:
            lines.append(f"  - {it}")
    else:
        lines.append("  # - heartbeat_missed")
        lines.append("  # - checkpoint_stale")

    lines.append("")
    lines.append("# Required recovery tests that must pass")
    lines.append("required_recovery_tests:")
    if config.required_recovery_tests:
        for rt in config.required_recovery_tests:
            lines.append(f"  - {rt}")
    else:
        lines.append("  # - scheduler_restart")
        lines.append("  # - redis_reconnect")

    lines.append("")
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# 10. CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if not args:
        print("Usage: python runtime_gate_ledger.py <command> [args...]", file=sys.stderr)
        print("Commands: init, collect, validate, finalize, report", file=sys.stderr)
        sys.exit(1)

    cmd = args[0]

    if cmd == "init":
        gate_root = Path(args[1]) if len(args) > 1 else Path(".ai/runtime-gates")
        gate_id = args[2] if len(args) > 2 else "DEFAULT"
        gate_dir = init_gate_dir(gate_root, gate_id)
        print(json.dumps({"gate_dir": str(gate_dir), "status": "initialized"}))

    elif cmd == "collect":
        gate_dir = Path(args[1])
        trading_day = args[2] if len(args) > 2 else "T+0"
        trading_date = args[3] if len(args) > 3 else ""
        synthetic_path = args[4] if len(args) > 4 else ""
        git_commit = args[5] if len(args) > 5 else ""
        service_version = args[6] if len(args) > 6 else ""

        synthetic_data = None
        if synthetic_path and Path(synthetic_path).is_file():
            synthetic_data = json.loads(Path(synthetic_path).read_text(encoding="utf-8"))

        config = load_gate_config(gate_dir)

        # Idempotency check
        daily_dir = gate_dir / "daily"
        idem_key = compute_idempotency_key(trading_day, trading_date)
        if is_idempotent(daily_dir, trading_day, idem_key):
            print(json.dumps({"idempotent": True, "trading_day": trading_day}))
            sys.exit(0)

        record = collect_daily_status(
            gate_dir, trading_day, trading_date,
            synthetic_data=synthetic_data,
            git_commit=git_commit,
            service_version=service_version,
        )
        record = validate_daily_completeness(record, config)

        # Write
        daily_dir.mkdir(parents=True, exist_ok=True)
        out_path = daily_dir / f"{trading_day}.json"
        out_path.write_text(record.to_json(), encoding="utf-8")

        print(json.dumps({
            "collected": True,
            "trading_day": trading_day,
            "status": record.status,
            "missing_evidence": record.missing_evidence,
        }))

    elif cmd == "validate":
        gate_dir = Path(args[1])
        trading_day = args[2] if len(args) > 2 else "T+0"
        config = load_gate_config(gate_dir)
        daily_path = gate_dir / "daily" / f"{trading_day}.json"
        if not daily_path.is_file():
            print(json.dumps({"valid": False, "error": f"no record for {trading_day}"}))
            sys.exit(1)

        record = DailyRecord.from_json_file(daily_path)
        record = validate_daily_completeness(record, config)
        daily_path.write_text(record.to_json(), encoding="utf-8")

        print(json.dumps({
            "valid": record.status != GATE_STATUS_FAILED,
            "status": record.status,
            "missing_evidence": record.missing_evidence,
        }))

    elif cmd == "finalize":
        gate_dir = Path(args[1])
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        md = generate_final_report(report)

        report_path = gate_dir / "final-report.md"
        report_path.write_text(md, encoding="utf-8")

        print(json.dumps({"final_status": report.final_status, "report_path": str(report_path)}))

    elif cmd == "report":
        gate_dir = Path(args[1])
        config = load_gate_config(gate_dir)
        report = finalize_gate(gate_dir, config)
        print(generate_final_report(report))

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
