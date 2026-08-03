from __future__ import annotations

from copy import deepcopy
from inspect import signature
from io import StringIO
import json
from pathlib import Path

import pytest

from app.data_core import task07
from app.data_core.task07 import (
    AssetDisposition,
    Task07Asset,
    build_kline_manifest_index,
    build_migration_plan,
    load_kline_manifest_evidence,
    write_kline_manifest_evidence,
)
from app.data_core.task07_migration import prepare_legacy_parquet_batch
from app.guiyi_cli.main import main


SUPPORTED_FREQUENCIES = {"1m", "5m", "15m", "30m", "60m", "1d", "1w"}


def _asset(**overrides: object) -> Task07Asset:
    values: dict[str, object] = {
        "market_data_file_id": 1,
        "provider": "rqdata",
        "data_type": "bars",
        "symbol": "jm",
        "contract_or_series": "JM.MAIN",
        "frequency": "1m",
        "data_role": "primary",
        "quality_status": "passed",
        "file_path": "/data/jm.parquet",
        "source_scope": "approved_data_root",
        "content_gate_status": "passed",
        "checksum": "a" * 64,
        "file_size_bytes": 10,
        "physical_exists": True,
        "physical_checksum": "a" * 64,
        "catalog_checksum": None,
        "dataset_kind": "continuous",
        "coverage_start": "2026-01-01T00:00:00+00:00",
        "coverage_end": "2026-01-02T00:00:00+00:00",
        "row_count": 1,
    }
    values.update(overrides)
    return Task07Asset(**values)


