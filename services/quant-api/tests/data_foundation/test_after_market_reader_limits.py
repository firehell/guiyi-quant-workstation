"""Status capacity crosses every existing readback seam without widening config reads."""
from datetime import UTC, date, datetime
import json

import pytest

from app.market_data import after_market_closeout, after_market_history, closeout_binding
from app.market_data.after_market import public_after_market_status
from app.market_data.runtime_promotion import _INVALID, _load_after_market_status

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def status_bytes(*, publications=0, padding=0):
    last = {"trading_day": "2026-09-30", "status": "passed", "attempts": 1,
            "started_at": "2026-09-30T18:05:00+08:00", "finished_at": "2026-09-30T18:11:00+08:00",
            "products": ["au"], "error_code": None}
    if publications:
        last["historical_publications"] = [{
            "dataset": ["contract", "au", "AU2610", "1m"], "year": 2026, "month": 9,
            "file_name": "part." + "a" * 64 + ".parquet",
            "provenance": {"version": 1, "input_source": "rqdata", "input_sha256": "b" * 64},
        }] * publications
    value = {"schema_version": 3, "current_run": None, "last_run": last,
             "last_successful_trading_day": "2026-09-30", "last_failure": None}
    return json.dumps(value, separators=(",", ":")).encode() + b" " * padding


@pytest.mark.parametrize("publications,padding", [(8192, 0), (0, 3 * 1024 * 1024)])
def test_large_status_crosses_health_authority_closeout_promotion_and_recovery(
    tmp_path, monkeypatch, publications, padding
):
    from app.services import runtime_health
    from app.guiyi_cli import captured_recovery
    root = tmp_path / "runtime"
    run = root / ".run"
    run.mkdir(parents=True)
    path = run / "after-market-status.json"
    content = status_bytes(publications=publications, padding=padding)
    path.write_bytes(content)
    public = public_after_market_status(json.loads(content))
    assert public["last_run"]["status"] == "passed"
    assert after_market_history._bytes(path) == content
    assert closeout_binding._snapshot(path)[0] == content
    with after_market_closeout._directory(run) as directory:
        assert after_market_closeout._read(directory, path.name) == content
    assert public_after_market_status(_load_after_market_status(path)) == public
    from app.market_data.market_read_service import _load_after_market_status as market_status
    assert dict(market_status(path)) == public
    monkeypatch.setattr(captured_recovery, "PROJECT_ROOT", root)
    captured_recovery._after_market_preflight(date(2026, 10, 9))
    monkeypatch.setattr(runtime_health, "load_operational_products", lambda: ("au",))
    monkeypatch.setattr(runtime_health, "_expected_after_market_day",
                        lambda *a, **kw: (date(2026, 9, 30), False))
    health = runtime_health._collect_current_after_market_health(None, path, now=NOW,
                                                               configured_enabled=True)
    assert health.get("error_type") != "after_market_status_invalid"
    assert health["last_run"]["status"] == "passed"


def test_large_history_readback_and_provenance(tmp_path):
    value = after_market_history.make_history(status_bytes(), commit="a" * 40,
                                             products=("au",), now=NOW)
    path = tmp_path / after_market_history.NAME
    content = json.dumps(value).encode() + b" " * (3 * 1024 * 1024)
    path.write_bytes(content)
    assert after_market_history.read_history(path, products=("au",), now=NOW) == value


def test_8192_publications_round_trip_history(tmp_path):
    content = status_bytes(publications=8192)
    assert len(content) > 2 * 1024 * 1024
    value = after_market_history.make_history(content, commit="a" * 40, products=("au",), now=NOW)
    path = tmp_path / after_market_history.NAME
    assert after_market_history.publish_history(path, value) == "retained"
    assert after_market_history.read_history(path, products=("au",), now=NOW) == value
    assert len(value["status"]["last_run"]["historical_publications"]) == 8192


