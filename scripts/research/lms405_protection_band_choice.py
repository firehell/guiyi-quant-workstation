"""Compare author-disclosed early and later protection areas on completed bars."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405.protection_band import ProtectionBandUpdate, active_band, visible_bands
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_pre_touch_protection import analyze
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import display
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

PRIOR_OIL = Path("output/lms405-pre-touch-protection-20261125/final.json")
PRIOR_OIL_SHA = "d5053217c8be047d853955709fdca77b8b268656f5cb2af0b078574399e94a60"
SODA_LIST = "https://stock.weibo.cn/page/detail?market=gn&symbol=SA0"
WINDOWS = (
    ("OI2609", "2026-06-03T10:13", "S5305666088472874", "LONG",
     ("10175", "10197"), ("10019", "10151"), "REGULAR_WEAK_SIDE_AREA"),
    # Preserve the frozen display-as-local sensitivity. See lms405_sa_bd_clock for calibration.
    ("SA2701", "2026-10-19T09:02", None, "SHORT",
     ("932", "937"), ("941", "946"), "OPTIONAL_LATER_PROTECTION_FOR_DIFFERENT_CONTINUITY_HANDLING"),
    ("SR2701", "2026-08-10T11:04", "S5330321279291289", "LONG",
     ("5334", "5342"), ("5320", "5334"), "LATER_RISK_LIMIT_ONLY"),
)


def compare_scoped_choices(contract, *, start, side, near, late, late_role):
    """Exercise the existing resolver with explicit hypothetical choices."""
    args = dict(contract=contract, side=side, known_at=start, effective_after=start,
                source="BAND_CHOICE_STUDY_ASSUMPTION")
    early = ProtectionBandUpdate(revision="early", role="PROTECTION", lower=near[0], upper=near[1], **args)
    pending = ProtectionBandUpdate(revision="unselected", role="REVIEW_PENDING", **args)
    configs = {"early_selected": (early,), "no_selection": (pending,)}
    if late_role != "LATER_RISK_LIMIT_ONLY":
        later = ProtectionBandUpdate(revision="late", role="PROTECTION", lower=late[0], upper=late[1], **args)
        configs.update(late_selected=(later,), conflicting_same_time_choices=(early, later))
    result = {}
    for name, updates in configs.items():
        available = start + US
        selected, reason = active_band(visible_bands(updates, contract, available), available, side)
        previous, _ = active_band(visible_bands(updates, contract, start), start, side)
        if previous is not None:
            raise ValueError("BAND_CHOICE_SCOPE_APPLIED_BEFORE_KNOWN")
        result[name] = dict(active_revision=selected.revision if selected else None, reason=reason)
    return result


def inspect_band(series, *, publication, start, cut, protected_side, band):
    protection_side = "LONG" if protected_side == "SHORT" else "SHORT"
    args = dict(start=start, band=band, side=protection_side, leg=None)
    geometry = analyze(series, cut=cut, **args)
    prefix_cut = start + (cut - start) / 2
    prefix = analyze(series, cut=prefix_cut, **args)
    status = {}
    for key, events in geometry["variants"].items():
        before = prefix["variants"][key]
        after = [row for row in events if row["available_at"] < prefix_cut]
        signal_keys = ("confirmed_at", "in_band", "pre_touch_arm", "first_touch_known_before_shape")
        if [tuple(row[k] for k in signal_keys) for row in before] != [tuple(row[k] for k in signal_keys) for row in after]:
            raise ValueError("BAND_CHOICE_PREFIX_CHANGED")
        status[key] = dict(
            immediate_in_band=[row for row in events if row["in_band"]],
            wait_and_survive=[row for row in events if row["survives_both_diagnostics"]],
            after_known_touch=[row for row in events if row["first_touch_known_before_shape"]],
            before_touch_without_waiting=[row for row in events if row["pre_touch_arm"]],
        )
    before_publication = [bar for bar in series[1] if bar.end + US < publication]
    bars = completed(series[1], start, cut)
    far = band[0] if protection_side == "SHORT" else band[1]

    def beyond_far(bar):
        return bar.close < far if protection_side == "SHORT" else bar.close > far

    fresh_cross = next((display(bar.end) for prev, bar in zip(bars, bars[1:])
                        if prev.end == bar.start and not beyond_far(prev) and beyond_far(bar)), None)
    return dict(band=band, path=observations(bars, band, protection_side),
                before_publication_path=observations(before_publication, band, protection_side),
                first_completed_close_already_beyond_far=beyond_far(bars[0]),
                first_fresh_far_close_cross_at=fresh_cross, hypotheses=status)


def study(session, market, existing_oil):
    from app.market_data.market_data_service import MarketDataError

    index = input_sources()
    cases = {}
    for contract, published, source_id, side, near, late, late_role in WINDOWS:
        publication = at(published)
        start, cut = publication + ONE, at(f"{publication.date()}T15:00") + 2 * US
        near, late = tuple(map(Decimal, near)), tuple(map(Decimal, late))
        boundary_index = 1 if side == "LONG" else 0
        distance = late[boundary_index] - near[boundary_index]
        if side == "LONG":
            distance = -distance
        if near[0] >= near[1] or late[0] >= late[1] or distance <= 0:
            raise ValueError("BAND_CHOICE_ROLE_ORDER_INVALID")
        source = index[source_id] if source_id is not None else dict(source_url=SODA_LIST, excerpt_only=True)
        if source_id is not None:
            if datetime.fromisoformat(source["published_at"]) != publication:
                raise ValueError("BAND_CHOICE_SOURCE_TIME_CHANGED")
            source = source | dict(archive_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()))
        scope = dict(published_at=publication, start=start, cut_exclusive=cut, source_id=source_id, source=source,
                     protected_side=side, late_band_role=late_role, early_band=near, late_band=late,
                     adverse_near_edge_difference_in_points=distance,
                     scoped_resolver_comparison=compare_scoped_choices(
                         contract, start=start, side=side, near=near, late=late, late_role=late_role,
                     ),
                     author_active_choice=None, author_action_at=None, author_vplus_at=None)
        try:
            series = read_window(session, market, contract, publication.date())
        except MarketDataError as exc:
            if exc.code != "DATASET_OR_PARTITION_MISSING":
                raise
            cases[contract] = scope | dict(status=exc.code)
            continue
        fingerprints = {f"{p}m": digest(bars) for p, bars in series.items()}
        if contract == "OI2609" and fingerprints != existing_oil["market"]:
            raise ValueError("BAND_CHOICE_OIL_MARKET_CHANGED")
        points = completed(series[1], start, cut)
        if not points:
            raise ValueError("BAND_CHOICE_PRICE_WINDOW_EMPTY")
        args = dict(publication=publication, start=start, cut=cut, protected_side=side)
        cases[contract] = scope | dict(
            status="COMPLETED_WINDOW_READABLE", market=fingerprints,
            window_extrema=[min(b.low for b in points), max(b.high for b in points)],
            early=inspect_band(series, band=near, **args),
            late=inspect_band(series, band=late, **args) | dict(
                comparison_only=late_role == "LATER_RISK_LIMIT_ONLY",
            ),
        )
    return dict(version="lms405-protection-band-choice-v1", cases=cases, prior_oil_report_sha256=PRIOR_OIL_SHA,
                scope="ALTERNATIVE_PRICE_AREA_HYPOTHESES_ONLY", actual_account_actions_scored=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
        oil = verified_json(PRIOR_OIL, PRIOR_OIL_SHA)["cases"]["oi"]
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), oil)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('BAND_CHOICE_') and code.isidentifier() else 'BAND_CHOICE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
