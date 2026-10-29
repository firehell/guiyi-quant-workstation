from datetime import timedelta
import pytest
from guiyi_quant.lms_confirmed_replay import replay, state_dict
from test_protection_proposals import bar, state

US = timedelta(microseconds=1)


def bars():
    return [bar(-1, h="20", low="5"), bar(0), bar(1, "11", "16", "6", "7"), bar(2)]


def baseline():
    b = bars()
    return replay(b, state("LONG"), as_of=b[2].end + US)


def decision(p, **kw):
    return (
        dict(
            decision_id="d1",
            proposal_id=p["proposal_id"],
            state_fingerprint=p["state_fingerprint"],
            decision="ACCEPT",
            decided_at=(bars()[2].end + timedelta(seconds=1)).isoformat(),
            known_at=(bars()[2].end + timedelta(seconds=1)).isoformat(),
            record_kind="TEST_FIXTURE",
        )
        | kw
    )


def test_zero_confirmation_then_accept_and_restart():
    b = bars()
    r = baseline()
    assert r["current_state"] == state_dict(state("LONG"))
    p = r["proposals"][0]
    d = decision(p, decided_at=(b[2].end + timedelta(seconds=1)).isoformat())
    a = replay(b, state("LONG"), [d], as_of=b[2].end + timedelta(seconds=2))
    assert a["current_state"]["position"] == {
        "contract": "JM2509",
        "long": "1",
        "short": "1",
    }
    assert a["current_state"]["since"] == d["known_at"] and len(a["transitions"]) == 1
    end = b[-1].end + US
    assert replay(
        b, state("LONG"), [d], as_of=end, checkpoint=a["checkpoint"]
    ) == replay(b, state("LONG"), [d], as_of=end)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"decision": "REJECT"}, "REJECTED"),
        ({"state_fingerprint": "bad"}, "STATE_MISMATCH"),
        ({"proposal_id": "bad"}, "UNKNOWN_PROPOSAL"),
        ({"known_at": (bars()[-1].end + US).isoformat()}, "PROPOSAL_NOT_PENDING"),
        ({"decided_at": bars()[1].end.isoformat()}, "DECISION_NOT_AFTER_PROPOSAL"),
    ],
)
def test_rejected_decisions_never_change_state(change, reason):
    r = baseline()
    d = decision(r["proposals"][0], **change)
    result = replay(
        bars(), state("LONG"), [d], as_of=bars()[-1].end + timedelta(seconds=1)
    )
    assert not result["transitions"] and result["decisions"][0]["reason"] == reason


def test_duplicates_tamper_and_equal_time_conflict():
    p = baseline()["proposals"][0]
    d = decision(p, decided_at=(bars()[2].end + timedelta(seconds=1)).isoformat())
    end = bars()[-1].end + US
    assert len(replay(bars(), state("LONG"), [d, d], as_of=end)["transitions"]) == 1
    r = replay(bars(), state("LONG"), [d, d | {"decision": "REJECT"}], as_of=end)
    assert not r["transitions"]
    r = replay(
        bars(),
        state("LONG"),
        [d, d | {"decision_id": "d2", "decision": "REJECT"}],
        as_of=end,
    )
    assert not r["transitions"]


def test_prefix_checkpoint_tamper_and_future_hidden():
    b = bars()
    r = baseline()
    assert replay(b[:3], state("LONG"), as_of=b[2].end + US) == r
    with pytest.raises(ValueError):
        replay(
            b,
            state("LONG"),
            as_of=b[-1].end + US,
            checkpoint=r["checkpoint"] | {"current_state": {}},
        )
    with pytest.raises(ValueError):
        replay([b[0], b[0]], state("LONG"), as_of=b[-1].end + US)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_continuous_lock_restore_original_direction(side):
    # Synthetic fixture: two opposite breakouts separated by new post-state ibar.
    b = bars()[:3] + [bar(2, "10", "13", "8", "11"), bar(3, "11", "16", "7", "15")]
    if side == "SHORT":
        from dataclasses import replace

        b = [
            replace(
                x,
                open=30 - x.open,
                high=30 - x.low,
                low=30 - x.high,
                close=30 - x.close,
            )
            for x in b
        ]
    seed = state(side)
    t = b[2].end + timedelta(seconds=1)
    r = replay(b, seed, as_of=b[2].end + US)
    p = r["proposals"][0]
    d = decision(p, decided_at=t.isoformat(), known_at=t.isoformat())
    r = replay(b, seed, [d], as_of=b[-1].end + US)
    pending = [p for p in r["proposals"] if p["status"] == "PENDING"][0]
    t2 = b[-1].end + timedelta(seconds=1)
    d2 = decision(
        pending, decision_id="d2", decided_at=t2.isoformat(), known_at=t2.isoformat()
    )
    final = replay(b, seed, [d, d2], as_of=t2)
    assert len(final["transitions"]) == 2
    assert final["current_state"]["position"] == state_dict(seed)["position"]
    assert final["current_state"]["original_side"] == side
    assert final["performance"] is None and final["fill"] is None


