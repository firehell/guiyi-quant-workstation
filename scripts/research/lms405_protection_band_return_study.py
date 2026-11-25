"""Compare fresh price returns to source-linked protection bands after role changes."""

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_i2701_case import readback
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_replay import display, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

OCTOBER = Path("output/lms405-protection-lot-timing-20261125/final.json")
OCTOBER_SHA = "6a61d2ea4463ed8b2115ddc59d90a4726f53c23db44970f58c45307eafc925e8"
CASES = {
    "iron_oct": ("I2701", "2026-10-27", "2026-10-26T22:03:00.000001", "2026-10-27T11:30:00.000002",
                 "LONG", "A5358325549629506", {
                     "published_protection": "667 671", "target_reuse_hypothesis": "654 662.5",
                 }),
    "soda_oct": ("SH2701", "2026-10-27", "2026-10-26T22:03:00.000001", "2026-10-27T10:13",
                 "LONG", "WRouYm67Bc", {
                     "stale_protection_control": "1516 1529", "completed_target_reuse_hypothesis": "1498 1498",
                     "next_target_reuse_hypothesis": "1483 1485",
                 }),
    "soda_gap": ("SH2605", "2026-03-06", "2026-03-05T21:08", "2026-03-06T15:01",
                 "SHORT", "S5273215752472002", {
                     "published_protection": "2281 2310", "reclassified_m_control": "2273 2278",
                 }),
    "coal_new_band": ("JM2609", "2026-06-05", "2026-06-05T14:07", "2026-06-05T15:01",
                      "SHORT", "S5306449299508533", {
                          "published_protection": "1425 1446", "completed_target_control": "1462 1468",
                      }),
    "coal_reclassified_retrospective": ("JM2701", "2026-09-02", "2026-09-01T21:00", "2026-09-02T15:01",
                                       "SHORT", "S5338740245135941", {"retrospective_protection": "1723 1749"}),
    "coal_reclassified_later_session": ("JM2701", "2026-09-03", "2026-09-02T21:00", "2026-09-03T15:01",
                                      "SHORT", "S5338740245135941", {"published_band_sensitivity_only": "1723 1749"}),
    "soda_explicit_reuse": ("SH2609", "2026-06-26", "2026-06-26T10:54", "2026-06-26T15:01",
                            "LONG", "S5314010922615018", {"published_reuse": "1926 1950"}),
    "pvc_explicit_reuse": ("V2609", "2026-06-22", "2026-06-22T10:06", "2026-06-22T15:01",
                           "LONG", "S5312549333501242", {"published_reuse": "4561 4593"}),
}


def compare_band(bars, *, band, side, frontier=None):
    """Observe boundaries; no intraminute path or protection action is inferred."""
    low, high = band
    if not bars or low > high or side not in ("LONG", "SHORT"):
        raise ValueError("INVALID_PROTECTION_BAND_WINDOW")
    near, far = (low, high) if side == "LONG" else (high, low)

    def beyond(price, level):
        return price > level if side == "LONG" else price < level

    def event(bar):
        if bar is None:
            return None
        return dict(bar_end=bar.bar_end, available_at=bar.bar_end + US, close=bar.close,
                    whole_leg_price_possible=None if frontier is None else bar.bar_end <= frontier)

    near_cross = far_cross = ordered_far = adverse_run = None
    for previous, current in zip(bars, bars[1:]):
        if current.bar_end - previous.bar_end != ONE or not beyond(current.close, near):
            adverse_run = None
            continue
        if not beyond(previous.close, near):
            adverse_run = current
            near_cross = near_cross or current
        if beyond(current.close, far) and not beyond(previous.close, far):
            far_cross = far_cross or current
            if ordered_far is None and adverse_run and adverse_run.bar_end + US < current.bar_end:
                ordered_far = event(current) | {"preceding_near": event(adverse_run)}
    return dict(
        near=near, far=far, first_bar=event(bars[0]), last_bar=event(bars[-1]),
        first_range_overlap=event(next((b for b in bars if b.low <= high and b.high >= low), None)),
        first_close_in_band=event(next((b for b in bars if low <= b.close <= high), None)),
        first_fresh_near_close=event(near_cross), first_fresh_far_close=event(far_cross),
        first_later_far_after_near=ordered_far,
    )


