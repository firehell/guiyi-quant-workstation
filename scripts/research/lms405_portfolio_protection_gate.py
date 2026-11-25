"""Compare typed protection references against directional reach in the frozen LMS portfolio."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate, active_band, visible_bands
from lms405_locked_exit_audit import BASELINE_SHA256
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, DAYS, FIVE, batch_fixture_transitions, input_sources
from lms405_protection_lot_timing import EXPOSURE, verified_json
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import digest, signals
from lms405_sizing_audit import EXPOSURE_SHA256
from lms_near405_replay import encoded, sha

VERSION = "lms405-portfolio-protection-price-admission-v1"
BASELINE = Path("output/lms405-portfolio-oct-20261125/fixture.json")
CONTROLS = Path("output/lms405-public-protection-and-m-20261126/final-a.json")
CONTROL_SHA = "0d3068a8a05cf32fa8f4954c413d4d2534d198ea79b5a1915ac5cb92d2cc9cad"
PLANS = (
    ("A5356884629782554", "A5356884885635211", {
        "FG2701": ((829, 836), (842, 844)), "JM2701": (("1382.5", "1397.5"), ("1410.5", 1420)),
        "SA2701": ((931, 936), (942, 945)), "SH2701": ((1610, 1632), (1660, 1668)),
        "RU2701": ((19530, 19680), (19790, 19935)), "I2701": (None, (675, "677.5")),
    }),
    ("A5357264059367516", "A5357264793370945", {
        "FG2701": ((829, 836), (842, 844)), "I2701": ((667, 671), (675, "677.5")),
        "RU2701": ((19530, 19680), (19790, 19935)), "SH2701": ((1595, 1603), (1614, 1628)),
    }),
    ("A5358325549629506", "A5358325972992140", {
        "FG2701": ((829, 836), (842, 844)), "I2701": ((667, 671), (675, "677.5")),
        "RU2701": ((19530, 19680), (19790, 19935)), "SH2701": ((1516, 1529), (1544, 1547)),
    }),
    ("A5358686423089344", "A5358686695981271", {
        "FG2701": ((829, 836), (842, 844)), "I2701": ((667, 671), (675, "677.5")),
        "RU2701": ((19360, 19405), (19515, 19610)), "SH2701": ((1490, 1501), (1513, 1523)),
    }),
)
ALTERNATIVES = {"RU2701", "SH2701", "TA2701"}
OBSERVED_REVIEW = "WRouYm67Bc"
CARRY_SOURCE = "WRov1j6e10"
OPPOSITE = {"LONG": "SHORT", "SHORT": "LONG"}


def plan_rows(index, contract):
    updates, m_by_revision, sources = [], {}, {}
    for regular, alternative, rows in PLANS:
        source_id = alternative if contract in ALTERNATIVES else regular
        source = sources[source_id] = load_source(index, source_id)
        known = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE
        protection, m = rows.get(contract, (None, None))
        # Reviewed references here apply to original shorts only. Plans lacking an
        # identified protection area do not inherit the previous day's area.
        bounds = tuple(Decimal(str(price)) for price in protection) if protection else ()
        updates.append(ProtectionBandUpdate(
            contract, source_id, "PROTECTION" if bounds else "REVIEW_PENDING",
            known, known, source["source_url"], "SHORT", *bounds,
        ))
        if m:
            m_by_revision[source_id] = tuple(Decimal(str(price)) for price in m)
    if contract == "SH2701":
        source = sources[OBSERVED_REVIEW] = load_source(index, OBSERVED_REVIEW)
        known = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE
        updates.append(ProtectionBandUpdate(
            contract, OBSERVED_REVIEW, "REVIEW_PENDING", known, known, source["source_url"], "SHORT",
        ))
    return tuple(updates), m_by_revision, sources


def price_admission(minutes, band, event, *, position_since=None):
    """Read only completed bars from the signal's continuous segment and plan revision."""
    shape_start = event["shape_end"] - FIVE
    known = event["available_at"]
    from_time = max(band.effective_after, position_since) if position_since is not None else band.effective_after
    if from_time >= shape_start:
        return dict(status="PLAN_NOT_KNOWN_BEFORE_SHAPE", loose_due_at=None, ordinary_due_at=None)
    window = []
    for bar in reversed(minutes):
        if bar.end + US >= known:
            continue
        if bar.start < from_time or (window and bar.end != window[-1].start):
            break
        window.append(bar)
    window.reverse()
    lower, upper = band.lower, band.upper
    up = band.side == "SHORT"
    near = lower if up else upper
    reached = next((bar for bar in window if (bar.high >= near if up else bar.low <= near)), None)
    contact = next((bar for bar in window if bar.low <= upper and bar.high >= lower), None)
    inside = lower <= event["close"] <= upper
    starts_beyond = bool(window and (window[0].open > upper if up else window[0].open < lower))
    if reached is None:
        status = "NO_PRIOR_DIRECTIONAL_REACH"
    elif contact is None:
        status = "REACH_WITHOUT_RANGE_CONTACT"
    elif not inside:
        status = "CONFIRMATION_OUTSIDE_PROTECTION_RANGE"
    else:
        status = "ORDINARY_PRICE_CONTEXT"
    return dict(status=status, window_starts_beyond=starts_beyond, confirmation_inside=inside,
                first_contact_at=contact.end if contact else None,
                loose_due_at=reached.end + US if reached else None,
                ordinary_due_at=contact.end + US if status == "ORDINARY_PRICE_CONTEXT" else None)


