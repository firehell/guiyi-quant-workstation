"""Compare old protection carry, release, and fresh protection against frozen observations."""

import argparse
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Event, Position, replay_events
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import US, at
from lms_near405_replay import encoded

VERSION = "lms405-cross-session-protection-v1"
REFERENCES = {
    "JM2605": ("lms405-jm2605-gap-legs-20261126/final-a.json",
               "d34ced2b884f8ae695f874ee3aa50c5bbc45390fe3d373f0c06dadb405312c02"),
    "SH2701": ("lms405-protection-rebuild-20261125/final.json",
               "159d33f417da7d49e9849c41d6d3bc1f21a4c2a9abd360b4ac3da38f9a30b6b3"),
    "I2701": ("lms405-iron-leg-visibility-20261126/final.json",
              "ebba0160404c3b37c59430dddf2178e2e258d56048c780b8c9faf1f4e3194b2d"),
}
SIDES = ("long", "short")


def leg(quantity, today_quantity, opening_average=None):
    return dict(quantity=quantity, today_quantity=today_quantity, opening_average=opening_average)


def transition(contract, action, lots, effective, reference):
    return Event(f"{contract}:{action}:{reference}", contract, effective, effective - US,
                 Action(action, Decimal(lots)), f"TEST_FIXTURE:{reference}")


def parsed_events(contract, rows):
    result = []
    for row in rows:
        if row["contract"] != contract or not row["source"].startswith("TEST_FIXTURE:"):
            raise ValueError("CROSS_SESSION_FROZEN_EVENT_CHANGED")
        event = transition(
            contract, row["action"]["kind"], row["action"]["quantity"],
            datetime.fromisoformat(row["effective_at"]), row["source"].removeprefix("TEST_FIXTURE:"),
        )
        if event.known_at != datetime.fromisoformat(row["known_at"]):
            raise ValueError("CROSS_SESSION_FROZEN_EVENT_CHANGED")
        result.append(event)
    return result


def inspect_leg(quantity, today, previous, observed, new_average_possible):
    if observed is None:
        return dict(quantity=None, today=None, opening_average=None)
    qty = quantity == observed["quantity"]
    today_quantity = observed["today_quantity"]
    avg = observed["opening_average"]
    average_compatible = None
    if qty and quantity and avg is not None:
        if today:
            average_compatible = new_average_possible
        elif previous["opening_average"] is not None:
            average_compatible = Decimal(previous["opening_average"]) == Decimal(avg)
    return dict(quantity=qty, today=None if today_quantity is None else today == today_quantity,
                opening_average=average_compatible)


def compare(contract, protection_side, seed, night_start, visible, anchors, steps, price_by_anchor):
    initial = Position(contract, **{side: Decimal(seed[side]["quantity"]) for side in SIDES})
    if not anchors or any(end <= night_start for end in anchors):
        raise ValueError("CROSS_SESSION_ANCHOR_OUTSIDE_NEXT_TRADING_DAY")
    if any(step.action.kind not in {"LOCK", f"UNLOCK_{'SHORT' if protection_side == 'long' else 'LONG'}"}
           or (step.action.kind == "LOCK" and step.effective_at < night_start) for step in steps):
        raise ValueError("CROSS_SESSION_EVENT_OUTSIDE_PROTECTION_PATH")
    checks = []
    for end in anchors:
        prefix = [step for step in steps if step.known_at < step.effective_at < end]
        position = replay_events(contract, steps, initial=initial, cutoff=end - US)
        if position != replay_events(contract, prefix, initial=initial, cutoff=end - US):
            raise ValueError("CROSS_SESSION_REPLAY_PREFIX_DIVERGED")
        last = max(prefix, key=lambda event: event.effective_at, default=None)
        has_new = last is not None and last.action.kind == "LOCK"
        fields, model = {}, {}
        for side in SIDES:
            qty = getattr(position, side)
            today = qty if has_new and side == protection_side else Decimal(0)
            model[side] = dict(quantity=qty, today_quantity=today)
            fields[side] = inspect_leg(qty, today, seed[side], visible.get(side), price_by_anchor.get(end))
        values = [value for checks_by_leg in fields.values() for value in checks_by_leg.values()]
        required_missing = any(
            side not in visible or (
                visible[side]["quantity"] > 0 and (
                    fields[side]["today"] is None or fields[side]["opening_average"] is None))
            for side in SIDES
        )
        status = "INCOMPATIBLE" if False in values else (
            "INDETERMINATE" if required_missing else "COMPATIBLE_UNDER_ASSUMPTIONS")
        checks.append(dict(end=end, model=model, fields=fields, status=status))
    return dict(fixture_steps=[asdict(step) for step in steps], checks=checks,
                counts={status: sum(row["status"] == status for row in checks)
                        for status in ("INCOMPATIBLE", "INDETERMINATE", "COMPATIBLE_UNDER_ASSUMPTIONS")})