def study(session, market, october):
    index = input_sources()
    cases = {}
    for name, (contract, day, start, end, side, source, bands) in CASES.items():
        symbol, trading_day = contract[:-4].lower(), date.fromisoformat(day)
        raw = read_session_series(session, market, symbol, contract, "1m", ONE, (trading_day,))
        beginning, cutoff = at(start), at(end)
        bars = [bar for bar in raw if bar.bar_end - ONE >= beginning and bar.bar_end + US < cutoff]
        lot_reference = october["cases"].get(contract)
        if lot_reference and readback(raw)[day] != lot_reference["market"]:
            raise ValueError("PROTECTION_BAND_RETURN_OCTOBER_MARKET_CHANGED")
        frontier = at(lot_reference["optimistic_latest_whole_leg_start"]) if lot_reference else None
        entry = index[source]
        published = at(entry["published_at"])
        if name != "coal_reclassified_retrospective" and beginning < published.replace(second=0, microsecond=0) + ONE:
            raise ValueError("PROTECTION_BAND_RETURN_SOURCE_TOO_LATE")
        result = dict(
            contract=contract, trading_day=day, start=beginning, cutoff_exclusive=cutoff, direction=side,
            market_sha256=bars_sha(raw), market_count=len(raw), window_count=len(bars),
            source=entry, source_sha256=sha((ARCHIVE.parent / entry["archive_path"]).read_bytes()),
            historical_source_revision_verified=False,
            price_only_hypotheses={name: compare_band(bars, band=tuple(map(Decimal, text.split())), side=side,
                                                       frontier=frontier) for name, text in bands.items()},
            observed_full_day_low=min(b.low for b in raw), observed_full_day_high=max(b.high for b in raw),
            author_vplus=None, author_action_at=None,
        )
        if lot_reference:
            target = tuple(map(Decimal, lot_reference["bands"]["target"]))
            variants = {}
            for label in ("short_target_far", "short_target_far_strict_close"):
                trigger = lot_reference["bounds"][label]
                remaining = (
                    [b for b in bars if b.bar_end - ONE > at(trigger["gate_bar_end"])] if trigger else []
                )
                variants[label] = dict(
                    trigger=None if trigger is None else trigger["gate_bar_end"],
                    return_path=compare_band(remaining, band=target, side=side, frontier=frontier) if remaining else None,
                )
            result["target_reuse_completion_sensitivity"] = variants
        if name == "coal_new_band":
            before = [b for b in raw if b.bar_end + US < published]
            far = Decimal("1468")
            result["prior_strong_target"] = dict(
                band=["1462", "1468"],
                first_far_touch=next((display(bar.bar_end) for bar in before if bar.high >= far), None),
                first_far_strict_close=next((display(bar.bar_end) for bar in before if bar.close > far), None),
            )
        if name == "soda_gap":
            previous = read_session_series(session, market, symbol, contract, "1m", ONE, (date(2026, 3, 5),))
            result["gap_context"] = dict(previous_market_sha256=bars_sha(previous), previous_count=len(previous),
                                         previous_close=previous[-1].close, open=raw[0].open,
                                         gap=raw[0].open - previous[-1].close, first_minute_low=raw[0].low)
        cases[name] = result
    return dict(
        version="lms405-protection-band-return-study-v1", october_reference_sha256=OCTOBER_SHA, cases=cases,
        admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None,
    )


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
        october = verified_json(OCTOBER, OCTOBER_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=40):
            result = study(session, build_market_data_service(session), october)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "PROTECTION_BAND_RETURN_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
