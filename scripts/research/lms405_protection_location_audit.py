"""Compare a V+ proxy's shape-location and confirmation-location constraints across fixed cases."""

from argparse import ArgumentParser
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lms405_jm_july_recovery_clock import SOURCE_INDEX
from lms405_portfolio_leg_audit import scoped_input_quotes
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_next_night_replay import TOUCH, TOUCH_SHA
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded, sha

GLASS = (Path("output/lms405-glass-lock-followup-20261125/reviewed.json"),
         "cbc1a8e41badb0cf18cc97c3ce63b82953f916b5f863643561d0cd996690f9f8")
COAL = (Path("output/lms405-shape-audit-20261125/report.json"),
        "692ad01e734a6a47d27f063e2b87299e9ce7f9d0aa3d060d444e11392c552079")
COAL_ANCHOR = (Path("output/lms405-jm-july-recovery-20261125/protection-origin.json"),
              "4d45113813a483fa790ad9cc03f79d902ba0c518645912da77d845270c94825f")
GLASS_OCTOBER = (Path("output/lms405-target-protection-roles-20261125/checked.json"),
                 "d7573c3881e92ecf77049ae4d46bcb519cf28f4b21d331fba03863823cc9df76")
RULES = ("shape_range_contact", "shape_body_contact", "shape_close_inside", "confirmation_close_inside")


def location_flags(shape, confirmed, band):
    lo, hi = band
    return dict(shape_range_contact=shape.low <= hi and lo <= shape.high,
                shape_body_contact=min(shape.open, shape.close) <= hi and lo <= max(shape.open, shape.close),
                shape_close_inside=lo <= shape.close <= hi,
                confirmation_close_inside=lo <= confirmed <= hi)


def case_rows(series, start, cutoff, side):
    out, checks = {}, 0
    for shape, confirmation in VARIANTS:
        full = signals(series, shape, confirmation, side=side, start=start, cut=cutoff)
        for split in {e["available_at"] + offset for e in full for offset in (0 * US, US)}:
            prefix = {p: [b for b in bars if b.end + US < split] for p, bars in series.items()}
            if signals(prefix, shape, confirmation, side=side, start=start, cut=split) != [
                    e for e in full if e["available_at"] < split]:
                raise ValueError("LOCATION_PREFIX_DIVERGED")
            checks += 1
        out[f"{shape}m_to_{confirmation}m"] = full
    return out, checks


def recount(rows, *, comparable_price):
    rules, quote_support, strict_quote_support = Counter(), Counter(), Counter()
    shapes = {rule: set() for rule in RULES}
    for event in rows:
        if event["placement"] is None:
            continue
        for rule in RULES:
            if event["placement"][rule]:
                rules[rule] += 1
                shapes[rule].add((event["variant"].split("_to_")[0], event["shape_end"]))
                quote_support[rule] += bool(event["same_row_quote_price_support_count"])
                strict_quote_support[rule] += bool(event["prior_to_quote_minute_price_support_count"])
    return {rule: dict(candidates=rules[rule], distinct_shapes=len(shapes[rule]),
                       candidates_with_whole_leg_price_support=quote_support[rule] if comparable_price else None,
                       candidates_with_whole_leg_support_before_quote_minute=(
                           strict_quote_support[rule] if comparable_price else None))
            for rule in RULES}


