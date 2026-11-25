"""Verify published node roles and price milestones without inferring strategy states."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, LOCAL, input_sources
from lms405_protection_shape_audit import price_digest
from lms405_protection_timeframes import read_window
from lms405_replay import display
from lms405_right_side_study import ONE
from lms405_v_zone_progress import MINUTE_HASHES, observations, publication_windows
from lms_near405_replay import encoded, sha

CASES = {
    "iron_base_and_extension": ("I2609", "SHORT", "S5306120929544557", "BEAR_TREND_ON_UPDATED_EXTENSION_REPORTED", (
        ("original_node_1", "ORIGINAL_SELECTED_PATH", "774.5 777"),
        ("original_node_2", "ORIGINAL_SELECTED_PATH", "771.5 773"),
        ("new_extension", "SEPARATELY_UPDATED_EXTENSION", "766.5 768.5"),
    )),
    "iron_one_observed_node": ("I2609", "LONG", "S5318444568282605", "AUTHOR_LEFT_RANGE_ASSESSMENT_UNCHANGED", (
        ("divider", "DIVIDER", "733 737"),
        ("visible_preparation_node", "PREPARATION_NODE_TEST_REPORTED", "743 747"),
        ("other_preparation_node", "PRICE_NOT_OBSERVED", None),
    )),
    "soda_break_then_target_test": ("SA2609", "SHORT", "S5306490611304828", "TREND_CHANGE_NOT_DISCLOSED", (
        ("marked_break_band", "KEY_BREAK_BAND", "1175 1194"),
        ("next_target_near", "TARGET_NEAR_EDGE_ONLY", "1160"),
    )),
    "pvc_update_then_optional_extension": ("V2609", "SHORT", "S5312549333501242", "INTRADAY_CONDITIONAL_PLAN_ONLY", (
        ("previous_target", "PRIOR_PATH_COMPLETED_REPORTED", "4561 4593"),
        ("new_target", "NEW_STRONG_SIDE_TARGET", "4536 4553"),
        ("particularly_strong_extension", "OPTIONAL_EXTENSION", "4508 4508"),
    )),
}
COAL_FOLLOWUP = ("JM2609", "SHORT", "S5313011682379978", "TREND_FOLLOW_THROUGH_INTENT_4_0_5", (
    ("previous_target", "PRIOR_STRONG_SIDE_TARGET", "1257.5 1263.5"),
    ("particularly_strong_extension", "PRIOR_OPTIONAL_EXTENSION", "1241.5 1248"),
))


def hypothetical_publication_cutoffs(bars, band, side):
    """Latest hypothetical publication minute that leaves a whole qualifying bar."""
    edge = band[0] if side == "SHORT" else band[1]
    if side == "SHORT":
        touched = [bar for bar in bars if bar.low <= edge]
        closed = [bar for bar in bars if bar.close < edge]
    else:
        touched = [bar for bar in bars if bar.high >= edge]
        closed = [bar for bar in bars if bar.close > edge]
    return {
        name: dict(
            first_bar_end=display(matches[0].end) if matches else None,
            last_bar_end=display(matches[-1].end) if matches else None,
            latest_release_minute_for_first=display(matches[0].start - ONE) if matches else None,
            latest_release_minute_for_any=display(matches[-1].start - ONE) if matches else None,
        )
        for name, matches in (("directional_far_reach", touched), ("strict_close_beyond_far", closed))
    }


def compare(series, side, nodes, published_minute, *, publication_followup=False):
    periods = {}
    for period, bars in series.items():
        before, after = publication_windows(bars, published_minute)
        levels = {}
        for name, role, raw in nodes:
            if raw is None:
                levels[name] = dict(role=role, band=None, before_review=None, after_release=None)
                continue
            if role == "TARGET_NEAR_EDGE_ONLY":
                near = Decimal(raw)
                near_read = observations(before, (near, near), side)
                levels[name] = dict(role=role, band=None, before_review={
                    key: near_read[key] for key in (
                        "near", "complete_bars", "first_near_reach", "first_strict_close_beyond_near",
                    )
                } | dict(far=None), after_release=None)
                continue
            band = tuple(map(Decimal, raw.split()))
            levels[name] = dict(
                role=role, band=band, before_review=observations(before, band, side),
                after_release=observations(after, band, side) if role in (
                    "NEW_STRONG_SIDE_TARGET", "OPTIONAL_EXTENSION",
                ) else None,
            )
            if publication_followup and role == "SEPARATELY_UPDATED_EXTENSION":
                levels[name]["hypothetical_publication_cutoffs"] = hypothetical_publication_cutoffs(before, band, side)
        periods[f"{period}m"] = dict(
            bar_count=len(bars), market_sha256=sha(encoded(price_digest(bars)).encode()),
            high=max(b.high for b in bars), low=min(b.low for b in bars), close=bars[-1].close,
            first_bar_after_release=display(after[0].end) if after else None, nodes=levels,
        )
    return periods


def study(session, market, *, publication_followup=False):
    index = input_sources()
    cases = {}
    cases_input = CASES | {"coal_trend_intent_before_optional_completion": COAL_FOLLOWUP} if publication_followup else CASES
    for name, (contract, side, key, wording, nodes) in cases_input.items():
        source = index[key]
        path = ARCHIVE.parent / source["archive_path"]
        published = datetime.fromisoformat(source["published_at"]).astimezone(LOCAL)
        series = read_window(session, market, contract, published.date())
        periods = compare(series, side, nodes, published.replace(second=0, microsecond=0),
                          publication_followup=publication_followup)
        if contract == "V2609" and periods["1m"]["market_sha256"] != MINUTE_HASHES[published.date().isoformat()]:
            raise ValueError("PATH_STAGE_FROZEN_PVC_MARKET_CHANGED")
        cases[name] = dict(
            source=source | dict(id=key, sha256=sha(path.read_bytes())), contract=contract, side=side,
            trading_day=published.date(), after_review_wording=wording, market=periods,
            historical_vplus_revision_verified=False, author_state_transition_at=None,
        )
    version = "lms405-path-stage-publication-audit-v1" if publication_followup else "lms405-path-stage-audit-v1"
    return dict(version=version, cases=cases, admitted_author_action_samples=0,
                executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publication-followup", action="store_true")
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
            report = study(session, build_market_data_service(session), publication_followup=args.publication_followup)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "PATH_STAGE_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
