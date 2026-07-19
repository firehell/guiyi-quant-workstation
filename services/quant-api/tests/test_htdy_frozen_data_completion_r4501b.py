from datetime import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

import app.backtest.htdy_frozen_data_completion as completion
from app.backtest.htdy_frozen_data_completion import (
    _verify_file,
    _verify_manifest_row,
    build_completion_rows,
    run_completion,
    write_outputs,
)
from app.backtest.htdy_stage45_closeout import file_sha256, load_verified_packet, packet_hash


REPO_ROOT = Path(__file__).resolve().parents[3]
FIELDS = ("datetime", "trading_day", "open", "high", "low", "close", "volume", "provider", "source", "data_role", "quality_status", "period", "symbol", "contract", "open_interest", "turnover")


def _row(timestamp: str, close: float) -> dict[str, object]:
    return {
        "datetime": datetime.fromisoformat(timestamp), "trading_day": "2026-07-10",
        "open": close, "high": close, "low": close, "close": close, "volume": 1.0,
        "provider": "rqdata", "source": "rqdata", "data_role": "primary",
        "quality_status": "passed", "period": "15m", "symbol": "jm", "contract": "jm.MAIN",
        "open_interest": 1.0, "turnover": 1.0,
    }


def _packet(payload: dict[str, object]) -> dict[str, object]:
    packet = dict(payload)
    packet["packet_hash"] = packet_hash(packet)
    return packet


def _write_packet(path: Path, packet: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet), encoding="utf-8")


def _pipeline_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, dict[str, Path]]:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data-root"
    repo_root.mkdir()
    data_root.mkdir()

    old_path = data_root / "assets/old.parquet"
    execution_path = data_root / "assets/execution.parquet"
    source_path = data_root / completion.ONE_MINUTE_RELATIVE_PATH
    for path, content in ((old_path, b"old"), (execution_path, b"execution"), (source_path, b"source")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    protocol = {
        "parameter_hash": "parameter-hash",
        "frozen_data_policy": {
            "data_role": "primary",
            "quality_status": "passed",
            "relative_path": "assets/old.parquet",
            "source_file_sha256": file_sha256(old_path),
            "full_window_start": "2023-01-03T00:00:00",
            "full_window_end": "2026-07-10T15:00:00",
        },
    }
    protocol_path = repo_root / completion.PROTOCOL
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    protocol_sha = file_sha256(protocol_path)
    candidate = _packet(
        {
            "gate": "HTDY_TRUSTED_BACKTEST_CANDIDATE",
            "protocol_hash": protocol_sha,
            "parameter_hash": "parameter-hash",
            "execution_snapshot": {
                "data_role": "primary",
                "quality_status": "passed",
                "data_version": "execution-v2",
                "file_sha256": file_sha256(execution_path),
                "market_data_file_id": 71338,
                "relative_path": "assets/execution.parquet",
            },
        }
    )
    baseline = _packet(
        {
            "gate": "STAGE45_CLOSEOUT_BASELINE_READY",
            "protocol_hash": protocol_sha,
            "parameter_hash": "parameter-hash",
            "evidence": {"x503": {"packet_hash": candidate["packet_hash"]}},
        }
    )
    failed = _packet({"gate": "STRATEGY_VALIDATION_BLOCKED_DATA_IDENTITY_DRIFT"})
    packet_paths = {
        "baseline": repo_root / completion.BASELINE,
        "original_failure": repo_root / completion.ORIGINAL_FAILURE,
        "candidate": repo_root / completion.CANDIDATE,
    }
    for label, packet in (("baseline", baseline), ("original_failure", failed), ("candidate", candidate)):
        _write_packet(packet_paths[label], packet)
    monkeypatch.setattr(completion, "BASELINE_PACKET_HASH", baseline["packet_hash"])
    monkeypatch.setattr(completion, "OLD_PACKET_HASH", failed["packet_hash"])

    manifest_path = repo_root / completion.MANIFEST
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "period,data_version,checksum,market_data_file_id,data_quality_report_id,row_count,data_role,quality_status,standard_path\n"
        f"15m,execution-v2,{file_sha256(execution_path)},71338,68804,35477,primary,passed,{execution_path}\n"
        f"1m,source-v2,{file_sha256(source_path)},71290,68568,532155,primary,passed,{source_path}\n",
        encoding="utf-8",
    )
    return repo_root, data_root, {
        **packet_paths,
        "base": old_path,
        "source": source_path,
        "execution": execution_path,
        "manifest": manifest_path,
    }


