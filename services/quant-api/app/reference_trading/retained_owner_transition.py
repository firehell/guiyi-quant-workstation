"""One explicitly proved adjacent rank1 transition, never an owner substitution."""

from dataclasses import dataclass
from datetime import date, datetime

from app.reference_trading.original_conflict_warm_seed import require, _hash


@dataclass(frozen=True)
class Rank1OwnerTransition:
    contract: str
    owner_segment_id: str
    calculation_segment_id: str
    proof: dict


def prove_rank1_owner_transition(
    market,
    authority,
    identity,
    checkpoint,
    *,
    previous_day: date,
    trading_day: date,
    knowledge_at: datetime,
) -> Rank1OwnerTransition:
    code = "RETAINED_OWNER_TRANSITION_UNVERIFIED"
    require(
        identity.frequency == "60m"
        and previous_day < trading_day
        and market.previous_trading_day(identity.product, trading_day) == previous_day,
        code,
    )
    old = market.dominant_segment_for_day(identity.product, previous_day)
    new = market.dominant_segment_for_day(identity.product, trading_day)
    require(
        old.contract == checkpoint.physical_contract
        and old.contract != new.contract
        and old.end_trading_day == previous_day
        and new.start_trading_day == trading_day,
        code,
    )
    old_windows = market.session_windows(
        symbol=identity.product, trading_day=previous_day
    )
    new_windows = market.session_windows(
        symbol=identity.product, trading_day=trading_day
    )
    require(old_windows and new_windows, code)
    old_end = max(window.end for window in old_windows)
    new_start = min(window.start for window in new_windows)
    require(
        checkpoint.computed_through == old_end and old_end < new_start <= knowledge_at,
        code,
    )
    endpoints = market.expected_contract_replay_endpoints(
        symbol=identity.product,
        contract=old.contract,
        frequency="60m",
        trading_day=previous_day,
        cutoff=old_end,
        after=None,
        since=previous_day,
    )
    require(
        endpoints and endpoints[-1] == (checkpoint.computed_through, previous_day), code
    )
    require(
        authority.owner_segments(
            identity, old.contract, previous_day, checkpoint.computed_through
        )
        == (checkpoint.owner_segment_id, checkpoint.calculation_segment_id),
        code,
    )
    # Binding at the new Session start proves the new owner, not a guessed
    # contract chosen solely to satisfy an expected-endpoint query.
    owner, calculation = authority.owner_segments(
        identity, new.contract, trading_day, new_start
    )

    def wire(segment):
        return {
            key: str(getattr(segment, key))
            for key in ("symbol", "contract", "start_trading_day", "end_trading_day")
        }

    proof = {
        "version": "retained_rank1_owner_transition_v1",
        "previous_day": previous_day.isoformat(),
        "trading_day": trading_day.isoformat(),
        "old_rank1": wire(old),
        "new_rank1": wire(new),
        "old_terminal": old_end.isoformat(),
        "new_session_start": new_start.isoformat(),
        "old_owner": [
            checkpoint.physical_contract,
            checkpoint.owner_segment_id,
            checkpoint.calculation_segment_id,
        ],
        "new_owner": [new.contract, owner, calculation],
        "session_sha256": _hash(
            {
                "old": [(w.start, w.end) for w in old_windows],
                "new": [(w.start, w.end) for w in new_windows],
            }
        ),
        "old_endpoints_sha256": _hash(endpoints),
        "reset_policy": "native_seed_replay_state_on_rollover",
    }
    return Rank1OwnerTransition(new.contract, owner, calculation, proof)
