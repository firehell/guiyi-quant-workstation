"""Compare visible LMS holdings against fixture states at verified quote anchors."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from guiyi_quant.lms405 import timestamp
from lms405_portfolio_replay import BOOK
from lms405_replay import ohlc, read_session_series
from lms405_sizing_audit import EXPOSURE_SHA256, positive_decimal
from lms_near405_replay import encoded, sha

QUOTES = BOOK.with_name("portfolio-oct-aligned-quotes.json")
SIZED_SHA256 = "4f06124f6ad5c648738496d51460bac51e8c2b6e24c4fea768dcf85f4687c76d"
RESPONSE_DELAY = timedelta(microseconds=2)
ONE = timedelta(minutes=1)
SIDES = ("long", "short")


def indexed_snapshots(exposure, inputs):
    tables = {(t["source"], t["table"]): t for t in exposure["tables"]}
    if len(tables) != len(exposure["tables"]):
        raise ValueError("DUPLICATE_EXPOSURE_TABLE")
    snapshots = []
    for row in inputs["snapshots"]:
        table = tables[row["source"], row["table"]]
        anchor = datetime.fromisoformat(table["quote_anchor"])
        timestamp(anchor)
        if not anchor < datetime.fromisoformat(table["published_at"]):
            raise ValueError("QUOTE_ANCHOR_NOT_BEFORE_POST")
        if row["quotes"].keys() != table["contracts"].keys():
            raise ValueError("QUOTE_SCOPE_DOES_NOT_COVER_VISIBLE_CONTRACTS")
        snapshots.append((table, anchor, row["quotes"]))
    return snapshots


def visible_leg_checks(author, model):
    checks = {}
    for side in SIDES:
        observed = author.get(side, {}).get("quantity")
        projected = model[side]
        if observed is None:
            status = "AUTHOR_LEG_UNKNOWN"
        elif projected is None:
            status = "MODEL_SIZE_UNKNOWN"
        elif Decimal(observed) == Decimal(projected):
            status = "VISIBLE_QUANTITY_AGREES"
        else:
            status = "VISIBLE_QUANTITY_DIFFERS"
        checks[side] = dict(author_visible=observed, projected_lots=projected, status=status)
    return checks


def compare_state(author, actions):
    last = actions[-1] if actions else None
    model = last["after"] if last else dict(long="0", short="0", net="0", gross="0")
    checks = visible_leg_checks(author, model)
    results = {leg["status"] for leg in checks.values()}
    if "VISIBLE_QUANTITY_DIFFERS" not in results:
        status = "UNRESOLVED" if "MODEL_SIZE_UNKNOWN" in results else "VISIBLE_LEGS_AGREE_ONLY"
    elif not actions:
        status = "NO_MODEL_ENTRY_BEFORE_ANCHOR"
    elif model["gross"] == "0":
        status = "MODEL_CLEARED_BEFORE_ANCHOR"
    elif len(author) == 2 and any(model_side == "0" for model_side in (model["long"], model["short"])):
        status = "MODEL_SINGLE_LEG_AUTHOR_SHOWS_BOTH"
    elif any(side in author and model[side] == "0" for side in SIDES):
        status = "MODEL_MISSING_VISIBLE_DIRECTION"
    else:
        status = "VISIBLE_SIZE_DIFFERENCE"
    return dict(
        classification=status, legs=checks, projected_position=model,
        last_action=last, earlier_model_locks=sum(a["action"] == "LOCK" for a in actions),
    )


def old_leg_recurrence(first, contract, visible):
    prior = first["contracts"].get(contract, {}).get("legs", {})
    return [side for side, leg in visible.items()
            if (earlier := prior.get(side))
            and earlier["today_quantity"] == 0
            and earlier["quantity"] == leg["quantity"]
            and earlier["opening_average"] is not None and leg["opening_average"] is not None
            and Decimal(earlier["opening_average"]) == Decimal(leg["opening_average"])]


def study(exposure, sized, inputs, market):
    if sized["fixture_only"] is not True or sized["executable"] is not False:
        raise ValueError("FROZEN_FIXTURE_REQUIRED")
    (first,) = [row for row in exposure["tables"] if row["source"] == inputs["first_night_older_leg_screen"]]
    first_post = datetime.fromisoformat(first["published_at"])
    windows = sized["windows"]["development"]
    aligned = []
    for table, anchor, displayed_quotes in indexed_snapshots(exposure, inputs):
        if first_post + ONE >= anchor:
            raise ValueError("FIRST_NIGHT_IMAGE_UNAVAILABLE_AT_ANCHOR")
        rows = {}
        for contract, raw_quote in displayed_quotes.items():
            quote = positive_decimal(raw_quote)
            close = market.get((contract, anchor))
            visible = table["contracts"][contract]["legs"]
            row = rows[contract] = dict(displayed_quote=quote, mds_close=close, quote_aligned=quote == close,
                                        author_visible_legs=visible, variants={})
            if quote != close:
                continue
            row["same_fields_on_first_night_older_legs"] = old_leg_recurrence(first, contract, visible)
            for variant, window in windows.items():
                if datetime.fromisoformat(window["as_of"]) < anchor + RESPONSE_DELAY:
                    raise ValueError("FIXTURE_COVERAGE_INSUFFICIENT")
                prior, response = [], []
                for batch in window["timeline"]:
                    action_at = datetime.fromisoformat(batch["at"])
                    if action_at > anchor + RESPONSE_DELAY:
                        break
                    seen = prior if action_at < anchor else response
                    seen.extend(a | {"at": batch["at"]} for a in batch["actions"] if a["contract"] == contract)
                row["variants"][variant] = dict(
                    before_quote_close=compare_state(visible, prior),
                    quote_close_response_actions=response,
                    through_quote_close_response=compare_state(visible, prior + response),
                )
        aligned.append(dict(
            source=table["source"], source_url=table["source_url"], image=table["image"],
            binding=table["binding"], quote_anchor=table["quote_anchor"],
            source_published_at=table["published_at"], contracts=rows,
        ))
    baseline = [row["variants"]["BASELINE"]["before_quote_close"] for snap in aligned
                for row in snap["contracts"].values() if row["quote_aligned"]]
    return dict(
        version="lms405-visible-snapshot-comparison-v1", snapshots=aligned,
        first_night_source=first["source"], first_night_source_url=first["source_url"],
        known_at_policy="MODEL_ACTIONS_STRICTLY_BEFORE_QUOTE_CLOSE; RESPONSE_THROUGH_CLOSE_PLUS_2US_SEPARATE",
        visible_baseline_classifications=dict(Counter(row["classification"] for row in baseline)),
        account_identity=None, first_night_position_continuity=None, author_action_matches=None,
        admitted_author_action_samples=0, fills=None, pnl=None, executable=False,
    )


def read_quotes(session, market, snapshots):
    by_contract_day = defaultdict(set)
    for _, anchor, quotes in snapshots:
        for contract in quotes:
            by_contract_day[contract, anchor.date()].add(anchor)
    prices, coverage = {}, {}
    for (contract, trading_day), anchors in sorted(by_contract_day.items()):
        bars = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (trading_day,))
        prices.update({(contract, bar.bar_end): bar.close for bar in bars if bar.bar_end in anchors})
        coverage[f"{contract}:{trading_day.isoformat()}"] = dict(
            count=len(bars),
            sha256=sha(encoded([(bar.bar_end.isoformat(), *map(str, ohlc(bar))) for bar in bars]).encode()),
        )
    return prices, coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--exposure-audit", type=Path, required=True)
    parser.add_argument("--sized-replay", type=Path, required=True)
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
        raw_exposure, raw_sized, raw_quotes = args.exposure_audit.read_bytes(), args.sized_replay.read_bytes(), QUOTES.read_bytes()
        if sha(raw_exposure) != EXPOSURE_SHA256 or sha(raw_sized) != SIZED_SHA256:
            raise ValueError("FROZEN_INPUT_HASH_MISMATCH")
        exposure, sized, inputs = (json.loads(raw) for raw in (raw_exposure, raw_sized, raw_quotes))
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            prices, coverage = read_quotes(session, market, indexed_snapshots(exposure, inputs))
        result = study(exposure, sized, inputs, prices)
        result["market_1m"] = coverage
        result["input_sha256"] = dict(exposure=sha(raw_exposure), sized_replay=sha(raw_sized), quotes=sha(raw_quotes))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as error:
        parser.exit(2, f"MDS_BLOCKED: {error.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