def test_build_completion_rows_requires_exact_old_base_and_only_fifteen_new_bars() -> None:
    old = [_row("2026-07-09T23:00:00", 1.0)]
    times = (
        "09:15", "09:30", "09:45", "10:00", "10:15", "10:45", "11:00", "11:15",
        "11:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00",
    )
    rebuilt = old + [_row(f"2026-07-10T{time}:00", float(index)) for index, time in enumerate(times)]
    execution = rebuilt.copy()
    completion = build_completion_rows(old, rebuilt, execution, fields=FIELDS)
    assert len(completion) == 15
    assert completion[0]["datetime"] == "2026-07-10T09:15:00"
    assert completion[-1]["datetime"] == "2026-07-10T15:00:00"


def test_build_completion_rows_rejects_base_field_drift() -> None:
    old = [_row("2026-07-09T23:00:00", 1.0)]
    rebuilt = [_row("2026-07-09T23:00:00", 2.0)]
    with pytest.raises(ValueError, match="immutable base"):
        build_completion_rows(old, rebuilt, rebuilt, fields=FIELDS)


def test_build_completion_rows_rejects_duplicate_or_incomplete_completion() -> None:
    old = [_row("2026-07-09T23:00:00", 1.0)]
    duplicate = old + [_row("2026-07-10T09:15:00", 2.0), _row("2026-07-10T09:15:00", 2.0)]
    with pytest.raises(ValueError, match="duplicate"):
        build_completion_rows(old, duplicate, duplicate, fields=FIELDS)


@pytest.mark.parametrize("label", ["base", "source", "execution"])
def test_verify_file_rejects_each_declared_sha_mismatch(tmp_path: Path, label: str) -> None:
    path = tmp_path / f"{label}.parquet"
    path.write_bytes(b"identity")
    with pytest.raises(ValueError, match="identity mismatch"):
        _verify_file(path, "0" * 64)


@pytest.mark.parametrize("label", ["baseline", "original_failure", "candidate"])
def test_packet_loader_rejects_each_tampered_prerequisite(tmp_path: Path, label: str) -> None:
    path = tmp_path / f"{label}.json"
    packet = {"label": label}
    packet["packet_hash"] = packet_hash(packet)
    packet["label"] = "tampered"
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError, match="hash is invalid"):
        load_verified_packet(path)