def study(session, market):
    stored = verified_json(TOUCH, TOUCH_SHA)["cases"]
    glass, coal, anchor, glass_oct = (verified_json(*ref) for ref in (GLASS, COAL, COAL_ANCHOR, GLASS_OCTOBER))
    quotes = scoped_input_quotes()
    frozen_cases = {name: dict(
        contract=c["contract"], day=c["trading_day"], start=c["start"], cutoff=c["cut"], band=c["band"],
        side=c["side"], market=c["market"], source=c["plan"]["id"], visible=c["visible_leg"],
    ) for name, c in stored.items()}
    july = coal["cases"]["JM2509"]
    junes = glass["june"]["before_lock_report"]
    july_glass = glass["july"]
    october_glass = glass_oct["cases"]["FG2701/2026-10-16"]
    frozen_cases |= {
        "glass_lock_report": dict(contract="FG2609", day="2026-06-15", start=junes["start"],
            cutoff=junes["cutoff_exclusive"], market=glass["market_digests"]["2026-06-15"],
            side="LONG", band=None, source="S5309094833425065"),
        "glass_july_reference": dict(contract="FG2609", day="2026-07-08", start=july_glass["start"],
            cutoff=july_glass["cutoff_exclusive"], market=glass["market_digests"]["2026-07-08"],
            side="LONG", band=("957", "960"), source="S5318448139471722"),
        "glass_october_reference": dict(contract="FG2701", day="2026-10-16", start="2026-10-15T21:00+08:00",
            cutoff=october_glass["cutoff_exclusive"], market=october_glass["market"],
            side="LONG", band=("855", "861"), source="S5354685196405809"),
        "coal_july_ebar": dict(contract="JM2509", day=july["day"], start=july["start"],
            cutoff=july["cutoff"], market=july["periods"], side="SHORT", band=july["band"].split(),
            source=july["source"]),
    }
    cases = {}
    loaded = {}
    for name, cfg in frozen_cases.items():
        contract, day = cfg["contract"], date.fromisoformat(cfg["day"])
        if (contract, day) not in loaded:
            loaded[contract, day] = read_window(session, market, contract, day)
        series = loaded[contract, day]
        fingerprints = {f"{p}m": digest(rows) for p, rows in series.items()}
        expected = {p: v["sha256"] if isinstance(v, dict) else v for p, v in cfg["market"].items()}
        if fingerprints != expected:
            raise ValueError("LOCATION_MARKET_CHANGED")
        start, cutoff = (datetime.fromisoformat(cfg[k]) for k in ("start", "cutoff"))
        band = tuple(map(Decimal, cfg["band"])) if cfg["band"] is not None else None
        if band is not None and (len(band) != 2 or not band[0] <= band[1]):
            raise ValueError("LOCATION_INVALID_BAND")
        timelines, checks = case_rows(series, start, cutoff, cfg["side"])
        if name in stored and any(
            [e["available_at"].isoformat() for e in events]
            != [datetime.fromisoformat(e["available_at"]).isoformat() for e in stored[name]["variants"][variant]]
            for variant, events in timelines.items()
        ):
            raise ValueError("LOCATION_GEOMETRY_FROZEN_CHANGED")
        minutes = completed(series[1], start, cutoff)
        observed = cfg.get("visible")
        anchors = []
        if observed:
            image = observed["image"]
            if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
                raise ValueError("LOCATION_SNAPSHOT_CHANGED")
            row = quotes[observed["source"], contract]
            mark = Decimal(row["mark"])
            anchors = [b.end for b in minutes if b.low <= mark <= b.high]
            lots, tick = observed["quantity"], Decimal(observed["tick_size"])
            totals = displayed_tick_totals(Decimal(observed["display_average"]), lots, tick)
            if [totals.start, totals.stop - 1] != observed["displayed_tick_total_interval"]:
                raise ValueError("LOCATION_SNAPSHOT_PRECISION_CHANGED")
        shaped = {p: {b.end: b for b in rows} for p, rows in series.items()}
        enriched = []
        for variant, events in timelines.items():
            period = int(variant.split("m", 1)[0])
            for event in events:
                bar = shaped[period][event["shape_end"]]
                through_quote = before_quote = None
                if observed and anchors:
                    after_confirm = [b for b in minutes if event["available_at"] < b.start]
                    through_quote = sum(0 in earlier_lot_counts(None, tick_bounds([
                        b for b in after_confirm if b.end <= end
                    ], tick), lots, totals) for end in anchors)
                    before_quote = sum(0 in earlier_lot_counts(None, tick_bounds([
                        b for b in after_confirm if b.end < end
                    ], tick), lots, totals) for end in anchors)
                enriched.append(event | dict(variant=variant, shape_ohlc=[bar.open, bar.high, bar.low, bar.close],
                    placement=location_flags(bar, event["close"], band) if band else None,
                    same_row_quote_price_support_count=through_quote,
                    prior_to_quote_minute_price_support_count=before_quote))
        cases[name] = dict(contract=contract, source=cfg["source"], band=band, direction=cfg["side"],
                           market=fingerprints, observation_cutoff=cutoff, strict_prefix_checks=checks,
                           visible_leg=observed, candidate_quote_count=len(anchors),
                           by_rule=recount(enriched, comparable_price=bool(anchors)) if band else None,
                           events=enriched)

    series = read_window(session, market, "JM2509", date(2025, 7, 22))
    anchor_market = {f"{p}m": dict(count=len(rows), sha256=sha(encoded([
        (b.start, b.end, b.open, b.high, b.low, b.close) for b in rows
    ]).encode())) for p, rows in series.items()}
    if anchor_market != anchor["market"] or sha(SOURCE_INDEX.read_bytes()) != anchor["source_index_sha256"]:
        raise ValueError("LOCATION_COAL_ANCHOR_CHANGED")
    by_end = {b.end: b for b in series[5]}
    shape, confirm = (by_end[at(f"2025-07-22T09:{minute}")] for minute in ("10", "15"))
    level = Decimal("991.5")
    one_sided = dict(contract="JM2509", sources=["H06", "H11", "H12"], shape_end=shape.end,
                     reference=level, shape_wholly_above=shape.low > level,
                     shape_ohlc=[shape.open, shape.high, shape.low, shape.close], confirmation_end=confirm.end,
                     confirmation_close_above=confirm.close > level, confirmation_close=confirm.close,
                     anchor_report_sha256=COAL_ANCHOR[1], identification="ONE_SIDED_REFERENCE_NOT_A_BAND")
    return dict(version="lms405-protection-location-audit-v1", cases=cases, labeled_coal_proxy=one_sided,
                author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False)


def main():
    parser = ArgumentParser(description=__doc__)
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (InvalidOperation, KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("LOCATION_")
                        else "LOCATION_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
