"""Small display projection of an authenticated replay, never a strategy engine."""
from decimal import Decimal

from guiyi_quant.newow.product_contracts import FeatureRuntimeStatus, MainState, TradeEligibility


def project_home_summary(replay, anchor, status, prices):
    if anchor is None:
        return None
    bar = anchor.bar.bar
    ready = status.status is FeatureRuntimeStatus.READY
    actions = [action for action in replay.actions
               if action.bar_end <= bar.bar_end
               and action.physical_contract == bar.physical_contract
               and action.segment_id == bar.segment_id
               and action.calculation_segment_id == anchor.bar.calculation_segment_id
               and action.trade_eligibility is TradeEligibility.ELIGIBLE]
    latest = actions[-1] if actions else None
    entry = latest if ready and anchor.main_state in {MainState.BUILD, MainState.HOLD} and latest and latest.kind.value == 'BUILD' else None
    target = prices.target.raw if ready and prices else None
    absorb = prices.absorb.raw if ready and prices else None
    return {
        'state': anchor.main_state.value if ready else None,
        'status': status.status.value, 'reason_code': status.reason_code,
        'bar_end': bar.bar_end, 'physical_contract': bar.physical_contract,
        'segment_id': bar.segment_id, 'calculation_segment_id': anchor.bar.calculation_segment_id,
        'source_identity': bar.source_identity,
        'reference_current': bar.close if ready else None,
        'target': target, 'absorb': absorb,
        'price_formula_version': prices.formula_version if prices else None,
        'reference_cost': entry.reference_price if entry else None,
        'entry_signal_id': entry.signal_id if entry else None,
        'target_space_percent': (target - bar.close) / bar.close * Decimal(100) if target is not None and bar.close > 0 else None,
        'recent_action': {'kind': latest.kind.value, 'bar_end': latest.bar_end, 'signal_id': latest.signal_id} if latest else None,
        'page_parity': True, 'executable': False,
    }
