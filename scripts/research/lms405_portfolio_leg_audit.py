"""Compare per-leg replay origins to the quantities, trading days and averages visible in photos."""

from argparse import ArgumentParser
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Bar, Position, apply_action
from lms405_first_night_confirmation_clocks import CASES as FIRST_LEG_DISPLAY
from lms405_locked_exit_audit import verify_aggregation
from lms405_managed_portfolio import SNAPSHOTS, SNAPSHOT_SHA256
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, DAYS, FIVE
from lms405_position_continuity import TRADING_DAYS
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import US
from lms405_replay import ohlc, read_session_series
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA, SPECS_SHA
from lms405_right_side_study import ONE
from lms405_sh_lock_lifecycle import digest
from lms405_sh_protection_replacement import NIGHT
from lms405_sized_portfolio_replay import PTA_CASE_ENTRY, lot_profile, pta_example
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms_near405_replay import encoded, sha

MANAGED = Path("output/lms405-managed-portfolio-20261125/checked.json")
MANAGED_SHA = "189be2418f2872c1ef0060de54d3c1490d232534a39e34f5534a45dbdeb81a2d"
SIZE = Path("output/lms405-exposure-20261125/sizing-audit.json")
SIZE_SHA = "ef8c8dd93f5fde25d3fb7ac7a25f90659b6122b729cae7aae7c4224fb4d30ce1"
SH_REREAD = Path("output/lms405-sh-protection-replacement-20261125/verified.json")
SH_REREAD_SHA = "700523eff5ab60c4330cd180b223c58dd3f664feadcc8fa1df8dc67283733286"
QUOTES = (
    (PHOTO, PHOTO_SHA),
    (Path("output/lms-i2701-oct-20261125/comparison.json"),
     "12aba77f900209d38ea180daae08dadc398a83d57c8d60c7024532da24b9bdba"),
    (Path("output/lms-v-ta-oct-20261125/comparison.json"),
     "fcb5f1f9252afa59346910ef843e4d4ddfae682f4580b6acc13935fab22998af"),
)
SIDES = ("long", "short")
FIRST = "WRnTlEfj1t"


def leg_changes(contract, transitions):
    """Keep each leg's own creation identity through opposite-leg changes."""
    position = Position(contract)
    origins, changes = {}, []
    for row in transitions:
        when = datetime.fromisoformat(row["at"])
        before, after = (Position(contract, *map(Decimal, row[k])) for k in ("before", "after"))
        qty = before.long + before.short if row["action"] == "CLEAR" else Decimal(1)
        if position != before or apply_action(before, Action(row["action"], qty)) != after or (
            changes and when <= changes[-1][0]
        ):
            raise ValueError("AUDIT_REPLAY_TRANSITION_INVALID")
        for side in SIDES:
            prior, current = getattr(before, side), getattr(after, side)
            if current not in (0, 1):
                raise ValueError("AUDIT_ONLY_COMPLETE_UNIT_LEGS_SUPPORTED")
            if not current:
                origins.pop(side, None)
            elif not prior:
                origins[side] = (when, row["action"], None)
            elif origins[side][2] is None:
                # The retained leg must exist before this later transition can use its pre-state.
                origins[side] = (*origins[side][:2], when)
        changes.append((when, dict(origins)))
        position = after
    return changes


def scoped_input_quotes():
    """Retain each file's single-row matches without joining across images."""
    rows = {}
    for path, hash_key in QUOTES:
        photos = verified_json(path, hash_key)["photos"]
        for source, photo in photos.items():
            for symbol, row in photo["per_symbol"].items():
                key = source, f"{symbol.upper()}2701"
                if key in rows and rows[key] != row:
                    raise ValueError("AUDIT_QUOTE_SOURCE_CONFLICT")
                rows[key] = row
    return rows


