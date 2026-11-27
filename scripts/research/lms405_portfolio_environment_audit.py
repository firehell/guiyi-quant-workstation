"""Compare archived author context with the unchanged short-window research context."""

import argparse
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
import re
from statistics import median

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_managed_portfolio import BASELINE, BASELINE_SHA256
from lms405_minute_recovery_context import study as study_minute_context
from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, DAYS, FIVE, LOCAL, input_sources
from lms405_portfolio_protection_gate import plan_rows
from lms405_protection_shape_audit import price_digest
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import ohlc, read_session_series
from lms405_reversal_stage_bounds import SPECS_SHA
from lms405_right_side_study import ONE, US
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded, sha

# Only normalize explicit descriptions in the existing article tables.
# Qualified cycle descriptions and the PVC chapter that mentions 5.0 are visible separately.
PLANS = {
    23: ("A5357264059367516", "A5357264793370945",
         ("RANGE", "RANGE_MIXED", "UP_CYCLE", "RANGE", "UP_CYCLE", "UP_PVC_CONTEXT", None, "DOWN", "RANGE")),
    26: ("A5358325549629506", "A5358325972992140",
         ("RANGE", "RANGE", "RANGE", "RANGE", "RANGE", "RANGE", None, "DOWN", "RANGE")),
    27: ("A5358686423089344", "A5358686695981271",
         ("RANGE", "DOWN", "RANGE", "RANGE", "UP_CYCLE", "RANGE", None, "DOWN", "RANGE")),
}
BACKUP = {"RU2701", "TA2701", "SH2701"}
MINUTE_CONTEXT = (Path("output/lms405-minute-recovery-context-20261126/replay-a.json"),
                  "4d4d3f6ec34603c4542bfb451cf860236e7ac1289cc76f61df6cd28bede7d48c")
LABEL_CUES = {"RANGE": ("盘整",), "RANGE_MIXED": ("盘整与循环交替",), "DOWN": ("空头趋势",),
              "UP_CYCLE": ("多循环", "多头循环"), "UP_PVC_CONTEXT": ("多趋势",), None: ("建模",)}
SHORT_TARGETS_BY_PLAN_DATE = {
    "I2701": (((654, "662.5"),), ((654, "662.5"),)),
    "FG2701": (((825, 825), (814, 821)), ((825, 825), (814, 821))),
    "RU2701": (((19320, 19420), (19220, 19290)), ((19320, 19420), (19220, 19290))),
    "SH2701": (((1543, 1543),), ((1506, 1520), (1498, 1498))),
}
TRANSFER_SOURCE_PAIRS = {
    22: (("A5356507058536457", "A5356507360788540"), ("A5356884629782554", "A5356884885635211")),
    23: (("A5356884629782554", "A5356884885635211"), ("A5357264059367516", "A5357264793370945")),
}
TRANSFER_SHORT_BANDS = {
    22: {
        "JM2701": (("1424.5", "1436.5"), ("1382.5", "1397.5"), ((1393, "1399.5"), ("1381.5", 1388),
                                                              ("1376.5", "1376.5"))),
        "FG2701": ((841, 852), (829, 836), ((850, 864), (834, 839))),
        "LH2701": ((10025, 10085), (9855, 9970), ((10150, 10220), (9940, 10045))),
        "SH2701": ((1684, 1695), (1610, 1632), ((1681, 1690), (1653, 1667))),
        "RU2701": ((19575, 19685), (19530, 19680), ((19555, 19610), (19430, 19495), (19320, 19420))),
    },
    23: {
        "FG2701": ((829, 836), (829, 836), ((825, 825), (814, 821))),
        "LH2701": ((9855, 9970), (9855, 9970), ((9725, 9725),)),
        "SH2701": ((1610, 1632), (1595, 1603), ((1543, 1543),)),
        "RU2701": ((19530, 19680), (19530, 19680), ((19320, 19420), (19220, 19290))),
    },
}
TRANSFER_EXCLUSIONS = {
    22: {
        "I2701": "PRIOR_NO_SHORT_PROTECTION_AND_NEXT_PROTECTION_TEXT_CONFLICT",
        "RB2701": "NO_EXPLICIT_SHORT_PROTECTION_IN_EITHER_PLAN",
        "SA2701": "PRIOR_NO_EXPLICIT_SHORT_PROTECTION",
        "OI2701": "NEXT_NO_EXPLICIT_SHORT_PROTECTION",
        "V2701": "NO_COMPARABLE_SHORT_PROTECTION",
        "TA2701": "PUBLIC_MODEL_PAUSED",
    },
    23: {
        "I2701": "PRIOR_PROTECTION_TEXT_CONFLICT",
        "RB2701": "NO_EXPLICIT_SHORT_PROTECTION_IN_EITHER_PLAN",
        "JM2701": "NEXT_ONLY_EXPLICIT_LONG_DEFENCE",
        "SA2701": "NEXT_NO_EXPLICIT_SHORT_PROTECTION",
        "OI2701": "NO_EXPLICIT_SHORT_PROTECTION_IN_EITHER_PLAN",
        "V2701": "NEXT_ONLY_EXPLICIT_LONG_DEFENCE",
        "TA2701": "PUBLIC_MODEL_PAUSED",
    },
}
TRANSFER_SCOPE = frozenset({"I2701", "RB2701", "JM2701", "FG2701", "SA2701", "OI2701", "V2701",
                            "LH2701", "TA2701", "SH2701", "RU2701"})
