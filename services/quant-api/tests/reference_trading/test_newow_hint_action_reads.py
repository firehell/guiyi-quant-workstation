"""Minute hint suppression reads only matching saved actions; daily contract remains bounded."""

from datetime import date, datetime

import pytest

from app.reference_trading.persisted_newow import PersistedNewowReference

CUTOFF = datetime.fromisoformat("2026-09-24T07:00:00+00:00")
SINCE = date(2023, 1, 1)


def point(
    contract="SM2701", segment="owner", bar="2026-09-23T07:00:00+00:00", sequence=1
):
    return {
        "value": {
            "physical_contract": contract,
            "segment_id": segment,
            "bar_end": bar,
            "sequence": sequence,
        }
    }


def read(query, minute=True, cancel=None):
    value = PersistedNewowReference(lambda: None)
    value._query = query
    return value._reference_facts(
        "stream",
        "snapshot",
        SINCE,
        date(2022, 1, 1),
        date(2026, 9, 24),
        CUTOFF,
        {"input_count": 896561},
        minute,
        cancel,
    )


class Query:
    def __init__(self, hints=(), actions=()):
        self.hints = list(hints)
        self.actions = actions
        self.calls = []
        self.closed = False

    def presentation_facts(self, *args, **kwargs):
        self.calls.append(("facts", kwargs))
        if "action" in kwargs["kinds"] and len(self.actions) > 200000:
            raise ValueError("PRESENTATION_BUDGET_EXCEEDED")
        return {
            "availability": [],
            "boundary": [],
            "hint": self.hints,
            **({"action": list(self.actions)} if "action" in kwargs["kinds"] else {}),
        }

    def historical_actions(self, *args, **kwargs):
        self.calls.append(("actions", kwargs))
        try:
            for action in self.actions:
                if kwargs.get("check_cancelled"):
                    kwargs["check_cancelled"]()
                yield action
        finally:
            self.closed = True


def test_more_than_web_cap_unrelated_actions_and_no_hint_never_read_actions():
    q = Query(actions=[point()] * 231038)
    with pytest.raises(ValueError, match="PRESENTATION_BUDGET_EXCEEDED"):
        q.presentation_facts(kinds=("availability", "boundary", "hint", "action"))
    q.calls.clear()
    result = read(q)
    assert result["action"] == []
    assert [name for name, _ in q.calls] == ["facts"]
    assert q.calls[0][1]["max_points"] == 200000
    assert q.calls[0][1]["kinds"] == ("availability", "boundary", "hint")


def test_all_same_bar_sequences_retained_and_hint_suppression_golden():
    same = [point(sequence=1), point(sequence=2)]
    unrelated = [point(contract="OTHER")] * 200001
    hints = []
    for sequence in (None, 1, 2, 3):
        hints.append(
            {
                "value": {
                    **point(sequence=sequence)["value"],
                    "hint_id": str(sequence),
                    "known_at": "2026-09-23T07:00:00+00:00",
                    "kind": "process",
                    "retrospective": False,
                }
            }
        )
    future = {
        "value": {
            **hints[-1]["value"],
            "hint_id": "future",
            "known_at": "2026-09-25T07:00:00+00:00",
        }
    }
    q = Query(hints + [future], same + unrelated)
    facts = read(q)
    assert facts["action"] == same and q.closed
    trade = {
        "reference_trade_id": "trade",
        "physical_contract": "SM2701",
        "owner_segment_id": "owner",
        "status": "CLOSED",
        "entry_bar_end": "2026-09-22T07:00:00+00:00",
        "exit_bar_end": "2026-09-24T07:00:00+00:00",
        "entry_sequence": 0,
        "exit_sequence": 5,
    }
    expected = PersistedNewowReference._hint_ids(
        [trade], same + unrelated, q.hints, CUTOFF
    )
    assert (
        PersistedNewowReference._hint_ids(
            [trade], facts["action"], facts["hint"], CUTOFF
        )
        == expected
        == {"trade": ["3"]}
    )
    call = q.calls[1][1]
    assert (
        call["snapshot_token"] == "snapshot"
        and call["input_count"] == 896561
        and call["cutoff"] == CUTOFF
        and call["since"] == SINCE
    )


def test_cancel_closes_saved_iterator_and_returns_no_partial_facts():
    q = Query([point()], [point()] * 10)

    def cancel():
        raise ValueError("NEWOW_READ_CANCELLED")

    with pytest.raises(ValueError, match="NEWOW_READ_CANCELLED"):
        read(q, cancel=cancel)
    assert q.closed


def test_corrupt_matching_key_closes_saved_iterator():
    q = Query([point()], [{"value": {"bar_end": "2026-09-23T07:00:00+00:00"}}])
    with pytest.raises(KeyError):
        read(q)
    assert q.closed


def test_daily_keeps_existing_collector_without_historical_actions():
    q = Query([point()], [point()])
    result = read(q, minute=False)
    assert result["action"] == [point()]
    assert len(q.calls) == 1 and q.calls[0][1]["max_points"] == 100000
    assert q.calls[0][1]["since"] == date(2022, 1, 1)
    assert q.calls[0][1]["kinds"] == ("availability", "boundary", "hint", "action")
