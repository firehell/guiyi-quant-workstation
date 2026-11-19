import pytest
from app import runtime_retirement as m


@pytest.mark.parametrize("omit_close_resolution", (False, True))
@pytest.mark.parametrize("calendars,original", ((False, False), (True, True)))
def test_archive_post_feed_stopped_chain_requires_unique_close_resolution(
    tmp_path, monkeypatch, omit_close_resolution, calendars, original
):
    from app import runtime_cohort as cohort, runtime_cohort_recovery as recovery
    from app.runtime_handover import _write
    from tests.test_runtime_stopped_recovery import recover_after_feed_failure

    host, failed, fresh = recover_after_feed_failure(
        tmp_path, monkeypatch, calendars=calendars, original=original
    )
    if omit_close_resolution:
        folder = host.directory / "cohort-forward-recoveries" / fresh["plan_sha256"]
        receipt = m._json(folder / "receipt.json")
        del receipt["feed_close_resolution"]
        _write(folder / "receipt.json", receipt)
        state = m._json(folder / "state.json")
        state["receipt_sha256"] = m.sha((folder / "receipt.json").read_bytes())
        _write(folder / "state.json", state)
    terminal = host.directory / "cohort-attempts" / ("f" * 64)
    terminal.mkdir(mode=0o700)
    _write(
        terminal / "plan.json",
        {"plan_sha256": terminal.name, "created_at": fresh["created_at"], "new": {}},
    )
    _write(
        terminal / "state.json",
        {
            "schema_version": 1,
            "plan_sha256": terminal.name,
            "phase": "switched",
            "effects": {
                "verified": {"continuous_identity": "matched"},
                "calendars_on": {
                    "calendar_registration_only": True,
                    "identity": "matched",
                },
            },
        },
    )
    previous = m._json((fresh if original else failed)["stopped_confirmation"]["path"])
    assert len(previous["attempts"]) == 2
    expected = set(previous["attempts"]) | {
        fresh["plan_sha256"],
        failed["plan_sha256"],
        fresh["closed_feed"]["plan_sha256"],
        failed["source"]["plan_sha256"],
        terminal.name,
    }
    monkeypatch.setattr(cohort, "validate", lambda *a, **k: None)
    monkeypatch.setattr(recovery, "_validate", lambda *a, **k: None)
    seal = {
        "directory": str(host.directory),
        "releases": [],
        "terminal_cohort": terminal.name,
        "closed_attempts": sorted(expected),
        "originals": {str(p): m.sha(p.read_bytes()) for p in tmp_path.rglob("*.json")},
    }
    if omit_close_resolution:
        with pytest.raises(ValueError):
            m._closed_history(seal, tmp_path)
    else:
        assert m._closed_history(seal, tmp_path) == expected


def test_archive_original_intake_timeout_closed_by_stopped_recovery(
    tmp_path, monkeypatch
):
    from app import runtime_cohort as cohort, runtime_cohort_recovery as recovery
    from app.runtime_stopped_recovery import reconcile_stopped
    from app.runtime_handover import _write
    from tests.test_runtime_stopped_recovery import original_failed_consumers

    host, failed_path, failed, _ = original_failed_consumers(tmp_path, monkeypatch)
    selected = reconcile_stopped(host, failed_path)["confirmation"]
    plan = recovery.freeze_forward_recovery(
        host, failed["source"]["plan_path"], stopped_confirmation=selected["path"]
    )
    intake = {
        "schema_version": 2,
        "kind": "reference_receiving_liveness_v1",
        "mode": "durable_receiving_caught_up_idle",
        "calculation_ready": False,
        "before_sha256": "a" * 64,
        "after_sha256": "b" * 64,
        "advanced_count": 0,
        "remaining_count": 0,
        "old_tail_reached": True,
    }
    host.await_consumers = lambda *args: intake
    host.resume_feed = lambda *args: {"bootstrapped": True, "label": "com.guiyi.quant-market-feed"}
    host.verify_forward = lambda *args: {
        "continuous_identity": "matched",
        "calculation_ready": False,
        "intake": intake,
        "natural_acceptance": "pending",
    }
    host.forward_calendars = lambda *args: {
        "calendar_registration_only": True,
        "identity": "matched",
    }
    path = tmp_path / "stopped-fresh.json"
    _write(path, plan)
    recovery.apply_forward_recovery(host, path)
    # A later successful version switch remains required before retirement.
    terminal = host.directory / "cohort-attempts" / ("f" * 64)
    terminal.mkdir(mode=0o700)
    _write(
        terminal / "plan.json",
        {"plan_sha256": terminal.name, "created_at": plan["created_at"], "new": {}},
    )
    _write(
        terminal / "state.json",
        {
            "schema_version": 1,
            "plan_sha256": terminal.name,
            "phase": "switched",
            "effects": {
                "verified": {"continuous_identity": "matched"},
                "calendars_on": {
                    "calendar_registration_only": True,
                    "identity": "matched",
                },
            },
        },
    )
    monkeypatch.setattr(cohort, "validate", lambda *a, **k: None)
    monkeypatch.setattr(recovery, "_validate", lambda *a, **k: None)
    expected = {
        plan["plan_sha256"],
        failed["plan_sha256"],
        failed["original_close"]["plan_sha256"],
        failed["source"]["plan_sha256"],
        terminal.name,
    }
    seal = {
        "directory": str(host.directory),
        "releases": [],
        "terminal_cohort": terminal.name,
        "closed_attempts": sorted(expected),
        "originals": {str(p): m.sha(p.read_bytes()) for p in tmp_path.rglob("*.json")},
    }
    assert m._closed_history(seal, tmp_path) == expected