CHAPTER_ID = re.compile(r"(?:^|[。\n])\s*\|?(I|RB|JM|FG|SA|OI|V|LH|TA|SH|RU)(?:2701)?(?=[|\u4e00-\u9fff])")


def archive_case(index, source_id, session_date, contract, author_class):
    source = index[source_id]
    published = datetime.fromisoformat(source["published_at"]).astimezone(LOCAL)
    if published.date() != session_date or not time(15) < published.time() < time(21):
        raise ValueError("ENVIRONMENT_SOURCE_WINDOW_CHANGED")
    path = ARCHIVE.parent / source["archive_path"]
    raw = path.read_bytes()
    lines = [line for line in raw.decode().splitlines() if line.startswith(f"|{contract}|")]
    if len(lines) != 1:
        raise ValueError("ENVIRONMENT_SOURCE_ROW_CHANGED")
    label = lines[0].split("|")[2]
    if not any(cue in label for cue in LABEL_CUES[author_class]):
        raise ValueError("ENVIRONMENT_SOURCE_LABEL_CHANGED")
    return source | dict(archived_label=label, sha256=sha(raw))


def clocks(bars, session_date):
    day_close = datetime.combine(session_date, time(15), LOCAL)
    night_start = datetime.combine(session_date, time(21), LOCAL)
    close_index = next(i for i, bar in enumerate(bars) if bar.end == day_close)
    close = candidate.context(bars[:close_index + 1], close_index)
    if close is None:
        raise ValueError("DAY_CLOSE_CONTEXT_MISSING")
    night = [(i, bar) for i, bar in enumerate(bars) if night_start < bar.end <= night_start + 7 * FIVE]
    expected = [night_start + i * FIVE for i in range(1, 8)]
    if [bar.end for _, bar in night] != expected:
        raise ValueError("NIGHT_CONTEXT_WINDOW_INCOMPLETE")
    contexts = []
    for i, bar in night[1:]:
        context = candidate.context(bars[:i + 1], i)
        if context is None or context != candidate.context(bars, i):
            raise ValueError("ENVIRONMENT_PREFIX_DIVERGED")
        contexts.append(dict(clock=bar.end, environment=context["environment"],
                             input_first=context["window_start"], input_last=context["window_end"]))
    return dict(day_close=close, opening_clocks=contexts,
                opening_flips=sum(a["environment"] != b["environment"] for a, b in zip(contexts, contexts[1:])))


