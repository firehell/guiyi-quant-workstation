from __future__ import annotations

import importlib.util
from pathlib import Path

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
