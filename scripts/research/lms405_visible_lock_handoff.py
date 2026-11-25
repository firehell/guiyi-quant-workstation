"""Compare post-snapshot handoffs with a visible two-leg research seed."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff, HandoffConfirmation, assess_handoff
from guiyi_quant.lms405.public_conditions import Condition
from lms405_counter_m_study import beyond
from lms405_m_permission_study import completed_paths
from lms405_portfolio_replay import ARCHIVE, EVIDENCE, input_sources
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded, sha

DAY = date(2026, 10, 28)
NIGHT = "WRoEvasxQR"
CASES = {
    # Short bands are author targets, tested here only as a recovery proxy.
    "I2701": ("U03", "A5358686423089344", NIGHT, "654 662.5", "675 677.5"),
    "RU2701": (NIGHT, "A5358686695981271", "WRoLeVhPQ1", "19090 19200", "19515 19610"),
    "SH2701": (NIGHT, "A5358686695981271", "WRoLeVhPQ1", "1450 1460", "1513 1523"),
}


def stamp(source):
    return datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0)


def market_paths(series, side, band, start, cut):
    scoped = {period: completed(rows, start, cut) for period, rows in series.items()}
    minutes = scoped[1]
    with_predecessor = {bar.end for previous, bar in zip(minutes, minutes[1:]) if previous.end == bar.start}
    thresholds = dict(zip(("near", "far"), band if side == "LONG" else band[::-1], strict=True))
    paths = {key: completed_paths(minutes, price, side) for key, price in thresholds.items()}
    groups = {}
    for shape, confirmation in VARIANTS:
        entries = []
        for event in signals(scoped, shape, confirmation, side=side, start=start, cut=cut):
            shape_start = event["shape_end"] - shape * ONE
            checks = {}
            for key, price in thresholds.items():
                first, active = paths[key][event["confirmed_at"]]
                first = first if first is not None and first + US < event["available_at"] else None
                active = active if active is not None and active + US < shape_start else None
                checks[key] = dict(prior_strict_close=first, current_run_before_shape=active,
                                   current_run_started_with_new_crossing=active in with_predecessor if active else None,
                                   still_beyond=beyond(event["close"], price, side))
            entries.append(event | dict(shape_start=shape_start, shape_minutes=shape,
                                        confirmation_minutes=confirmation, checks=checks))
        groups[f"{shape}m_to_{confirmation}m"] = entries
    return dict(groups=groups, edges={key: dict(
        price=price, first_strict_close=paths[key][minutes[-1].end][0] if minutes else None,
    ) for key, price in thresholds.items()})


def compare_paths(series, side, band, start, cut):
    full = market_paths(series, side, band, start, cut)
    cuts = {row["available_at"] for rows in full["groups"].values() for row in rows}
    cuts.update(edge["first_strict_close"] + US for edge in full["edges"].values()
                if edge["first_strict_close"] is not None)
    for split in sorted(cuts):
        prefix = {p: [bar for bar in rows if bar.end + US < split] for p, rows in series.items()}
        prior = market_paths(prefix, side, band, start, split)
        for variant, rows in full["groups"].items():
            if prior["groups"][variant] != [row for row in rows if row["available_at"] < split]:
                raise ValueError("LOCK_HANDOFF_PREFIX_CHANGED")
        for key, edge in full["edges"].items():
            first = edge["first_strict_close"]
            expected = first if first is not None and first + US < split else None
            if prior["edges"][key]["first_strict_close"] != expected:
                raise ValueError("LOCK_HANDOFF_EDGE_PREFIX_CHANGED")
    return full | dict(checked_prefixes=len(cuts))


def position_view(position):
    return dict(long=position.long, short=position.short,
                gross=position.long + position.short, net=position.long - position.short)


def branch_position(request, source, start, cut, side_paths):
    """Keep missing author facts unasserted and model only market-supported what-ifs."""
    unresolved = assess_handoff(request, (), as_of=cut, source=source,
                                source_available_at=start, version_405=None)
    rows = sorted((row for events in side_paths["groups"].values() for row in events
                   if row["available_at"] < cut),
                  key=lambda row: row["available_at"])
    is_counter = request.route == "COUNTER_M_FROM_LOCK"
    # Original-side shape alone is a loose alternative. Counter M adds a near-edge price gate.
    candidate = next((row for row in rows if not is_counter or
                      (row["checks"]["near"]["prior_strict_close"] is not None
                       and row["checks"]["near"]["still_beyond"])), None)
    same_run = {edge: next((row for row in rows if row["checks"][edge]["current_run_before_shape"] is not None), None)
                for edge in side_paths["edges"]}
    new_crossing = {edge: next((row for row in rows if row["checks"][edge]["current_run_started_with_new_crossing"]), None)
                    for edge in side_paths["edges"]}
    result = dict(unresolved_assessment_with_assumed_position=unresolved, weak_market_candidate=candidate,
                  same_run_market_candidates=same_run, new_crossing_market_candidates=new_crossing,
                  test_fixture=None)
    if candidate is None:
        return result
    signal_at = candidate["confirmed_at"]
    signal_known = candidate["available_at"]
    fixture_source = f"TEST_FIXTURE:{source}"

    def fact(name, at, known):
        return Condition(name, request.scope, request.before.contract, True, at, known,
                         fixture_source, "EVENT_TIME")

    facts = [fact("POSITION_PATH_CONFIRMED", start, start), fact("SIGNAL", signal_at, signal_known)]
    if is_counter:
        first = candidate["checks"]["near"]["prior_strict_close"]
        facts += [fact("M_CONFIG_PERMITS", start, start), fact("INTERRUPTION", first, first + US)]
    else:
        facts.append(fact("ORIGINAL_PLAN_VALID", start, start))
    decision = signal_known + US
    if decision + US >= cut:
        return result
    approval = HandoffConfirmation(request.confirmation_scope(fixture_source, start, True),
                                   f"fixture:{request.scope}", True, decision, decision, "TEST_FIXTURE")
    fixture = assess_handoff(request, tuple(facts), as_of=decision + US, source=fixture_source,
                             source_available_at=start, version_405=True, approval=approval,
                             allow_test_fixture=True)
    if fixture["after"] is None:
        raise ValueError("LOCK_HANDOFF_QUALIFIED_FIXTURE_REJECTED")
    result["test_fixture"] = fixture
    return result


def read_evidence():
    index = input_sources()
    with ARCHIVE.open(newline="", encoding="utf-8") as stream:
        archive = {row["source_id"]: row for row in csv.DictReader(stream)}
    keys = sorted({key for spec in CASES.values() for key in spec[:3]})
    sources = {}
    for key in keys:
        row = archive[key]
        image_paths = list(filter(None, row["images"].split(";")))
        image_hashes = list(filter(None, row["sha256"].split(";")))
        images = [dict(path=path, sha256=hash_value)
                  for path, hash_value in zip(image_paths, image_hashes, strict=True)]
        sources[key] = index[key] | dict(observed_at=row["observed_at"], images=images,
                                        archive_sha256=sha((ARCHIVE.parent / row["path"]).read_bytes()))
    inputs = {}
    for name in ("portfolio-oct-observations.json", "portfolio-oct-leg-fields.json"):
        raw = (EVIDENCE / "evidence" / name).read_bytes()
        inputs[name] = dict(sha256=sha(raw), rows=json.loads(raw))
    return sources, inputs


def visible_seed(contract, key, inputs, sources):
    observations = inputs["portfolio-oct-observations.json"]["rows"]["snapshots"]
    row, = (row for row in observations if row["source"] == key and contract in row["legs"])
    tables = inputs["portfolio-oct-leg-fields.json"]["rows"]["tables"]
    table, = (t for t in tables if t["source"] == key and t["table"] == row["table"])
    fields = table["fields"][contract]
    quantities = row["legs"][contract]
    if set(quantities) != {"long", "short"} or quantities["long"] != quantities["short"] or fields["short"][1] != 0:
        raise ValueError("LOCK_HANDOFF_VISIBLE_SEED_CHANGED")
    source = sources[key]
    image, = (record for record in source["images"] if Path(record["path"]).name == table["image"])
    if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
        raise ValueError("LOCK_HANDOFF_IMAGE_HASH_CHANGED")
    return Position(contract, Decimal(quantities["long"]), Decimal(quantities["short"])), dict(
        image=image, table=row["table"], system=row["system"], binding=row["binding"], fields=fields,
        role_assumption="OLDER_SHORT_IS_ORIGINAL_AND_BOTH_LEGS_CARRY_TO_WINDOW",
        capture_at=None, account_continuity=None,
    )


def study(session, market):
    sources, inputs = read_evidence()
    cases = {}
    for contract, (key, plan, followup, short_band, m_band) in CASES.items():
        position, seed = visible_seed(contract, key, inputs, sources)
        start = max(stamp(sources[key]), stamp(sources[plan])) + ONE
        cut = stamp(sources[followup])
        if start >= cut:
            raise ValueError("LOCK_HANDOFF_WINDOW_CHANGED")
        series = read_window(session, market, contract, DAY)
        results = {}
        for route, side, raw_band in (("RESUME_ORIGINAL", "SHORT", short_band),
                                     ("COUNTER_M_FROM_LOCK", "LONG", m_band)):
            band = tuple(map(Decimal, raw_band.split()))
            paths = compare_paths(series, side, band, start, cut)
            identity = f"visible:{key}:{contract}"
            next_id = f"{identity}:counter-m" if side == "LONG" else None
            request = Handoff(route, position, "SHORT", f"{identity}:plan", f"{identity}:cycle",
                              next_id, start, start)
            role = "M_REGION_CLOSE_AS_INTERRUPTION_PROXY" if side == "LONG" else "SHORT_TARGET_AS_RECOVERY_PROXY"
            results[route] = dict(paths=paths, threshold_role=role,
                                  **branch_position(request, sources[plan]["source_url"], start, cut, paths))
        cases[contract] = dict(start=start, cut_exclusive=cut, seed_source=key, plan_source=plan,
                               followup_source=followup, seed=seed,
                               no_accepted_transition_assumed_state=position_view(position), branches=results,
                               market={f"{p}m": dict(bars=len(rows), sha256=digest(rows)) for p, rows in series.items()},
                               analyzed_minutes=len(completed(series[1], start, cut)),
                               author_action_at=None)
    return dict(version="lms405-visible-lock-handoff-v1", trade_day=DAY.isoformat(),
                time_scope="RETROSPECTIVE_PUBLICATION_MINUTE_BOUND_EDIT_HISTORY_UNVERIFIED",
                observed_source_and_model_times_are_distinct=True,
                input_sha256={key: item["sha256"] for key, item in inputs.items()},
                sources=sources, cases=cases, admitted_author_actions=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


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
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('LOCK_HANDOFF_') and code.isidentifier() else 'LOCK_HANDOFF_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