@pytest.mark.parametrize("data_role,quality_status", [("primary", "warning"), ("candidate", "passed")])
def test_manifest_helper_rejects_warning_or_non_primary_source(tmp_path: Path, data_role: str, quality_status: str) -> None:
    path = tmp_path / "manifest.csv"
    path.write_text(
        "period,market_data_file_id,data_quality_report_id,row_count,data_role,quality_status\n"
        f"1m,71290,68568,532155,{data_role},{quality_status}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        _verify_manifest_row(path, "1m", {"market_data_file_id": 71290, "data_quality_report_id": 68568, "row_count": 532155})


def test_build_completion_rows_rejects_field_drift_duplicate_short_extra_and_wrong_times() -> None:
    old = [_row("2026-07-09T23:00:00", 1.0)]
    times = ("09:15", "09:30", "09:45", "10:00", "10:15", "10:45", "11:00", "11:15", "11:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00")
    good = old + [_row(f"2026-07-10T{time}:00", float(index)) for index, time in enumerate(times)]
    changed = [dict(row) for row in good]
    changed[-1]["close"] = 999.0
    with pytest.raises(ValueError, match="differs"):
        build_completion_rows(old, good, changed, fields=FIELDS)
    for malformed in (
        good[:-1],
        good + [_row("2026-07-10T10:30:00", 9.0)],
        good + [_row("2026-07-10T09:00:00", 9.0)],
        old + [_row("2026-07-10T09:00:00", 1.0)] + good[2:],
    ):
        with pytest.raises(ValueError, match="exactly"):
            build_completion_rows(old, malformed, good, fields=FIELDS)


@pytest.mark.parametrize("populated", ["completion", "revalidated", "pointer"])
def test_write_outputs_rejects_any_nonempty_target_before_creating_others(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    populated: str,
) -> None:
    monkeypatch.setattr(completion, "OUTPUT_ROOT", Path("evidence"))
    root = tmp_path / "evidence"
    targets = {
        "completion": root / "data_completion_r4501b",
        "revalidated": root / "data_equivalence_revalidated_r4501b",
        "pointer": root / "R45_01_ACCEPTANCE.json",
    }
    target = targets[populated]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix:
        target.write_text("x", encoding="utf-8")
    else:
        target.mkdir()
        (target / "existing.json").write_text("x", encoding="utf-8")
    packets = {"completion": {"gate": "x"}, "revalidated": {"gate": "x"}, "acceptance": {"gate": "x"}}
    with pytest.raises(ValueError, match="already populated"):
        write_outputs(tmp_path, packets)
    for label, path in targets.items():
        if label != populated:
            assert not path.exists()


def test_manifest_absolute_path_is_normalized_but_never_used_as_data_root_bypass(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    path.write_text(
        "period,market_data_file_id,data_quality_report_id,row_count,data_role,quality_status,standard_path\n"
        "1m,71290,68568,532155,primary,passed,/untrusted/root/data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_1m_20200102_20260711_v2.parquet\n",
        encoding="utf-8",
    )
    _verify_manifest_row(path, "1m", {"market_data_file_id": 71290, "data_quality_report_id": 68568, "row_count": 532155})


def test_cli_returns_two_for_missing_data_root(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "services/quant-api/scripts/htdy_frozen_data_completion.py"),
            "--data-root",
            str(tmp_path / "missing"),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "R4501B fail-closed" in result.stderr


@pytest.mark.parametrize("label", ["baseline", "original_failure", "candidate"])
def test_run_completion_rejects_each_tampered_prerequisite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    repo_root, data_root, paths = _pipeline_fixture(tmp_path, monkeypatch)
    packet = json.loads(paths[label].read_text(encoding="utf-8"))
    packet["tampered"] = True
    paths[label].write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(ValueError, match="hash is invalid"):
        run_completion(repo_root, data_root)


@pytest.mark.parametrize("label", ["base", "source", "execution"])
def test_run_completion_rejects_each_asset_sha_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    repo_root, data_root, paths = _pipeline_fixture(tmp_path, monkeypatch)
    paths[label].write_bytes(b"tampered")

    with pytest.raises(ValueError, match="identity mismatch"):
        run_completion(repo_root, data_root)


def test_run_completion_rejects_warning_source_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root, data_root, paths = _pipeline_fixture(tmp_path, monkeypatch)
    manifest_lines = paths["manifest"].read_text(encoding="utf-8").splitlines()
    manifest_lines[2] = manifest_lines[2].replace("primary,passed", "primary,warning")
    paths["manifest"].write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"primary\+passed"):
        run_completion(repo_root, data_root)


def test_cli_returns_two_for_schema_key_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script_path = REPO_ROOT / "services/quant-api/scripts/htdy_frozen_data_completion.py"
    spec = importlib.util.spec_from_file_location("r4501b_cli_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "run_completion", lambda *_args: (_ for _ in ()).throw(KeyError("schema")))
    monkeypatch.setattr(sys, "argv", [str(script_path), "--data-root", str(tmp_path)])

    assert module.main() == 2