def summarize(rows):
    clear = [r for r in rows if r["author_class"] in ("RANGE", "DOWN")]
    coarse = [r for r in rows if r["author_class"] is not None]
    for row in coarse:
        label = row["author_class"].split("_")[0]
        sequence = [x["environment"] for x in row["opening_clocks"]]
        row.update(coarse_class=label, close_agrees=row["day_close"]["environment"] == label,
                   first_open_agrees=sequence[0] == label, all_open_agree=all(state == label for state in sequence))
    columns = ("close_agrees", "first_open_agrees", "all_open_agree")
    return {name: dict(count=len(group), labels=dict(Counter(r["coarse_class"] for r in group)),
                       **{key: sum(r[key] for r in group) for key in columns},
                       opening_flips=sum(r["opening_flips"] > 0 for r in group))
            for name, group in (("clear_wording", clear), ("include_qualified_contexts", coarse))}


def context_before(bars, cutoff):
    prefix = [bar for bar in bars if bar.end + US < cutoff]
    return candidate.context_from_window(prefix[-6:])


def resistance_context_before(bars, cutoff):
    """Use the most recent confirmed high and its upper wick as a research band."""
    window = [bar for bar in bars if bar.end + US < cutoff][-6:]
    if len(window) != 6:
        return None
    for i in range(len(window) - 2, 0, -1):
        left, pivot, right = window[i - 1:i + 2]
        if not (left.end == pivot.start and pivot.end == right.start and pivot.high > max(left.high, right.high)):
            continue
        lower, upper = max(pivot.open, pivot.close), pivot.high
        if lower >= upper or any(bar.close >= upper for bar in window[i + 1:]):
            return None
        return dict(lower=lower, upper=upper, valid=True, window_end=window[-1].end,
                    pivot_end=pivot.end, confirmed_at=right.end + US,
                    context_hash=sha(encoded(price_digest((left, pivot, right))).encode()))
    return None


def known_and(left, right):
    if left is False or right is False:
        return False
    return None if left is None or right is None else True


def opening_alternatives(rows):
    clear = [row for row in rows if row["author_class"] in ("RANGE", "DOWN")]
    totals = {mode: Counter() for mode in ("ROLLING", "HOLD_DAY_CLOSE", "TWO_LOCAL_VOTES")}
    for row in clear:
        rolling = [slot["environment"] for slot in row["opening_clocks"]]
        parked = row["day_close"]["environment"]
        elected, previous = parked, None
        votes = []
        for state in rolling:
            if state == previous:
                elected = state
            votes.append(elected)
            previous = state
        for name, states in zip(totals, (rolling, [parked] * len(rolling), votes), strict=True):
            expected = row["author_class"]
            totals[name].update({
                "cases": 1, "first_agrees": int(states[0] == expected),
                "all_agree": int(all(value == expected for value in states)),
                "cases_with_flip": int(len(set(states)) > 1),
            })
    return totals


def minute_gate_comparison(session, market):
    frozen = verified_json(*MINUTE_CONTEXT)
    local = study_minute_context(session, market)
    if encoded(local) != encoded(frozen):
        raise ValueError("ENVIRONMENT_MINUTE_CONTEXT_CHANGED")
    result = []
    for contract, row in local["cases"].items():
        five = read_window(session, market, contract, date.fromisoformat(row["trading_day"]))[5]
        for item in row["candidates"]:
            contexts = item["context"]
            at_shape = contexts["before_shape"]
            shape, confirmation = (contexts[key]["known_before"] for key in ("before_shape", "before_confirmation"))
            shape_env, confirm_env = (context_before(five, cut) for cut in (shape, confirmation))
            direction = "UP" if item["proposal"]["action"] == "UNLOCK_LONG" else "DOWN"
            aligned = shape_env["environment"] == direction if shape_env else None
            atr_context = at_shape["atr_context"]
            atr = atr_context["exceeds_atr14"]["trading_day_range"] if atr_context else None
            contraction = at_shape["contraction"]
            day = contraction["trading_day"]
            narrowed = day["latest_narrower_than_opening"] if day else None
            segment = contraction["continuous_session"]
            local_narrowed = segment["latest_narrower_than_opening"] if segment else None
            result.append(dict(
                contract=contract, proposal=item["proposal"], shape_context=shape_env,
                pre_confirmation_context=confirm_env, atr_above_prior14=atr,
                session_narrower_than_opening=local_narrowed, day_narrower_than_opening=narrowed,
                same_direction_environment=aligned,
                known_negative_author_case=contract == "V2609",
                hypothetical_admission=dict(
                    direction_context_only=aligned, atr_only=atr, day_narrowing_only=narrowed,
                    direction_context_and_atr=known_and(aligned, atr),
                    direction_context_and_day_narrowing=known_and(aligned, narrowed),
                    direction_context_and_segment_narrowing=known_and(aligned, local_narrowed),
                ),
            ))
    return result


