"""Attach versioned auxiliary hints without changing strategy actions."""
from decimal import Decimal


def with_attack_hints(replay):
    identity = replay.identity
    from dataclasses import replace
    from guiyi_quant.newow.oscillation_attack import calculate_oscillation_attack, FORMULA_VERSION
    from guiyi_quant.newow.product_contracts import StrategyHint
    groups = {}
    for frame in replay.frames:
        key = (frame.bar.bar.physical_contract, frame.bar.calculation_segment_id)
        groups.setdefault(key, []).append(frame)
    extra = {}
    for group in groups.values():
        values = calculate_oscillation_attack(tuple(f.bar.bar for f in group))
        for frame, value in zip(group, values):
            bar = frame.bar.bar
            if not bar.observation_eligible:
                continue
            hints = []
            for kind, enabled, anchor in (
                ('ZLGJ_BUY', value['buy'], bar.close),
                ('ZLGJ_SELL', value['sell'], bar.close),
                ('OSCILLATION_J', value['j_warning'], bar.high * Decimal('1.01'))):
                if enabled:
                    hints.append(StrategyHint(identity, bar.physical_contract, bar.segment_id,
                        bar.bar_end, bar.trading_day, kind, bar.bar_end, anchor,
                        source_marker_id=FORMULA_VERSION, calculation_segment_id=frame.bar.calculation_segment_id))
            extra[(bar.physical_contract, bar.segment_id, frame.bar.calculation_segment_id, bar.bar_end)] = tuple(hints)
    enriched = tuple(replace(f, hints=f.hints + extra.get((f.bar.bar.physical_contract, f.bar.bar.segment_id, f.bar.calculation_segment_id, f.bar.bar.bar_end), ())) for f in replay.frames)
    return replace(replay, frames=enriched, hints=tuple(h for f in enriched for h in f.hints))
