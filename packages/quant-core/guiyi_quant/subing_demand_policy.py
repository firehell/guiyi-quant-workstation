"""Pure offline demand projection, not orders or a replacement strategy.

Caller must supply confirmed environment, trusted gross remaining-position PnL,
validated consecutive range-day count and authoritative session phase. This
module does not derive those facts from raw bars or the mixed swing envelope.
"""
from dataclasses import dataclass
from decimal import Decimal as D

VERSION='subing_demand_policy_candidate_v1'
REGIMES={'RANGE','TREND_UP','TREND_DOWN','UNKNOWN'}

@dataclass(frozen=True)
class Facts:
    side: str
    regime: str
    phase: str='BAR_CLOSE'
    pending_break: str | None=None
    gross_remaining: D | None=None
    nonpositive_range_days: int | None=None
    data_ready: bool=True
    execution_ready: bool=False
    first_entry_ready: bool=False
    add_ready: bool=False
    all_exit_required: bool=False
    reduce_required: bool=False
    action_pending: bool=False

@dataclass(frozen=True)
class Demand:
    kind: str
    reason: str
    execution: str='NOT_APPLICABLE'
    # No quantity, price or fill claims. This is eligibility/management intent.


def project(f):
    if f.side not in ('FLAT','LONG','SHORT') or f.regime not in REGIMES:
        raise ValueError('IDENTITY_INVALID')
    if f.phase not in ('BAR_CLOSE','DAY_END','NEXT_OPEN_AFTER_DAY_END') or f.pending_break not in (None,'UP','DOWN'):
        raise ValueError('PHASE_INVALID')
    if f.gross_remaining is not None and (not isinstance(f.gross_remaining,D) or not f.gross_remaining.is_finite()):
        raise ValueError('GROSS_PNL_INVALID')
    if f.nonpositive_range_days is not None and (type(f.nonpositive_range_days) is not int or f.nonpositive_range_days<0):
        raise ValueError('DAY_COUNT_INVALID')
    for name in ('data_ready','execution_ready','first_entry_ready','add_ready','all_exit_required','reduce_required','action_pending'):
        if type(getattr(f,name)) is not bool:raise ValueError('BOOLEAN_REQUIRED')
    execution='AWAIT_LATER_EXECUTION' if f.execution_ready else 'EXECUTION_FACTS_MISSING'
    if f.all_exit_required:
        return Demand('EXIT_OBLIGATION','EXISTING_FULL_EXIT',execution)
    # A current full-exit condition outranks an in-flight non-exit action. This
    # projector creates no new order and cannot cancel or acknowledge an action.
    open_review_reason=None
    if f.side!='FLAT' and f.phase=='NEXT_OPEN_AFTER_DAY_END' and f.regime=='RANGE':
        if not f.data_ready or f.gross_remaining is None:
            open_review_reason='GROSS_PNL_UNAVAILABLE'
        elif f.gross_remaining<0:
            return Demand('EXIT_REQUIRED','RANGE_OPEN_GROSS_LOSS',execution)
        elif f.gross_remaining==0:
            if f.nonpositive_range_days is None:
                open_review_reason='RANGE_DAY_COUNT_UNAVAILABLE'
            elif f.nonpositive_range_days>=3:
                return Demand('EXIT_REQUIRED','RANGE_THREE_NONPOSITIVE_DAYS',execution)
    if f.reduce_required:
        return Demand('REDUCE_OBLIGATION','EXISTING_REDUCTION',execution)
    if open_review_reason:
        return Demand('REVIEW_REQUIRED',open_review_reason)
    if f.action_pending:
        return Demand('MANAGE_PENDING','NO_DUPLICATE_ACTION')
    if not f.data_ready or f.regime=='UNKNOWN':
        return Demand('WAIT' if f.side=='FLAT' else 'HOLD_NO_ADD','REQUIRED_FACTS_UNAVAILABLE')
    if f.phase=='DAY_END':
        return Demand('WAIT' if f.side=='FLAT' else 'RECORD_ONLY','DAY_END_NO_NEW_EXPOSURE')
    if f.pending_break:
        return Demand('WAIT_CONFIRMATION' if f.side=='FLAT' else 'HOLD_NO_ADD','BREAK_'+f.pending_break+'_PENDING')
    if f.side=='FLAT':
        if f.regime=='RANGE':return Demand('WAIT','CONFIRMED_RANGE_NO_FIRST_ENTRY')
        if f.first_entry_ready:return Demand('CHECK_ENTRY_ELIGIBILITY','ORIGINAL_ENTRY_FACTS_READY')
        return Demand('WAIT','ORIGINAL_ENTRY_FACTS_NOT_READY')
    same=(f.side=='LONG' and f.regime=='TREND_UP') or (f.side=='SHORT' and f.regime=='TREND_DOWN')
    if same and f.add_ready:return Demand('CHECK_ADD_ELIGIBILITY','FRESH_POSITION_AND_ORIGINAL_ADD_FACTS_READY')
    return Demand('HOLD' if same else 'HOLD_NO_ADD','WAIT_FRESH_POSITION' if same else 'REGIME_DISALLOWS_ADD')
