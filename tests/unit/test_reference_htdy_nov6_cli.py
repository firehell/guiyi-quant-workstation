"""Nov6 CLI binds the exact approved originals and both OPEN reference IDs."""

from hashlib import sha256
import json
import pytest
from tests.unit.test_reference_htdy_three_conflict_cli import cli as _cli


@pytest.fixture
def cli():
    return _cli.__wrapped__()


def inventory(cli):
    return {
        "pending": [
            dict(
                stream_id=sid,
                revision_id=v[0],
                capture_id=v[1],
                activation_generation=v[2],
                checkpoint_batch_id=v[3],
                reference_trade_id=v[4],
                reference_open=v[4] is not None,
                code="OBSERVATION_GAP",
                endpoint_shift_equal=True,
            )
            for sid, v in cli.NOV06_BINDINGS.items()
        ]
    }


def test_nov6_exact_inventory_and_no_wider_scope(cli, tmp_path, monkeypatch):
    assert len(cli.NOV06_BINDINGS) == 11
    assert sum(v[4] is not None for v in cli.NOV06_BINDINGS.values()) == 2
    assert cli.schema(cli.NOV06_VERSION) == "reference_htdy_conflict_cli_20261106_v1"
    assert (
        cli.inventory_sha(cli.NOV06_VERSION)
        == "0edfab2eefb2042ae33fba864caf2934eb7e897feb8ed2a4fd5c3172f466dada"
    )
    raw = json.dumps(inventory(cli)).encode()
    monkeypatch.setattr(cli, "NOV06_INVENTORY_SHA256", sha256(raw).hexdigest())
    p = tmp_path / "inventory.json"
    p.write_bytes(raw)
    p.chmod(0o600)
    assert cli.frozen_scope(p, incident=cli.NOV06_VERSION) == tuple(
        sorted(cli.NOV06_BINDINGS)
    )
    p.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="INVENTORY_DRIFT"):
        cli.frozen_scope(p, incident=cli.NOV06_VERSION)
    for ids in (
        list(cli.NOV06_BINDINGS)[:-1],
        list(cli.NOV06_BINDINGS) + ["outside"],
        list(cli.NOV06_BINDINGS) + [next(iter(cli.NOV06_BINDINGS))],
    ):
        with pytest.raises(ValueError, match="FROZEN_SCOPE"):
            cli.checked_scope(ids, incident=cli.NOV06_VERSION)
    with pytest.raises(ValueError, match="FROZEN_SCOPE"):
        cli.checked_scope(cli.NOV06_BINDINGS)


@pytest.mark.parametrize("change", ["missing_open", "foreign_open", "extra_open"])
def test_nov6_open_identity_is_exact(cli, change):
    items = [
        {
            "binding": {
                "stream_id": sid,
                "revision_id": v[0],
                "checkpoint_sha256": "a" * 64,
                "checkpoint": {
                    "reference_state": {
                        "open_trade": None
                        if v[4] is None
                        else {"reference_trade_id": v[4]}
                    }
                },
            }
        }
        for sid, v in cli.NOV06_BINDINGS.items()
    ]
    domain = {"items": items}
    assert len(cli.frozen_open_trades(domain, incident=cli.NOV06_VERSION)) == 2
    for item in items:
        state = item["binding"]["checkpoint"]["reference_state"]
        if change == "extra_open" and state["open_trade"] is None:
            state["open_trade"] = {"reference_trade_id": "outside"}
            break
        if change != "extra_open" and state["open_trade"] is not None:
            state["open_trade"] = (
                None if change == "missing_open" else {"reference_trade_id": "outside"}
            )
            break
    with pytest.raises(ValueError, match="OPEN_SCOPE_DRIFT"):
        cli.frozen_open_trades(domain, incident=cli.NOV06_VERSION)
