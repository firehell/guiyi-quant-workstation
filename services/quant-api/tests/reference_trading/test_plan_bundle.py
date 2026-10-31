from hashlib import sha256
import json

import pytest
from app.reference_trading import plan_bundle as codec


def large():
    return {
        "plan_hash": "f" * 64,
        "values": [sha256(str(i).encode()).hexdigest() for i in range(1000)],
    }


def test_bundle_roundtrip_and_plain_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(codec, "INLINE_BYTES", 512)
    monkeypatch.setattr(codec, "CHUNK_BYTES", 1024)
    path = tmp_path / "plan.json"
    codec.write_plan(path, large())
    envelope = json.loads(path.read_text())
    assert envelope["codec"] == codec.CODEC
    assert len(envelope["chunks"]) > 1
    assert codec.read_plan(path) == large()
    with pytest.raises(ValueError):
        codec.write_plan(path, large())
    plain = tmp_path / "plain.json"
    codec.write_plan(plain, {"small": True})
    assert codec.read_plan(plain) == {"small": True}


@pytest.mark.parametrize(
    "change", ["missing", "tamper", "duplicate", "escape", "symlink", "size", "tail"]
)
def test_bundle_rejects_unproven_chunks(tmp_path, monkeypatch, change):
    monkeypatch.setattr(codec, "INLINE_BYTES", 512)
    monkeypatch.setattr(codec, "CHUNK_BYTES", 1024)
    path = tmp_path / "plan.json"
    codec.write_plan(path, large())
    head = json.loads(path.read_text())
    parts = tmp_path / "plan.json.parts"
    first = parts / head["chunks"][0]["name"]
    if change == "missing":
        first.unlink()
    if change == "tamper":
        first.write_bytes(b"bad")
    if change == "duplicate":
        head["chunks"].append(head["chunks"][0])
    if change == "escape":
        head["chunks"][0]["name"] = "../secret"
    if change == "symlink":
        target = tmp_path / "target"
        first.rename(target)
        first.symlink_to(target)
    if change == "size":
        head["decoded_bytes"] = codec.MAX_DECODED_BYTES + 1
    if change == "tail":
        last = head["chunks"][-1]
        p = parts / last["name"]
        data = p.read_bytes() + b"junk"
        p.write_bytes(data)
        last["bytes"] = len(data)
    path.write_text(json.dumps(head))
    with pytest.raises(ValueError):
        codec.read_plan(path)


def test_bundle_rejects_linked_directory_and_partial_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(codec, "INLINE_BYTES", 512)
    path = tmp_path / "plan.json"
    codec.write_plan(path, large())
    parts = tmp_path / "plan.json.parts"
    parts.rename(tmp_path / "other")
    parts.symlink_to(tmp_path / "other", target_is_directory=True)
    with pytest.raises(ValueError):
        codec.read_plan(path)
    missing = tmp_path / "unfinished.json"
    (tmp_path / "unfinished.json.parts").mkdir()
    with pytest.raises(ValueError):
        codec.read_plan(missing)


def test_cli_bundle_keeps_original_plan_hash_and_dry_run(tmp_path, monkeypatch):
    from argparse import Namespace
    from app.guiyi_cli.reference_commands import run_reference_command
    from app.reference_trading.planning import plan_to_dict
    from tests.reference_trading.test_bootstrap import Reader, _plan

    plan = _plan(Reader())
    path = tmp_path / "plan.json"
    codec.write_plan(path, plan_to_dict(plan), force_bundle=True)
    result = run_reference_command(
        Namespace(
            reference_command="build",
            plan=str(path),
            expected_plan_hash=plan.plan_hash,
            apply=False,
        )
    )
    assert result["readonly"] and result["plan_hash"] == plan.plan_hash


def test_refresh_control_remains_small_and_corrupt_side_file_blocks(tmp_path):
    from app.reference_trading.historical_refresh import (
        RefreshStateStore,
        VERSION,
        PLAN_FILE_CODEC,
    )

    store = RefreshStateStore(tmp_path / "refresh.json")
    value = {
        "version": VERSION,
        "cursor": "s",
        "routes": {"s": {"status": "pending", "plan": large()}},
    }
    store.write(value)
    state = store.read()
    reference = state["routes"]["s"]["plan"]
    assert reference["codec"] == PLAN_FILE_CODEC
    assert store.path.stat().st_size < 1000
    assert store.read_plan(reference) == large()
    folder = tmp_path / "refresh.json.plans"
    artifact = folder / reference["file"]
    artifact.write_text("{}")
    state = store.read()  # Unselected plans are not expanded.
    with pytest.raises(ValueError):
        store.read_plan(state["routes"]["s"]["plan"])


@pytest.mark.parametrize("where", ["descriptor", "chunk"])
def test_fifo_is_rejected_before_any_blocking_read(tmp_path, monkeypatch, where):
    import os
    from time import monotonic

    path = tmp_path / "fifo-plan.json"
    if where == "descriptor":
        os.mkfifo(path)
    else:
        codec.write_plan(path, large(), force_bundle=True)
        head = json.loads(path.read_text())
        first = path.with_name(path.name + ".parts") / head["chunks"][0]["name"]
        first.unlink()
        os.mkfifo(first)
    start = monotonic()
    with pytest.raises(ValueError):
        codec.read_plan(path)
    assert monotonic() - start < 1


def test_bundle_streams_large_value_without_canonical_byte_copy(tmp_path, monkeypatch):
    original = codec.canonical_bytes
    value = {'input_fingerprints': ['a' * 64] * 2049}
    expected_size, expected_digest = codec.canonical_size_digest(value)

    def small_header_only(item):
        assert 'input_fingerprints' not in item
        return original(item)

    monkeypatch.setattr(codec, 'canonical_bytes', small_header_only)
    path = tmp_path / 'streamed.json'
    codec.write_plan(path, value, force_bundle=True)
    head = json.loads(path.read_text())
    assert (head['decoded_bytes'], head['decoded_sha256']) == (expected_size, expected_digest)
    assert codec.read_plan(path) == value