def compare_leg(observed, average, observed_day, quote_end, active, minutes, size, tick):
    if active is None:
        return dict(status="SIDE_ABSENT")
    since, action, dependency = active
    if not since < quote_end:
        raise ValueError("AUDIT_LOOKAHEAD_TO_REPLAY_ACTION")
    result = dict(origin_at=since, origin_action=action, projected_size=size, first_dependent_action_at=dependency)
    if size is None or size != observed["quantity"]:
        return result | dict(status="SIZE_UNKNOWN" if size is None else "SIZE_DIFFERS")
    latest = min(quote_end, dependency) if dependency else quote_end
    allowed = [b for b in minutes if since < b.bar_end <= latest]
    if not allowed:
        return result | dict(status="NO_ELIGIBLE_MINUTE")
    first_day = allowed[0].trading_day
    today = observed["today_quantity"]
    totals = displayed_tick_totals(average, int(size), tick)

    def supports(rows):
        return bool(earlier_lot_counts(None, tick_bounds(rows, tick), int(size), totals))

    same_day = [b for b in allowed if b.trading_day == first_day]
    wide = supports(same_day)
    strict = supports([b for b in same_day if b.bar_end - ONE > since])
    today_compatible = None if today is None else today == (size if first_day == observed_day else 0)
    status = ("TRADING_DAY_DIFFERS" if today_compatible is False else "AVERAGE_OUTSIDE_ENVELOPE" if not wide else
              "TODAY_UNKNOWN_PRICE_COMPATIBLE" if today is None else "PRICE_COMPATIBLE")
    by_displayed_day = None
    if today in (0, size):
        # Show whether delaying the entire modeled leg to a later eligible trading day could fix a mismatch.
        by_displayed_day = any(supports([b for b in allowed if b.trading_day == day])
                               for day in {b.trading_day for b in allowed}
                               if (day == observed_day) == (today == size))
    return result | dict(status=status, first_eligible_trading_day=first_day, today_compatible=today_compatible,
                         price_compatible_permissive=wide, price_compatible_strict=strict,
                         price_compatible_if_trade_day_can_be_deferred=by_displayed_day)


def study(session, market, *, extra_variant=None):
    managed = verified_json(MANAGED, MANAGED_SHA)
    if set(managed["cases"]) != set(CONTRACTS) or managed["fixture_only"] is not True:
        raise ValueError("AUDIT_FIXTURE_SCOPE_CHANGED")
    tables = verified_json(EXPOSURE, EXPOSURE_SHA256)["tables"]
    sized = verified_json(SIZE, SIZE_SHA)
    profile, ta_lots = lot_profile(sized), pta_example(sized)
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    quote_rows = scoped_input_quotes()
    aligned = {s["source"]: s for s in verified_json(SNAPSHOTS, SNAPSHOT_SHA256)["snapshots"]}
    reread = verified_json(SH_REREAD, SH_REREAD_SHA)["with_night_today_quantity"]
    cut = datetime.fromisoformat(managed["as_of"])
    outputs = {}
    for table in tables:
        image = table["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("AUDIT_IMAGE_CHANGED")
    for contract in CONTRACTS:
        case = managed["cases"][contract]
        minutes = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, DAYS)
        raw_fives = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        fives = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw_fives if b.bar_end + US <= cut]
        verify_aggregation(fives, minutes)
        if digest(fives) != case["input_prefix_sha256"] or len(fives) != case["bars"]:
            raise ValueError("AUDIT_REPLAY_INPUT_CHANGED")
        minute_index = {b.bar_end: b for b in minutes}
        states = {name: leg_changes(contract, variant["transitions"]) for name, variant in case["variants"].items()}
        if extra_variant is not None:
            name, rows = extra_variant(fives, cut)
            if not name or name in states:
                raise ValueError("AUDIT_VARIANT_NAME_CONFLICT")
            states[name] = leg_changes(contract, rows)
        rows = []
        for table in tables:
            source = table["source"]
            visible = table["contracts"].get(contract, {}).get("legs", {})
            if not visible:
                continue
            day = TRADING_DAYS[source]
            quote = quote_rows.get((source, contract))
            if source in aligned:
                entry = aligned[source]["contracts"][contract]
                if entry["quote_aligned"] is not True or entry["author_visible_legs"] != visible:
                    raise ValueError("AUDIT_ALIGNED_QUOTE_FIELDS_CHANGED")
                endings, mark = [aligned[source]["quote_anchor"]], entry["displayed_quote"]
            else:
                endings, mark = (quote["contains"], quote["mark"]) if quote is not None else ([], None)
            anchors = sorted(map(datetime.fromisoformat, endings))
            published = datetime.fromisoformat(table["published_at"]).replace(second=0, microsecond=0)
            for end in anchors:
                bar = minute_index[end]
                if not (end < published and end <= cut and bar.trading_day == day
                        and bar.low <= Decimal(mark) <= bar.high and (source not in aligned or bar.close == Decimal(mark))):
                    raise ValueError("AUDIT_QUOTE_WINDOW_CHANGED")
            for side in SIDES:
                if side not in visible:
                    rows.append(dict(source=source, side=side, status="UNLISTED_UNKNOWN"))
                    continue
                leg = dict(visible[side])
                average = Decimal(leg["opening_average"])
                precision = "ARCHIVED_DECIMAL_ENVELOPE"
                if source == FIRST and side == "long":
                    average = Decimal(FIRST_LEG_DISPLAY[contract][0])
                    precision = "DISPLAYED"
                if (source, contract, side) == (NIGHT, "SH2701", "long"):
                    if table["image"]["sha256"] != reread["image_sha256"]:
                        raise ValueError("AUDIT_CAUSTIC_REREAD_SCOPE_CHANGED")
                    leg["today_quantity"] = reread["today_quantity"]
                    average = Decimal("1492.0")
                    precision = "DISPLAYED"
                if average != Decimal(leg["opening_average"]):
                    raise ValueError("AUDIT_AVERAGE_IDENTITY_CHANGED")
                opposite = visible.get("short" if side == "long" else "long", {})
                paired_today = leg["today_quantity"] == leg["quantity"] and opposite.get("today_quantity") == 0
                by_candidate = {}
                for name, changes in states.items():
                    for end in anchors:
                        active = next((state.get(side) for instant, state in reversed(changes) if instant < end), None)
                        size = profile.get(contract)
                        if contract == "TA2701" and active and active[0] == PTA_CASE_ENTRY:
                            size = ta_lots
                        by_candidate.setdefault(name, {})[end.isoformat()] = compare_leg(
                            leg, average, day, end, active, minutes, size, specs[contract]["tick"],
                        )
                rows.append(dict(source=source, side=side, visible=leg, precision=precision,
                                 paired_today_leg=paired_today, quote_scope="ALIGNED" if source in aligned else "ROW_ONLY",
                                 source_url=table["source_url"], reported_quote=mark, assumed_trading_day=day,
                                 status="CHECKED" if anchors else "NO_VERIFIED_QUOTE_CANDIDATE", by_variant=by_candidate))
        outputs[contract] = rows
    return dict(version="lms405-portfolio-leg-audit-v1", contracts=outputs, classifications=summarize(outputs),
                inputs=dict(managed=MANAGED_SHA, exposure=EXPOSURE_SHA256, sizing=SIZE_SHA),
                author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False)


