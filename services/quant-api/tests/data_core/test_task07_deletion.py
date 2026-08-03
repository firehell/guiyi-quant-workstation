from __future__ import annotations

from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.data_core.task07 import canonical_digest
from app.data_core.task07_deletion import (
    Task07DeletionError,
    _apply_unlocked_deletion_plan as apply_deletion_plan,
    _build_unlocked_deletion_approval_packet as build_deletion_approval_packet,
    _build_unlocked_deletion_preflight as build_deletion_preflight,
    apply_deletion_plan as public_apply_deletion_plan,
    build_deletion_approval_packet as public_build_deletion_approval_packet,
    build_deletion_plan,
    build_deletion_preflight as public_build_deletion_preflight,
    verify_deletion_apply,
)
from app.guiyi_cli.main import main


BASE_SHA = "1" * 40
REVISION = "20260802_0031"


def _asset(path: Path, **overrides: object) -> dict[str, object]:
    payload = path.read_bytes()
    record: dict[str, object] = {
        "market_data_file_id": 1,
        "provider": "unknown",
        "data_type": "ticks",
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": "tick",
        "data_role": "candidate",
        "quality_status": "passed",
        "file_path": str(path),
        "source_scope": "approved_data_root",
        "content_gate_status": "not_applicable",
        "checksum": sha256(payload).hexdigest(),
        "physical_checksum": sha256(payload).hexdigest(),
        "file_size_bytes": len(payload),
        "physical_exists": True,
        "dataset_kind": None,
        "disposition": "RETIREMENT_CANDIDATE",
    }
    record.update(overrides)
    return record


def _replacement(source_id: int, source_checksum: str) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "command": "data.task07.apply",
        "status": "passed",
        "market_data_file_id": source_id,
        "physical_checksum": "c" * 64,
        "source_checksum": source_checksum,
        "manifest_digest": "d" * 64,
        "file_uri": "rqdata/continuous/jm/1m/part.parquet",
    }
    return {**body, "receipt_digest": canonical_digest(body)}


def _plan(tmp_path: Path, assets: list[dict[str, object]]) -> dict[str, object]:
    approved = tmp_path / "approved"
    quarantine = approved / ".task07-quarantine"
    quarantine.mkdir(mode=0o700, exist_ok=True)
    return build_deletion_plan(
        assets=assets,
        approved_roots=(approved,),
        quarantine_root=quarantine,
        base_sha=BASE_SHA,
        database_revision=REVISION,
        reference_digest="a" * 64,
    )


