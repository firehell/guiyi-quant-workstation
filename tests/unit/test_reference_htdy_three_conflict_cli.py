from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/reference_htdy_conflict_recovery.py"


@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location("htdy_three_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_scope_is_separate_from_default48(cli):
    ids = tuple(cli.OCT31_BINDINGS)
    assert cli.checked_scope(ids, incident=cli.OCT31_VERSION) == tuple(sorted(ids))
    with pytest.raises(ValueError, match="FROZEN_SCOPE"):
        cli.checked_scope(ids)


def test_new_scope_rejects_arbitrary_three_and_duplicate(cli):
    ids = list(cli.OCT31_BINDINGS)
    for bad in (ids[:2], ids + [ids[0]], [*ids[:2], "foreign"]):
        with pytest.raises(ValueError, match="FROZEN_SCOPE"):
            cli.checked_scope(bad, incident=cli.OCT31_VERSION)


def test_exact_new_inventory_does_not_accept_changed_bytes(cli, tmp_path, monkeypatch):
    assert (
        cli.OCT31_INVENTORY_SHA256
        == "b52df9f680afaea1a974bfc11c7d79b96a1f837f6813977ca7645bbf37bd8788"
    )
    raw = json.dumps(
        {
            "pending": [
                {
                    "stream_id": sid,
                    "revision_id": rev,
                    "capture_id": cap,
                    "code": "OBSERVATION_GAP",
                }
                for sid, (rev, cap) in cli.OCT31_BINDINGS.items()
            ]
        }
    ).encode()
    monkeypatch.setattr(cli, "OCT31_INVENTORY_SHA256", sha256(raw).hexdigest())
    path = tmp_path / "inventory.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    assert sha256(raw).hexdigest() == cli.OCT31_INVENTORY_SHA256
    assert cli.frozen_scope(path, incident=cli.OCT31_VERSION) == tuple(
        sorted(cli.OCT31_BINDINGS)
    )
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="INVENTORY_DRIFT"):
        cli.frozen_scope(path, incident=cli.OCT31_VERSION)


class ThreeBackend:
    def __init__(self, cli):
        self.cli = cli
        self.now = datetime(2026, 10, 31, 4, tzinfo=UTC)
        self.result = None
        self.apply_calls = 0

    def identity(self):
        return {
            "root": "/fixed/code",
            "commit": "a" * 40,
            "tag": "v1.16.48",
            "config_sha256": "b" * 64,
        }

    def check_window(self):
        pass

    @contextmanager
    def fenced(self):
        yield self

    def plan(self, ids, **kwargs):
        return {
            "version": self.cli.OCT31_VERSION,
            "plan_hash": "c" * 64,
            "items": [
                {
                    "binding": {
                        "stream_id": sid,
                        "revision_id": self.cli.OCT31_BINDINGS[sid][0],
                        "checkpoint_sha256": "d" * 64,
                        "checkpoint": {
                            "reference_state": {
                                "open_trade": {"reference_trade_id": "original-ss-open"}
                                if sid == self.cli.OCT31_OPEN_STREAM
                                else None
                            }
                        },
                    }
                }
                for sid in ids
            ],
        }

    def apply(self, plan, **kwargs):
        self.apply_calls += 1
        self.result = {i["binding"]["stream_id"]: "new" for i in plan["items"]}
        return self.result

    def readback(self, plan):
        return self.result


def new_plan(cli, tmp_path):
    backend = ThreeBackend(cli)
    runner = cli.Coordinator(
        backend,
        tmp_path / "attempt",
        clock=lambda: backend.now,
        incident=cli.OCT31_VERSION,
    )
    path = tmp_path / "plan.json"
    p = runner.plan(
        path,
        cli.OCT31_BINDINGS,
        inventory_sha256=cli.OCT31_INVENTORY_SHA256,
        recording_start=backend.now + timedelta(minutes=30),
        expires_at=backend.now + timedelta(minutes=5),
    )
    return backend, runner, path, p


def test_three_once_private_claim_and_original_profile_cannot_load(cli, tmp_path):
    b, runner, path, p = new_plan(cli, tmp_path)
    assert p["schema"] == "reference_htdy_conflict_cli_20261031_v1"
    assert len(p["stream_ids"]) == 3 and len(p["open_trades"]) == 1
    original_apply = b.apply

    def apply(*args, **kwargs):
        assert (runner.directory / "apply-claim.json").exists()
        return original_apply(*args, **kwargs)

    b.apply = apply
    result = runner.apply(path, expected_plan_hash=p["plan_hash"])
    assert result["status"] == "COMMITTED" and result["streams"] == 3
    with pytest.raises(FileExistsError):
        runner.apply(path, expected_plan_hash=p["plan_hash"])
    assert b.apply_calls == 1
    old = cli.Coordinator(b, runner.directory, clock=lambda: b.now)
    with pytest.raises(ValueError, match="PLAN_INVALID"):
        old.status(path, expected_plan_hash=p["plan_hash"])


@pytest.mark.parametrize("change", ["missing", "foreign", "extra"])
def test_three_exact_single_ss_open_is_required(cli, tmp_path, change):
    b, runner, path, p = new_plan(cli, tmp_path)
    domain = p["domain_plan"]
    for item in domain["items"]:
        sid = item["binding"]["stream_id"]
        state = item["binding"]["checkpoint"]["reference_state"]
        if sid == cli.OCT31_OPEN_STREAM and change in ("missing", "foreign"):
            state["open_trade"] = None
        if sid != cli.OCT31_OPEN_STREAM and change in ("extra", "foreign"):
            state["open_trade"] = {"reference_trade_id": "foreign"}
            break
    with pytest.raises(ValueError, match="OPEN_SCOPE_DRIFT"):
        cli.frozen_open_trades(domain, incident=cli.OCT31_VERSION)