def summarize(outputs):
    classifications = {}
    for contract, rows in outputs.items():
        cases = {}
        names = ("baseline", "managed", *sorted({name for row in rows for name in row.get("by_variant", {})}
                                              - {"baseline", "managed"}))
        for name in names:
            counts = Counter()
            sides_by_source = {}
            for row in rows:
                checks = row.get("by_variant", {}).get(name, {})
                if row["status"] != "CHECKED":
                    counts[row["status"]] += 1
                    continue
                result = {check["status"] for check in checks.values()}
                counts["VISIBLE_LEGS_CHECKED"] += 1
                counts["AT_LEAST_ONE_QUOTE_COMPATIBLE"] += "PRICE_COMPATIBLE" in result
                counts["AT_LEAST_ONE_STRICT_QUOTE_COMPATIBLE"] += any(
                    check["status"] == "PRICE_COMPATIBLE" and check["price_compatible_strict"] for check in checks.values()
                )
                counts["EVERY_QUOTE_COMPATIBLE"] += result == {"PRICE_COMPATIBLE"}
                counts["TODAY_FIELD_UNKNOWN"] += row["visible"]["today_quantity"] is None
                counts["PAIRED_TODAY_LEGS_CHECKED"] += row["paired_today_leg"]
                counts["PAIRED_TODAY_COMPATIBLE"] += row["paired_today_leg"] and "PRICE_COMPATIBLE" in result
                sides_by_source.setdefault(row["source"], {})[row["side"]] = checks
                for status in result - {"PRICE_COMPATIBLE"}:
                    counts[f"AT_LEAST_ONE_{status}"] += 1
            for sides in sides_by_source.values():
                if set(sides) != set(SIDES):
                    continue
                counts["TWO_VISIBLE_LEGS_CHECKED"] += 1
                counts["BOTH_LEGS_COMPATIBLE_AT_SAME_QUOTE"] += any(
                    check["status"] == "PRICE_COMPATIBLE"
                    and sides["short"].get(at, {}).get("status") == "PRICE_COMPATIBLE"
                    for at, check in sides["long"].items()
                )
            cases[name] = dict(counts)
        classifications[contract] = cases
    return classifications


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
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("AUDIT_") else "AUDIT_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
