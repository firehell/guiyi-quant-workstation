"""Read-only explanation of an already evaluated account transition."""
from .subing_demand_policy import Facts, project

VERSION = 'subing_demand_explanation_v2'

def explain(*, state, regime, phase, pending_break, gross, streak, actions, opening_review=None):
    """Never mutates decisions. Preserve triggering facts and original obligations."""
    opening = next((a for a in actions if a.get('kind') in ('OPEN', 'ADD')), None)
    close = next((a for a in actions if a.get('kind') == 'CLOSE'), None)
    result = project(Facts(side=state['side'] or 'FLAT', regime=regime, phase='BAR_CLOSE' if opening_review else phase,
        pending_break=pending_break, gross_remaining=gross, nonpositive_range_days=streak,
        all_exit_required=bool(state['clear_reasons']), reduce_required=bool(state['exit_layers']),
        action_pending=bool(state['pending'])))
    kind, reason = result.kind, result.reason
    triggers = list(state['clear_reasons'])
    if close:
        kind = 'EXIT_OBLIGATION' if state['clear_reasons'] else 'REDUCE_OBLIGATION'
        triggers = list(close['reasons'])
    elif opening:
        kind = 'CHECK_ENTRY_ELIGIBILITY' if opening['kind'] == 'OPEN' else 'CHECK_ADD_ELIGIBILITY'
        reason = 'ORIGINAL_ENTRY_FACTS_READY' if opening['kind'] == 'OPEN' else 'FRESH_POSITION_AND_ORIGINAL_ADD_FACTS_READY'
    elif state['pending'] and state['pending']['kind']=='CLOSE':
        kind = 'EXIT_OBLIGATION' if state['clear_reasons'] else 'REDUCE_OBLIGATION'
        triggers = list(state['pending']['reasons'])
    if opening_review and opening_review['demand'] in ('EXIT_REQUIRED','EXIT_OBLIGATION'):
        triggers = list(dict.fromkeys([opening_review['reason'], *triggers]))
    if opening_review and opening_review['demand']=='EXIT_REQUIRED' and not state['clear_reasons'] and not close:
        kind='EXIT_REQUIRED'
    if triggers:
        reason=triggers[0]
    blocking=[r for a in actions if a.get('kind')=='REJECT' for r in a.get('reasons',[])]
    if not triggers and not opening and blocking:
        # Keep phase/environment priority while retaining exact technical failures.
        if reason=='ORIGINAL_ENTRY_FACTS_NOT_READY':reason=blocking[0]
    missing=[]
    if regime=='UNKNOWN':missing.append('ENVIRONMENT_FACTS_MISSING')
    if not state['technical_ready']:missing.append('TECHNICAL_FACTS_UNKNOWN')
    if not state['day_reconciled']:missing.append('RECONCILIATION_REQUIRED')
    wait = ('EXIT_EXECUTION' if triggers else
            'INTENT_EXECUTION' if state['pending'] else
            'NEXT_SESSION_OPEN_REVIEW' if phase=='DAY_END' else
            'BREAK_CONFIRMATION' if pending_break else
            'REQUIRED_FACTS' if missing else
            'FRESH_POSITION' if state['quantity'] else 'NEW_VALID_ENTRY')
    return dict(projection_version=VERSION, phase=phase, demand=kind, reason=reason,
        trigger_reasons=triggers, supporting_reasons=list(dict.fromkeys([reason,*triggers])),
        blocking_reasons=list(dict.fromkeys(blocking)), condition_gaps=missing, next_wait=wait)