@pytest.mark.parametrize(
    "damage", (None, "source", "close_receipt", "close_effect", "resolution")
)
def test_original_feed_recovery_archive_closes_only_verified_chain(
    tmp_path, monkeypatch, damage
):
    from app import runtime_cohort as cohort, runtime_cohort_recovery as recovery
    from tests.test_runtime_cohort_original_feed_recovery import original_fixture

    host, _source, source_path, source_attempt, source_bytes, _identity = (
        original_fixture(tmp_path, monkeypatch)
    )
    intake = {
        "schema_version": 2,
        "kind": "reference_receiving_liveness_v1",
        "mode": "durable_receiving_caught_up_idle",
        "calculation_ready": False,
        "before_sha256": "a" * 64,
        "after_sha256": "b" * 64,
        "advanced_count": 0,
        "remaining_count": 0,
        "old_tail_reached": True,
    }
    host.await_consumers = lambda *args: intake
    host.verify_forward = lambda *args: {
        "continuous_identity": "matched",
        "calculation_ready": False,
        "intake": intake,
    }
    host.forward_calendars = lambda *args: {
        "calendar_registration_only": True,
        "identity": "matched",
    }
    close_plan = recovery.freeze_forward_recovery(
        host, source_path, original_verified_feed_halt=True, close_feed_only=True
    )
    close_path = tmp_path / "close.json"
    from app.runtime_handover import _write

    _write(close_path, close_plan)
    recovery.apply_forward_recovery(host, close_path)
    normal = recovery.freeze_forward_recovery(
        host, source_path, original_verified_feed_halt=True, feed_close_plan=close_path
    )
    normal_path = tmp_path / "normal.json"
    _write(normal_path, normal)
    recovery.apply_forward_recovery(host, normal_path)
    close_dir = host.directory / "cohort-forward-recoveries" / close_plan["plan_sha256"]
    normal_dir = host.directory / "cohort-forward-recoveries" / normal["plan_sha256"]
    if damage == "source":
        state = m._json(source_attempt / "state.json")
        state["failed_phase"] = "feed"
        _write(source_attempt / "state.json", state)
    elif damage == "close_receipt":
        receipt = m._json(close_dir / "receipt.json")
        receipt["recovery_started"] = True
        _write(close_dir / "receipt.json", receipt)
    elif damage == "close_effect":
        state = m._json(close_dir / "state.json")
        state["effects"]["feed_stop"]["label_absent"] = False
        _write(close_dir / "state.json", state)
    elif damage == "resolution":
        receipt = m._json(normal_dir / "receipt.json")
        receipt["original_feed_halt_resolution"]["source"] = {}
        _write(normal_dir / "receipt.json", receipt)
    # Release/plan schema validation is covered by the recovery tests. This test
    # exercises immutable archive linkage without any live registry dependency.
    monkeypatch.setattr(cohort, "validate", lambda *a, **k: None)
    monkeypatch.setattr(recovery, "_validate", lambda *a, **k: None)
    terminal = host.directory / "cohort-attempts" / ("f" * 64)
    terminal.mkdir(mode=0o700)
    _write(
        terminal / "plan.json",
        {"plan_sha256": terminal.name, "created_at": normal["created_at"], "new": {}},
    )
    _write(
        terminal / "state.json",
        {
            "schema_version": 1,
            "plan_sha256": terminal.name,
            "phase": "switched",
            "effects": {
                "verified": {"continuous_identity": "matched"},
                "calendars_on": {
                    "calendar_registration_only": True,
                    "identity": "matched",
                },
            },
        },
    )
    seal = {
        "directory": str(host.directory),
        "releases": [],
        "terminal_cohort": terminal.name,
        "closed_attempts": [
            source_attempt.name,
            close_dir.name,
            normal_dir.name,
            terminal.name,
        ],
        "originals": {
            str(path): m.sha(path.read_bytes()) for path in tmp_path.rglob("*.json")
        },
    }
    if damage:
        with pytest.raises((ValueError, KeyError)):
            m._closed_history(seal, tmp_path)
    else:
        assert m._closed_history(seal, tmp_path) == {
            source_attempt.name,
            close_dir.name,
            normal_dir.name,
            terminal.name,
        }
        assert (source_attempt / "state.json").read_bytes() == source_bytes