def endpoint_comparison(context, declared, tick):
    if not context or not context["valid"]:
        return None
    lower, upper = (Decimal(context[k]) for k in ("lower", "upper"))
    matched = declared.role == "PROTECTION"
    return dict(
        lower=lower, upper=upper, overlap=(lower <= declared.upper and declared.lower <= upper) if matched else None,
        lower_error_ticks=(lower - declared.lower) / tick if matched else None,
        upper_error_ticks=(upper - declared.upper) / tick if matched else None,
        context_hash=context["context_hash"], known_window_end=context["window_end"],
    ) | {key: context[key] for key in ("pivot_end", "confirmed_at") if key in context}


def range_revision_audit(bars, session_date, declared, tick, *, resolve=context_before):
    start = datetime.combine(session_date, time(21), LOCAL)
    if not max(declared.known_at, declared.effective_after) < start:
        raise ValueError("ENVIRONMENT_RANGE_PLAN_NOT_KNOWN_AT_OPEN")
    if declared.side != "SHORT":
        raise ValueError("ENVIRONMENT_RANGE_PLAN_NOT_SHORT")
    frozen = resolve(bars, start)
    first = endpoint_comparison(frozen, declared, tick)
    failure_at, changes = None, 0
    updates = []
    previous = None if first is None else (first["lower"], first["upper"])
    expected_closes = [start + i * FIVE for i in range(1, 8)]
    night = [bar for bar in bars if start < bar.end <= expected_closes[-1]]
    if [bar.end for bar in night] != expected_closes:
        raise ValueError("ENVIRONMENT_RANGE_WINDOW_INCOMPLETE")
    for bar in night:
        at = bar.end + 2 * US
        ready = resolve(bars, at)
        prefix = [prior for prior in bars if prior.end + US < at]
        if ready != resolve(prefix, at):
            raise ValueError("ENVIRONMENT_RANGE_PREFIX_DIVERGED")
        rolling = endpoint_comparison(ready, declared, tick)
        current = None if rolling is None else (rolling["lower"], rolling["upper"])
        changes += current != previous
        previous = current
        if frozen and frozen["valid"] and failure_at is None and bar.close >= Decimal(frozen["upper"]):
            # Study same-side short risk boundary on a frozen envelope; never advances an account.
            failure_at = bar.end + US
        updates.append(dict(at=at, rolling=rolling, frozen_valid_for_short=failure_at is None
                            if frozen and frozen["valid"] else None))
    return dict(
        contract=declared.contract, session_date=session_date, declared_role=declared.role,
        source=declared.source, revision=declared.revision, declared_bounds=[declared.lower, declared.upper],
        declared_known_at=declared.known_at,
        opening_at=start, frozen_at_open=first, rolling_updates=changes, checkpoints=updates,
        frozen_short_boundary_invalidated_at=failure_at,
    )


def range_summary(rows):
    generated = [row for row in rows if row["frozen_at_open"] is not None]
    compared = [row for row in generated if row["frozen_at_open"]["overlap"] is not None]
    return dict(
        generated_opening_ranges=len(generated), paired_author_bands=len(compared),
        unavailable_pairings=len(rows) - len(compared),
        overlap_at_open=sum(row["frozen_at_open"]["overlap"] for row in compared),
        exact_at_open=sum(row["frozen_at_open"]["lower_error_ticks"] == row["frozen_at_open"]["upper_error_ticks"] == 0
                          for row in compared),
        rolling_changes=sum(row["rolling_updates"] for row in generated),
        frozen_short_boundary_invalidations=sum(row["frozen_short_boundary_invalidated_at"] is not None
                                                for row in generated),
    )