def test_checkpoint_late_decision_and_changed_prefix_fail_closed():
    from dataclasses import replace

    b = bars()
    r = baseline()
    p = r["proposals"][0]
    with pytest.raises(ValueError, match="LATE_DECISION"):
        replay(
            b,
            state("LONG"),
            [decision(p, known_at=p["generated_at"])],
            as_of=b[-1].end + US,
            checkpoint=r["checkpoint"],
        )
    with pytest.raises(ValueError, match="CHECKPOINT"):
        replay(
            [replace(b[0], high=b[0].high + 1)] + b[1:],
            state("LONG"),
            as_of=b[-1].end + US,
            checkpoint=r["checkpoint"],
        )


def test_flat_missing_malformed_and_future_decision_visibility():
    b = bars()
    end = b[-1].end + US
    assert not replay(b, state("LONG", flat=True), as_of=end)["proposals"]
    r = replay(b, state("LONG"), [{}, {"known_at": "no"}], as_of=end)
    assert len(r["decisions"]) == 2 and not r["transitions"]
    future = decision(
        baseline()["proposals"][0], known_at=(end + timedelta(days=1)).isoformat()
    )
    assert replay(b, state("LONG"), [future], as_of=end) == replay(
        b, state("LONG"), as_of=end
    )


def test_later_id_tamper_does_not_erase_previous_transition():
    p = baseline()["proposals"][0]
    d = decision(p)
    late = d | {
        "known_at": (bars()[2].end + timedelta(seconds=3)).isoformat(),
        "decision": "REJECT",
    }
    r = replay(bars(), state("LONG"), [d, late], as_of=bars()[-1].end + US)
    assert len(r["transitions"]) == 1
    assert r["decisions"][-1]["reason"] == "DECISION_ID_CONTENT_CONFLICT"


def test_unhashable_id_is_invalid_not_process_crash():
    d = decision(baseline()["proposals"][0], decision_id=[])
    r = replay(bars(), state("LONG"), [d], as_of=bars()[-1].end + US)
    assert r["decisions"][0]["reason"] == "INVALID_DECISION"


@pytest.mark.parametrize("key", ["policy_version", "keybar_version", "replay_version"])
def test_explicit_wrong_version_rejected(key):
    d = decision(baseline()["proposals"][0], **{key: "wrong"})
    r = replay(bars(), state("LONG"), [d], as_of=bars()[-1].end + US)
    assert not r["transitions"] and r["decisions"][0]["reason"] == "IDENTITY_MISMATCH"


def test_invalid_records_survive_checkpoint_and_batch_incremental_parity():
    b = bars()
    records = [{}]
    at = b[2].end + US
    r = replay(b, state("LONG"), records, as_of=at)
    assert replay(
        b, state("LONG"), records, as_of=b[-1].end + US, checkpoint=r["checkpoint"]
    ) == replay(b, state("LONG"), records, as_of=b[-1].end + US)
    p = baseline()["proposals"][0]
    d = decision(p)
    cp = None
    for t in [
        b[0].end + US,
        b[1].end + US,
        b[2].end + US,
        b[2].end + timedelta(seconds=2),
        b[-1].end + US,
    ]:
        incremental = replay(b, state("LONG"), [d], as_of=t, checkpoint=cp)
        assert incremental == replay(b, state("LONG"), [d], as_of=t)
        cp = incremental["checkpoint"]


@pytest.mark.parametrize(
    "bad",
    [
        {"record_kind": "ROBOT"},
        {"contract": "SH2701"},
        {"decision": "AUTO"},
        {"known_at": "2025-07-22T01:10:00"},
        {"decided_at": "2025-07-22T02:00:00+00:00"},
    ],
)
def test_invalid_or_cross_contract_records_cannot_apply(bad):
    r = replay(
        bars(),
        state("LONG"),
        [decision(baseline()["proposals"][0], **bad)],
        as_of=bars()[-1].end + US,
    )
    assert not r["transitions"]


def test_second_id_same_proposal_cannot_apply_twice():
    p = baseline()["proposals"][0]
    first = decision(p)
    second = first | {
        "decision_id": "d2",
        "known_at": (bars()[2].end + timedelta(seconds=2)).isoformat(),
    }
    r = replay(bars(), state("LONG"), [second, first], as_of=bars()[-1].end + US)
    assert len(r["transitions"]) == 1
    assert r["decisions"][-1]["reason"] == "PROPOSAL_NOT_PENDING"
