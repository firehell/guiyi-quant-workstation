"""Compare directional milestones from published reviews on completed physical-contract bars."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_plan_driven_replay import local_market_case
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_timeframes import read_window
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import digest
from lms405_trial_to_trend import assess_role, milestones
from lms405_v_zone_progress import observations, publication_windows
from lms_near405_replay import encoded, sha


# Keep basic nodes distinct from the subsequent extension quoted by the author.
WINDOWS = (
    ("S5369078518647988", "JM2701", "2026-11-25", "STRONG_LONG_CYCLE_REPORTED",
     {"LONG": ("1414.5 1426.5", "1433.5 1442")}, ("LONG", "1455.5 1462.5")),
    ("S5303225496111492", "JM2609", "2026-05-27", "STRONG_LONG_CYCLE_NOT_COMPLETED",
     {"LONG": ("1269 1274", "1280 1285")}, None),
    ("S5333301370032813", "I2701", "2026-08-18", "BOTH_DIRECTIONS_BASIC_NODES_INTRADAY_M",
     {"SHORT": ("699.5 703.5",), "LONG": ("709.5 712",)}, None),
    ("S5306120929544557", "I2609", "2026-06-04", "STRONG_SHORT_CYCLE_THEN_TREND_REPORTED",
     {"SHORT": ("774.5 777", "771.5 773")}, ("SHORT", "766.5 768.5")),
)

TRIAL_REVIEWS = (
    ("PEKMSnUvf", "PS2511", ("2025-08-05", "2025-08-06", "2025-08-07"), {
        "long_trend_gate": ("LONG", "51815 52480"),
    }),
    ("S5329232944955498", "CF2609", ("2026-08-07",), {
        "long_rebound_quality": ("LONG", "16265 16345"),
        "balance_boundary": ("SHORT", "16190 16190"),
        "long_rebound_interruption": ("SHORT", "16120 16155"),
    }),
    ("S5288088578560326", "LH2605", ("2026-04-15",), {
        "reported_short_trial_end_price": ("LONG", "9280 9280"),
    }),
    ("S5288088578560326", "LH2607", ("2026-04-16",), {
        "long_rebound_quality": ("LONG", "11075 11105"),
        "stop_falling_reference": ("SHORT", "10730 10730"),
        "rebound_failure_boundary": ("SHORT", "10660 10730"),
    }),
    ("S5306494870623342", "V2609", ("2026-06-05",), {
        "recalled_short_target": ("SHORT", "4776 4802"),
    }),
)


def price_comparison(bars, paths, extension):
    directions = {}
    for side, bands in paths.items():
        nodes = [observations(bars, tuple(map(Decimal, band.split())), side) for band in bands]
        directions[side] = dict(
            nodes=nodes, counts={
                label: sum(node[field] is not None for node in nodes)
                for label, field in (
                    ("near", "first_near_reach"), ("far", "first_far_reach"),
                    ("strict_far_close", "first_strict_close_beyond_far"),
                )
            }, first_observations=milestones(nodes),
        )
    extension_observation = None
    if extension:
        side, band = extension
        extension_observation = dict(side=side, **observations(bars, tuple(map(Decimal, band.split())), side))
    return dict(
        count=len(bars), sha256=digest(bars), high=max((bar.high for bar in bars), default=None),
        low=min((bar.low for bar in bars), default=None), directions=directions,
        pooled_far_count=sum(path["counts"]["far"] for path in directions.values()),
        extension=extension_observation,
    )


def study(*, market_input):
    from app.market_data.market_data_service import MarketDataError
    session, market = market_input
    archive = input_sources()
    cases = {}
    for source_id, contract, day_text, narrative, paths, extension in WINDOWS:
        day = date.fromisoformat(day_text)
        source = archive[source_id]
        # A minute-only publication time is recorded at :00, so its whole minute is excluded.
        publication = datetime.fromisoformat(source["published_at"])
        review = assess_role(trend=True if narrative == "STRONG_SHORT_CYCLE_THEN_TREND_REPORTED" else None,
                             trial_success=None, current_position_is_trial=None, version_405=None, author_role=None)
        case = dict(contract=contract, trading_day=day_text, source=source | {
            "archive_sha256": sha((ARCHIVE.parent / source["archive_path"]).read_bytes()),
        }, author_market_description=narrative, holding_review=review, historical_plan_verified=False)
        cases[source_id] = case
        try:
            series = read_window(session, market, contract, day)
        except MarketDataError as exc:
            case["market_gap"] = exc.code
            continue
        comparison = {}
        for period, bars in series.items():
            observed = [bar for bar in bars if bar.end + US < publication]
            same_calendar_date = [bar for bar in observed
                                  if bar.start.astimezone(publication.tzinfo).date() == publication.date()]
            comparison[f"{period}m"] = dict(
                complete_day_count=len(bars), complete_day_sha256=digest(bars),
                trading_day_prefix=price_comparison(observed, paths, extension),
                publication_date_prefix=price_comparison(same_calendar_date, paths, extension),
            )
        case["comparison"] = comparison
    return dict(
        version="lms405-directional-path-study-v1", mode="RETROSPECTIVE_PRICE_COMPARISON", cases=cases,
        admitted_author_actions=0, author_matches=None, executable=False, fills=None, pnl=None,
    )


def trial_price_observations(bars, bands):
    return dict(
        bars=len(bars), sha256=digest(bars),
        high=max((bar.high for bar in bars), default=None),
        low=min((bar.low for bar in bars), default=None),
        levels={name: dict(side=side, **observations(bars, tuple(map(Decimal, band.split())), side))
                for name, (side, band) in bands.items()},
    )


def trial_outcome_study(*, market_input):
    from app.market_data.market_data_service import MarketDataError
    session, market = market_input
    archive = input_sources()
    cases = {}
    for source_id, contract, dates, bands in TRIAL_REVIEWS:
        source = archive[source_id]
        # Exclude the publication minute even when the visible source provides seconds.
        publication = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0)
        for day in dates:
            case = dict(contract=contract, trading_day=day, source_id=source_id, source=source | {
                "archive_sha256": sha((ARCHIVE.parent / source["archive_path"]).read_bytes()),
            }, trial_identity=None, actual_transition_at=None, historical_plan_verified=False)
            cases[f"{contract}/{day}"] = case
            try:
                series = read_window(session, market, contract, date.fromisoformat(day))
            except MarketDataError as exc:
                case["market_gap"] = exc.code
                continue
            comparison = {}
            for period, bars in series.items():
                before, after = publication_windows(bars, publication)
                comparison[f"{period}m"] = dict(
                    whole_day=trial_price_observations(bars, bands),
                    before_publication=trial_price_observations(before, bands),
                    after_publication=trial_price_observations(after, bands),
                )
            case["comparison"] = comparison
    return dict(
        version="lms405-trial-outcome-price-review-v1", mode="RETROSPECTIVE_PRICE_COMPARISON", cases=cases,
        admitted_author_actions=0, author_matches=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trial-outcome", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    result = local_market_case(args.env_file, case=trial_outcome_study if args.trial_outcome else study)
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")


if __name__ == "__main__":
    main()
