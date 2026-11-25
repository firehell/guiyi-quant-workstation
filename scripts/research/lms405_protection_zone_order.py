"""Compare zone contact before shape against an in-zone confirming close."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from lms405_protection_timeframes import VARIANTS, WINDOWS, geometry_events, read_window
from lms405_portfolio_replay import ARCHIVE
from lms405_right_side_study import US, at
from lms405_sizing_audit import EXPOSURE_SHA256
from lms405_volatility_context import GEOMETRY_SHA256
from lms_near405_replay import encoded, sha

VOLATILITY_SHA256 = "da143fd9c6e296ea2865e30cf162b578588e0464c59ff8974dd4db3b86e87845"
OCTOBER_BANDS = Path("docs/research/lms405/evidence/portfolio-oct-protection-bands.json")
BANDS_SHA256 = "c87f540459e0150df19a72edbf6a78d46c8d7b6b28d0520e3a88bfec060faf15"
FIRST_NIGHT = ("2026-10-23", "2026-10-22T21:00", "2026-10-22T22:10", "LONG")
FIRST_NIGHT_CONTRACTS = ("FG2701", "JM2701", "SA2701", "RU2701")
RU_CASE = ("ru_before_m", "RU2701", "2026-10-28", "2026-10-27T21:00", "2026-10-27T22:12", "LONG",
           ("19360", "19405"), "A5358686695981271", ("2026-10-27T21:16",))


def price_band_status(price, bounds):
    low, high = bounds
    if price < low:
        return "BELOW"
    if price > high:
        return "ABOVE"
    return "INSIDE"


def zone_order(minutes, events, *, bounds, shape_minutes, start, as_of):
    """Require contact knowledge before the shape starts and keep restarts explicit."""
    if bounds is not None and bounds[0] >= bounds[1]:
        raise ValueError("INVALID_PROTECTION_BAND")
    eligible = [b for b in minutes if start <= b.start and b.end + US < as_of]
    segment, previous = {}, None
    contacts = []
    for bar in eligible:
        if previous is None or previous.end != bar.start:
            segment_start = bar.start
        previous = bar
        segment[bar.end] = segment_start
        if bounds is not None and bar.low <= bounds[1] and bounds[0] <= bar.high:
            contacts.append(bar.end)

    results = []
    for event in events:
        shape_end, confirmation = event["shape_end"], event["confirmed_at"]
        shape_start = shape_end - timedelta(minutes=shape_minutes)
        if not start <= shape_start < shape_end < confirmation < event["available_at"] < as_of:
            raise ValueError("ZONE_ORDER_EVENT_OUTSIDE_PREFIX")
        if shape_end not in segment or confirmation not in segment or segment[shape_end] != segment[confirmation]:
            raise ValueError("ZONE_ORDER_CONFIRMATION_SEGMENT_MISMATCH")
        if bounds is None:
            results.append(event | dict(shape_start=shape_start, before_shape_policy=None,
                                        close_inside_policy=None))
            continue
        earlier = next((end for end in reversed(contacts) if end + US < shape_start), None)
        prior_same_run = earlier is not None and segment[earlier] == segment[shape_end]
        status = price_band_status(event["close"], bounds)
        results.append(event | dict(
            shape_start=shape_start, prior_contact_at=earlier, prior_contact_same_run=prior_same_run,
            contact_ending_at_shape_start=shape_start in contacts, confirmation_close_relation=status,
            before_shape_policy=prior_same_run, close_inside_policy=status == "INSIDE",
        ))
    return results, contacts


def check_frozen_prior(previous, observed, *, band):
    if {key: row["sha256"] for key, row in previous["market"].items()} != observed["market"]:
        raise ValueError("FROZEN_ZONE_ORDER_INPUT_CHANGED")
    if previous["band"] != (list(band) if band is not None else None):
        raise ValueError("FROZEN_ZONE_ORDER_BAND_CHANGED")
    for name, result in observed["variants"].items():
        events = previous["hypotheses"][name]["events"]
        if len(events) != len(result["events"]):
            raise ValueError("FROZEN_GEOMETRY_EVENT_COUNT_CHANGED")
        for a, b in zip(events, result["events"], strict=True):
            normalized = a | {key: datetime.fromisoformat(a[key])
                              for key in ("shape_end", "confirmed_at", "available_at")}
            normalized.update({key: Decimal(a[key]) for key in ("close", "boundary")})
            if any(b[key] != value for key, value in normalized.items()):
                raise ValueError("FROZEN_GEOMETRY_EVENT_CHANGED")


def after_confirmation_bounds(minutes, *, after, cutoff, average):
    """A later OHLC envelope can exclude a shown mean but cannot verify a fill."""
    later = [bar for bar in minutes if bar.start >= after and bar.end + US < cutoff]
    if not later:
        return dict(count=0, low=None, high=None, compatible=None)
    low, high = min(bar.low for bar in later), max(bar.high for bar in later)
    return dict(count=len(later), low=low, high=high, compatible=low <= average <= high)


def compare_display(tables, name, contract, cutoff, minutes, variants):
    source = "WRoEvasxQR" if name == "ru_before_m" else "WRnTlEfj1t"
    table = tables[source]
    if table["system"] != "4.0.5" or datetime.fromisoformat(table["published_at"]) != cutoff:
        raise ValueError("ZONE_ORDER_DISPLAY_SCOPE_MISMATCH")
    leg = table["contracts"][contract]["legs"]["long"]
    if leg["today_quantity"] != leg["quantity"]:
        raise ValueError("ZONE_ORDER_DISPLAY_FRESH_LEG_UNKNOWN")
    average = Decimal(leg["opening_average"])
    return dict(
        source=source, quote_anchor=None, visible_leg=leg,
        after_confirmations={key: [dict(
            confirmed_at=event["confirmed_at"],
            **after_confirmation_bounds(minutes, after=event["confirmed_at"], cutoff=cutoff, average=average),
        ) for event in entry["events"] if event["before_shape_policy"] or event["close_inside_policy"]]
            for key, entry in variants.items()},
    )


def case(series, *, start, as_of, side, band, split):
    bounds = tuple(map(Decimal, band)) if band is not None else None
    results, contacts = {}, []
    for shape, confirmation in VARIANTS:
        args = dict(start=start, side=side)
        raw = geometry_events(series, shape, confirmation, as_of=as_of, **args)
        events, contacts = zone_order(series[1], raw, bounds=bounds, shape_minutes=shape, start=start, as_of=as_of)
        prefix_raw = geometry_events(series, shape, confirmation, as_of=split, **args)
        prefix, _ = zone_order(series[1], prefix_raw, bounds=bounds, shape_minutes=shape, start=start, as_of=split)
        if prefix != [row for row in events if row["available_at"] < split]:
            raise ValueError("ZONE_ORDER_PREFIX_DIVERGED")
        results[f"{shape}m_to_{confirmation}m"] = dict(
            candidates=len(events),
            before_shape_pass=sum(row["before_shape_policy"] is True for row in events) if bounds is not None else None,
            close_inside_pass=sum(row["close_inside_policy"] is True for row in events) if bounds is not None else None,
            both_pass=sum(row["before_shape_policy"] and row["close_inside_policy"]
                          for row in events) if bounds is not None else None,
            events=events,
        )
    return dict(
        first_contact=contacts[0] if contacts else None, contact_minutes=len(contacts) if bounds is not None else None,
        variants=results, prefix_verified=True,
        market={f"{p}m": sha(encoded([[b.end.isoformat(), *map(str, (b.open, b.high, b.low, b.close))]
                                      for b in bars]).encode()) for p, bars in series.items()},
    )


def study(session, market, geometry, volatility, bands, exposure):
    prior_bands = bands["opening_average_bands"]
    additions = tuple(
        (contract[:-4].lower() + "_first_night", contract, *FIRST_NIGHT,
         tuple(prior_bands[contract]["band"]), prior_bands[contract]["source"], ("2026-10-22T21:45",))
        for contract in FIRST_NIGHT_CONTRACTS
    )
    tables = {row["source"]: row for row in exposure["tables"] if row["source"] in ("WRnTlEfj1t", "WRoEvasxQR")}
    for table in tables.values():
        if sha((ARCHIVE.parent / table["image"]["path"]).read_bytes()) != table["image"]["sha256"]:
            raise ValueError("ZONE_ORDER_DISPLAY_IMAGE_CHANGED")
    results = {}
    for name, contract, trading_day, start, cutoff, side, band, source, milestones in (*WINDOWS, *additions, RU_CASE):
        series = read_window(session, market, contract, date.fromisoformat(trading_day))
        output = case(series, start=at(start), as_of=at(cutoff), side=side, band=band, split=at(milestones[0]))
        output.update(contract=contract, trading_day=trading_day, start=start, cutoff=cutoff,
                      plan_band=band, source_id=source, side=side)
        if name in geometry["cases"]:
            check_frozen_prior(geometry["cases"][name], output, band=band)
            context = volatility["cases"][name]
            if context["minute_sha256"] != output["market"]["1m"]:
                raise ValueError("FROZEN_VOLATILITY_INPUT_CHANGED")
            for variant, entry in output["variants"].items():
                for event, point in zip(entry["events"], context["geometry_context_before_shape"][variant], strict=True):
                    if (datetime.fromisoformat(point["shape_start"]) != event["shape_start"]
                            or datetime.fromisoformat(point["confirmed_at"]) != event["confirmed_at"]):
                        raise ValueError("VOLATILITY_SHAPE_ALIGNMENT_MISMATCH")
                    event["atr_context_known_before_shape"] = point["known_before_shape"]
        if name in ("sh", "ru_before_m") or name.endswith("_first_night"):
            output["display_comparison"] = compare_display(
                tables, name, contract, at(cutoff), series[1], output["variants"],
            )
        results[name] = output
    return dict(
        version="lms405-protection-zone-order-v1", cases=results,
        policy_before_shape="LATEST_COMPLETED_CONTACT_STRICTLY_KNOWN_BEFORE_SHAPE_IN_SAME_CONTIGUOUS_RUN",
        policy_close_inside="CONFIRMATION_CLOSE_WITHIN_INCLUSIVE_PLAN_BAND",
        source_text_timing="RETROSPECTIVE_ARCHIVE_HISTORY_NOT_VERIFIED",
        author_action_samples=0, author_match_rate=None, protection_confirmation=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--volatility", type=Path, required=True)
    parser.add_argument("--exposure", type=Path, required=True)
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
        paths = (args.geometry, args.volatility, OCTOBER_BANDS, args.exposure)
        documents = tuple(path.read_bytes() for path in paths)
        expected = dict(geometry=GEOMETRY_SHA256, volatility=VOLATILITY_SHA256,
                        zones=BANDS_SHA256, exposure=EXPOSURE_SHA256)
        if tuple(map(sha, documents)) != tuple(expected.values()):
            raise ValueError("FROZEN_ZONE_ORDER_REPORT_CHANGED")
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session), *map(json.loads, documents))
        result["input_sha256"] = expected
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
