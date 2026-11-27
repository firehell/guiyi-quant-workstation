"""Check cross-contract quote compatibility and conditional JM M-lot continuity."""

import argparse
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from lms405_counter_m_continuation_study import DAY, EARLY, first_rebuilt_envelope
from lms405_jm_early_counter_m_window import LEGS, price_window
from lms405_jm_m_leg_handoff import CONTRACT, LATER
from lms405_plan_driven_replay import local_market_case
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import digest
from lms405_sh_protection_replacement import compatible_counts
from lms_near405_replay import encoded, sha

LOCAL = ZoneInfo("Asia/Shanghai")
RUBBER = (Path("output/lms405-rubber-leg-transition-20261125/final.json"),
          "b73fbed1e6052c56e98fe232906b561408159895d069d63edfcbf06b26943541")


def target_confirmation_window(bars, quotes, target, pre_target, *, tick, lots, total, close_quote):
    reversal = datetime.combine(DAY, time(10, 48), LOCAL)  # Frozen 5m shape / 1m confirmation.
    contact_bar_end = target - US
    in_window = {}
    for quote in quotes:
        if not target < quote < reversal:
            continue
        strict = price_window(bars, after=target, through=quote - ONE, tick=tick)
        wide = tick_bounds([bar for bar in bars if contact_bar_end <= bar.end <= quote], tick)
        in_window[quote.isoformat()] = {
            name: {"post_target_price_ticks": prices, "minimum_pre_target_lots": {
                gate: min(earlier_lot_counts(prior, prices, lots, total)) for gate, prior in pre_target.items()
            }}
            for name, prices in (("strict", strict), ("with_boundary_minutes", wide))
        }
    first_full = first_rebuilt_envelope(bars, after=target, cutoff=close_quote, target_ticks=total,
                                       lots=lots, tick=tick)
    return dict(contract=CONTRACT, displayed_lots=lots, displayed_total_ticks=list(total),
                target_proxy_known_at=target, research_reversal_bar_end=reversal,
                single_row_quote_cases=in_window, all_row_quote_assumption_used=False,
                first_whole_leg_price_known_at=first_full, earlier_opening_average_required=False,
                author_position_before_target=None, author_position_between_target_and_confirmation=None,
                author_action_samples=0, author_match_rate=None, executable=False, fills=None)


def study(session, market, *, between_target_and_confirmation=False):
    photo = verified_json(PHOTO, PHOTO_SHA)["photos"][LATER]
    rubber = verified_json(*RUBBER)
    image = rubber["source_images"][LATER]
    if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
        raise ValueError("JM_M_PHOTO_ATTACHMENT_CHANGED")

    matched = {product: [datetime.fromisoformat(value) for value in record["contains"]]
               for product, record in photo["per_symbol"].items()}
    day_open = datetime.combine(DAY, time(9), LOCAL)
    matched["ru"] = [t for t in (datetime.fromisoformat(row["end"]) for row in rubber["later_mark_compatible"])
                     if t > day_open]
    if set(matched) != {"fg", "v", "oi", "jm", "j", "rb", "sh", "i", "ru"} or not all(matched.values()):
        raise ValueError("JM_M_QUOTE_ROWS_INCOMPLETE")
    distances = {anchor: {product: min(abs(t - anchor) for t in times) // ONE
                          for product, times in matched.items()} for anchor in matched["jm"]}
    anchors = {width: [t for t, row in distances.items() if max(row.values()) <= width]
               for width in (0, 1, 2, 3, 5)}

    early = verified_json(*EARLY)
    earlier_leg = verified_json(*LEGS)["visible"][LATER]["legs"]["long"]
    lots = early["displayed_long_lots"]
    if earlier_leg["quantity"] != lots or earlier_leg["opening_average"] != "1415.03":
        raise ValueError("JM_M_PHOTO_POSITION_CHANGED")
    tick = Decimal(early["tick_size"])
    total = range(early["ending_sum_ticks"][0], early["ending_sum_ticks"][-1] + 1)
    bars = read_window(session, market, CONTRACT, DAY)[1]
    if early["inputs"]["1"] != {"count": len(bars), "sha256": digest(bars)}:
        raise ValueError("JM_M_PHOTO_MARKET_CHANGED")
    gates = {name: datetime.fromisoformat(row["known_at"]) for name, row in early["gates"].items()}
    target = gates.pop("late_extreme_far_price_proxy")
    # The four earlier entry hypotheses were tested before choosing cross-row quote tolerances.
    pre_target = {name: price_window(bars, after=gate, through=target - ONE, tick=tick)
                  for name, gate in gates.items()}
    pre_target["entire_pre_target_day"] = tick_bounds([bar for bar in bars if bar.end < target - US], tick)
    close_quote = datetime.fromisoformat(early["close_quote"])
    if between_target_and_confirmation:
        return target_confirmation_window(bars, matched["jm"], target, pre_target,
                                          tick=tick, lots=lots, total=total, close_quote=close_quote)

    bounds = {}
    # Completed-bar ends are only quote compatibility labels. The wide scope includes
    # the whole quote minute and the minute starting at the decision bar's end.
    for quote in (*anchors[2], close_quote):
        bounds[quote.isoformat()] = {}
        for label in ("10:38", "10:48", "10:57", "14:19"):
            decision_end = datetime.combine(DAY, time.fromisoformat(label), LOCAL)
            scopes = {
                "strict": price_window(bars, after=decision_end, through=quote - ONE, tick=tick),
                "with_boundary_minutes": tick_bounds([b for b in bars if decision_end < b.end <= quote], tick),
            }
            bounds[quote.isoformat()][label] = {
                name: {gate: min(row[0] for row in compatible_counts(lots, total, total, prior, None, prices))
                       for gate, prior in pre_target.items()} for name, prices in scopes.items()
            }
    return dict(contract=CONTRACT, source_image=image, quote_marks={
                    product: row["mark"] for product, row in photo["per_symbol"].items()
                } | {"ru": rubber["later"]["quote_candidate"]},
                max_row_quote_lag_minutes={t.isoformat(): max(row.values()) for t, row in distances.items()},
                compatible_jm_minutes=anchors, displayed_lots=lots, opening_average=earlier_leg["opening_average"],
                minimum_pre_target_lots_by_exit=bounds, same_account_and_short_term_task_verified=False,
                author_action_samples=0, author_match_rate=None, fills=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--between-target-and-confirmation", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("JM_M_PHOTO_OUTPUT_EXISTS")
    try:
        result = local_market_case(args.env_file, case=lambda market_input: study(
            *market_input, between_target_and_confirmation=args.between_target_and_confirmation,
        ))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() else "JM_M_PHOTO_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
