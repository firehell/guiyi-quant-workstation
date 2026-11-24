"""Run the frozen LMS candidate per contract and align separate source observations."""

import argparse
from collections import defaultdict
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar, physical_contract, timestamp
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha, summarize

LOCAL = ZoneInfo("Asia/Shanghai")
DAYS = tuple(date(2026, 10, day) for day in (23, 26, 27, 28))
CONTRACTS = ("OI2701", "RU2701", "JM2701", "FG2701", "SA2701", "V2701", "TA2701", "SH2701", "I2701")
FIVE = timedelta(minutes=5)
BOOK = Path("docs/research/lms405/evidence/portfolio-oct-observations.json")
ARCHIVE = Path("docs/research/lms-source-archive/index.csv")
EVIDENCE = Path("docs/research/lms405")


def input_sources():
    index = {}
    specs = (
        (ARCHIVE, "source_id", "published_at", "edited"),
        (EVIDENCE / "sources.csv", "id", "published", "edited"),
        (EVIDENCE / "evidence/author-control-20261016.csv", "id", "published", "edited"),
    )
    for path, key, published, edited in specs:
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if not row.get(published) or not row.get("url"):
                    continue
                try:
                    when = datetime.fromisoformat(row[published])
                except ValueError:
                    # Some background sources have dates expressed as ranges.
                    continue
                if when.tzinfo is None:
                    when = when.replace(tzinfo=LOCAL)
                index[row[key]] = dict(
                    source_url=row["url"], published_at=when.isoformat(),
                    edited=row.get(edited) or None, archive_path=row.get("path"),
                )
    return index


def visible_legs(legs):
    if set(legs) - set(CONTRACTS):
        raise ValueError("OBSERVATION_CONTRACT_OUTSIDE_PORTFOLIO")
    result = {}
    for symbol in CONTRACTS:
        sides = legs.get(symbol, {})
        if set(sides) - {"long", "short"}:
            raise ValueError("OBSERVATION_SIDE_INVALID")
        if any(q is not None and (type(q) is not int or q <= 0) for q in sides.values()):
            raise ValueError("OBSERVATION_QUANTITY_INVALID")
        known = [Decimal(q) for q in sides.values() if q is not None]
        complete = len(known) == 2
        result[symbol] = dict(
            long_shown="long" in sides, short_shown="short" in sides,
            long=sides.get("long"), short=sides.get("short"),
            visible_gross_lower_bound=str(sum(known)) if known else None,
            displayed_signed_net=str(Decimal(sides["long"]) - sides["short"]) if complete else None,
        )
    return result


def observation_events(book, sources, *, as_of):
    events = []
    identities = set()
    for kind, key in (("HOLDINGS_DISPLAY", "snapshots"), ("AUTHOR_TEXT", "notices")):
        for row in book[key]:
            source = sources[row["source"]]
            published = datetime.fromisoformat(source["published_at"])
            timestamp(published)
            available = published + timedelta(minutes=1)
            identity = (kind, row["source"], row.get("table"), row.get("contract"))
            if identity in identities:
                raise ValueError("DUPLICATE_OBSERVATION")
            identities.add(identity)
            if not available < as_of:
                continue
            data = {k: v for k, v in row.items() if k != "legs"}
            if kind == "HOLDINGS_DISPLAY":
                data["positions"] = visible_legs(row["legs"])
                if row.get("quote_anchor") and datetime.fromisoformat(row["quote_anchor"]) > published:
                    raise ValueError("QUOTE_ANCHOR_AFTER_PUBLICATION")
            elif row["contract"] is not None:
                physical_contract(row["contract"])
            events.append(dict(
                time=available.isoformat(), layer=kind,
                payload=data | source | dict(action_at=None, author_action_verified=False),
            ))
    return events


def unit_positions(positions):
    return dict(
        locked_products=sum(long > 0 and short > 0 for long, short in positions.values()),
        directional_products=sum((long > 0) != (short > 0) for long, short in positions.values()),
        total_legs_units=str(sum(long + short for long, short in positions.values())),
    )


