from __future__ import annotations

import importlib.util
from datetime import date, datetime, UTC
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "jm_htdy_s6_08_schema_v3_gate.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "jm_htdy_s6_08_schema_v3_gate",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_and_runtime_git_identities_are_collected_from_distinct_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    source_root = tmp_path / "source"
    runtime_root = tmp_path / "runtime"
    source_root.mkdir()
    runtime_root.mkdir()
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_git(root: Path, *arguments: str) -> str:
        calls.append((root, arguments))
        if arguments == ("branch", "--show-current"):
            return "codex/v1-htdy-step04-final-closure"
        if arguments[:2] == ("status", "--porcelain=v1"):
            return ""
        if arguments == ("rev-parse", "HEAD"):
            return "1" * 40 if root == source_root else "2" * 40
        if arguments == ("rev-parse", "HEAD^{tree}"):
            return "3" * 40 if root == source_root else "4" * 40
        raise AssertionError(arguments)

    monkeypatch.setattr(module, "_git", fake_git)

    identities = module.collect_source_runtime_git_identities(
        source_root=source_root,
        runtime_root=runtime_root,
    )

    assert identities["source"]["commit"] == "1" * 40
    assert identities["runtime"]["commit"] == "2" * 40
    assert identities["runtime"]["tree"] == "4" * 40
    assert (runtime_root, ("rev-parse", "HEAD")) in calls


def test_service_parent_binds_approved_target_runtime_identity(
    tmp_path: Path,
) -> None:
    module = _module()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    identities = {
        "source": {
            "commit": "1" * 40,
            "tree": "2" * 40,
        },
        "runtime": {
            "commit": "3" * 40,
            "tree": "4" * 40,
        },
    }

    binding = module.target_runtime_binding(
        identities,
        runtime_root=runtime_root,
    )

    assert binding["root"] == str(runtime_root.resolve())
    assert binding["commit"] == "1" * 40
    assert binding["commit"] != identities["runtime"]["commit"]
    assert len(binding["tree_sha256"]) == 64
    assert binding["tracked_clean"] is True


def test_retired_step34_branch_cannot_generate_new_packets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    source_root = tmp_path / "source"
    runtime_root = tmp_path / "runtime"
    source_root.mkdir()
    runtime_root.mkdir()

    def fake_git(root: Path, *arguments: str) -> str:
        if arguments == ("branch", "--show-current"):
            return "codex/v1-htdy-step34-completion"
        if arguments[:2] == ("status", "--porcelain=v1"):
            return ""
        return "1" * 40

    monkeypatch.setattr(module, "_git", fake_git)

    with pytest.raises(RuntimeError, match="source_identity_invalid"):
        module.collect_source_runtime_git_identities(
            source_root=source_root,
            runtime_root=runtime_root,
        )


def test_parent_uses_latest_known_mapping_not_future_window_day() -> None:
    module = _module()
    rows = [
        SimpleNamespace(
            id=7,
            trade_date=date(2026, 7, 23),
            contract_code="JM2609",
            data_version="mapping-23",
            created_at=datetime(2026, 7, 23, tzinfo=UTC),
        ),
        SimpleNamespace(
            id=8,
            trade_date=date(2026, 7, 24),
            contract_code="JM2609",
            data_version="mapping-24",
            created_at=datetime(2026, 7, 24, tzinfo=UTC),
        ),
    ]

    identity = module.select_parent_mapping_identity(
        rows,
        as_of_date=date(2026, 7, 26),
    )

    assert identity["trade_date"] == "2026-07-24"
    assert identity["contract_code"] == "JM2609"
    assert len(identity["sha256"]) == 64


def test_parent_latest_mapping_duplicate_or_future_only_fails_closed() -> None:
    module = _module()
    latest = SimpleNamespace(
        id=8,
        trade_date=date(2026, 7, 24),
        contract_code="JM2609",
        data_version="mapping-24",
        created_at=datetime(2026, 7, 24, tzinfo=UTC),
    )

    with pytest.raises(
        RuntimeError,
        match="parent_mapping_missing_or_duplicate",
    ):
        module.select_parent_mapping_identity(
            [latest, SimpleNamespace(**{**vars(latest), "id": 9})],
            as_of_date=date(2026, 7, 26),
        )
    with pytest.raises(
        RuntimeError,
        match="parent_mapping_missing_or_duplicate",
    ):
        module.select_parent_mapping_identity(
            [
                SimpleNamespace(
                    id=10,
                    trade_date=date(2026, 7, 27),
                    contract_code="JM2609",
                    data_version="mapping-27",
                    created_at=datetime(2026, 7, 27, tzinfo=UTC),
                )
            ],
            as_of_date=date(2026, 7, 26),
        )
