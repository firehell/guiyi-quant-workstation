"""Small display projection of an authenticated replay, never a strategy engine."""
from decimal import Decimal

from guiyi_quant.newow.product_auxiliary import calculate_auxiliary_component
from guiyi_quant.newow.main_rise import calculate_main_rise_series
from guiyi_quant.newow.subplots import calculate_zhaoyao_mirror

from guiyi_quant.newow.product_contracts import FeatureRuntimeStatus, MainState, TradeEligibility


def project_home_inputs(replay, anchor):
    """Strategy-independent inputs; callers share only an identical owner prefix."""
    control = calculate_auxiliary_component(
        replay.identity, tuple(frame.bar for frame in replay.frames if frame.bar.bar.bar_end <= anchor.bar.bar.bar_end),
        'main_force_control', as_of=anchor.bar.bar.bar_end,
    )
    return control, project_row_hints(replay, anchor, True)


def project_home_summary(replay, anchor, status, prices, shared_inputs=None):
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
    # Only the confirmed anchor event may override the display stage. Recent
    # history remains available for provenance, never as a fresh crossing.
    current = next((action for action in reversed(actions) if action.bar_end == bar.bar_end), None) if ready else None
    ma10 = dict(anchor.main_values).get('b') if replay.identity.strategy.value == 'trend' and ready else None
    control, row_hints = shared_inputs if shared_inputs is not None else project_home_inputs(replay, anchor)
    tail = control.segments[-1] if control.segments else None
    control_ready = ready and tail is not None and tail.status.status is FeatureRuntimeStatus.READY and tail.value is not None and tail.physical_contract == bar.physical_contract and tail.segment_id == anchor.bar.calculation_segment_id and tail.bar_ends[-1] == bar.bar_end
    return {
        'display_projection_version': 'newow_home_display_v1',
        'current_event': {'kind': current.kind.value, 'bar_end': current.bar_end, 'signal_id': current.signal_id} if current else None,
        'guard_ma10': ma10,
        'state': anchor.main_state.value if ready else None,
        'status': status.status.value, 'reason_code': status.reason_code,
        'bar_end': bar.bar_end, 'physical_contract': bar.physical_contract,
        'segment_id': bar.segment_id, 'calculation_segment_id': anchor.bar.calculation_segment_id,
        'source_identity': bar.source_identity,
        'reference_current': bar.close if ready else None,
        'target': target, 'absorb': absorb,
        'price_sources': {kind: {
            'raw': value.raw, 'display_value': value.display,
            'frequency': prices.frequency.value, 'as_of': prices.as_of,
            'bar_end': prices.anchor_bar_end, 'physical_contract': prices.physical_contract,
            'segment_id': prices.segment_id, 'calculation_segment_id': prices.calculation_segment_id,
            'input_sha256': prices.input_sha256, 'formula_version': prices.formula_version,
            'branch': 'chart_hhv10' if kind == 'target' else 'chart_llv10',
            'source_category': 'canonical_channel',
        } if ready and value.status.status is FeatureRuntimeStatus.READY else None
            for kind, value in [('target', prices.target), ('absorb', prices.absorb)]} if prices else None,
        'price_input_sha256': prices.input_sha256 if prices else None,
        'price_formula_version': prices.formula_version if prices else None,
        'reference_cost': entry.reference_price if entry else None,
        'entry_signal_id': entry.signal_id if entry else None,
        'target_space_percent': (target - bar.close) / bar.close * Decimal(100) if target is not None and bar.close > 0 else None,
        'absorb_space_percent': (absorb - bar.close) / bar.close * Decimal(100) if absorb is not None and bar.close > 0 else None,
        'main_force_control': {'status': 'ready' if control_ready else 'warming',
            'label': tail.value.current_status.value if control_ready else None,
            'formula_version': control.formula_version, 'bar_end': bar.bar_end,
            'physical_contract': bar.physical_contract, 'calculation_segment_id': anchor.bar.calculation_segment_id,
            'page_parity': True, 'executable': False},
        'row_hints': row_hints if ready else None,
        'recent_action': {'kind': latest.kind.value, 'bar_end': latest.bar_end, 'signal_id': latest.signal_id} if latest else None,
        'page_parity': True, 'executable': False,
    }


def project_home_performance(result):
    """Copy the ordinary page projection; never substitute ReferenceSummary PnL."""
    delivery = result.reference
    value = delivery.value
    page = (value.payload.get('page_performance') if hasattr(value, 'payload')
            else getattr(value, 'page_performance', None))
    ordinary = page.get('ordinary') if page else None
    if not ordinary or delivery.status is None:
        return {'status': 'unavailable', 'reason_code': 'NEWOW_PAGE_PERFORMANCE_UNAVAILABLE'}
    summary = ordinary['summary']
    return {'status': delivery.status.status.value,
        'version': page['version'], 'strategy': result.meta.identity.strategy.value,
        'frequency': result.meta.identity.frequency.value, 'as_of': result.meta.as_of,
        'input_sha256': page['input_sha256'], 'source_evidence_sha256': page['source_evidence_sha256'],
        'since': ordinary['trading_days'][0] if ordinary['trading_days'] else None,
        'through': ordinary['trading_days'][-1] if ordinary['trading_days'] else None,
        'cum_return_percent': summary['cumReturn'], 'trade_count': summary['tradeCount'],
        'page_parity': True, 'executable': False}


def project_row_hints(replay, anchor, ready):
    """Public home icon window: confirmation/action on the latest two D1 bars."""
    if not ready or replay.identity.frequency.value != '1d':
        return None
    bars = tuple(frame.bar.bar for frame in replay.frames
                 if frame.bar.calculation_segment_id == anchor.bar.calculation_segment_id
                 and frame.bar.bar.physical_contract == anchor.bar.bar.physical_contract
                 and frame.bar.bar.bar_end <= anchor.bar.bar.bar_end)
    if len(bars) < 20 or bars[-1].bar_end != anchor.bar.bar.bar_end:
        return None
    mirror = calculate_zhaoyao_mirror(bars)
    hints = []
    if mirror and mirror.confirmed_peak_events:
        peak, confirmed = mirror.confirmed_peak_events[-1]
        if len(bars) - confirmed <= 2:
            hints.append({'kind': 'caution', 'peak_day': bars[peak].trading_day,
                          'event_day': bars[confirmed].trading_day,
                          'formula_version': mirror.formula_version})
    series = calculate_main_rise_series(bars)
    event = project_home_j_hint(series)
    if event is not None and len(bars) - event <= 2:
        hints.append({'kind': 'reduce', 'event_day': bars[event].trading_day,
                      'j_value': str(series[event].j_value), 'reference_price': str(bars[event].high),
                      'formula_version': 'newow_home_j_hint_page_v1'})
    return {'status': 'ready', 'bar_end': bars[-1].bar_end,
            'physical_contract': bars[-1].physical_contract,
            'calculation_segment_id': anchor.bar.calculation_segment_id,
            'page_parity': True, 'executable': False, 'items': hints}


def project_home_j_hint(series):
    """Home calcMainRiseJ uses previous hint, not previous band CLEAR."""
    latest = None
    previous_hint = False
    for index in range(1, len(series)):
        prior, current = series[index - 1], series[index]
        hint = (prior.j_value is not None and current.j_value is not None
                and prior.j_value - 0.01 > current.j_value
                and current.j_value < prior.j_value
                and prior.state.previous_bdgd and not previous_hint)
        if hint:
            latest = index
        previous_hint = hint
    return latest
