"""Complete closed-chain collection remains gated by the deployed reader."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app import runtime_retirement as m
from tests.test_runtime_retirement import forward_terminal_case


def ancestor_case(tmp_path):
    entries, paths = [], {}

    def add(parent, name, plan, state):
        child = tmp_path / parent / name
        child.mkdir(parents=True)
        plan = {"plan_sha256": name, **plan}
        state = {"plan_sha256": name, **state}
        m._write(child / "plan.json", m._encoded(plan))
        m._write(child / "state.json", m._encoded(state))
        entries.append((child, state))
        paths[child] = child / "plan.json"
        return child

    def registry(generation):
        return {
            "services": {
                "api": {
                    "root": f"/release/{generation}",
                    "generation": generation,
                    "tag": f"v1.0.{generation}",
                    "commit": str(generation) * 40,
                    "contracts": {"reference": "a" * 64},
                    "launchd_label": "api",
                }
            }
        }

    old, new = registry(51), registry(52)
    proof = {"continuous_identity": "matched"}
    calendar = {"calendar_registration_only": True, "identity": "matched"}
    anchor = add(
        "cohort-attempts",
        "a" * 64,
        {"new": old},
        {"phase": "switched", "effects": {"verified": proof, "calendars_on": calendar}},
    )
    source = add(
        "cohort-attempts",
        "b" * 64,
        {"old": old, "new": new},
        {"phase": "outcome_unknown"},
    )
    identity = {"plan_sha256": source.name}
    recovered = add(
        "cohort-forward-recoveries",
        "c" * 64,
        {"new": new, "source": identity},
        {
            "phase": "recovered",
            "source": identity,
            "effects": {"verified": proof, "calendars": calendar},
        },
    )
    receipt = {
        "plan_sha256": recovered.name,
        "source": identity,
        "original_attempt_preserved": True,
        "readback": proof,
    }
    m._write(recovered / "receipt.json", m._encoded(receipt))
    entries[-1][1]["receipt_sha256"] = m.sha((recovered / "receipt.json").read_bytes())
    return new, entries, paths, anchor, source, recovered


def test_recovered_predecessor_reaches_exact_ordinary_anchor(tmp_path):
    target, entries, paths, anchor, _source, _recovered = ancestor_case(tmp_path)
    assert m._ordinary_ancestor(target, entries, paths) == anchor.name


@pytest.mark.parametrize(
    "damage",
    [
        "ambiguous",
        "cycle",
        "jump",
        "label",
        "contracts",
        "missing_receipt",
        "changed_receipt",
        "unmatched",
        "no_anchor",
    ],
)
def test_ancestor_requires_unique_complete_identity_chain(tmp_path, damage):
    target, entries, paths, anchor, source, recovered = ancestor_case(tmp_path)
    if damage == "ambiguous":
        extra = recovered.with_name("d" * 64)
        extra.mkdir()
        paths[extra] = extra / "plan.json"
        m._write(paths[extra], m._read(paths[recovered]))
        entries.append((extra, deepcopy(entries[-1][1])))
    elif damage in ("cycle", "jump"):
        value = m._json(paths[source])
        value["old"] = target if damage == "cycle" else deepcopy(value["old"])
        if damage == "jump":
            value["old"]["services"]["api"]["generation"] = 49
        paths[source].write_bytes(m._encoded(value))
    elif damage in ("label", "contracts"):
        target = deepcopy(target)
        key = "launchd_label" if damage == "label" else "contracts"
        target["services"]["api"][key] = "different"
    elif damage == "missing_receipt":
        (recovered / "receipt.json").unlink()
    elif damage == "changed_receipt":
        (recovered / "receipt.json").write_text("{}")
    elif damage == "unmatched":
        entries[-1][1]["effects"]["verified"]["continuous_identity"] = "unmatched"
    else:
        entries.pop(0)
    with pytest.raises((ValueError, OSError)):
        m._ordinary_ancestor(target, entries, paths)


def complete_case(tmp_path, monkeypatch):
    backend, root, _old, _anchor, _source, _close, _normal = forward_terminal_case(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        m, "_closed_history", lambda plan, _: set(plan["closed_attempts"])
    )
    identity = {"root": str(tmp_path / "current"), "tag": "v1.2.4", "commit": "e" * 40}
    monkeypatch.setattr(backend, "active_reader_identity", lambda: identity)
    calls = []
    monkeypatch.setattr(
        backend,
        "verify_active_reader",
        lambda plan, folder=None: calls.append((plan["collection_policy"], folder)),
    )
    return backend, root, calls


def test_complete_collection_and_fresh_seal_keep_explicit_policy(tmp_path, monkeypatch):
    backend, root, calls = complete_case(tmp_path, monkeypatch)
    plan = m.build_closeout_plan(
        (root,), backend=backend, include_latest_recoveries=True
    )
    assert len(plan["closed_attempts"]) == 5
    assert plan["collection_policy"] == m.COMPLETE_HISTORY
    result = m.seal_closed(plan, backend=backend)
    assert calls[-1][1] is not None
    assert all(policy == m.COMPLETE_HISTORY for policy, _ in calls)
    assert m.seal_closed(plan, backend=backend) == result


def test_complete_seal_rejects_marker_drift_before_publication(tmp_path, monkeypatch):
    backend, root, _calls = complete_case(tmp_path, monkeypatch)
    plan = m.build_closeout_plan(
        (root,), backend=backend, include_latest_recoveries=True
    )
    (root / ".run").mkdir(exist_ok=True)
    (root / ".run/market-runtime-enabled").write_text("changed")
    with pytest.raises(ValueError):
        m.seal_closed(plan, backend=backend)
    assert not (
        backend.directory / "release-retirements" / plan["plan_sha256"]
    ).exists()


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "hash",
        "members",
        "failure",
        "identity",
        "late_identity",
        "timeout",
        "non_json",
        "extra_field",
    ],
)
def test_active_reader_probe_pins_interpreter_source_and_result(
    tmp_path, monkeypatch, damage
):
    backend = m.RetirementBackend(tmp_path, tmp_path)
    identity = {"root": str(tmp_path), "tag": "v1.2.4", "commit": "a" * 40}
    changed = {**identity, "commit": "b" * 40}
    identities = iter(
        [identity, changed] if damage == "late_identity" else [identity, identity]
    )
    monkeypatch.setattr(backend, "active_reader_identity", lambda: next(identities))
    plan = {
        "reader_identity": changed if damage == "identity" else identity,
        "plan_sha256": "c" * 64,
        "closed_attempts": ["d" * 64],
    }
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert args[0] == str(tmp_path / "services/quant-api/.venv/bin/python")
        assert args[1:3] == ["-I", "-c"]
        assert kwargs["cwd"] == tmp_path
        assert json.loads(kwargs["input"])["folder"] is None
        if damage == "timeout":
            raise m.subprocess.TimeoutExpired(args, 120)
        proof = {
            "plan_sha256": plan["plan_sha256"],
            "closed_attempts": plan["closed_attempts"],
        }
        if damage == "hash":
            proof["plan_sha256"] = "f" * 64
        if damage == "members":
            proof["closed_attempts"] = []
        if damage == "extra_field":
            proof["extra"] = True
        return SimpleNamespace(
            returncode=1 if damage == "failure" else 0,
            stdout="not-json" if damage == "non_json" else json.dumps(proof),
        )

    monkeypatch.setattr(m.subprocess, "run", run)
    if damage:
        with pytest.raises(ValueError):
            backend.verify_active_reader(plan)
    else:
        backend.verify_active_reader(plan)
        assert len(calls) == 1


@pytest.mark.parametrize("parent", ["cohort-attempts"])
def test_complete_mode_rejects_additional_unresolved_attempt(
    tmp_path, monkeypatch, parent
):
    backend, root, _calls = complete_case(tmp_path, monkeypatch)
    child = backend.directory / parent / ("9" * 64)
    child.mkdir(parents=True, mode=0o700, exist_ok=True)
    m._write(
        child / "plan.json",
        m._encoded(
            {
                "plan_sha256": child.name,
                "created_at": "2026-10-27T00:00:00+00:00",
                "new": {},
            }
        ),
    )
    m._write(
        child / "state.json",
        m._encoded(
            {
                "schema_version": 1,
                "plan_sha256": child.name,
                "phase": "outcome_unknown",
                "effects": {},
            }
        ),
    )
    if parent == "cohort-attempts":
        with pytest.raises(ValueError):
            m.build_closeout_plan(
                (root,), backend=backend, include_latest_recoveries=True
            )
