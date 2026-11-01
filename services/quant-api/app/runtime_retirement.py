"""Seal closed recovery dependencies without rewriting their original outcomes.

A seal archives only exact non-Git runtime markers. Plans/states/receipts stay in
place and are hash checked on every historical read. Active deployment identity
continues to use the ordinary strict worktree validator.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from app.runtime_bindings import _git


class RetirementError(ValueError):
    pass


def require(value):
    if not value:
        raise RetirementError("RETIREMENT_EVIDENCE_UNPROVEN")


def sha(raw):
    return sha256(raw).hexdigest()


def _encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest(value):
    return sha(_encoded(value))


def _read(path):
    path = Path(path)
    require(path.is_absolute() and path == path.resolve())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_size <= 64 * 1024 * 1024
        )
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(64 * 1024 * 1024 + 1)
        require(len(raw) <= 64 * 1024 * 1024)
        return raw
    finally:
        os.close(fd)


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result

    value = json.loads(_read(path), object_pairs_hook=unique)
    require(isinstance(value, dict))
    return value


def _directory(path):
    info = path.lstat()
    require(
        path == path.resolve()
        and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )


def _sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())


def _common(repo_root):
    return str(
        Path(
            _git(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve(strict=True)
    )


def _verify_git(repo_root, identity):
    tag, commit = identity["tag"], identity["commit"]
    require(
        re.fullmatch(r"v\d+\.\d+\.\d+", tag) and re.fullmatch(r"[0-9a-f]{40}", commit)
    )
    require(
        _git(repo_root, "cat-file", "-t", f"refs/tags/{tag}") == "tag"
        and _git(repo_root, "rev-parse", f"refs/tags/{tag}^{{commit}}") == commit
    )


def build_closeout_plan(roots, backend=None):
    backend = backend or RetirementBackend()
    roots = tuple(Path(root) for root in roots)
    require(roots and len(set(roots)) == len(roots))
    for root in roots:
        require(root.is_absolute() and root == root.resolve(strict=True))
    facts = backend.collect(roots)
    plan = {
        "schema_version": 1,
        "kind": "closed_release_retirement_v1",
        **facts,
        "roots": [str(root) for root in roots],
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def _valid_plan(plan):
    require(
        isinstance(plan, dict)
        and plan.get("schema_version") == 1
        and plan.get("kind") == "closed_release_retirement_v1"
        and plan.get("plan_sha256")
        == _digest({k: v for k, v in plan.items() if k != "plan_sha256"})
    )


def seal_closed(plan, backend=None):
    """One atomic local evidence commit; no launch, DB or original-state writes."""
    from app.runtime_handover import deployment_lock

    _valid_plan(plan)
    backend = backend or RetirementBackend()
    with deployment_lock(runtime_dir=backend.directory):
        return _seal_closed(plan, backend)


def _seal_closed(plan, backend):
    require(
        str(backend.directory) == plan["directory"]
        and str(backend.repo_root) == plan["repo_root"]
    )
    directory = Path(plan["directory"])
    parent = directory / "release-retirements"
    target = parent / plan["plan_sha256"]
    if target.exists():
        _load_index(target, Path(plan["repo_root"]))
        require(_json(target / "index.json")["plan"] == plan)
        return {
            "status": "sealed",
            "plan_sha256": plan["plan_sha256"],
            "path": str(target / "index.json"),
        }
    require(
        build_closeout_plan(
            tuple(Path(root) for root in plan["roots"]), backend=backend
        )
        == plan
    )
    _directory(directory)
    parent.mkdir(mode=0o700, exist_ok=True)
    _directory(parent)
    staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=parent))
    # Incomplete staging directories never authorize any historical read.
    for path, expected in plan["markers"].items():
        if expected is None:
            require(not os.path.lexists(path))
            continue
        raw = _read(path)
        require(sha(raw) == expected)
        blob = staging / expected
        if not blob.exists():
            _write(blob, raw)
    require(
        build_closeout_plan(
            tuple(Path(root) for root in plan["roots"]), backend=backend
        )
        == plan
    )
    index = {"schema_version": 1, "plan": plan}
    index["index_sha256"] = _digest(index)
    _write(staging / "index.json", _encoded(index))
    _sync(staging)
    os.rename(staging, target)
    _sync(parent)
    _load_index(target, Path(plan["repo_root"]))
    return {
        "status": "sealed",
        "plan_sha256": plan["plan_sha256"],
        "path": str(target / "index.json"),
    }


def _closed_history(seal, repo_root):
    """Derive closure only from immutable typed evidence; never trust index membership.

    This reader has no dependency on live bindings/global state or other seals.
    """
    from app import runtime_cohort as cohort, runtime_cohort_recovery as recovery
    from app.runtime_stopped_recovery import failure_feed_state, valid_parked_feed_audit
    from app.reference_trading.recovery_campaign import digest

    directory = Path(seal["directory"])
    originals = seal["originals"]
    identities = {row["root"]: row for row in seal["releases"]}

    verified_identities = set()

    def verifier(root, tag, commit, directory):
        require(Path(directory) == Path(seal["directory"]))
        identity = {"root": str(root), "tag": tag, "commit": commit}
        require(identities.get(str(root)) == identity)
        key = (str(root), tag, commit)
        if key in verified_identities:
            return
        _verify_git(repo_root, identity)
        if os.path.lexists(root):
            _verify_present_release(repo_root, identity)
        verified_identities.add(key)

    def read(path):
        path = Path(path)
        require(str(path) in originals and sha(_read(path)) == originals[str(path)])
        return _json(path)

    documents = {path: read(path) for path in originals}
    states, plans, plan_paths = {}, {}, {}
    for path, state in documents.items():
        path = Path(path)
        if path.name != "state.json" or path.parent.parent not in {
            directory / "cohort-attempts",
            directory / "cohort-forward-recoveries",
        }:
            continue
        name = path.parent.name
        require(
            name not in states
            and state.get("plan_sha256") == name
            and state.get("schema_version") == 1
        )
        private = path.parent / "plan.json"
        candidates = [
            p
            for p, value in documents.items()
            if value.get("plan_sha256") == name
            and "created_at" in value
            and "new" in value
        ]
        require(candidates)
        chosen = str(private) if str(private) in candidates else sorted(candidates)[0]
        require(all(documents[p] == documents[chosen] for p in candidates))
        plan = documents[chosen]
        validate = (
            cohort.validate
            if path.parent.parent.name == "cohort-attempts"
            else recovery._validate
        )
        validate(
            plan,
            datetime.fromisoformat(plan["created_at"]),
            historical=True,
            history_directory=directory,
            history_verifier=verifier,
        )
        states[name], plans[name], plan_paths[name] = (path, state), plan, chosen

    def source(identity):
        name = identity["plan_sha256"]
        require(
            name in states
            and states[name][0].parent.parent == directory / "cohort-attempts"
        )
        require(
            read(identity["plan_path"]) == plans[name]
            and originals[identity["plan_path"]] == identity["plan_bytes_sha256"]
            and originals[str(states[name][0])]
            == identity["attempt_bytes_sha256"]
            == identity["global_bytes_sha256"]
        )
        if identity.get("kind") == recovery.ORIGINAL_FEED_SOURCE:
            require(
                originals[str(states[name][0].parent / "plan.json")]
                == identity["private_plan_bytes_sha256"]
                and digest(states[name][1]["effects"]) == identity["effects_sha256"]
                and recovery.valid_original_verified_feed_state(
                    plans[name], states[name][1]
                )
            )
            return name
        require(
            states[name][1].get("phase") == "outcome_unknown"
            and {"drain", "install", "consumers"}
            <= set(states[name][1].get("effects", {}))
            and not {"feed", "verified", "calendars_on"}
            & set(states[name][1]["effects"])
        )
        return name

    def descriptor(value, identity):
        if identity.get("kind") == recovery.ORIGINAL_FEED_SOURCE:
            require(
                set(value)
                == {
                    "plan_path",
                    "plan_sha256",
                    "plan_bytes_sha256",
                    "private_plan_bytes_sha256",
                    "state_bytes_sha256",
                    "receipt_bytes_sha256",
                }
            )
        name = value["plan_sha256"]
        require(
            name in states
            and states[name][0].parent.parent == directory / "cohort-forward-recoveries"
        )
        path, state = states[name]
        require(
            plans[name].get("source") == state.get("source") == identity
            and read(value["plan_path"]) == plans[name]
            and originals[value["plan_path"]] == value["plan_bytes_sha256"]
            and originals[str(path.parent / "plan.json")]
            == value["private_plan_bytes_sha256"]
            and originals[str(path)] == value["state_bytes_sha256"]
        )
        if "ancestor" in value:
            require(plans[name].get("predecessor") == value["ancestor"])
        if "effects_sha256" in value:
            require(digest(state["effects"]) == value["effects_sha256"])
        if "live_stop_sha256" in value:
            require(digest(state["effects"]["live_stop"]) == value["live_stop_sha256"])
        if "confirmation_bytes_sha256" in value:
            require(
                originals[str(path.parent / "feed-close-confirmation.json")]
                == value["confirmation_bytes_sha256"]
            )
        if "receipt_bytes_sha256" in value:
            require(
                originals[str(path.parent / "receipt.json")]
                == value["receipt_bytes_sha256"]
            )
        return name

    def original_close(name, identity, new):
        close_path, close_state = states[name]
        close_plan = plans[name]
        close_receipt = read(close_path.parent / "receipt.json")
        require(
            close_plan.get("mode") == recovery.ORIGINAL_FEED_MODE
            and close_plan.get("source") == close_state.get("source") == identity
            and close_plan.get("stop_after") == "feed_close"
            and close_plan["new"] == new
            and close_state.get("phase") == "feed_closed"
            and close_state.get("kind") == recovery.KIND
            and close_state.get("receipt_sha256")
            == originals[str(close_path.parent / "receipt.json")]
            and close_receipt.get("schema_version") == 1
            and close_receipt.get("kind") == "feed_close_readback_v1"
            and close_receipt.get("plan_sha256") == name
            and close_receipt.get("source") == identity
            and close_receipt.get("recovery_started") is False
            and close_receipt.get("original_attempt_preserved") is True
            and set(close_state.get("effects", {})) == {"feed_stop"}
            and close_state["effects"]["feed_stop"] == close_receipt.get("feed_close")
            and recovery._valid_feed_close(
                close_receipt.get("feed_close"), close_plan["audit"]["feed_close"]
            )
        )

    def failed(name, identity):
        path, state = states[name]
        plan = plans[name]
        require(
            plan.get("source") == state.get("source") == identity
            and state.get("kind") == recovery.KIND
        )
        effects = state.get("effects", {})
        mode = plan.get("mode")
        generation = plan["new"]["services"]["live"]["generation"]
        if mode == "reconciled_stopped" and plan.get("stop_after") == "feed_close":
            stopped_close(name, identity, plan["new"], plan["stopped_confirmation"])
            return
        if (
            mode == recovery.ORIGINAL_FEED_MODE
            and plan.get("stop_after") == "feed_close"
        ):
            original_close(name, identity, plan["new"])
            return
        if mode == "confirmed_feed_halt" and plan.get("stop_after") == "feed_close":
            intent = plan["audit"]["feed_close"]
            if state.get("phase") == "outcome_unknown":
                effect = effects.get("feed_stop", {})
                require(
                    state.get("failed_stage") == "feed_stop_intent"
                    and state.get("error_type") == "RuntimeIdentityError"
                    and state.get("error_code") == "SERVICE_IDENTITY_INVALID"
                    and set(effects) == {"feed_stop"}
                    and effect.get("phase") in {"bootout_requested", "bootout_waiting"}
                    and effect.get("intent") == intent
                    and str(path.parent / "receipt.json") not in originals
                )
                confirmation = read(path.parent / "feed-close-confirmation.json")
                require(
                    confirmation.get("kind") == "feed_close_confirmation_v1"
                    and confirmation.get("recovery_started") is False
                    and descriptor(confirmation["source_close_attempt"], identity)
                    == name
                    and recovery._valid_feed_close(
                        confirmation.get("feed_close"), intent
                    )
                    and confirmation["feed_close"]["observed_pids"]
                    == effect.get("observed_pids")
                )
            else:
                receipt = read(path.parent / "receipt.json")
                require(
                    state.get("phase") == "feed_closed"
                    and state.get("receipt_sha256")
                    == originals[str(path.parent / "receipt.json")]
                    and receipt.get("kind") == "feed_close_readback_v1"
                    and receipt.get("source") == identity
                    and receipt.get("plan_sha256") == name
                    and receipt.get("recovery_started") is False
                    and recovery._valid_feed_close(receipt.get("feed_close"), intent)
                )
            return
        if mode in {
            "reconciled_stopped",
            recovery.ORIGINAL_FEED_MODE,
            "confirmed_feed_halt",
        }:
            require(str(path.parent / "receipt.json") not in originals)
            failure_feed_state(plan, state)
            if mode == recovery.ORIGINAL_FEED_MODE:
                require(
                    state.get("error_type") == "CohortError"
                    and "stop_after" not in plan
                )
            return
        require(
            state.get("phase") == "outcome_unknown"
            and str(path.parent / "receipt.json") not in originals
        )
        if mode is None:
            effect = effects.get("live_stop", {})
            intent = plan["audit"].get("live_restart_intent")
            require(
                set(effects) == {"live_stop"}
                and effect.get("phase") in {"bootout_requested", "bootout_waiting"}
                and effect.get("intent") == intent
                and recovery.compatible_live_restart_intent(intent, intent)
                and intent["binding_sha256"] == digest(plan["new"]["services"]["live"])
                and isinstance(effect.get("observed_pids"), list)
                and 2 <= len(effect["observed_pids"]) <= 64
                and effect["observed_pids"] == sorted(set(effect["observed_pids"]))
                and set(intent["observed_pids"]) <= set(effect["observed_pids"])
            )
        elif mode == "confirmed_intake_halt":
            require(
                state.get("failed_stage") == "verified"
                and set(effects) == {"consumers", "intake", "feed"}
                and effects["consumers"] == {"resumed_generation": generation}
                and recovery._valid_intake_result(effects["intake"])
                and effects["feed"]
                == {"bootstrapped": True, "label": "com.guiyi.quant-market-feed"}
            )
        else:
            require(
                mode
                in {
                    "confirmed_live_stop",
                    "confirmed_feed_halt",
                    "reconciled_stopped",
                    recovery.ORIGINAL_FEED_MODE,
                }
                and state.get("failed_stage") == "intake"
                and effects == {"consumers": {"resumed_generation": generation}}
            )
            if mode != "confirmed_live_stop":
                require(state.get("error_code") == "COHORT_FORWARD_READY_TIMEOUT")
            if mode == recovery.ORIGINAL_FEED_MODE:
                require(
                    state.get("error_type") == "CohortError"
                    and "stop_after" not in plan
                )

    def ancestry(value, identity):
        result = set()
        while value:
            name = descriptor(value, identity)
            require(name not in result)
            failed(name, identity)
            result.add(name)
            value = value.get("ancestor")
        return result

    visiting = set()

    def stopped_close(name, identity, new, selected):
        path, state = states[name]
        plan = plans[name]
        receipt = read(path.parent / "receipt.json")
        require(
            plan.get("mode") == "reconciled_stopped"
            and plan.get("stop_after") == "feed_close"
            and plan.get("new") == new
            and plan.get("source") == state.get("source") == identity
            and plan.get("stopped_confirmation") == selected
            and state.get("kind") == recovery.KIND
            and state.get("phase") == "feed_closed"
            and state.get("receipt_sha256")
            == originals[str(path.parent / "receipt.json")]
            and receipt.get("schema_version") == 1
            and receipt.get("kind") == "feed_close_readback_v1"
            and receipt.get("plan_sha256") == name
            and receipt.get("source") == identity
            and receipt.get("original_attempt_preserved") is True
            and receipt.get("recovery_started") is False
            and set(state.get("effects", {})) == {"feed_stop"}
            and state["effects"]["feed_stop"] == receipt.get("feed_close")
            and recovery._valid_feed_close(
                receipt.get("feed_close"), plan["audit"]["feed_close"]
            )
        )
        confirmation(selected, identity)
        prior = read(selected["path"])
        require(
            prior["audit"].get("feed_state") == "parked"
            and valid_parked_feed_audit(prior["audit"], new)
            and prior["audit"]["feed_close"] == plan["audit"]["feed_close"]
        )

    def confirmation(selected, identity):
        path = selected["path"]
        require(path not in visiting and originals.get(path) == selected["sha256"])
        visiting.add(path)
        value = read(path)
        require(
            value.get("schema_version") == 1
            and value.get("kind") == "consumer_stopped_confirmation_v1"
            and value.get("source") == identity
            and Path(path).parent.name == value.get("failed_plan_sha256")
        )
        for file, fingerprint in value["files"].items():
            require(originals.get(file) == fingerprint)
            read(file)
        name = value["failed_plan_sha256"]
        require(name in plans and read(value["failed_plan_path"]) == plans[name])
        failed(name, identity)
        plan = plans[name]
        require(
            value["audit"].get("feed_state", "absent")
            == failure_feed_state(plan, states[name][1])
        )
        if value["audit"].get("feed_state") == "parked":
            require(valid_parked_feed_audit(value["audit"], plan["new"]))
        if plan.get("mode") == recovery.ORIGINAL_FEED_MODE:
            require("stop_after" not in plan)
            member = descriptor(plan["original_close"], identity)
            original_close(member, identity, plan["new"])
            expected = {member, name}
        elif plan.get("mode") == "reconciled_stopped":
            expected = confirmation(plan["stopped_confirmation"], identity) | {name}
            if "closed_feed" in plan:
                member = descriptor(plan["closed_feed"], identity)
                stopped_close(
                    member, identity, plan["new"], plan["stopped_confirmation"]
                )
                expected.add(member)
        else:
            require(
                plan.get("mode") == "confirmed_feed_halt" and "stop_after" not in plan
            )
            expected = ancestry(plan["predecessor"], identity) | {name}
            close = descriptor(plan["audit"]["feed_close"]["attempt"], identity)
            failed(close, identity)
            require(plans[close]["predecessor"] == plan["predecessor"])
            expected.add(close)
        require(
            isinstance(value["attempts"], list)
            and len(value["attempts"]) == len(set(value["attempts"]))
        )
        require(set(value["attempts"]) == expected)
        for member in expected:
            for leaf in ("plan.json", "state.json"):
                require(str(states[member][0].parent / leaf) in value["files"])
        visiting.remove(path)
        return expected

    closed = set()
    for name, (path, state) in states.items():
        if (
            path.parent.parent.name != "cohort-forward-recoveries"
            or state.get("phase") != "recovered"
        ):
            continue
        plan = plans[name]
        receipt = read(path.parent / "receipt.json")
        require(
            state.get("receipt_sha256") == originals[str(path.parent / "receipt.json")]
            and receipt.get("schema_version") == 1
            and receipt.get("kind") == "postcas_forward_recovery_readback"
            and receipt.get("plan_sha256") == name
            and receipt.get("source") == state.get("source") == plan.get("source")
            and receipt.get("original_attempt_preserved") is True
            and {"consumers", "intake", "feed", "verified", "calendars"}
            <= set(state.get("effects", {}))
            and receipt.get("intake") == state["effects"]["intake"]
            and receipt.get("readback") == state["effects"]["verified"]
            and recovery._valid_intake_result(receipt.get("intake"))
            and receipt.get("readback", {}).get("continuous_identity") == "matched"
            and receipt.get("readback", {}).get("calculation_ready") is False
            and recovery._valid_intake_result(receipt.get("readback", {}).get("intake"))
            and state["effects"]["calendars"]
            == {"calendar_registration_only": True, "identity": "matched"}
        )
        identity = plan["source"]
        source_name = source(identity)
        require(plan["new"] == plans[source_name]["new"])
        closed.update((name, source_name))
        if plan.get("mode") == recovery.ORIGINAL_FEED_MODE:
            resolution = receipt["original_feed_halt_resolution"]
            require(
                "stop_after" not in plan
                and set(resolution) == {"kind", "source", "feed_close", "confirmation"}
                and resolution["kind"]
                == "original_cohort_verified_feed_halt_resolution_v1"
                and resolution["source"] == identity
                and resolution["feed_close"] == plan["original_close"]
                and resolution["confirmation"]
                == plan["audit"]["original_verified_feed_halt"]
                and recovery.valid_original_verified_feed_halt(
                    resolution["confirmation"], identity, plan["audit"]
                )
            )
            member = descriptor(plan["original_close"], identity)
            original_close(member, identity, plan["new"])
            closed.add(member)
        elif plan.get("mode") == "reconciled_stopped":
            require(receipt.get("stopped_resolution") == plan["stopped_confirmation"])
            closed.update(confirmation(plan["stopped_confirmation"], identity))
            require(receipt.get("feed_close_resolution") == plan.get("closed_feed"))
            if "closed_feed" in plan:
                member = descriptor(plan["closed_feed"], identity)
                stopped_close(
                    member, identity, plan["new"], plan["stopped_confirmation"]
                )
                closed.add(member)
        elif "predecessor" in plan:
            resolution = receipt["predecessor_resolution"]
            require(
                resolution.get("successor_plan_sha256") == name
                and resolution.get("predecessor") == plan["predecessor"]
                and resolution.get("confirmation") == plan["audit"][plan["mode"]]
            )
            closed.update(ancestry(plan["predecessor"], identity))
            if plan["mode"] == "confirmed_feed_halt":
                member = descriptor(plan["audit"]["feed_close"]["attempt"], identity)
                failed(member, identity)
                closed.add(member)
    for name, (path, state) in states.items():
        if path.parent.parent.name != "cohort-attempts":
            continue
        effects = state.get("effects", {})
        phase = state.get("phase")
        if phase == "switched":
            require(
                {"verified", "calendars_on"} <= set(effects)
                and effects["verified"].get("continuous_identity") == "matched"
                and effects["calendars_on"]
                == {"calendar_registration_only": True, "identity": "matched"}
            )
            closed.add(name)
        elif phase == "cancelled":
            require(
                not {"consumers", "feed", "verified", "calendars_on"} & set(effects)
            )
            closed.add(name)
        elif phase == "restore_unknown":
            receipt = read(path.parent / "recovery-readback.json")
            require(
                receipt.get("schema_version") == 1
                and receipt.get("kind") == "precommit_restore_readback"
                and receipt.get("plan_sha256") == name
                and receipt.get("source_attempt_sha256")
                == receipt.get("source_global_sha256")
                == originals[str(path)]
                and receipt.get("source_plan_sha256") == originals[plan_paths[name]]
                and re.fullmatch(
                    r"[0-9a-f]{64}", receipt.get("proof", {}).get("identity_sha256", "")
                )
                and set(effects)
                <= {
                    "prewarm",
                    "calendars_off",
                    "drain",
                    "old_exited",
                    "preserve",
                    "install",
                    "bootout_requests",
                }
            )
            closed.add(name)
        else:
            require(phase == "outcome_unknown" and name in closed)
    terminal = seal["terminal_cohort"]
    require(
        terminal in states
        and states[terminal][0].parent.parent.name == "cohort-attempts"
        and states[terminal][1].get("phase") == "switched"
        and states[terminal][1]
        .get("effects", {})
        .get("verified", {})
        .get("continuous_identity")
        == "matched"
        and states[terminal][1]
        .get("effects", {})
        .get("calendars_on", {})
        .get("identity")
        == "matched"
    )
    require(set(states) == closed == set(seal["closed_attempts"]))
    return closed


def _load_index(folder, repo_root):
    _directory(folder)
    index = _json(folder / "index.json")
    require(
        index.get("index_sha256")
        == _digest({k: v for k, v in index.items() if k != "index_sha256"})
    )
    plan = index["plan"]
    _valid_plan(plan)
    require(
        folder.name == plan["plan_sha256"]
        and _common(repo_root) == plan["repository_common_dir"]
        and folder.parent.parent == Path(plan["directory"])
    )
    expected_files = {"index.json"} | {
        value for value in plan["markers"].values() if value is not None
    }
    require({path.name for path in folder.iterdir()} == expected_files)
    for name in expected_files:
        info = (folder / name).lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1
        )
    for row in plan["releases"]:
        _verify_git(repo_root, row)
        if os.path.lexists(row["root"]):
            _verify_present_release(repo_root, row)
    attempt_parents = {
        Path(path).parent
        for path in plan["originals"]
        if Path(path).name in LEAVES
        and Path(path).parent.parent.name
        in {"cohort-attempts", "cohort-forward-recoveries"}
    }
    for parent in attempt_parents:
        expected = {
            Path(path).name for path in plan["originals"] if Path(path).parent == parent
        }
        actual = {path.name for path in parent.iterdir() if path.name in LEAVES}
        require(actual == expected)
    for path, expected in plan["originals"].items():
        require(sha(_read(path)) == expected)
    for path, expected in plan["markers"].items():
        require(
            any(
                Path(path).parent == Path(row["root"]) / ".run"
                for row in plan["releases"]
            )
        )
        require(Path(path).name in MARKERS)
        if expected is not None:
            require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None)
            require(sha(_read(folder / expected)) == expected)
    _closed_history(plan, repo_root)
    return plan


def _seals(directory, repo_root):
    parent = directory / "release-retirements"
    if not os.path.lexists(parent):
        return []
    _directory(parent)
    children = list(parent.iterdir())
    require(len(children) <= 1024)
    result = []
    for folder in sorted(children):
        if folder.name.startswith(".pending-"):
            _directory(folder)
            continue
        require(re.fullmatch(r"[0-9a-f]{64}", folder.name) is not None)
        result.append((folder, _load_index(folder, repo_root)))
    return result


def sealed_closed_attempts(directory: Path, repo_root: Path, entries: list) -> set[str]:
    closed, covered_paths = set(), {}
    for _folder, plan in _seals(directory, repo_root):
        closed.update(plan["closed_attempts"])
        covered_paths.update(plan["originals"])
    for child, state in entries:
        child = Path(child)
        require(
            child.parent
            in {
                Path(directory) / "cohort-forward-recoveries",
                Path(directory) / "cohort-attempts",
            }
        )
        path = child / "state.json"
        require(_json(path) == state)
        if child.name in closed:
            require(
                str(path) in covered_paths
                and sha(_read(path)) == covered_paths[str(path)]
            )
            if child.parent.name == "cohort-forward-recoveries":
                require(str(child / "plan.json") in covered_paths)
        # Uncovered entries are deliberately absent from the result; the caller
        # must classify them and retention will keep their referenced roots.
    return closed


def verify_historical_release(directory, repo_root, root, tag, commit):
    identity = {"root": str(root), "tag": tag, "commit": commit}
    require(
        any(
            identity in plan["releases"]
            for _, plan in _seals(Path(directory), Path(repo_root))
        )
    )
    _verify_git(Path(repo_root), identity)
    if os.path.lexists(root):
        _verify_present_release(Path(repo_root), identity)


def _verify_present_release(repo_root, identity):
    from app.runtime_bindings import verify_release

    root = Path(identity["root"])
    require(root == root.resolve(strict=True) and not root.is_symlink())
    verify_release(root, identity["tag"], identity["commit"])
    require(_common(root) == _common(repo_root))


def historical_bytes(directory, repo_root, path):
    path = str(Path(path))
    found = []
    for folder, plan in _seals(Path(directory), Path(repo_root)):
        if path in plan["markers"]:
            expected = plan["markers"][path]
            found.append(None if expected is None else _read(folder / expected))
    require(found and all(value == found[0] for value in found))
    if found[0] is None:
        raise FileNotFoundError(path)
    return found[0]


MARKERS = frozenset(
    {
        "after-market-status.json",
        "after-market-history.json",
        "market-runtime-enabled",
        "alert-runtime-enabled",
        "reference-worker-enabled",
        "weekly-audit-enabled",
    }
)
LEAVES = frozenset(
    {
        "plan.json",
        "state.json",
        "receipt.json",
        "recovery-readback.json",
        "feed-close-confirmation.json",
        "stopped-confirmation.json",
    }
)


def _walk(value):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _entries(directory):
    found = []
    for name in ("cohort-attempts", "cohort-forward-recoveries"):
        parent = directory / name
        if not os.path.lexists(parent):
            continue
        _directory(parent)
        children = list(parent.iterdir())
        require(len(children) <= 1024)
        for child in sorted(children):
            _directory(child)
            require(re.fullmatch(r"[0-9a-f]{64}", child.name) is not None)
            found.append((child, _json(child / "state.json")))
    return found


def _public_plans(directory, repo_root):
    """Bounded, named operator-plan discovery; never crawl general runtime JSON."""
    common_root = Path(_common(repo_root)).parent
    candidates = list(directory.glob("rollover-readiness-*/cohort-plan*.json"))
    candidates += list(common_root.glob("output/*/cohort-plan*.json"))
    candidates += list(common_root.glob("output/*/*/cohort-plan*.json"))
    require(len(candidates) <= 1024)
    result = {}
    for path in sorted(candidates):
        value = _json(path)
        if value.get("kind") != "stopped_world_release_v1":
            continue
        name = value.get("plan_sha256")
        from app.reference_trading.recovery_campaign import digest

        require(name == digest({k: v for k, v in value.items() if k != "plan_sha256"}))
        if name in result:
            require(_json(result[name][0]) == value)
            result[name].append(path)
        else:
            result[name] = [path]
    return result


def _plan_paths(entries, directory, repo_root):
    public = None
    result = {}
    for child, _state in entries:
        path = child / "plan.json"
        if not os.path.lexists(path):
            require(child.parent.name == "cohort-attempts")
            if public is None:
                public = _public_plans(directory, repo_root)
            require(child.name in public)
            candidates = public[child.name]
            hashes = set()
            restored = child / "recovery-readback.json"
            if os.path.lexists(restored):
                hashes.add(_json(restored)["source_plan_sha256"])
            for other, _ in entries:
                private = other / "plan.json"
                if other.parent.name == "cohort-forward-recoveries" and os.path.lexists(
                    private
                ):
                    source = _json(private).get("source", {})
                    if source.get("plan_sha256") == child.name:
                        hashes.add(source["plan_bytes_sha256"])
            if hashes:
                require(len(hashes) == 1)
                candidates = [
                    candidate
                    for candidate in candidates
                    if sha(_read(candidate)) in hashes
                ]
                require(candidates)
            else:
                require(len({sha(_read(candidate)) for candidate in candidates}) == 1)
            path = candidates[0]
        result[child] = path
    return result


def recovery_references(directory, repo_root, roots):
    """Unsealed recovery dependencies pin their roots even when currently stopped."""
    directory, repo_root = Path(directory), Path(repo_root)
    result = {str(root): [] for root in roots}
    entries = _entries(directory)
    paths = _plan_paths(entries, directory, repo_root)
    closed = sealed_closed_attempts(directory, repo_root, entries)
    for child, _state in entries:
        if child.name in closed:
            continue
        for path in {paths[child], *(child / leaf for leaf in LEAVES)}:
            if not os.path.lexists(path):
                continue
            value = _json(path)
            encoded = json.dumps(value, sort_keys=True, ensure_ascii=False)
            for root in roots:
                if str(root) in encoded:
                    result[str(root)].append(
                        f"recovery:{child.parent.name}:{child.name}"
                    )
    return result


def _forward_terminal_subset(directory, current, entries, plan_paths, host, bindings):
    """Prove the live forward result, then leave its new-source chain unsealed.

    The deployed v1.16.60 historical reader cannot validate the later native
    COHORT_NEW_READY_TIMEOUT source shape. Its v1 seal therefore contains only
    the independently closed history through the preceding ordinary cohort.
    """
    from app import runtime_cohort as cohort, runtime_cohort_recovery as recovery

    require(
        set(current) == {
            "schema_version", "kind", "phase", "source_phase",
            "plan_sha256", "source_plan_sha256", "receipt_sha256",
            "original_attempt_preserved", "original_feed_halt_resolution",
        }
        and current["schema_version"] == 1
        and current["kind"] == "postcas_forward_recovery_result"
        and current["phase"] == "switched"
        and current["source_phase"] == "outcome_unknown"
        and current["original_attempt_preserved"] is True
    )
    name = current["plan_sha256"]
    child = directory / "cohort-forward-recoveries" / name
    require(child in plan_paths and plan_paths[child] == child / "plan.json")
    plan = _json(child / "plan.json")
    state = _json(child / "state.json")
    receipt_raw = _read(child / "receipt.json")
    receipt = _json(child / "receipt.json")
    recovery._validate(
        plan, datetime.fromisoformat(plan["created_at"]), historical=True,
        history_directory=directory,
    )
    require(
        set(state) == {
            "schema_version", "kind", "phase", "plan_sha256", "source",
            "receipt_sha256", "effects",
        }
        and state["schema_version"] == 1
        and state["kind"] == recovery.KIND
        and state["phase"] == "recovered"
        and state["plan_sha256"] == name == plan["plan_sha256"]
        and state["source"] == plan["source"]
        and state["receipt_sha256"] == current["receipt_sha256"] == sha(receipt_raw)
        and set(state["effects"])
        == {"consumers", "intake", "feed", "verified", "calendars"}
        and state["effects"]["consumers"] == {
            "resumed_generation": plan["new"]["services"]["live"]["generation"],
        }
        and state["effects"]["feed"]
        == {"bootstrapped": True, "label": "com.guiyi.quant-market-feed"}
        and set(receipt) == {
            "schema_version", "kind", "plan_sha256", "source",
            "observed_at", "intake", "readback", "natural_acceptance",
            "original_attempt_preserved", "original_feed_halt_resolution",
        }
        and receipt["schema_version"] == 1
        and receipt["kind"] == "postcas_forward_recovery_readback"
        and receipt["plan_sha256"] == name
        and receipt["source"] == plan["source"]
        and receipt["original_attempt_preserved"] is True
        and receipt["natural_acceptance"] == "pending"
        and receipt["intake"] == state["effects"]["intake"]
        and receipt["readback"] == state["effects"]["verified"]
        and recovery._valid_intake_result(receipt["intake"])
        and receipt["readback"].get("continuous_identity") == "matched"
        and receipt["readback"].get("calculation_ready") is False
        and recovery._valid_intake_result(receipt["readback"].get("intake"))
        and state["effects"]["calendars"]
        == {"calendar_registration_only": True, "identity": "matched"}
        and plan.get("mode") == recovery.ORIGINAL_FEED_MODE
        and "stop_after" not in plan
        and "predecessor" not in plan
    )
    source_plan, _source_state, source_identity = (
        recovery._original_verified_feed_source(
            host, plan["source"]["plan_path"], historical=True,
        )
    )
    require(
        source_identity == plan["source"]
        and source_identity["plan_sha256"] == current["source_plan_sha256"]
        and source_plan["new"] == plan["new"]
        and bindings == cohort.registry(plan["new"])
    )
    resolution = receipt["original_feed_halt_resolution"]
    close = plan["original_close"]
    require(
        set(resolution) == {"kind", "source", "feed_close", "confirmation"}
        and resolution["kind"]
        == "original_cohort_verified_feed_halt_resolution_v1"
        and resolution["source"] == source_identity
        and resolution["feed_close"] == close
        and resolution["confirmation"]
        == plan["audit"]["original_verified_feed_halt"]
        and recovery.valid_original_verified_feed_halt(
            resolution["confirmation"], source_identity, plan["audit"],
        )
        and current["original_feed_halt_resolution"] == {
            "source_plan_sha256": source_identity["plan_sha256"],
            "feed_close_plan_sha256": close["plan_sha256"],
            "receipt_sha256": current["receipt_sha256"],
        }
        and recovery._original_feed_close_attempt(
            host, close["plan_path"], source_identity,
        )[0] == close
    )
    candidates = [
        candidate for candidate, candidate_state in entries
        if candidate.parent.name == "cohort-attempts"
        and candidate_state.get("phase") == "switched"
        and _json(plan_paths[candidate]).get("new") == source_plan["old"]
    ]
    require(len(candidates) == 1)
    terminal = candidates[0]
    excluded = {
        source_identity["plan_sha256"], child.name, close["plan_sha256"],
    }
    for candidate, _candidate_state in entries:
        if candidate.parent.name != "cohort-forward-recoveries":
            continue
        candidate_source = _json(plan_paths[candidate]).get("source")
        if (isinstance(candidate_source, dict)
                and candidate_source.get("plan_sha256")
                == source_identity["plan_sha256"]):
            require(candidate_source == source_identity
                    and candidate.name in excluded)
    require(
        child.name in excluded
        and close["plan_sha256"] in excluded
        and any(candidate.name == source_identity["plan_sha256"]
                and candidate.parent.name == "cohort-attempts"
                for candidate, _state in entries)
    )
    return terminal.name, excluded


class RetirementBackend:
    def __init__(self, directory=None, repo_root=None):
        from app.runtime_handover import runtime_directory
        from app.core.env import PROJECT_ROOT

        self.directory = runtime_directory() if directory is None else Path(directory)
        self.repo_root = PROJECT_ROOT if repo_root is None else Path(repo_root)

    def collect(self, roots):
        from app.runtime_retention import RetentionBackend
        from app.runtime_bindings import read_bindings
        from app.runtime_cohort_recovery import (
            ForwardRecoveryHost,
            _no_unresolved_recovery,
        )
        from app.runtime_cohort import registry, validate

        _directory(self.directory)
        global_path = self.directory / "cohort-release.json"
        global_raw, current = _read(global_path), _json(global_path)
        require(current.get("phase") == "switched")
        current_id = current.get("plan_sha256")
        require(
            isinstance(current_id, str) and re.fullmatch(r"[0-9a-f]{64}", current_id)
        )
        bindings = read_bindings()
        require(
            len({(row.root, row.tag, row.commit) for row in bindings.services.values()})
            == 1
        )
        require(
            not any(
                row.root in {str(root) for root in roots}
                for row in bindings.services.values()
            )
        )
        host = ForwardRecoveryHost()
        host.directory = self.directory
        _no_unresolved_recovery(host)
        all_entries = _entries(self.directory)
        all_plan_paths = _plan_paths(all_entries, self.directory, self.repo_root)
        excluded = set()
        if current.get("kind") == "postcas_forward_recovery_result":
            current_id, excluded = _forward_terminal_subset(
                self.directory, current, all_entries, all_plan_paths, host, bindings,
            )
        else:
            terminal = self.directory / "cohort-attempts" / current_id
            plan = _json(terminal / "plan.json")
            validate(
                plan,
                datetime.fromisoformat(plan["created_at"]),
                historical=True,
                history_directory=self.directory,
            )
            require(_read(terminal / "state.json") == global_raw)
            require(
                current.get("schema_version") == 1
                and "kind" not in current
                and plan.get("plan_sha256") == current_id
                and current.get("effects", {})
                .get("verified", {})
                .get("continuous_identity")
                == "matched"
                and current.get("effects", {})
                .get("calendars_on", {})
                .get("identity")
                == "matched"
                and current.get("effects", {})
                .get("calendars_on", {})
                .get("calendar_registration_only")
                is True
                and bindings == registry(plan["new"])
            )
        entries = [
            (child, state) for child, state in all_entries
            if child.name not in excluded
        ]
        plan_paths = {child: all_plan_paths[child] for child, _state in entries}
        historical_identities = {}
        for path in plan_paths.values():
            for item in _walk(_json(path)):
                if isinstance(item, dict) and {"root", "tag", "commit"} <= set(item):
                    identity = {key: item[key] for key in ("root", "tag", "commit")}
                    root = Path(identity["root"])
                    require(
                        root.is_absolute()
                        and root == root.resolve()
                    )
                    _verify_git(self.repo_root, identity)
                    if os.path.lexists(root):
                        _verify_present_release(self.repo_root, identity)
                    previous = historical_identities.get(identity["root"])
                    require(previous is None or previous == identity)
                    historical_identities[identity["root"]] = identity

        def history_verifier(root, tag, commit, directory):
            require(Path(directory) == self.directory)
            identity = {"root": str(root), "tag": tag, "commit": commit}
            require(historical_identities.get(str(root)) == identity)
            _verify_git(self.repo_root, identity)
            if os.path.lexists(root):
                _verify_present_release(self.repo_root, identity)

        originals, markers = {}, {}
        recovered_sources = set()
        for child, state in entries:
            if (
                child.parent.name == "cohort-forward-recoveries"
                and state.get("phase") == "recovered"
            ):
                raw = _read(child / "receipt.json")
                require(sha(raw) == state.get("receipt_sha256"))
                receipt = _json(child / "receipt.json")
                require(
                    receipt.get("plan_sha256") == child.name
                    and receipt.get("source") == state.get("source")
                    and receipt.get("kind") == "postcas_forward_recovery_readback"
                    and receipt.get("original_attempt_preserved") is True
                    and {"consumers", "intake", "feed", "verified", "calendars"}
                    <= set(state.get("effects", {}))
                    and receipt.get("intake") == state["effects"]["intake"]
                    and receipt.get("readback") == state["effects"]["verified"]
                )
                recovered_sources.add(receipt["source"]["plan_sha256"])
        for child, state in entries:
            private = _json(plan_paths[child])
            originals[str(plan_paths[child])] = sha(_read(plan_paths[child]))
            if child.parent.name == "cohort-attempts":
                validate(
                    private,
                    datetime.fromisoformat(private["created_at"]),
                    historical=True,
                    history_directory=self.directory,
                    history_verifier=history_verifier,
                )
                require(
                    state.get("plan_sha256") == child.name == private.get("plan_sha256")
                )
                if state.get("phase") == "restore_unknown":
                    receipt = _json(child / "recovery-readback.json")
                    require(
                        receipt.get("kind") == "precommit_restore_readback"
                        and receipt.get("schema_version") == 1
                        and receipt.get("plan_sha256") == child.name
                        and receipt.get("source_attempt_sha256")
                        == sha(_read(child / "state.json"))
                        and receipt.get("source_global_sha256")
                        == receipt["source_attempt_sha256"]
                        and receipt.get("source_plan_sha256")
                        == sha(_read(plan_paths[child]))
                        and re.fullmatch(
                            r"[0-9a-f]{64}",
                            receipt.get("proof", {}).get("identity_sha256", ""),
                        )
                        and set(state.get("effects", {}))
                        <= {
                            "prewarm",
                            "calendars_off",
                            "drain",
                            "old_exited",
                            "preserve",
                            "install",
                            "bootout_requests",
                        }
                    )
                else:
                    require(
                        state.get("phase") in {"switched", "cancelled"}
                        or child.name in recovered_sources
                    )
                    if state.get("phase") == "switched":
                        require(
                            {"verified", "calendars_on"}
                            <= set(state.get("effects", {}))
                        )
                    elif state.get("phase") == "cancelled":
                        require(
                            not {"consumers", "feed", "verified", "calendars_on"}
                            & set(state.get("effects", {}))
                        )
            else:
                from app.runtime_cohort_recovery import _validate

                _validate(
                    private,
                    datetime.fromisoformat(private["created_at"]),
                    historical=True,
                    history_directory=self.directory,
                )
            for leaf in LEAVES:
                path = child / leaf
                if os.path.lexists(path):
                    originals[str(path)] = sha(_read(path))
        # Follow typed descriptors to public plan/confirmation preimages, never arbitrary configs.
        queue = list(originals)
        seen = set(queue)
        while queue:
            path = queue.pop()
            value = _json(path)
            for item in _walk(value):
                if not isinstance(item, dict):
                    continue
                for key, val in item.items():
                    candidate = None
                    if (
                        (
                            key in {"plan_path", "failed_plan_path"}
                            or key == "path"
                            and isinstance(val, str)
                            and Path(val).name in LEAVES
                        )
                        and isinstance(val, str)
                        and val.endswith(".json")
                    ):
                        candidate = Path(val)
                    elif (
                        key.startswith("/")
                        and key.endswith(".json")
                        and isinstance(val, str)
                        and re.fullmatch(r"[0-9a-f]{64}", val)
                    ):
                        candidate = Path(key)
                    if (
                        candidate is not None
                        and str(candidate) not in seen
                        and ".run" not in candidate.parts
                    ):
                        # Only runtime receipts or public operator plans may be traversed.
                        require(candidate.is_absolute() and candidate.suffix == ".json")
                        raw = _read(candidate)
                        document = _json(candidate)
                        if not (
                            "plan_sha256" in document
                            or "schema_version" in document
                            and candidate.name in LEAVES
                        ):
                            continue
                        originals[str(candidate)] = sha(raw)
                        seen.add(str(candidate))
                        queue.append(str(candidate))
                    if key.startswith("/"):
                        candidate = Path(key)
                        if any(candidate.parent == root / ".run" for root in roots):
                            require(candidate.name in MARKERS)
                            expected = (
                                val.get("sha256") if isinstance(val, dict) else val
                            )
                            actual = (
                                sha(_read(candidate))
                                if os.path.lexists(candidate)
                                else None
                            )
                            require(expected == actual)
                            markers[str(candidate)] = actual
        for path in originals:
            require(not excluded.intersection(Path(path).parts))
            require(not any(
                item in excluded
                for item in _walk(_json(path))
                if isinstance(item, str)
            ))
        for root in roots:
            for name in MARKERS:
                path = root / ".run" / name
                actual = sha(_read(path)) if os.path.lexists(path) else None
                if str(path) in markers:
                    require(markers[str(path)] == actual)
                markers[str(path)] = actual
        retention = RetentionBackend()
        references = retention.references_by_root(roots)
        require(set(references) == {str(root) for root in roots})
        require(
            all(
                reason.startswith("recovery:")
                for reasons in references.values()
                for reason in reasons
            )
        )
        identities = [retention.candidate_identity(root) for root in roots]
        for identity in identities:
            _verify_git(self.repo_root, identity)
            previous = historical_identities.get(identity["root"])
            require(previous is None or previous == identity)
            historical_identities[identity["root"]] = identity
        result = {
            "directory": str(self.directory),
            "repo_root": str(self.repo_root),
            "repository_common_dir": _common(self.repo_root),
            "releases": [
                historical_identities[key] for key in sorted(historical_identities)
            ],
            "closed_attempts": sorted(child.name for child, _state in entries),
            "originals": dict(sorted(originals.items())),
            "markers": dict(sorted(markers.items())),
            "guards": {
                "global_sha256": sha(global_raw),
                "bindings_sha256": _digest(asdict(bindings)),
                "references_sha256": _digest(references),
            },
            "terminal_cohort": current_id,
        }
        _closed_history(result, self.repo_root)
        return result