@pytest.mark.parametrize("name", ["project.env", "live-heartbeat.json", "com.guiyi.quant-live.plist"])
def test_status_capacity_does_not_expand_config_or_heartbeat(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(ValueError):
        closeout_binding._snapshot(path)
    with after_market_closeout._directory(tmp_path) as directory:
        with pytest.raises(ValueError):
            after_market_closeout._read(directory, name)


@pytest.mark.parametrize("name,limit", [("after-market-status.json", 16 * 1024 * 1024),
                                       ("after-market-history.json", 32 * 1024 * 1024)])
def test_oversized_evidence_fail_closed(tmp_path, name, limit):
    path = tmp_path / name
    with path.open("wb") as stream:
        stream.truncate(limit + 1)
    with pytest.raises(ValueError):
        after_market_history._bytes(path, max_bytes=limit)
    if name == "after-market-status.json":
        with pytest.raises(ValueError):
            closeout_binding._snapshot(path)
        with after_market_closeout._directory(tmp_path) as directory:
            with pytest.raises(ValueError):
                after_market_closeout._read(directory, name)
        assert _load_after_market_status(path) is _INVALID


def test_history_writer_rejects_overflow_before_creating_proof(tmp_path):
    path = tmp_path / after_market_history.NAME
    with pytest.raises(ValueError, match="HISTORY_INVALID"):
        after_market_history.publish_history(path, {"oversized": "x" * (32 * 1024 * 1024)})
    assert not path.exists()


@pytest.mark.parametrize("content", [b"{", b"[]", b"null"])
def test_corrupt_history_remains_rejected(tmp_path, content):
    path = tmp_path / after_market_history.NAME
    path.write_bytes(content)
    with pytest.raises((ValueError, TypeError)):
        after_market_history.read_history(path, products=("au",), now=NOW)


@pytest.mark.parametrize("name,limit", [("after-market-status.json", 16 * 1024 * 1024),
                                       ("after-market-history.json", 32 * 1024 * 1024)])
def test_exact_file_capacity_boundary_is_readable(tmp_path, name, limit):
    path = tmp_path / name
    content = status_bytes()
    content += b" " * (limit - len(content))
    path.write_bytes(content)
    assert after_market_history._bytes(path, max_bytes=limit) == content
    if name == "after-market-status.json":
        assert closeout_binding._snapshot(path)[0] == content
        with after_market_closeout._directory(tmp_path) as directory:
            assert after_market_closeout._read(directory, name) == content


def test_large_history_can_be_retained_into_a_second_runtime(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.market_data import operational_universe, runtime_status_authority
    source, target = tmp_path / "source", tmp_path / "target"
    for root in (source, target):
        (root / ".run").mkdir(parents=True)
    value = after_market_history.make_history(status_bytes(publications=8192), commit="a" * 40,
                                             products=("au",), now=NOW)
    after_market_history.publish_history(source / ".run" / after_market_history.NAME, value)
    authority = SimpleNamespace(path=source / ".run/after-market-status.json", mode="loaded",
                                recheck=lambda: None)
    monkeypatch.setattr(runtime_status_authority, "resolve_market_runtime_status_authority", lambda **kw: authority)
    monkeypatch.setattr(operational_universe, "load_operational_products", lambda: ("au",))
    assert after_market_history.retain_from_supervised(target, apply=False) == "ready"
    assert after_market_history.retain_from_supervised(target, apply=True) == "retained"
    assert after_market_history.retain_from_supervised(target, apply=True) == "already_retained"
    assert (target / ".run" / after_market_history.NAME).read_bytes() == (source / ".run" / after_market_history.NAME).read_bytes()


@pytest.mark.parametrize("schema", [1, 2])
def test_legacy_status_still_retains_and_reads_without_synthetic_evidence(tmp_path, schema):
    raw = json.loads(status_bytes())
    raw["schema_version"] = schema
    value = after_market_history.make_history(json.dumps(raw).encode(), commit="a" * 40,
                                             products=("au",), now=NOW)
    path = tmp_path / after_market_history.NAME
    after_market_history.publish_history(path, value)
    readback = after_market_history.read_history(path, products=("au",), now=NOW)
    assert readback["status"].get("schema_version", 1) == schema
    assert readback["source_commit"] == "a" * 40
    assert "historical_publications" not in readback["status"]["last_run"]
    assert "live_evidence" not in readback["status"]["last_run"]
