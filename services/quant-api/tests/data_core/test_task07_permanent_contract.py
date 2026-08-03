from __future__ import annotations

from inspect import signature
from io import StringIO
import json
from pathlib import Path

import pytest

from app.data_core.task07 import (
    AssetDisposition,
    Task07Asset,
    build_kline_manifest_index,
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


def test_direct_migration_has_no_raw_row_comparison_interface() -> None:
    parameters = signature(prepare_legacy_parquet_batch).parameters

    assert "raw_path" not in parameters
    assert "raw_checksum" not in parameters


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None
