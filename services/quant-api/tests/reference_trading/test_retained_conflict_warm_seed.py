from copy import deepcopy
from dataclasses import replace

import pytest

from app.reference_trading import original_conflict_warm_seed as warm
from app.reference_trading.repository import RepositoryConflict
from test_original_conflict_warm_seed import fixture, START


def retained_fixture():
    baseline, snapshot, inputs, authority, _, _, _ = fixture()
    items = []
    for item in inputs:
        proof = {
            k: v
            for k, v in item.source_proof.items()
            if k not in ("recovery_plan_sha256", "recovery_readback_sha256")
        }
        if item.source_kind == "completed_live":
            proof.update(
                provenance="retained_completed_observation_v1",
                journal_key="live:observations:completed:2026-10-13",
                observation_id="original-h1",
                journal_id="1791900000000-0",
                envelope_sha256="4" * 64,
                identity_index_sha256="5" * 64,
                interval_sha256="6" * 64,
                original_readback_sha256="7" * 64,
            )
        items.append(replace(item, source_proof=proof))

    def run(values=tuple(items), verify=authority):
        entry = getattr(warm, "materialize_retained_warm_seed", None)
        assert callable(entry), (
            "retained observations need their own versioned warm entry"
        )
        return entry(
            baseline,
            fresh_snapshot=snapshot,
            inputs=values,
            expected_endpoints=tuple(i.product_bar.bar.bar_end for i in values),
            recording_start=START,
            cutoff=values[-1].product_bar.bar.bar_end,
            stage="final_observation",
            verify_authority=verify,
        )

    return tuple(items), run


def test_retained_original_advances_real_kernel_without_fabricated_repair_receipt():
    items, run = retained_fixture()
    seed = run()
    assert seed.proof["version"] == "retained_conflict_warm_seed_v1"
    assert seed.binding["kind"] == "retained_conflict_warm_seed_v1"
    assert seed.checkpoint.computed_through == items[-1].product_bar.bar.bar_end
    assert seed.proof["first_seen"] is False
    assert seed.proof["natural_capture"] is False
    assert "recovery_plan_sha256" not in seed.proof["inputs"][-1]["authority"]


@pytest.mark.parametrize(
    "field",
    [
        "envelope_sha256",
        "identity_index_sha256",
        "interval_sha256",
        "original_readback_sha256",
        "journal_id",
        "observation_id",
        "journal_key",
    ],
)
def test_retained_input_requires_original_provenance(field):
    items, run = retained_fixture()
    bad = deepcopy(items[-1].source_proof)
    bad.pop(field)
    with pytest.raises(RepositoryConflict, match="RETAINED_OBSERVATION_UNVERIFIED"):
        run((items[0], replace(items[-1], source_proof=bad)))


def test_v1_recovery_contract_stays_strict_for_retained_originals():
    items, _ = retained_fixture()
    _, _, _, _, run, _, _ = fixture()
    with pytest.raises(RepositoryConflict, match="LIVE_RECOVERY_UNVERIFIED"):
        run(items)


def test_retained_recovery_has_separate_admission_and_atomic_four_route_identity():
    from datetime import timedelta
    from app.reference_trading.conflict_recovery import (
        RetainedWarmConflictRevisionRecovery,
    )
    from tests.reference_trading.test_final_warm_conflict_recovery import (
        prepared,
        NEW_START,
        EXPIRY,
    )
    from tests.reference_trading.test_newow_bootstrap import START as OLD_START

    factory, repo, sources, targets, _, seeds, old_service = prepared()
    service = RetainedWarmConflictRevisionRecovery(
        factory,
        source_loader=old_service.source_loader,
        verify_source=old_service.verify_source,
        assert_fenced=lambda: None,
    )
    with pytest.raises(RepositoryConflict, match="WARM_SEED_UNVERIFIED"):
        service.plan(
            sources,
            recording_start=NEW_START,
            expires_at=EXPIRY,
            now=OLD_START + timedelta(minutes=1),
        )
    # These fixture seeds contain verified Canonical inputs only. Rebind their
    # separate version to exercise protocol admission; Live provenance is tested above.
    for sid, seed in list(seeds.items()):
        proof = deepcopy(seed.proof)
        proof["version"] = warm.RETAINED_VERSION
        for base in proof.get("base_proofs", []):
            base["version"] = warm.RETAINED_VERSION
        seeds[sid] = warm._result(
            seed.identity,
            seed.checkpoint,
            seed.schema,
            proof,
            seed.binding["original_source_binding"],
        )
    plan = service.plan(
        sources,
        recording_start=NEW_START,
        expires_at=EXPIRY,
        now=OLD_START + timedelta(minutes=1),
    )
    assert plan["version"] == "reference_capture_retained_warm_recovery_v1"
    result = service.apply(
        plan, expected_plan_hash=plan["plan_hash"], now=OLD_START + timedelta(minutes=2)
    )
    assert set(result) == set(targets)
    for sid in targets:
        state = repo.read_state(sid)
        assert state.dependency_manifest["reader"] == warm.RETAINED_VERSION
        assert "capture_retained_warm_conflict_recovery_v1" in state.dependency_manifest
        assert repo.load_checkpoint(sid)[1].reference_state.open_trade is None
    assert (
        service.apply(
            plan,
            expected_plan_hash=plan["plan_hash"],
            now=NEW_START + timedelta(days=1),
        )
        == result
    )


def test_retained_rollover_uses_only_new_contract_kernel_state():
    from guiyi_quant.newow.product_adapters import replay_step, seed_replay_state

    _, _, _, _, _, identity, _ = fixture()
    baseline, _, _, _, _, _, _ = fixture()
    inputs, run = retained_fixture()
    changed = []
    for index, item in enumerate(inputs):
        product = replace(
            item.product_bar,
            bar=replace(
                item.product_bar.bar,
                physical_contract="RB2705",
                segment_id="next-owner",
            ),
            calculation_segment_id="next-calc",
        )
        item = replace(item, product_bar=product)
        changed.append(
            replace(
                item,
                source_proof={
                    **item.source_proof,
                    **warm._input_facts(item),
                    "rollover": index == 0,
                },
            )
        )
    seed = run(tuple(changed))
    expected = seed_replay_state()
    inherited = baseline.checkpoint.strategy_state
    for item in changed:
        expected, _, _ = replay_step(identity, expected, item.product_bar)
        inherited, _, _ = replay_step(identity, inherited, item.product_bar)
    assert seed.checkpoint.strategy_state == expected
    assert seed.checkpoint.strategy_state != inherited
    assert len(seed.proof["rollovers"]) == 1
    assert seed.proof["rollovers"][0]["next"] == ["RB2705", "next-owner", "next-calc"]