def paired_band_summary(baseline, alternatives):
    pairs = [(a["frozen_at_open"], b["frozen_at_open"]) for a, b in zip(baseline, alternatives, strict=True)
             if a["declared_role"] == "PROTECTION" and a["frozen_at_open"] and b["frozen_at_open"]]
    result = {}
    for i, name in enumerate(("baseline", "resistance_pivot")):
        rows = [pair[i] for pair in pairs]
        result[name] = dict(
            overlaps=sum(row["overlap"] for row in rows),
            exact_matches=sum(row["lower_error_ticks"] == row["upper_error_ticks"] == 0 for row in rows),
            median_abs_lower_ticks=median(abs(row["lower_error_ticks"]) for row in rows) if rows else None,
            median_abs_upper_ticks=median(abs(row["upper_error_ticks"]) for row in rows) if rows else None,
        )
    return dict(common_pairs=len(pairs), **result)


def short_target_progress(minutes, cutoff, lower, upper):
    usable = [bar for bar in minutes if bar.bar_end + US < cutoff]
    return {label: {
        "first_reach": next((bar.bar_end for bar in usable if bar.low <= edge), None),
        "first_contact": next((bar.bar_end for bar in usable if bar.low <= edge <= bar.high), None),
        "first_close_below": next((bar.bar_end for bar in usable if bar.close < edge), None),
    } for label, edge in (("near", upper), ("far", lower))}


def audited_target_progress(bars, cutoff, bands, chapter):
    progress = []
    for lo, hi in bands:
        if (str(lo) if lo == hi else f"{lo}-{hi}") not in chapter:
            raise ValueError("PROTECTION_REVISION_TARGET_TEXT_CHANGED")
        lower, upper = Decimal(str(lo)), Decimal(str(hi))
        record = short_target_progress(bars, cutoff, lower, upper)
        times = {clock + US for edge in record.values() for clock in edge.values() if clock is not None}
        for cut in times | {clock + US for clock in times}:
            prefix = [bar for bar in bars if bar.bar_end + US < cut]
            if short_target_progress(prefix, cut, lower, upper) != short_target_progress(bars, cut, lower, upper):
                raise ValueError("PROTECTION_REVISION_TARGET_PREFIX_CHANGED")
        progress.append(dict(lower=lower, upper=upper, events=record))
    return progress


def protection_revision_progress(session, market, index):
    cases = []
    days = DAYS[1:3]
    observed_ids = {plan_id for plan in PLANS.values() for plan_id in plan[:2]}
    for contract, targets in SHORT_TARGETS_BY_PLAN_DATE.items():
        updates, _, sources = plan_rows(index, contract)
        known_plans = [row for row in updates if row.role == "PROTECTION" and row.revision in observed_ids]
        if len(known_plans) != 3:
            raise ValueError("PROTECTION_REVISION_PLAN_COVERAGE_CHANGED")
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, days)
        for day, bands, prior, next_plan in zip(days, targets, known_plans[:-1], known_plans[1:], strict=True):
            bars = [bar for bar in raw if bar.trading_day == day]
            if not bars or not prior.known_at < bars[0].bar_end - ONE or not (
                bars[-1].bar_end + US < next_plan.known_at
            ):
                raise ValueError("PROTECTION_REVISION_KNOWLEDGE_WINDOW_CHANGED")
            original = ARCHIVE.parent / sources[prior.revision]["archive_path"]
            chapter, = [line for line in original.read_text(encoding="utf-8").splitlines()
                        if line.startswith(f"|{contract}|")]
            chapter = chapter.replace("–", "-").replace("—", "-")
            progress = audited_target_progress(bars, next_plan.known_at, bands, chapter)
            cases.append(dict(
                contract=contract, trading_day=day, prior=sources[prior.revision], next_plan=sources[next_plan.revision],
                prior_protection=(prior.lower, prior.upper), next_protection=(next_plan.lower, next_plan.upper),
                published_band_changed=(prior.lower, prior.upper) != (next_plan.lower, next_plan.upper),
                market_count=len(bars), market_sha256=sha(encoded([
                    (bar.bar_end, *ohlc(bar)) for bar in bars
                ]).encode()), market_low=min(bar.low for bar in bars), target_progress=progress,
            ))
    return dict(cases=cases, gate_diagnostics=revision_gate_diagnostics(cases),
                historical_source_revisions_verified=False, development_evidence_only=True,
                admitted_author_action_samples=0)


