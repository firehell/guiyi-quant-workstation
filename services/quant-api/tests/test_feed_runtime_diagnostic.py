"""Host decoder checks; never attach to any service or contact a provider."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


_PATH = Path(__file__).resolve().parents[3] / "scripts/ops/macos/feed_runtime_diagnostic.py"
_SPEC = importlib.util.spec_from_file_location("feed_runtime_diagnostic_tested", _PATH)
diagnostic = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(diagnostic)


def test_snapshot_hash_compares_values_and_ignores_pair_order():
    assert diagnostic._snapshot_hash("2026-11-02", [("jm", "JM2701"), ("rb", "RB2701")]) == (
        diagnostic._snapshot_hash("2026-11-02", [("rb", "RB2701"), ("jm", "JM2701")]))
    assert diagnostic._snapshot_hash("2026-11-02", [("jm", "JM2701")]) != (
        diagnostic._snapshot_hash("2026-11-03", [("jm", "JM2701")]))
    assert diagnostic._snapshot_hash("2026-11-02", [("jm", "JM2701")]) != (
        diagnostic._snapshot_hash("2026-11-02", [("jm", "JM2705")]))


@pytest.mark.parametrize("pairs", [[("jm", "JM2701"), ("jm", "JM2705")],
                                    [("jm", "secret value")], [("jm",)], [("jm", "JM2701", "extra")]])
def test_snapshot_rejects_ambiguous_or_nonidentity_values(pairs):
    with pytest.raises(ValueError):
        diagnostic._snapshot_hash("2026-11-02", pairs)


@pytest.mark.parametrize("flags,basicsize", [(16, 16), (20, 24)])
def test_inline_dictionary_requires_flag_and_exact_basicsize(flags, basicsize):
    reader = object.__new__(diagnostic._Reader)
    reader.off = {"pyobject": {"ob_type": 8}, "type_object": {"tp_flags": 168}}
    reader.layout = {"managed_dict_flag": 16, "inline_values_flag": 4,
                     "managed_dict_offset": -24, "type_basicsize": 32, "object_size": 16}
    memory = {10008: 20000, 20168: flags, 9976: 0, 20032: basicsize}
    reader.integer = lambda address, *args, **kwargs: memory[address]
    with pytest.raises(ValueError, match="INLINE_VALUES_UNPROVEN"):
        reader.attrs(10000, {"_provider"})


def test_private_output_never_overwrites_or_follows_symlink(tmp_path):
    target = tmp_path / "target"
    target.write_text("preserved")
    link = tmp_path / "output"
    link.symlink_to(target)
    with pytest.raises(OSError):
        diagnostic._private_write(link, {"status": "UNPROVEN"})
    assert target.read_text() == "preserved"
    output = tmp_path / "proof"
    diagnostic._private_write(output, {"status": "UNPROVEN"})
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        diagnostic._private_write(output, {})


def test_successful_proof_exposes_only_bound_identity_and_snapshot(tmp_path, monkeypatch):
    process = SimpleNamespace(GetProcessID=lambda: 12345, GetNumThreads=lambda: 0,
                              Detach=lambda: SimpleNamespace(Success=lambda: True))
    debugger = SimpleNamespace(GetSelectedTarget=lambda: SimpleNamespace(GetProcess=lambda: process))

    class Reader:
        off = {"tuple_object": {"ob_size": 16}}
        def service(self, root):
            return 100
        def attrs(self, obj, allowed):
            values = {
                100: {"_input_failure": 20, "_closed_retirement_failed": True, "_provider": 200,
                      "_pending": 40, "_trading_day": 60, "_contracts": 70, "_cleanup_isolation": 300},
                200: {"_close_succeeded": True, "_close_failed": False, "_closed": True,
                      "_messages": 50, "_listener": 0, "_retired_listener": 0},
                300: {"day": 60, "local_day": 60, "provider": 200, "contracts": 400},
            }
            return {key: value for key, value in values[obj].items() if key in allowed}
        def string(self, obj):
            return {20: "LIVE_PROVIDER_CLOSE_UNKNOWN", 401: "jm", 402: "JM2701"}[obj]
        def boolean(self, obj):
            return obj
        def typename(self, obj):
            return {0: "NoneType", 40: "dict", 50: "collections.deque", 200: "RQDataLiveProvider",
                    300: "_CleanupIsolation"}[obj]
        def integer(self, address, **kwargs):
            assert address in (48, 66)
            return 0
        def tuple(self, obj, maximum=256):
            return {400: [410], 410: [401, 402]}[obj]
        def dict_pairs(self, obj):
            assert obj == 70
            return [("jm", 402)]
        def day(self, obj):
            assert obj == 60
            return "2026-11-02"

    monkeypatch.setitem(sys.modules, "lldb", SimpleNamespace())
    monkeypatch.setattr(diagnostic, "_Reader", lambda *args: Reader())
    layout = tmp_path / "layout.json"
    layout.write_text('{"dict_used":8}')
    output = tmp_path / "proof.json"
    identity = "a" * 64
    diagnostic.inspect(debugger, "/fixture", layout, output, identity)
    proof = json.loads(output.read_text())
    assert proof["status"] == "READ_ONLY_INSPECTED"
    assert proof["pid"] == 12345 and proof["process_identity"] == identity
    assert proof["isolation_day"] == "2026-11-02"
    assert proof["isolation_provider_matches"] and proof["isolation_snapshot_matches"]
    assert proof["isolation_local_day_matches"] and proof["detached"]
    assert proof["isolation_snapshot_sha256"] == diagnostic._snapshot_hash("2026-11-02", [("jm", "JM2701")])
    assert "JM2701" not in output.read_text()