def coal(reference):
    contract, lots = "JM2605", 44
    start = datetime.fromisoformat(reference["night_open"]["open_at"])
    quote_cap = datetime.fromisoformat(reference["sources"]["L02"]["display_minute"])
    first_touch = datetime.fromisoformat(reference["first_night_overlap"])
    short = reference["short"]
    if (reference["contract"] != contract or short["leg"]["quantity"] != lots
            or short["night_screen_displayed_short_today"] != 0 or not start < first_touch < quote_cap):
        raise ValueError("CROSS_SESSION_COAL_FROZEN_FIELDS_CHANGED")
    seed = dict(long=leg(lots, 0), short=leg(lots, lots, short["leg"]["opening_average"]))
    visible = dict(long=leg(lots, 0), short=leg(lots, 0, short["leg"]["opening_average"]))
    release = transition(contract, "UNLOCK_LONG", lots, start + 3 * US, "HYPOTHETICAL_NIGHT_RELEASE")
    add = transition(contract, "LOCK", lots, first_touch + 3 * US, "HYPOTHETICAL_NIGHT_ZONE_PERMISSION")
    routes = dict(carry=[], release_only=[release], release_and_fresh_protection=[release, add])
    price = {quote_cap: short["nightly_rebuild_if_same_display"]["whole_in_later"]}
    return dict(seed=seed, observed=visible, night_start=start, protection_side="short",
                comparison_time_scope="PUBLICATION_CAP_WHOLE_NIGHT_PRICE_ENVELOPE",
                paths={name: compare(contract, "short", seed, start, visible, [quote_cap], events, price)
                       for name, events in routes.items()})


def caustic(reference):
    contract = "SH2701"
    case = reference["contracts"][contract]
    start = at("2026-10-27T21:00")
    prior, visible = case["scopes"]["noon_visible"]["legs"], case["scopes"]["night_visible"]
    paths = {}
    for name, route in case["paths"].items():
        steps = parsed_events(contract, route["steps"])
        quotes = {datetime.fromisoformat(key): value for key, value in route["quote_checks"].items()}
        prices = {end: row["price_support"]["only_complete_minutes_after_permission"]["whole_leg_possible"]
                  for end, row in quotes.items() if row["price_support"] is not None}
        result = compare(contract, "long", prior, start, visible, sorted(quotes), steps, prices)
        if result["counts"]["COMPATIBLE_UNDER_ASSUMPTIONS"] != route["compatible_quotes"]:
            raise ValueError("CROSS_SESSION_CAUSTIC_FROZEN_PRICE_PARITY_FAILED")
        paths[name] = result
    return dict(seed=prior, observed=visible, night_start=start, protection_side="long",
                comparison_time_scope="FROZEN_SINGLE_ROW_QUOTE_CANDIDATES", paths=paths)


def iron(reference):
    contract = "I2701"
    start = at("2026-10-27T21:00")
    prior = reference["snapshots"]["U03"]["displayed_legs"]
    visible = reference["snapshots"]["WRoEvasxQR"]["displayed_legs"]
    window = reference["overnight_if_missing_long_is_confirmed_zero"]
    anchors = sorted(datetime.fromisoformat(end) for end in window["iron_quote_minutes"])
    if reference["contract"] != contract or "long" in visible or reference["actual_overnight_long_lots"] is not None:
        raise ValueError("CROSS_SESSION_IRON_FROZEN_FIELDS_CHANGED")
    routes = {"carry": []}
    for clock in ("geometry_5m_to_1m", "geometry_5m_to_5m", "first_strict_close_below_near"):
        known = datetime.fromisoformat(window["timing_sensitivity"][clock]["known_at"])
        routes[f"release_only:{clock}"] = [
            transition(contract, "UNLOCK_SHORT", prior["long"]["quantity"], known + 2 * US, clock),
        ]
    paths = {}
    for label, observed in (("as_shown", visible), ("hypothetically_verified_zero", visible | {"long": leg(0, 0)})):
        paths[label] = {
            name: compare(contract, "long", prior, start, observed, anchors, steps, {})
            for name, steps in routes.items()
        }
    return dict(seed=prior, observed=visible, night_start=start, protection_side="long",
                comparison_time_scope="FROZEN_SINGLE_ROW_QUOTE_CANDIDATES",
                fresh_protection_permission=None, paths=paths)


def report(root):
    frozen = {code: verified_json(root / name, sha) for code, (name, sha) in REFERENCES.items()}
    return dict(
        version=VERSION, cases={code: evaluate(frozen[code]) for code, evaluate in (
            ("JM2605", coal), ("SH2701", caustic), ("I2701", iron))},
        input_report_sha256={code: sha for code, (_, sha) in REFERENCES.items()},
        scope="CONDITIONAL_WHOLE_LEG_REPLAY_WITHOUT_ACTUAL_ACCOUNT_OR_PERMISSION_IDENTITY",
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-root", type=Path, default=Path("output"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    try:
        result = report(args.frozen_root)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("CROSS_SESSION_") and code.isidentifier()
                        else "CROSS_SESSION_FROZEN_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