def revision_gate_diagnostics(cases):
    gates = {}
    for name, select, field in (
        ("FIRST_NEAR_REACH", lambda bands: bands[:1], ("near", "first_reach")),
        ("FIRST_FAR_REACH", lambda bands: bands[:1], ("far", "first_reach")),
        ("FIRST_FAR_STRICT_CLOSE", lambda bands: bands[:1], ("far", "first_close_below")),
        ("ALL_DECLARED_FAR_REACH", lambda bands: bands, ("far", "first_reach")),
        ("ALL_DECLARED_FAR_STRICT_CLOSE", lambda bands: bands, ("far", "first_close_below")),
    ):
        outcomes = Counter()
        for case in cases:
            predicts_update = all(band["events"][field[0]][field[1]] is not None
                                  for band in select(case["target_progress"]))
            outcomes[("predicts_change" if predicts_update else "predicts_keep") + (
                "_changed" if case["published_band_changed"] else "_kept"
            )] += 1
        gates[name] = dict(outcomes)
    return gates


def archived_chapter(path, contract):
    body = path.read_text(encoding="utf-8").partition("## 内容记录")[2].replace("–", "-").replace("—", "-")
    entries = list(CHAPTER_ID.finditer(body))
    for current, following in zip(entries, entries[1:] + [None], strict=True):
        if current.group(1) == contract[:-4]:
            return body[current.end():(following.start() if following else len(body))]
    raise ValueError("PROTECTION_TRANSFER_CHAPTER_MISSING")


def protection_revision_transfer(session, market, index):
    cases, exclusions = [], []
    for day, pair in TRANSFER_SOURCE_PAIRS.items():
        specs, omitted = TRANSFER_SHORT_BANDS[day], TRANSFER_EXCLUSIONS[day]
        if specs.keys() & omitted.keys() or specs.keys() | omitted.keys() != TRANSFER_SCOPE:
            raise ValueError("PROTECTION_TRANSFER_SCOPE_CHANGED")
        trading_day = date(2026, 10, day)
        for contract in sorted(TRANSFER_SCOPE):
            side = 1 if contract in BACKUP | {"LH2701"} else 0
            prior, latest = (load_source(index, ids[side]) for ids in pair)
            identity = dict(contract=contract, trading_day=trading_day, prior=prior, next_plan=latest)
            if contract in omitted:
                exclusions.append(identity | {"reason": omitted[contract]})
                continue
            old_band, new_band, targets = specs[contract]
            old_chapter = archived_chapter(ARCHIVE.parent / prior["archive_path"], contract)
            new_chapter = archived_chapter(ARCHIVE.parent / latest["archive_path"], contract)
            if ("-".join(map(str, old_band)) not in old_chapter
                    or "-".join(map(str, new_band)) not in new_chapter):
                raise ValueError(f"PROTECTION_TRANSFER_BAND_TEXT_CHANGED:{contract}:{day}")
            prior_at, latest_at = (datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE
                                   for source in (prior, latest))
            bars = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (trading_day,))
            if not bars or not prior_at < bars[0].bar_end - ONE or not bars[-1].bar_end + US < latest_at:
                raise ValueError("PROTECTION_TRANSFER_KNOWLEDGE_WINDOW_CHANGED")
            progress = audited_target_progress(bars, latest_at, targets, old_chapter)
            cases.append(identity | dict(
                prior_protection=old_band, next_protection=new_band, published_band_changed=old_band != new_band,
                first_plan_known_after=prior_at, next_plan_known_after=latest_at, market_count=len(bars),
                market_low=min(bar.low for bar in bars), market_sha256=sha(encoded([
                    (bar.bar_end, *ohlc(bar)) for bar in bars
                ]).encode()), target_progress=progress,
            ))
    return dict(cases=cases, exclusions=exclusions, gate_diagnostics=revision_gate_diagnostics(cases),
                historical_source_revisions_verified=False, previously_read_archive=True,
                candidate_development_dates_excluded=True, admitted_author_action_samples=0)