@pytest.mark.parametrize(
    "command",
    (
        "inventory",
        "retirement-plan",
        "retirement-apply",
        "deletion-plan",
        "deletion-preflight",
        "deletion-apply",
        "deletion-verify",
    ),
)
def test_removed_generic_task07_commands_fail_before_database_open(command: str) -> None:
    stderr = StringIO()

    exit_code = main(
        ["data", "task07", command],
        session_factory=lambda: (_ for _ in ()).throw(
            AssertionError("removed command must not open database")
        ),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


def test_kline_manifest_cli_has_no_runtime_protected_or_quarantine_scope() -> None:
    observed: dict[str, object] = {}

    def runner(command, _session, args):
        observed["command"] = command
        observed["arguments"] = vars(args)
        return {"status": "passed", "command": command}

    exit_code = main(
        [
            "data",
            "task07",
            "kline-manifest",
            "--project-root",
            "/tmp/project",
            "--data-root",
            "/tmp/data",
            "--canonical-root",
            "/tmp/canonical",
            "--evidence-root",
            "/tmp/evidence",
        ],
        session_factory=lambda: _NullSession(),
        data_core_runner=runner,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert observed["command"] == "task07.kline-manifest"
    arguments = observed["arguments"]
    assert isinstance(arguments, dict)
    assert not ({"runtime_root", "protected_root", "quarantine_root"} & arguments.keys())


def test_task07_plan_consumes_manifest_not_generic_inventory() -> None:
    observed: dict[str, object] = {}

    def runner(command, _session, args):
        observed["command"] = command
        observed["manifest"] = args.manifest
        assert not hasattr(args, "inventory")
        return {"status": "planned", "command": command}

    exit_code = main(
        [
            "data",
            "task07",
            "plan",
            "--manifest",
            "/tmp/kline-manifest-index.json",
            "--staging-root",
            "/tmp/staging",
            "--canonical-root",
            "/tmp/canonical",
        ],
        session_factory=lambda: _NullSession(),
        data_core_runner=runner,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert observed == {
        "command": "task07.plan",
        "manifest": Path("/tmp/kline-manifest-index.json"),
    }


def test_kline_manifest_rejects_non_kline_and_unsupported_frequency() -> None:
    for asset in (
        _asset(data_type="indicator"),
        _asset(frequency="4h"),
    ):
        with pytest.raises(ValueError, match="TASK07_KLINE_MANIFEST_SCOPE_INVALID"):
            build_kline_manifest_index(
                [asset],
                base_sha="1" * 40,
                database_revision="20260803_0032",
            )


def test_kline_manifest_never_classifies_kline_for_retirement_or_exclusion() -> None:
    assets = [
        _asset(market_data_file_id=index, frequency=frequency, provider="tqsdk")
        for index, frequency in enumerate(sorted(SUPPORTED_FREQUENCIES), 1)
    ]

    manifest = build_kline_manifest_index(
        assets,
        base_sha="1" * 40,
        database_revision="20260803_0032",
    )

    dispositions = {item["disposition"] for item in manifest["assets"]}
    assert AssetDisposition.RETIREMENT_CANDIDATE.value not in dispositions
    assert AssetDisposition.EXCLUDE_DERIVED.value not in dispositions
    assert manifest["command"] == "data.task07.kline-manifest"
    assert manifest["supported_frequencies"] == sorted(SUPPORTED_FREQUENCIES)
    assert "inventory_digest" not in manifest
    assert "disposition_counts" not in manifest
    assert "reference_index" not in manifest
    assert "deletion_authorized" not in manifest


def test_generic_inventory_reference_and_retirement_apis_are_not_public() -> None:
    for name in (
        "scan_task07_references",
        "build_inventory_index",
        "write_inventory_evidence",
        "load_inventory_evidence",
        "build_retirement_plan",
        "collect_retirement_relations",
        "apply_retirement_plan",
    ):
        assert not hasattr(task07, name)


@pytest.mark.parametrize(
    "content_gate_status",
    (
        "trading_day_null_conflict",
        "trading_day_weekend_conflict",
        "night_session_trading_day_conflict",
        "day_session_trading_day_conflict",
    ),
)
def test_direct_trading_day_conflict_requires_rqdata_redownload(
    content_gate_status: str,
) -> None:
    manifest = build_kline_manifest_index(
        [_asset(content_gate_status=content_gate_status)],
        base_sha="1" * 40,
        database_revision="20260803_0032",
    )

    plan = build_migration_plan(manifest)

    assert manifest["classification_counts"] == {"CONFLICT_BLOCKED": 1}
    assert [item["action"] for item in plan["repair_actions"]] == [
        "rqdata_redownload"
    ]
    assert plan["provider_request_proposal"]["request_count"] == 1
    assert plan["provider_request_proposal"]["provider_call_authorized"] is False
    assert plan["repair_actions"][0]["authorized"] is False


def test_non_rqdata_direct_conflict_proposes_only_rqdata_redownload() -> None:
    manifest = build_kline_manifest_index(
        [_asset(provider="tqsdk")],
        base_sha="1" * 40,
        database_revision="20260803_0032",
    )

    plan = build_migration_plan(manifest)

    action = plan["repair_actions"][0]
    request = plan["provider_requests"][0]
    assert action["action"] == "rqdata_redownload"
    assert action["provider"] == "rqdata"
    assert action["original_provider"] == "tqsdk"
    assert request["provider"] == "rqdata"
    assert request["original_provider"] == "tqsdk"
    assert request["market_data_file_id"] == action["market_data_file_id"]
    task07._validate_migration_plan_integrity(plan)

    forged = deepcopy(plan)
    forged["provider_requests"][0]["provider"] = "tqsdk"
    forged["provider_request_proposal"]["requests"][0]["provider"] = "tqsdk"
    proposal_body = {
        key: value
        for key, value in forged["provider_request_proposal"].items()
        if key != "proposal_digest"
    }
    forged["provider_request_proposal"]["proposal_digest"] = (
        task07.canonical_digest(proposal_body)
    )
    with pytest.raises(ValueError, match="TASK07_PLAN_CONTROL_DRIFT"):
        task07._validate_migration_plan_integrity(forged)


def _manifest_scope(tmp_path: Path) -> dict[str, str]:
    roots = {
        "project_root": tmp_path / "project",
        "data_root": tmp_path / "data",
        "canonical_root": tmp_path / "canonical",
    }
    for root in roots.values():
        root.mkdir()
    return {key: str(value.resolve()) for key, value in roots.items()}


def test_kline_manifest_bundle_is_dedicated_and_loadable(tmp_path: Path) -> None:
    scope = _manifest_scope(tmp_path)
    evidence_root = tmp_path / "evidence"

    manifest = write_kline_manifest_evidence(
        [_asset()],
        evidence_root=evidence_root,
        base_sha="1" * 40,
        database_revision="20260803_0032",
        manifest_scope=scope,
    )
    loaded = load_kline_manifest_evidence(
        evidence_root / "kline-manifest-index.json"
    )

    assert manifest["manifest_digest"] == loaded["manifest_digest"]
    assert manifest["classification_counts"] == {"REUSE_TRUSTED_SOURCE": 1}
    assert set(manifest).isdisjoint(
        {
            "inventory_digest",
            "disposition_counts",
            "reference_index",
            "deletion_authorized",
        }
    )
    assert (evidence_root / "kline-assets-000001.jsonl").is_file()


def test_kline_manifest_rejects_evidence_overlap_with_data_scope(
    tmp_path: Path,
) -> None:
    scope = _manifest_scope(tmp_path)
    evidence_root = Path(scope["data_root"]) / "evidence"

    with pytest.raises(
        ValueError, match="TASK07_KLINE_MANIFEST_EVIDENCE_ROOT_INVALID"
    ):
        write_kline_manifest_evidence(
            [_asset()],
            evidence_root=evidence_root,
            base_sha="1" * 40,
            database_revision="20260803_0032",
            manifest_scope=scope,
        )

    assert not evidence_root.exists()


def test_kline_manifest_rejects_overlap_through_symlinked_parent(
    tmp_path: Path,
) -> None:
    scope = _manifest_scope(tmp_path)
    alias = tmp_path / "data-alias"
    alias.symlink_to(Path(scope["data_root"]), target_is_directory=True)
    evidence_root = alias / "evidence"

    with pytest.raises(
        ValueError, match="TASK07_KLINE_MANIFEST_EVIDENCE_ROOT_INVALID"
    ):
        write_kline_manifest_evidence(
            [_asset()],
            evidence_root=evidence_root,
            base_sha="1" * 40,
            database_revision="20260803_0032",
            manifest_scope=scope,
        )

    assert not evidence_root.exists()


def test_kline_manifest_failure_leaves_no_partial_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _manifest_scope(tmp_path)
    evidence_root = tmp_path / "evidence"
    original = task07._write_fsync_file
    calls = 0

    def fail_on_index(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected index write failure")
        original(path, payload)

    monkeypatch.setattr(task07, "_write_fsync_file", fail_on_index)

    with pytest.raises(OSError, match="injected index write failure"):
        write_kline_manifest_evidence(
            [_asset()],
            evidence_root=evidence_root,
            base_sha="1" * 40,
            database_revision="20260803_0032",
            manifest_scope=scope,
        )

    assert not evidence_root.exists()
    assert list(tmp_path.glob(".evidence.tmp-*")) == []


def test_direct_migration_has_no_raw_row_comparison_interface() -> None:
    parameters = signature(prepare_legacy_parquet_batch).parameters

    assert "raw_path" not in parameters
    assert "raw_checksum" not in parameters


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None
