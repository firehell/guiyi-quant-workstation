"""Audit the distance from displayed positions to documented protective regions."""

import argparse
from datetime import datetime, timedelta
from decimal import InvalidOperation
import json
from pathlib import Path

from lms405_portfolio_replay import BOOK, input_sources
from lms405_replay import ohlc, read_session_series
from lms405_sizing_audit import EXPOSURE_SHA256, HALF_LOT, SPECS, load_specs, positive_decimal
from lms_near405_replay import encoded, sha

BANDS = BOOK.with_name("portfolio-oct-protection-bands.json")
ONE = timedelta(minutes=1)


def band_distance(reference, band, quantity, multiplier):
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("DISPLAYED_SHORT_QUANTITY_REQUIRED")
    lower, upper = map(positive_decimal, band)
    if lower >= upper:
        raise ValueError("INVALID_PROTECTION_BAND")
    adverse = ((lower - reference) * multiplier, (upper - reference) * multiplier)
    if adverse[1] < 0:
        relation = "ENTIRE_BAND_BELOW_REFERENCE"
    elif adverse[0] > 0:
        relation = "ENTIRE_BAND_ABOVE_REFERENCE"
    else:
        relation = "REFERENCE_IN_OR_ON_BAND"
    return dict(
        reference=reference, band=[lower, upper], short_quantity=quantity,
        relation=relation, signed_short_leg_cost=[point * quantity for point in adverse],
        target_envelope=(
            [adverse[0] * (quantity - HALF_LOT), adverse[1] * (quantity + HALF_LOT)]
            if relation == "ENTIRE_BAND_ABOVE_REFERENCE" else None
        ),
    )


def included_target(rows):
    usable = [(contract, row["target_envelope"]) for contract, row in sorted(rows.items())
              if row["comparison_status"] == "RESEARCH_COMPARABLE"]
    if len(usable) < 2:
        return dict(contracts=[contract for contract, _ in usable], common_budget_possible=None)
    high, low = max(band[0] for _, band in usable), min(band[1] for _, band in usable)
    return dict(contracts=[contract for contract, _ in usable], required_minimum=high,
                allowed_maximum=low, common_budget_possible=high <= low)


def row_for_band(table, contract, band, reference, spec, sources, as_of):
    source = sources[band["source"]]
    published = datetime.fromisoformat(source["published_at"])
    if published + ONE > as_of:
        raise ValueError("PROTECTION_BAND_NOT_PRIOR_TO_REFERENCE")
    later_id = band.get("later_source")
    later = sources[later_id] if later_id else None
    if later and not published < datetime.fromisoformat(later["published_at"]) <= as_of - ONE:
        raise ValueError("LATER_PLAN_TIMESTAMP_UNVERIFIED")
    holding = table["contracts"][contract]
    short = holding["legs"]["short"]
    result = band_distance(reference, band["band"], short["quantity"], spec["multiplier"])
    return result | dict(
        band_source=band["source"], band_published_at=source["published_at"], band_url=source["source_url"],
        band_scope=band.get("scope", "CURRENT_VISIBLE_EARLIER_ARTICLE"),
        later_source=later_id, later_published_at=later["published_at"] if later else None,
        paired_leg_shown=holding["pair"] is not None,
        displayed_opening_average=short["opening_average"],
    )


def inspect(exposure, inputs, specs, sources, market_quotes):
    tables = {t["source"]: t for t in exposure["tables"]}
    opening = tables[inputs["opening_average_screen"]]
    cost_rows = {}
    for contract, band in inputs["opening_average_bands"].items():
        holding = opening["contracts"][contract]
        if holding["pair"]["older_side_by_today_field"] != "short":
            raise ValueError("OLDER_SHORT_LEG_NOT_VERIFIED")
        cost_rows[contract] = row_for_band(
            opening, contract, band, positive_decimal(holding["legs"]["short"]["opening_average"]),
            specs[contract], sources, datetime.fromisoformat(opening["published_at"]),
        )

    snapshots = []
    for screen in inputs["quote_screens"]:
        table = tables[screen["source"]]
        quote_anchor = datetime.fromisoformat(table["quote_anchor"])
        if not quote_anchor < datetime.fromisoformat(table["published_at"]):
            raise ValueError("QUOTE_ANCHOR_NOT_PRIOR_TO_POST")
        rows = {}
        for contract, raw in screen["quotes"].items():
            mark = positive_decimal(raw)
            local_close = market_quotes.get((contract, quote_anchor))
            if local_close != mark:
                rows[contract] = dict(
                    comparison_status="QUOTE_ANCHOR_NOT_VERIFIED",
                    displayed_price=mark, local_close=local_close,
                )
                continue
            result = row_for_band(table, contract, inputs["same_time_bands"][contract], mark,
                                  specs[contract], sources, quote_anchor)
            if result["band_scope"] == "OLDER_BAND_SENSITIVITY":
                status = "EARLIER_BAND_EFFECTIVITY_UNKNOWN"
            elif result["target_envelope"] is None:
                status = "NO_FULL_ADVERSE_BAND_AT_REFERENCE"
            else:
                status = "RESEARCH_COMPARABLE"
            rows[contract] = result | dict(comparison_status=status)
        snapshots.append(dict(
            source=table["source"], source_url=table["source_url"], image=table["image"],
            binding=table["binding"], quote_anchor=table["quote_anchor"], contracts=rows,
            common_target_test=included_target(rows),
        ))
    return dict(
        version="lms405-oct-protection-distance-v1",
        opening_average=dict(source=opening["source"], source_url=opening["source_url"], contracts=cost_rows),
        same_time_single_short_leg_counterfactual=snapshots,
        price_effectivity="RETROSPECTIVE_EARLIER_CURRENT_VISIBLE_TEXT",
        original_entry_risk=None, account_net_risk=None, author_budget=None,
        actual_lock_price=None, executable=False,
    )


def read_quotes(session, market, exposure, inputs):
    tables = {t["source"]: t for t in exposure["tables"]}
    anchors = {datetime.fromisoformat(tables[row["source"]]["quote_anchor"]) for row in inputs["quote_screens"]}
    days = tuple(sorted({anchor.date() for anchor in anchors}))
    contracts = {c for row in inputs["quote_screens"] for c in row["quotes"]}
    quotes, windows = {}, {}
    for contract in sorted(contracts):
        bars = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, days)
        quotes.update({(contract, bar.bar_end): bar.close for bar in bars if bar.bar_end in anchors})
        windows[contract] = dict(count=len(bars), sha256=sha(encoded([
            (bar.bar_end.isoformat(), *map(str, ohlc(bar))) for bar in bars
        ]).encode()))
    return quotes, windows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--exposure-audit", type=Path, required=True)
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
        raw_exposure, raw_bands, raw_specs = args.exposure_audit.read_bytes(), BANDS.read_bytes(), SPECS.read_bytes()
        if sha(raw_exposure) != EXPOSURE_SHA256:
            raise ValueError("EXPOSURE_AUDIT_HASH_MISMATCH")
        exposure, inputs = json.loads(raw_exposure), json.loads(raw_bands)
        specs, sources = load_specs(json.loads(raw_specs)), input_sources()
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            quotes, windows = read_quotes(session, build_market_data_service(session), exposure, inputs)
        report = inspect(exposure, inputs, specs, sources, quotes)
        report["market_1m"] = windows
        report["input_sha256"] = dict(exposure=sha(raw_exposure), bands=sha(raw_bands), spec_sources=sha(raw_specs))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as error:
        parser.exit(2, f"MDS_BLOCKED: {error.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