def test_plan_freezes_exact_identity_and_quarantine_only_policy(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "ticks.bin"
    source.write_bytes(b"obsolete")

    plan = _plan(tmp_path, [_asset(source)])

    item = plan["files"][0]
    stat = source.stat()
    assert item["lexical_path"] == str(source.absolute())
    assert item["resolved_path"] == str(source.resolve())
    assert item["approved_root_lexical"] == str(approved.absolute())
    assert item["approved_root_resolved"] == str(approved.resolve())
    assert item["root_dev"] == approved.stat().st_dev
    assert (item["file_dev"], item["file_inode"]) == (stat.st_dev, stat.st_ino)
    assert item["size"] == len(b"obsolete")
    assert item["mtime_ns"] == stat.st_mtime_ns
    assert item["sha256"] == sha256(b"obsolete").hexdigest()
    assert item["recoverability"] == "atomic_quarantine_restore"
    assert plan["permanent_unlink_authorized"] is False
    assert plan["deletion_authorized"] is False


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"source_scope": "protected_evidence_root"}, "TASK07_DELETION_PROTECTED"),
        ({"frequency": "15m", "disposition": "EXCLUDE_DERIVED"}, "TASK07_DELETION_KLINE_PRESERVED"),
        ({"disposition": "REGISTER_DATA_GAP"}, "TASK07_DELETION_DISPOSITION_BLOCKED"),
        ({"disposition": "CONFLICT_BLOCKED"}, "TASK07_DELETION_DISPOSITION_BLOCKED"),
        (
            {
                "provider": "rqdata",
                "data_type": "bars",
                "data_role": "primary",
                "disposition": "KEEP_CANONICAL_VERIFIED",
                "frequency": "1m",
            },
            "TASK07_DELETION_KLINE_PRESERVED",
        ),
    ],
)
def test_plan_excludes_protected_cold_unique_and_conflict_assets(
    tmp_path: Path, overrides: dict[str, object], code: str
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "asset.parquet"
    source.write_bytes(b"asset")

    with pytest.raises(Task07DeletionError, match=code):
        _plan(tmp_path, [_asset(source, **overrides)])


def test_direct_kline_is_preserved_even_with_forged_replacement_claim(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "bars.parquet"
    source.write_bytes(b"bars")
    asset = _asset(
        source,
        provider="rqdata",
        data_type="bars",
        frequency="1m",
        data_role="primary",
        dataset_kind="continuous",
        disposition="KEEP_CANONICAL_VERIFIED",
    )
    (approved / ".task07-quarantine").mkdir(mode=0o700)
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_KLINE_PRESERVED"):
        build_deletion_plan(
            assets=(asset,),
            approved_roots=(approved,),
            quarantine_root=approved / ".task07-quarantine",
            base_sha=BASE_SHA,
            database_revision=REVISION,
            reference_digest="a" * 64,
        )


def test_plan_rejects_symlink_and_path_outside_approved_root(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    link = approved / "link"
    link.symlink_to(outside)

    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_SYMLINK"):
        _plan(tmp_path, [_asset(link)])
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_OUTSIDE_ROOT"):
        _plan(tmp_path, [_asset(outside)])


def test_plan_rejects_historical_report_or_receipt_even_under_data_root(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    report_root = approved / "reports"
    report_root.mkdir(parents=True)
    report = report_root / "report-14.json"
    report.write_bytes(b"historical evidence")

    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_HISTORICAL_EVIDENCE"):
        _plan(tmp_path, [_asset(report)])


def test_preflight_rejects_stat_checksum_fact_and_approval_drift(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)

    build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    source.write_bytes(b"drift")
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_FILE_DRIFT"):
        build_deletion_preflight(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )
    source.write_bytes(b"old")
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_BASE_SHA_DRIFT"):
        build_deletion_preflight(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            current_base_sha="2" * 40,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )
    with pytest.raises(
        Task07DeletionError, match="TASK07_DELETION_DATABASE_REVISION_DRIFT"
    ):
        build_deletion_preflight(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            current_base_sha=BASE_SHA,
            current_database_revision="drifted",
            current_reference_digest="a" * 64,
        )
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_REFERENCE_DRIFT"):
        build_deletion_preflight(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="b" * 64,
        )
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_APPROVAL_HASH_MISMATCH"):
        build_deletion_preflight(
            plan,
            packet_path=packet_path,
            approval_hash="f" * 64,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )


def test_apply_quarantines_exact_files_and_verify_is_readonly(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    receipt = apply_deletion_plan(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        preflight=preflight,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    before = tuple((p, p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file())

    verified = verify_deletion_apply(
        plan,
        receipt,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )

    after = tuple((p, p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file())
    assert not source.exists()
    assert Path(receipt["files"][0]["quarantine_path"]).read_bytes() == b"old"
    assert receipt["permanent_unlink_authorized"] is False
    assert verified["readonly"] is True
    assert before == after


def test_mid_apply_failure_compensates_without_data_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    first = approved / "first.bin"
    second = approved / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    plan = _plan(tmp_path, [_asset(first), _asset(second, market_data_file_id=2)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    import app.data_core.task07_deletion as deletion

    original = deletion._rename_no_replace
    calls = 0

    def fail_second(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated rename failure")
        original(*args, **kwargs)

    monkeypatch.setattr(deletion, "_rename_no_replace", fail_second)
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_APPLY_COMPENSATED"):
        apply_deletion_plan(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            preflight=preflight,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )

    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_fsync_failure_after_rename_compensates_without_data_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    real_fsync = os.fsync
    calls = 0

    def fail_first_post_rename(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("simulated post-rename fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_first_post_rename)
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_APPLY_COMPENSATED"):
        apply_deletion_plan(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            preflight=preflight,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )

    assert source.read_bytes() == b"old"


def test_apply_rejects_cross_filesystem_and_existing_quarantine_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    import app.data_core.task07_deletion as deletion

    real_stat = deletion.os.stat

    def cross_device(path: object, *args: object, **kwargs: object):
        value = real_stat(path, *args, **kwargs)
        if Path(path) == Path(plan["quarantine_root"]):
            values = list(value)
            values[2] += 1
            return os.stat_result(values)
        return value

    monkeypatch.setattr(deletion.os, "stat", cross_device)
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_CROSS_FILESYSTEM"):
        apply_deletion_plan(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            preflight=preflight,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )

    monkeypatch.setattr(deletion.os, "stat", real_stat)
    quarantine = Path(plan["quarantine_root"])
    next(quarantine.glob("*.jsonl")).unlink()
    target = quarantine / f"1-{sha256(b'old').hexdigest()[:16]}-old.bin"
    target.write_bytes(b"preexisting")
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_TARGET_EXISTS"):
        apply_deletion_plan(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            preflight=preflight,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )
    assert source.read_bytes() == b"old"


def test_journal_and_directories_are_fsynced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    fsynced: list[int] = []
    real_fsync = os.fsync

    def tracked(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracked)
    apply_deletion_plan(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        preflight=preflight,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )

    assert len(fsynced) >= 4


def test_deletion_cli_forwards_exact_plan_arguments(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    engine = create_engine("sqlite://")
    captured: dict[str, object] = {}

    def runner(command: str, _session: object, args: object) -> dict[str, object]:
        captured.update(
            command=command,
            inventory=getattr(args, "inventory"),
            approved_root=getattr(args, "approved_root"),
            quarantine_root=getattr(args, "quarantine_root"),
        )
        return {"status": "passed", "approval_packet": None}

    exit_code = main(
        [
            "data",
            "task07",
            "deletion-plan",
            "--project-root",
            str(tmp_path),
            "--inventory",
            str(tmp_path / "inventory.json"),
            "--approved-root",
            str(tmp_path / "approved"),
            "--quarantine-root",
            str(tmp_path / "approved" / ".quarantine"),
        ],
        session_factory=lambda: Session(engine),
        data_core_runner=runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert captured == {
        "command": "task07.deletion-plan",
        "inventory": tmp_path / "inventory.json",
        "approved_root": [tmp_path / "approved"],
        "quarantine_root": tmp_path / "approved" / ".quarantine",
    }
    assert json.loads(stdout.getvalue())["approval_packet"] is None


def test_deletion_apply_is_blocked_before_database_without_exact_packet() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["data", "task07", "deletion-apply", "--plan", "/tmp/plan.json"],
        session_factory=lambda: (_ for _ in ()).throw(
            AssertionError("must not open database")
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 78
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == (
        "TASK07_RUNTIME_CUTOVER_GATE_REQUIRED"
    )


def _resign_apply_receipt(receipt: dict[str, object]) -> None:
    import app.data_core.task07_deletion as deletion

    excluded = {"schema_version", "command", "status", "receipt_digest", "effects"}
    facts = {key: value for key, value in receipt.items() if key not in excluded}
    receipt["receipt_digest"] = deletion._digest(
        "guiyi.task07.deletion-apply.v1", facts
    )


def test_verify_binds_receipt_paths_and_ids_to_plan_not_same_inode_hardlink(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    receipt = apply_deletion_plan(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        preflight=preflight,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    quarantine = Path(receipt["files"][0]["quarantine_path"])
    os.link(quarantine, source)
    receipt["files"][0]["source_path"] = str(tmp_path / "attacker-absent.bin")
    receipt["files"][0]["market_data_file_id"] = 999
    _resign_apply_receipt(receipt)

    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_RECEIPT_DRIFT"):
        verify_deletion_apply(
            plan,
            receipt,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )


def test_verify_rejects_extra_or_reordered_journal_events_even_when_resigned(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    receipt = apply_deletion_plan(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        preflight=preflight,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    journal = Path(receipt["journal_path"])
    with journal.open("ab") as handle:
        handle.write(b'{"event":"attacker-extra"}\n')
        handle.flush()
        os.fsync(handle.fileno())
    receipt["journal_sha256"] = sha256(journal.read_bytes()).hexdigest()
    _resign_apply_receipt(receipt)

    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_JOURNAL_DRIFT"):
        verify_deletion_apply(
            plan,
            receipt,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )


def test_deletion_plan_is_not_eligible_before_trusted_task6_runtime_cutover(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    quarantine = approved / ".task07-quarantine"
    quarantine.mkdir(mode=0o700)
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])

    assert plan["deletion_eligible"] is False
    assert plan["runtime_cutover_gate"] == "BLOCKED_TASK07_RUNTIME_CUTOVER_REQUIRED"
    with pytest.raises(Task07DeletionError, match="TASK07_RUNTIME_CUTOVER_GATE_REQUIRED"):
        public_build_deletion_approval_packet(plan)


def test_deletion_cli_rejects_caller_selected_runtime_root(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "task07",
            "deletion-plan",
            "--project-root",
            str(tmp_path),
            "--inventory",
            str(tmp_path / "inventory.json"),
            "--approved-root",
            str(tmp_path / "approved"),
            "--quarantine-root",
            str(tmp_path / "approved" / ".quarantine"),
            "--canonical-root",
            str(tmp_path / "canonical"),
            "--runtime-root",
            str(tmp_path / "caller-runtime"),
        ],
        session_factory=lambda: (_ for _ in ()).throw(
            AssertionError("must not open database")
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


def test_plan_freezes_existing_private_quarantine_identity(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    quarantine = approved / ".task07-quarantine"
    quarantine.mkdir(mode=0o700)
    source = approved / "old.bin"
    source.write_bytes(b"old")

    plan = _plan(tmp_path, [_asset(source)])

    value = quarantine.stat()
    assert plan["quarantine_root_lexical"] == str(quarantine.absolute())
    assert plan["quarantine_root_resolved"] == str(quarantine.resolve())
    assert plan["quarantine_dev"] == value.st_dev
    assert plan["quarantine_inode"] == value.st_ino


def test_plan_rejects_symlink_in_quarantine_parent_chain(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    real_parent = approved / "real"
    real_parent.mkdir()
    linked_parent = approved / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    quarantine = linked_parent / "quarantine"
    quarantine.mkdir(mode=0o700)
    source = approved / "old.bin"
    source.write_bytes(b"old")

    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_QUARANTINE_SYMLINK"):
        build_deletion_plan(
            assets=(_asset(source),),
            approved_roots=(approved,),
            quarantine_root=quarantine,
            base_sha=BASE_SHA,
            database_revision=REVISION,
            reference_digest="a" * 64,
        )


def test_core_rejects_v2_canonical_and_unknown_plan_annotations(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / ".task07-quarantine").mkdir(mode=0o700)
    source = approved / "canonical.parquet"
    source.write_bytes(b"canonical")
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_KLINE_PRESERVED"):
        _plan(
            tmp_path,
            [
                _asset(
                    source,
                    data_type="v2_canonical",
                    frequency="tick",
                    disposition="RETIREMENT_CANDIDATE",
                )
            ],
        )

    legacy = approved / "legacy.bin"
    legacy.write_bytes(b"legacy")
    plan = _plan(tmp_path, [_asset(legacy)])
    plan["attacker_annotation"] = True
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_PLAN_INVALID"):
        build_deletion_approval_packet(plan)


def test_public_preflight_and_apply_are_blocked_without_task6_receipt(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet_path = tmp_path / "packet.json"
    packet_path.write_text("{}", encoding="utf-8")
    with pytest.raises(Task07DeletionError, match="TASK07_RUNTIME_CUTOVER_GATE_REQUIRED"):
        public_build_deletion_preflight(
            plan,
            packet_path=packet_path,
            approval_hash="a" * 64,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )
    with pytest.raises(Task07DeletionError, match="TASK07_RUNTIME_CUTOVER_GATE_REQUIRED"):
        public_apply_deletion_plan(
            plan,
            packet_path=packet_path,
            approval_hash="a" * 64,
            preflight={},
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )


def test_journal_create_is_exclusive_even_if_path_precheck_is_raced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    journal = Path(plan["quarantine_root"]) / f"{plan['plan_digest']}.jsonl"
    journal.write_text("attacker", encoding="utf-8")
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    real_exists = Path.exists

    def raced_exists(path: Path) -> bool:
        if path == journal:
            return False
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", raced_exists)
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_JOURNAL_ALREADY_EXISTS"):
        apply_deletion_plan(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            preflight=preflight,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )
    assert source.read_bytes() == b"old"


def test_partial_journal_write_is_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "old.bin"
    source.write_bytes(b"old")
    plan = _plan(tmp_path, [_asset(source)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    real_write = os.write
    partial_once = True

    def partial_write(fd: int, payload: bytes) -> int:
        nonlocal partial_once
        if partial_once and len(payload) > 1:
            partial_once = False
            return real_write(fd, payload[: len(payload) // 2])
        return real_write(fd, payload)

    monkeypatch.setattr(os, "write", partial_write)
    receipt = apply_deletion_plan(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        preflight=preflight,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    assert verify_deletion_apply(
        plan,
        receipt,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )["status"] == "passed"


def test_committed_and_recovery_journal_failures_still_restore_every_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    first = approved / "first.bin"
    second = approved / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    plan = _plan(tmp_path, [_asset(first), _asset(second, market_data_file_id=2)])
    packet = build_deletion_approval_packet(plan)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    preflight = build_deletion_preflight(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha=BASE_SHA,
        current_database_revision=REVISION,
        current_reference_digest="a" * 64,
    )
    import app.data_core.task07_deletion as deletion

    real_append = deletion._append_journal_fd
    journal_failed = False

    def fail_from_committed(fd: int, entry: dict[str, object]) -> None:
        nonlocal journal_failed
        if entry.get("event") == "committed":
            journal_failed = True
        if journal_failed:
            raise OSError("persistent journal failure")
        real_append(fd, entry)

    monkeypatch.setattr(deletion, "_append_journal_fd", fail_from_committed)
    with pytest.raises(Task07DeletionError, match="TASK07_DELETION_APPLY_COMPENSATED"):
        apply_deletion_plan(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            preflight=preflight,
            current_base_sha=BASE_SHA,
            current_database_revision=REVISION,
            current_reference_digest="a" * 64,
        )

    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
