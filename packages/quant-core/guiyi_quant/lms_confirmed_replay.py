"""Human-confirmed hypothetical research replay; no fills or trading authority."""

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from .lms405 import Action, Position, apply_action, timestamp
from .lms_keybar_approx import classify, VERSION as KEYBAR_VERSION
from .lms_protection_proposals import (
    ResearchState,
    recommend,
    VERSION as PROPOSAL_VERSION,
)

VERSION = "lms-confirmed-replay-v1"
US = timedelta(microseconds=1)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def state_dict(state):
    return dict(
        position=dict(
            contract=state.position.contract,
            long=str(state.position.long),
            short=str(state.position.short),
        ),
        original_side=state.original_side,
        since=state.since.isoformat(),
        known_at=state.known_at.isoformat(),
    )


def state_from_dict(value):
    p = value["position"]
    return ResearchState(
        Position(p["contract"], Decimal(p["long"]), Decimal(p["short"])),
        value["original_side"],
        datetime.fromisoformat(value["since"]),
        datetime.fromisoformat(value["known_at"]),
    )


def _time(value):
    t = datetime.fromisoformat(value)
    timestamp(t)
    return t


def replay(bars, initial_state, decisions=None, *, as_of, checkpoint=None):
    """Replay only revealed rows. Checkpoints are validated by deterministic prefix replay.

    Input includes the full known prefix on resume, rather than trusting serialized
    state as an authority. Historical late records cannot rewrite a checkpoint.
    """
    timestamp(as_of)
    initial_state.__post_init__()
    if initial_state.known_at >= as_of:
        raise ValueError("INITIAL_STATE_NOT_AVAILABLE")
    decisions = list(decisions or [])
    visible = [b for b in bars if b.end + US <= as_of]
    if not visible:
        raise ValueError("VISIBLE_BARS_REQUIRED")
    frames = []
    for b in visible:
        frames.append(classify(frames[-1].bar if frames else None, b))
        if b.contract != initial_state.position.contract:
            raise ValueError("CONTRACT_BOUNDARY")
    if checkpoint is not None:
        old = _time(checkpoint["as_of"])
        if old > as_of:
            raise ValueError("CHECKPOINT_TIME_REVERSED")
        prior = replay(bars, initial_state, checkpoint["decision_records"], as_of=old)[
            "checkpoint"
        ]
        if prior != checkpoint:
            raise ValueError("CHECKPOINT_IDENTITY_MISMATCH")
        for d in decisions:
            if d not in checkpoint["decision_records"]:
                try:
                    late = _time(d["known_at"]) <= old
                except (ValueError, KeyError, TypeError):
                    late = True
                if late:
                    raise ValueError("LATE_DECISION_BEFORE_CHECKPOINT")
        decisions = checkpoint["decision_records"] + [
            d for d in decisions if d not in checkpoint["decision_records"]
        ]
    state = initial_state
    proposals = []
    evaluations = []
    outcomes = []
    transitions = []
    events = []
    records = []
    consumed = []
    for i, b in enumerate(visible):
        events.append((b.end + US, 0, i))
    for d in decisions:
        try:
            if not isinstance(d, dict):
                raise ValueError()
            known = _time(d["known_at"])
            if known > as_of:
                continue
            if not isinstance(d.get("decision_id"), str) or not d["decision_id"]:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            consumed.append(d)
            outcomes.append(dict(record=d, reason="INVALID_DECISION", status="INVALID"))
            continue
        records.append(d)
        consumed.append(d)
    processed = {}
    unique = []
    seen = set()
    for d in records:
        h = fingerprint(d)
        if h not in seen:
            unique.append(d)
            seen.add(h)
    groups = {}
    for d in unique:
        groups.setdefault(_time(d["known_at"]), []).append(d)
    for t, ds in groups.items():
        events.append((t, 1, ds))
    events.sort(key=lambda x: (x[0], x[1]))
    for t, kind, payload in events:
        if kind == 0:
            for p in proposals:
                if p["status"] == "PENDING":
                    p.update(status="EXPIRED", expired_at=t.isoformat())
            i = payload
            if i:
                e = recommend(state, frames[i - 1], visible[i], as_of=t)
                evaluations.append(e)
                if e["status"] == "PROPOSAL":
                    proposals.append(
                        e
                        | dict(
                            status="PENDING",
                            generated_at=t.isoformat(),
                            replay_version=VERSION,
                        )
                    )
            continue
        for d in payload:
            reason = None
            p = None
            try:
                if (
                    set(
                        (
                            "decision_id",
                            "proposal_id",
                            "state_fingerprint",
                            "decision",
                            "decided_at",
                            "known_at",
                            "record_kind",
                        )
                    )
                    - d.keys()
                ):
                    raise ValueError()
                if not all(
                    isinstance(d[k], str) and d[k]
                    for k in ("decision_id", "proposal_id", "state_fingerprint")
                ):
                    raise ValueError()
                decided = _time(d["decided_at"])
                if (
                    t < decided
                    or d["decision"] not in ("ACCEPT", "REJECT")
                    or d["record_kind"]
                    not in ("HUMAN_RESEARCH_DECISION", "TEST_FIXTURE")
                ):
                    raise ValueError()
                if "recorded_at" in d:
                    _time(d["recorded_at"])
                if d["decision_id"] in processed and processed[
                    d["decision_id"]
                ] != fingerprint(d):
                    reason = "DECISION_ID_CONTENT_CONFLICT"
                elif len(payload) > 1:
                    reason = "SAME_TIME_DECISION_CONFLICT"
                elif any(
                    d.get(k, v) != v
                    for k, v in {
                        "replay_version": VERSION,
                        "policy_version": PROPOSAL_VERSION,
                        "keybar_version": KEYBAR_VERSION,
                        "contract": state.position.contract,
                    }.items()
                ):
                    reason = "IDENTITY_MISMATCH"
                else:
                    p = next(
                        (p for p in proposals if p["proposal_id"] == d["proposal_id"]),
                        None,
                    )
                    if p is None:
                        reason = "UNKNOWN_PROPOSAL"
                    elif p["status"] != "PENDING":
                        reason = "PROPOSAL_NOT_PENDING"
                    elif d["state_fingerprint"] != p["state_fingerprint"] or d[
                        "state_fingerprint"
                    ] != fingerprint(asdict(state)):
                        reason = "STATE_MISMATCH"
                    elif decided <= _time(p["generated_at"]) or t <= _time(
                        p["generated_at"]
                    ):
                        reason = "DECISION_NOT_AFTER_PROPOSAL"
                    elif d["decision"] == "REJECT":
                        p["status"] = "REJECTED"
                        reason = "REJECTED"
                    else:
                        before = state_dict(state)
                        state = ResearchState(
                            apply_action(
                                state.position,
                                Action(p["suggested_action"], Decimal(1)),
                            ),
                            state.original_side,
                            t,
                            t,
                        )
                        p["status"] = "ACCEPTED"
                        reason = "ACCEPTED"
                        transitions.append(
                            dict(
                                decision_id=d["decision_id"],
                                proposal_id=p["proposal_id"],
                                known_at=t.isoformat(),
                                before=before,
                                after=state_dict(state),
                                record_kind=d["record_kind"],
                            )
                        )
            except (ValueError, TypeError, KeyError):
                reason = "INVALID_DECISION"
            processed.setdefault(d["decision_id"], fingerprint(d))
            outcomes.append(
                dict(
                    record=d,
                    reason=reason,
                    status=reason if reason in ("ACCEPTED", "REJECTED") else "INVALID",
                    confirmation_delay_seconds=str(
                        Decimal(str((t - _time(p["generated_at"])).total_seconds()))
                    )
                    if p
                    else None,
                )
            )
    cp = dict(
        version=VERSION,
        keybar_version=KEYBAR_VERSION,
        proposal_version=PROPOSAL_VERSION,
        as_of=as_of.isoformat(),
        input_prefix_hash=fingerprint([asdict(b) for b in visible]),
        initial_state=state_dict(initial_state),
        current_state=state_dict(state),
        pending_proposals=[p for p in proposals if p["status"] == "PENDING"],
        cursor=len(visible),
        decision_records=consumed,
        processed_decisions=[
            dict(
                decision_id=d.get("decision_id") if isinstance(d, dict) else None,
                content_hash=fingerprint(d),
            )
            for d in consumed
        ],
    )
    return dict(
        version=VERSION,
        evaluations=evaluations,
        proposals=proposals,
        decisions=outcomes,
        transitions=transitions,
        current_state=state_dict(state),
        checkpoint=cp,
        executable=False,
        fill=None,
        performance=None,
    )
