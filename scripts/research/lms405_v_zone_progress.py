"""Compare PVC touch, completion and boundary reuse on physical-contract bars."""

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_replay import display
from lms405_right_side_study import ONE, US, at
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded

CONTRACT = "V2609"
WINDOWS = {
    "2026-05-20": ("S5300692424327191", "16:50", "4936", None, (
        ("strong_1", "5032 5051", "SHORT", "COMPLETED_REPORTED"),
        ("strong_2", "5012 5024", "SHORT", "COMPLETED_REPORTED"),
        ("strong_3", "4987 4999", "SHORT", "COMPLETED_REPORTED"),
    )),
    "2026-06-04": ("S5306129550676828", "16:55", "4813", None, (
        ("strong_1", "4907 4915", "SHORT", "COMPLETED_REPORTED"),
        ("strong_2", "4892 4906", "SHORT", "COMPLETED_REPORTED"),
        ("strong_3", "4856 4872", "SHORT", "COMPLETED_REPORTED"),
        ("strong_extension", "4804 4855", "SHORT", "TESTED_REPORTED"),
    )),
    "2026-06-05": ("S5306494870623342", "17:07", "4754", None, (
        ("strong_target", "4776 4802", "SHORT", "TARGET_REACHED_REPORTED"),
    )),
    "2026-06-17": ("S5310836013794895", "16:37", None, "4690", (
        ("weak_target", "4686 4704", "LONG", "INCOMPLETE_REPORTED"),
    )),
    "2026-06-22": ("S5312549333501242", "10:05", None, None, (
        ("prior_short_target", "4561 4593", "SHORT", "COMPLETED_REPORTED"),
        ("same_band_reused_for_protection", "4561 4593", "LONG", "PROTECTION_IF_BROKEN"),
        ("new_strong_extension", "4536 4553", "SHORT", "NEW_PLAN"),
        ("new_extreme_target", "4508 4508", "SHORT", "NEW_CONDITIONAL_PLAN"),
    )),
    "2026-06-26": ("S5314108909162189", "17:22", "4385", None, (
        ("strong_target", "4372 4396", "SHORT", "TESTED_REPORTED"),
    )),
}
MINUTE_HASHES = {
    "2026-05-20": "b4d73e8716dcac986f520af3839c54ce495c9e3daf94bd69ab2d6b88fade1835",
    "2026-06-04": "ffffe62517a16dcd802a25e1403663760e181bef31541c5ffd42f7cf2094c087",
    "2026-06-05": "9109ca02fc565fdbb9ab20fd1a2757337010760a8551e2b6ad040dfacf000552",
    "2026-06-17": "5ae5ae342f164bf9fd3caf79f1a59ce8181d606ee85b9b8f52e5dfa47cd84654",
    "2026-06-22": "549bec88acfaeebf92649deb6a9c09c53437e38d350ad8e46c841f8db511fefd",
    "2026-06-26": "deafc8669fab4aa30685a5ca5dc07fbdf566b473c6b59da02d1bb8307b982ca9",
}


def observations(bars, band, side):
    """Preserve range overlap and directional price reach as separate observations."""
    lower, upper = band
    if lower > upper or side not in ("LONG", "SHORT"):
        raise ValueError("PVC_INVALID_DIRECTIONAL_BAND")
    near, far = (lower, upper) if side == "LONG" else (upper, lower)

    def reaches(bar, price):
        return bar.high >= price if side == "LONG" else bar.low <= price

    def breaks(bar, price):
        return bar.close > price if side == "LONG" else bar.close < price

    def first(predicate):
        return next((display(bar.end) for bar in bars if predicate(bar)), None)

    return dict(
        near=near, far=far, complete_bars=len(bars),
        first_range_overlap=first(lambda b: b.low <= upper and b.high >= lower),
        first_near_reach=first(lambda b: reaches(b, near)),
        first_far_reach=first(lambda b: reaches(b, far)),
        first_strict_close_beyond_near=first(lambda b: breaks(b, near)),
        first_strict_close_beyond_far=first(lambda b: breaks(b, far)),
    )


def publication_windows(bars, published_minute):
    before = [b for b in bars if b.end + US < published_minute]
    # Publication seconds and the first intra-bar price are unknown.
    after = [b for b in bars if b.start >= published_minute + ONE]
    return before, after


def study(session, market):
    cases = {}
    for day, (key, time, low, high, entries) in WINDOWS.items():
        raw, series = read_pair(session, market, CONTRACT, (date.fromisoformat(day),))
        hashes = {f"{p}m": bars_sha(rows) for p, rows in raw.items()}
        if hashes["1m"] != MINUTE_HASHES[day]:
            raise ValueError("PVC_FROZEN_MARKET_CHANGED")
        published = at(f"{day}T{time}")
        one = series[1]
        before, after = publication_windows(one, published)
        bands = {}
        for identity, raw_band, side, author_label in entries:
            band = tuple(map(Decimal, raw_band.split()))
            bands[identity] = dict(
                band=band, side=side, author_label=author_label,
                before_visible_post=observations(before, band, side),
                after_publication_minute=observations(after, band, side) if after else None,
            )
        cases[day] = dict(
            source_id=key, published_minute=published, author_reported_low=low, author_reported_high=high,
            market_low=min(b.low for b in one), market_high=max(b.high for b in one),
            low_before_post=min((b.low for b in before), default=None),
            high_before_post=max((b.high for b in before), default=None),
            bars={f"{p}m": len(rows) for p, rows in raw.items()}, market_sha256=hashes,
            bands=bands, author_signal_at=None, author_action_at=None,
        )
    return dict(
        version="lms405-v-zone-progress-v1", contract=CONTRACT, cases=cases,
        december_author_contract=None, december_author_preplan=None, author_completion_formula=None,
        admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "PVC_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
