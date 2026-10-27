"""Retired identities are auditable, but never usable as active bindings."""

from dataclasses import asdict

import pytest

from app import runtime_bindings as bindings
from app import runtime_cohort as cohort
from tests.test_runtime_cohort import Host, plan


def test_missing_root_is_rejected_by_active_binding_even_when_history_is_sealed(
    tmp_path, monkeypatch
):
    host = Host(tmp_path)
    value = asdict(host.old.services["live"])
    __import__("pathlib").Path(value["root"]).rmdir()
    monkeypatch.setattr(
        bindings, "_verify_archived_binding", lambda *args: None, raising=False
    )
    with pytest.raises(ValueError):
        bindings.ServiceBinding(**value)
    history = bindings.historical_binding(value)
    assert asdict(history) == value
    with pytest.raises(ValueError):
        cohort.registry(asdict(host.old))


def test_missing_history_root_requires_an_explicit_valid_seal(tmp_path, monkeypatch):
    host = Host(tmp_path)
    value = asdict(host.old.services["live"])
    __import__("pathlib").Path(value["root"]).rmdir()

    def unavailable(*args):
        raise ValueError("unsealed")

    monkeypatch.setattr(
        bindings, "_verify_archived_binding", unavailable, raising=False
    )
    with pytest.raises(ValueError):
        bindings.historical_binding(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("commit", "bad"),
        ("tag", "old"),
        ("generation", 0),
        ("enabled", 1),
        ("contracts", {}),
    ],
)
def test_seal_does_not_bypass_static_binding_validation(
    tmp_path, monkeypatch, field, value
):
    host = Host(tmp_path)
    row = asdict(host.old.services["live"])
    __import__("pathlib").Path(row["root"]).rmdir()
    row[field] = value
    called = []
    monkeypatch.setattr(
        bindings,
        "_verify_archived_binding",
        lambda *args: called.append(True),
        raising=False,
    )
    with pytest.raises(ValueError):
        bindings.historical_binding(row)
    assert not called


def test_historical_cohort_parses_retired_old_roots_without_weakening_live_validation(
    tmp_path, monkeypatch
):
    host = Host(tmp_path)
    frozen = plan(host)
    old = __import__("pathlib").Path(next(iter(host.old.services.values())).root)
    old.rmdir()
    monkeypatch.setattr(
        bindings, "_verify_archived_binding", lambda *args: None, raising=False
    )
    with pytest.raises(ValueError):
        cohort.validate(frozen, host.now())
    previous, current = cohort.validate(frozen, host.now(), historical=True)
    assert asdict(previous) == frozen["old"]
    assert asdict(current) == frozen["new"]


def test_historical_capability_is_not_serialized_or_accepted_by_active_writer(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    host = Host(tmp_path)
    value = asdict(host.old.services["live"])
    __import__("pathlib").Path(value["root"]).rmdir()
    monkeypatch.setattr(bindings, "_verify_archived_binding", lambda *args: None)
    audited = bindings.historical_binding(value)
    assert "_history" not in asdict(audited)
    registry = bindings.BindingRegistry(1, {"live": audited})
    with pytest.raises(ValueError):
        bindings.write_bindings(registry, home=tmp_path, expected_sha256=None)
    with pytest.raises(ValueError):
        replace(audited)
    with pytest.raises(ValueError):
        bindings.ServiceBinding(**value, _history=True)


def test_external_registry_cannot_supply_history_capability_even_for_existing_root(
    tmp_path,
):
    import json

    host = Host(tmp_path)
    value = asdict(host.old)
    value["services"]["live"]["_history"] = None
    path = bindings.registry_path(tmp_path)
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    with pytest.raises(ValueError):
        bindings.read_bindings(home=tmp_path)


def test_normal_cohort_retains_the_exact_consumed_plan_before_any_effect(tmp_path):
    import json

    host = Host(tmp_path)
    frozen = plan(host)
    original_prewarm = host.prewarm

    def checked(plan_value):
        path = host.directory / "cohort-attempts" / frozen["plan_sha256"] / "plan.json"
        assert json.loads(path.read_text()) == frozen
        return original_prewarm(plan_value)

    host.prewarm = checked
    cohort.apply_cohort(host, frozen)
    path = host.directory / "cohort-attempts" / frozen["plan_sha256"] / "plan.json"
    assert json.loads(path.read_text()) == frozen


def test_explicit_seal_collector_proof_cannot_be_used_as_active_registry(tmp_path):
    host = Host(tmp_path)
    value = asdict(host.old)
    __import__("pathlib").Path(value["services"]["live"]["root"]).rmdir()
    known = {(v["root"], v["tag"], v["commit"]) for v in value["services"].values()}

    def verified(root, tag, commit, directory):
        assert (root, tag, commit) in known

    audited = cohort.registry(value, historical=True, history_verifier=verified)
    with pytest.raises(ValueError):
        bindings.write_bindings(audited, home=tmp_path, expected_sha256=None)
    with pytest.raises(ValueError):
        cohort.registry(value, history_verifier=verified)