def study(session, market, *, compare_admission=False, compare_ranges=False, compare_resistance=False,
          compare_revisions=False, transfer_revisions=False):
    reference = verified_json(BASELINE, BASELINE_SHA256)
    index = input_sources()
    rows = []
    ranges, resistance = [], []
    compare_ranges = compare_ranges or compare_resistance
    specs = load_specs(verified_json(SPECS, SPECS_SHA)) if compare_ranges else {}
    for number, contract in enumerate(CONTRACTS):
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        bars = [Bar(contract, bar.bar_end, *ohlc(bar), start=bar.bar_end - FIVE) for bar in raw]
        digest = sha(encoded(price_digest(bars)).encode())
        if digest != reference["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("ENVIRONMENT_FROZEN_MARKET_CHANGED")
        updates = {item.revision: item for item in plan_rows(index, contract)[0]} if compare_ranges else {}
        for session_date in DAYS[:-1]:
            main, backup, labels = PLANS[session_date.day]
            source_id = backup if contract in BACKUP else main
            author_class = labels[number]
            row = dict(contract=contract, author_class=author_class, source_id=source_id,
                       session_date=session_date, market_sha256=digest,
                       source=archive_case(index, source_id, session_date, contract, author_class))
            rows.append(row | clocks(bars, session_date))
            if compare_ranges:
                ranges.append(range_revision_audit(bars, session_date, updates[source_id], specs[contract]["tick"]))
            if compare_resistance:
                resistance.append(range_revision_audit(bars, session_date, updates[source_id], specs[contract]["tick"],
                                                       resolve=resistance_context_before))
    extra = {}
    if compare_admission:
        extra["admission_comparison"] = dict(
            opening_alternatives=opening_alternatives(rows),
            minute_recovery_candidates=minute_gate_comparison(session, market),
            minute_context_sha256=MINUTE_CONTEXT[1], actual_author_timeframe_labels=0,
        )
    if compare_ranges:
        extra["generated_range_comparison"] = dict(
            version="lms405-generated-range-comparison-v1", summary=range_summary(ranges), cases=ranges,
            known_price_window="LAST_SIX_COMPLETED_FIVES", generated_role="RESEARCH_PRICE_RANGE",
            frozen_short_invalidation="FIRST_COMPLETED_CLOSE_AT_OR_ABOVE_FROZEN_UPPER",
        )
    if compare_resistance:
        extra["resistance_pivot_comparison"] = dict(
            version="lms405-resistance-pivot-protection-band-v1", cases=resistance,
            summary=range_summary(resistance), common_opening_comparison=paired_band_summary(ranges, resistance),
            known_price_window="LAST_SIX_COMPLETED_FIVES", generated_role="SHORT_PROTECTION_RESEARCH_ONLY",
            rule="LATEST_STRICT_CONTIGUOUS_HIGH_PIVOT_UPPER_WICK",
        )
    if compare_revisions:
        extra["protection_revision_progress"] = protection_revision_progress(session, market, index)
    if transfer_revisions:
        extra["protection_revision_transfer"] = protection_revision_transfer(session, market, index)
    return dict(version="lms405-portfolio-environment-audit-v1", label_comparison=summarize(rows), cases=rows,
                rule_hash=candidate.RULE_HASH, frozen_baseline_sha256=BASELINE_SHA256,
                comparison_role="ARCHIVED_WORDING_VERSUS_RESEARCH_CLOCKS_ONLY",
                admitted_author_action_samples=0, author_action_matches=None, executable=False, fills=None, pnl=None,
                **extra)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare-admission", action="store_true")
    parser.add_argument("--compare-generated-ranges", action="store_true")
    parser.add_argument("--compare-resistance-pivots", action="store_true")
    parser.add_argument("--compare-protection-revisions", action="store_true")
    parser.add_argument("--transfer-protection-revisions", action="store_true")
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), compare_admission=args.compare_admission,
                           compare_ranges=args.compare_generated_ranges, compare_resistance=args.compare_resistance_pivots,
                           compare_revisions=args.compare_protection_revisions,
                           transfer_revisions=args.transfer_protection_revisions)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError, StopIteration):
        parser.exit(2, "ENVIRONMENT_AUDIT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