def batch_fixture_transitions(transitions):
    known = defaultdict(list)
    positions = {contract: (Decimal(0), Decimal(0)) for contract in CONTRACTS}
    for row in transitions:
        if row["record_kind"] != "TEST_FIXTURE":
            raise ValueError("FIXTURE_TRANSITION_REQUIRED")
        known[datetime.fromisoformat(row["known_at"])].append(row)
    batches = []
    for at, rows in sorted(known.items()):
        actions = []
        seen = set()
        for row in sorted(rows, key=lambda v: v["before"]["contract"]):
            before, after = row["before"], row["after"]
            contract = before["contract"]
            start = Decimal(before["long"]), Decimal(before["short"])
            end = Decimal(after["long"]), Decimal(after["short"])
            if contract in seen or contract != after["contract"] or positions[contract] != start:
                raise ValueError("INCONSISTENT_FIXTURE_STATE")
            seen.add(contract)
            positions[contract] = end
            actions.append(dict(
                contract=contract, action=row["action"], reason=row["reason"],
                before=list(map(str, start)), after=list(map(str, end)), proposal_id=row["proposal_id"],
                before_cycle=before.get("cycle_id"), after_cycle=after.get("cycle_id"),
            ))
        batches.append(dict(
            time=at.isoformat(), layer="FIXTURE_STATE_BATCH",
            payload=dict(actions=actions, portfolio_units=unit_positions(positions)),
        ))
    return batches, positions


def replay_portfolio(inputs, book, sources, *, as_of, timely_fixture=False):
    timestamp(as_of)
    if set(inputs) != set(CONTRACTS):
        raise ValueError("NINE_PHYSICAL_CONTRACTS_REQUIRED")
    events = observation_events(book, sources, as_of=as_of)
    summaries, transitions = {}, []
    for contract in CONTRACTS:
        bars = inputs[contract]
        if not bars or any(b.contract != contract for b in bars):
            raise ValueError("INPUT_CONTRACT_IDENTITY_MISMATCH")
        visible = [b for b in bars if b.end + candidate.US <= as_of]
        if not visible:
            raise ValueError("NO_COMPLETED_BARS_IN_PORTFOLIO_WINDOW")
        result = candidate.replay(visible, as_of=as_of, timely_fixture=timely_fixture)
        summaries[contract] = summarize(result) | dict(
            input_prefix_sha256=sha(encoded([
                [b.end.isoformat(), *(str(value) for value in ohlc(b))] for b in visible
            ]).encode()),
        )
        transitions.extend(result["transitions"])
        events.extend(
            dict(time=p["generated_at"], layer="RESEARCH_PROPOSAL",
                 payload=dict(contract=contract, proposal_id=p["proposal_id"],
                              action=p["action"], reason=p["reason"], side=p["plan"]["side"]))
            for p in result["proposals"]
        )
    batches, terminal = batch_fixture_transitions(transitions)
    for contract, (long, short) in terminal.items():
        state = summaries[contract]["terminal_state"]
        if (Decimal(state["long"]), Decimal(state["short"])) != (long, short):
            raise ValueError("FIXTURE_TERMINAL_STATE_MISMATCH")
    events.extend(batches)
    events.sort(key=lambda row: (datetime.fromisoformat(row["time"]), row["layer"], encoded(row["payload"])))
    return dict(
        contract_summaries=summaries, timeline=events, as_of=as_of.isoformat(),
        fixture=timely_fixture, candidate_version=candidate.VERSION, candidate_rule_hash=candidate.RULE_HASH,
        author_action_matches=None, admitted_author_action_samples=0,
        author_region_mode_status="NO_ADMITTED_FULL_AUTHOR_REGIONS_IN_THIS_WINDOW",
        executable=False, fills=None, pnl=None,
        fixture_terminal_units=unit_positions(terminal) if timely_fixture else None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=datetime.fromisoformat)
    parser.add_argument("--timely-fixture", action="store_true")
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
            market = build_market_data_service(session)
            market_bars = {
                contract: read_session_series(
                    session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS,
                ) for contract in CONTRACTS
            }
        inputs = {
            contract: [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in bars]
            for contract, bars in market_bars.items()
        }
        raw = BOOK.read_bytes()
        book = json.loads(raw)
        catalog = input_sources()
        sources = {row["source"]: catalog[row["source"]]
                   for rows in book.values() for row in rows}
        last = max(bars[-1].end for bars in inputs.values())
        result = replay_portfolio(
            inputs, book, sources,
            as_of=args.as_of or (last + timedelta(microseconds=3)),
            timely_fixture=args.timely_fixture,
        )
        result["source_book_sha256"] = sha(raw)
        result["source_catalog_sha256"] = sha(encoded(sources).encode())
        result["trading_days"] = [d.isoformat() for d in DAYS]
        result["source_authority"] = "PUBLICATION_MINUTE_PLUS_ONE_FOR_ARCHIVE_DISPLAY_ONLY"
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (ValueError, KeyError):
        parser.exit(2, "PORTFOLIO_INPUT_OR_COVERAGE_UNVERIFIED\n")
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded(result))


if __name__ == "__main__":
    main()