def observations_for_contract(series, updates, m_bands, cutoff):
    minutes, fives = series[1], series[5]
    events = {}
    for signal_side in ("LONG", "SHORT"):
        for event in signals(series, 5, 5, side=signal_side, start=fives[0].start, cut=cutoff):
            key = event["confirmed_at"], signal_side
            shown = visible_bands(updates, fives[0].contract, event["available_at"])
            area, issue = active_band(shown, event["available_at"], OPPOSITE[signal_side])
            price = (price_admission(minutes, area, event) if area else
                     dict(status=issue, loose_due_at=None, ordinary_due_at=None))
            m = m_bands.get(area.revision) if area else None
            events[key] = dict(event=event, area=area, price=price,
                               m_reference=m, close_also_in_m=m[0] <= event["close"] <= m[1] if m else None)
    return events


def replay_with_price_context(series, updates, events, *, cutoff, due_field, seed=None):
    minutes, fives = series[1], series[5]
    proofs, attempts = [], []
    replay_args = dict(protection_bands=updates, timely_fixture=True)
    if seed:
        replay_args.update(carry_in=seed, carry_exit_evidence=())
    end_index = {bar.end: i for i, bar in enumerate(fives)}
    for (end, side), row in sorted(events.items()):
        due_at = row["price"][due_field]
        if due_at is None:
            continue
        signal, band = row["event"], row["area"]
        known = signal["available_at"]
        next_index = end_index[end] + 1
        if ((seed and known <= seed.known_at) or next_index == len(fives)
                or fives[next_index].start != end):
            continue
        # Give other actions from the signal bar time to update the position.
        state = candidate.replay(fives, as_of=known + US, protection_confirmations=tuple(proofs),
                                 **replay_args)["current_state"]
        if state["original_side"] != band.side or state["long"] == state["short"]:
            continue
        since = datetime.fromisoformat(state["since"])
        price = price_admission(minutes, band, signal, position_since=since)
        due_at = price[due_field]
        if due_at is None:
            continue
        proof = candidate.ScopedProtectionConfirmation(
            band.contract, candidate.fingerprint(state), due_at, end, known,
            f"{VERSION}:{due_field}", "TEST_FIXTURE", band.scope, signal["shape_end"] - FIVE, side,
        )
        proofs.append(proof)
        attempts.append(dict(
            proof=asdict(proof), price=price, next_driver_end=fives[next_index].end,
            signal_close=signal["close"], protection_revision=band.revision, m_reference=row["m_reference"],
            confirmed_in_m=row["close_also_in_m"],
        ))
    args = replay_args | dict(protection_confirmations=tuple(proofs))
    result = candidate.replay(fives, as_of=cutoff, **args)
    default_probe = seed.known_at if seed else fives[len(fives) // 2].end
    probes = [proof.known_at - US for proof in proofs] or [default_probe]
    for probe in probes:
        prefix = [bar for bar in fives if bar.end + US <= probe]
        known_proofs = tuple(proof for proof in proofs if proof.known_at <= probe)
        prev = candidate.replay(prefix, as_of=probe, protection_confirmations=known_proofs, **replay_args)
        if (prev != candidate.replay(fives, as_of=probe, **args)
                or result != candidate.replay(fives, as_of=cutoff,
                                              checkpoint=json.loads(encoded(prev["checkpoint"])), **args)):
            raise ValueError("PROTECTION_PRICE_PREFIX_OR_RESTART_DIVERGED")
    return result, attempts


def check_baseline_locks(baseline, events):
    proposals = {p["proposal_id"]: p for p in baseline["proposals"]}
    bar_by_index = {e["index"]: datetime.fromisoformat(e["bar_end"]) for e in baseline["evaluations"]}
    rows = []
    for transition in baseline["transitions"]:
        if transition["action"] != "LOCK":
            continue
        signal_side = OPPOSITE[transition["before"]["original_side"]]
        driver = bar_by_index[proposals[transition["proposal_id"]]["index"]]
        price = events.get((driver, signal_side))
        rows.append(dict(driver=driver, original_side=OPPOSITE[signal_side],
                         price_status=price["price"]["status"] if price else "NO_CONTIGUOUS_GEOMETRY",
                         area_revision=price["area"].revision if price and price["area"] else None))
    return rows


def carry_seeds(exposure):
    (table,) = (row for row in exposure["tables"] if row["source"] == CARRY_SOURCE)
    img = table["image"]
    if (table["binding"] != "SYSTEM_COVER" or table["system"] != "4.0.5"
            or sha((ARCHIVE.parent / img["path"]).read_bytes()) != img["sha256"]):
        raise ValueError("PROTECTION_PRICE_CARRY_IMAGE_CHANGED")
    # The observed row sets direction only. One unit is a research projection.
    known = datetime.fromisoformat(table["published_at"]).replace(second=0, microsecond=0) + ONE
    states = {}
    for contract, row in table["contracts"].items():
        legs = row["legs"]
        if set(legs) not in ({"long"}, {"short"}):
            raise ValueError("PROTECTION_PRICE_EXPECTED_DIRECTIONAL_CARRY")
        (side,) = legs
        states[contract] = candidate.CarryInSeed(contract, known, side.upper(), False,
                                                  "VISIBLE_405_DIRECTION_UNIT_HYPOTHESIS")
    return states, table


def study(session, market, baseline, control, exposure):
    cutoff = datetime.fromisoformat(baseline["as_of"])
    index = input_sources()
    modes = {key: [] for key in (
        "baseline", "no_protection_confirmation_fixture", "directional_reach_fixture", "ordinary_contact_fixture",
    )}
    seeds, seed_table = carry_seeds(exposure)
    results = {}
    for contract in CONTRACTS:
        _, series = read_pair(session, market, contract, DAYS)
        fives = series[5]
        if digest(fives) != baseline["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("PROTECTION_PRICE_FROZEN_MARKET_CHANGED")
        updates, m_bands, sources = plan_rows(index, contract)
        events = observations_for_contract(series, updates, m_bands, cutoff)
        original = candidate.replay(fives, as_of=cutoff, timely_fixture=True)
        independent = candidate.replay(fives, as_of=cutoff, timely_fixture=True, protection_bands=updates,
                                       protection_confirmations=())
        manual = candidate.replay(fives, as_of=cutoff, protection_bands=updates, protection_confirmations=())
        if manual["transitions"] or any(row["action"] == "LOCK" for row in independent["transitions"]):
            raise ValueError("PROTECTION_PRICE_PUBLIC_EVIDENCE_BECAME_ACTION")
        modes["baseline"].extend(original["transitions"])
        modes["no_protection_confirmation_fixture"].extend(independent["transitions"])
        fixtures = {}
        carry = {}
        for name, due_field in (("directional_reach_fixture", "loose_due_at"),
                                ("ordinary_contact_fixture", "ordinary_due_at")):
            outcome, attempts = replay_with_price_context(series, updates, events, cutoff=cutoff, due_field=due_field)
            modes[name].extend(outcome["transitions"])
            fixtures[name] = dict(attempts=attempts, terminal_status=outcome["terminal_status"])
            if contract in seeds:
                outcome, attempts = replay_with_price_context(series, updates, events, cutoff=cutoff,
                                                               due_field=due_field, seed=seeds[contract])
                carry[name] = dict(attempts=attempts, terminal_status=outcome["terminal_status"],
                                   transitions=outcome["transitions"])
        results[contract] = dict(
            market={f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()},
            schedules=[asdict(update) for update in updates], m_by_plan=m_bands, sources=sources,
            candidate_status=Counter(row["price"]["status"] for row in events.values()),
            non_ordinary_directional=[],
            baseline_locks=check_baseline_locks(original, events),
            manual_suggestions=len(manual["proposals"]), fixtures=fixtures, unit_carry_fixtures=carry,
        )
        for row in events.values():
            if row["price"]["loose_due_at"] is not None and row["price"]["ordinary_due_at"] is None:
                results[contract]["non_ordinary_directional"].append(dict(
                    known_at=row["event"]["available_at"], close=row["event"]["close"],
                    revision=row["area"].revision, price=row["price"], same_close_in_m=row["close_also_in_m"],
                ))
    actions = {
        mode: dict(counts=Counter(row["action"] for row in rows), timeline=batch_fixture_transitions(rows)[0])
        for mode, rows in modes.items()
    }
    if actions["baseline"]["timeline"] != [row for row in baseline["timeline"] if row["layer"] == "FIXTURE_STATE_BATCH"]:
        raise ValueError("PROTECTION_PRICE_BASELINE_DIVERGED")
    controls = control["cases"]
    return dict(version=VERSION, contracts=results, actions=actions, baseline_sha256=BASELINE_SHA256,
                historical_plan_revision_verified=False, author_action_samples=0, author_match_rate=None,
                evidence_controls_sha256=CONTROL_SHA,
                carry_context=dict(source=CARRY_SOURCE, image=seed_table["image"], seeds={
                    key: asdict(seed) for key, seed in seeds.items()
                }, exposure_sha256=EXPOSURE_SHA256, author_account_continuity=None),
                controls={key: controls[key]["role_windows"] for key in ("S5319173366613171", "S5323519697094213")},
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
        baseline, control = verified_json(BASELINE, BASELINE_SHA256), verified_json(CONTROLS, CONTROL_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=90):
            report = study(session, build_market_data_service(session), baseline, control,
                           verified_json(EXPOSURE, EXPOSURE_SHA256))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.isidentifier() else 'PROTECTION_PRICE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
