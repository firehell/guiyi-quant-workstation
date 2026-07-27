from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from scripts import jm_htdy_s6_10_stability_gate as cli


@pytest.mark.parametrize(
    "mode",
    (
        "prepare",
        "verify",
        "calendar-apply",
        "start",
        "sample",
        "seal-day",
        "inject-fault",
        "finalize",
        "stop",
    ),
)
def test_cli_exposes_exact_modes(mode: str) -> None:
    args = cli.parse_args(
        [
            mode,
            "--output-dir",
            "/tmp/s610",
            "--parent-packet",
            "/tmp/s610/parent.json",
        ]
    )
    assert args.mode == mode


def test_prepare_fails_before_writes_when_independent_backup_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "collect_backup_mount_facts",
        lambda _path: (_ for _ in ()).throw(
            cli.HtDyS610Error("backup_mount_missing")
        ),
    )
    result = cli.main(
        [
            "prepare",
            "--output-dir",
            str(tmp_path),
            "--parent-packet",
            str(tmp_path / "parent.json"),
        ]
    )
    assert result == 2
    assert not list(tmp_path.iterdir())
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "blocked",
        "error_type": "HtDyS610Error",
        "reason": "backup_mount_missing",
        "writes_authorized": False,
    }


def test_fault_and_calendar_modes_require_exact_approval_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for mode in ("calendar-apply", "start", "inject-fault", "finalize"):
        result = cli.main(
            [
                mode,
                "--output-dir",
                str(tmp_path),
                "--parent-packet",
                str(tmp_path / "missing.json"),
            ]
        )
        assert result == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["reason"] == "approval_hash_required"


def test_high_risk_modes_require_separately_approved_bundle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for mode in ("calendar-apply", "start", "inject-fault", "finalize"):
        result = cli.main(
            [
                mode,
                "--output-dir",
                str(tmp_path),
                "--parent-packet",
                str(tmp_path / "missing.json"),
                "--approval-hash",
                "a" * 64,
            ]
        )
        assert result == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["reason"] == "approval_c_signed_receipt_required"


def test_required_day_uses_frozen_friday_night_for_monday() -> None:
    packet = {
        "trading_days": ["2026-08-03"],
        "calendar_rows": [
            {
                "trade_date": "2026-08-03",
                "night_session_date": "2026-07-31",
            }
        ],
    }
    args = SimpleNamespace(trading_day=None)
    assert cli._required_day(
        args,
        packet,
        now=datetime(
            2026,
            7,
            31,
            21,
            1,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
    ) == date(2026, 8, 3)


def test_backup_restore_receipts_require_full_0025_and_readonly_smoke(
    tmp_path: Path,
) -> None:
    backup = {
        "schema_version": "guiyi_local_backup_v1",
        "status": "completed",
        "mode": "full",
        "retention_class": "milestone",
        "excluded_categories": ["data/raw"],
        "database": {
            "included": True,
            "alembic_revision": "20260721_0025",
            "report14": {"md5": "ae807ef77f7d9a4ce3067996558b57e8"},
        },
        "inventory": {"file_count": 3, "sha256": "a" * 64},
        "boundaries": {
            "secrets_included": False,
            "production_restore_authorized": False,
        },
    }
    backup_mount = tmp_path / "backup-mount"
    backup_root = backup_mount / "guiyi-v1-full-s610-test-abcdef123456"
    backup_root.mkdir(parents=True)
    backup_path = backup_root / "backup_manifest.json"
    backup_path.write_text(json.dumps(backup), encoding="utf-8")
    restore = {
        "schema_version": "guiyi_isolated_restore_v1",
        "status": "passed",
        "backup": {
            "manifest_sha256": cli._file_hash(backup_path),
        },
        "artifact_verification": {
            "all_declared_files_verified": True,
            "profile_verified": True,
        },
        "database": {
            "alembic_revision": "20260721_0025",
            "report14": {"md5": "ae807ef77f7d9a4ce3067996558b57e8"},
        },
        "consumer_smoke": [
            {"consumer": name, "method": "GET", "status": "passed"}
                for name in (
                    "market",
                    "backtest",
                    "signal_latest",
                    "signal_events",
                    "review",
                )
            ],
        "tool": {"postgres_image": "postgres:16"},
        "isolated": {
            "target_database": "guiyi_restore_s610_test",
            "target_data_root": "",
            "container_removed": True,
            "volume_removed": True,
        },
        "boundaries": {
            "transaction_read_only": True,
            "database_unchanged": True,
            "production_database_touched": False,
            "production_data_touched": False,
            "wechat_called": False,
        },
    }
    restore_parent = tmp_path / "restore-parent"
    restore_root = restore_parent / "guiyi-restore-s610-test"
    restore_root.mkdir(parents=True)
    restore_path = restore_root / "isolated_restore_receipt.json"
    restore["isolated"]["target_data_root"] = str(restore_root)
    restore_path.write_text(json.dumps(restore), encoding="utf-8")
    (restore_root / "isolated_restore_receipt.sha256").write_text(
        cli._file_hash(restore_path) + "\n",
        encoding="utf-8",
    )
    verifier = lambda _root: SimpleNamespace(  # noqa: E731
        manifest=backup,
        manifest_sha256=cli._file_hash(backup_path),
    )
    audit_root = restore_parent / "guiyi-restore-s610-audit-test"
    audit_root.mkdir()
    audit = json.loads(json.dumps(restore))
    audit["isolated"]["target_database"] = "guiyi_restore_s610_audit_test"
    audit["isolated"]["target_data_root"] = str(audit_root)
    audit_path = audit_root / "isolated_restore_receipt.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    (audit_root / "isolated_restore_receipt.sha256").write_text(
        cli._file_hash(audit_path) + "\n",
        encoding="utf-8",
    )
    restore_executor = lambda *_args: audit_path  # noqa: E731
    cli.validate_backup_restore_receipts(
        backup_path,
        restore_path,
        backup_mount=backup_mount,
        restore_parent=restore_parent,
        artifact_verifier=verifier,
        restore_executor=restore_executor,
    )

    restore["boundaries"]["production_database_touched"] = True
    restore_path.write_text(json.dumps(restore), encoding="utf-8")
    (restore_root / "isolated_restore_receipt.sha256").write_text(
        cli._file_hash(restore_path) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(cli.HtDyS610Error, match="restore_boundary_invalid"):
        cli.validate_backup_restore_receipts(
            backup_path,
            restore_path,
            backup_mount=backup_mount,
            restore_parent=restore_parent,
            artifact_verifier=verifier,
            restore_executor=restore_executor,
        )
