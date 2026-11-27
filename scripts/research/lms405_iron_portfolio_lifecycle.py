"""Extend the nine-contract tape with scoped I2701 hold and withdrawal hypotheses."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_common_protection_window import OCT27_QUOTES
from lms405_i2701_case import DAYS, FROZEN_COMPARISON_SHA256, PHOTOS, readback
from lms405_iron_first_protection import fixed_quote_span
from lms405_iron_leg_visibility import CONTRACT, LUNCH, CLOSE, NIGHT, NEAR, FAR
from lms405_lifecycle_tape import replay
from lms405_m_permission_study import read_pair
from lms405_pa_signal_deadline import comparison
from lms405_portfolio_lifecycle import candidate, seed
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import photo_comparison, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_sizing_audit import EXPOSURE_SHA256
from lms405_task_role_replay import EXPOSURE_PATH, TOTALS, TOTALS_SHA
from lms_near405_replay import encoded, sha

VERSION = "lms405-iron-portfolio-lifecycle-v1"
LIFETIME = Path("output/lms405-iron-release-lifetime-20261126/verified-a.json")
LIFETIME_SHA = "546471f7aa95729dcdd64164bd52352df0f0449f4b49bc7d7f451c551dc970f9"
PORTFOLIO = Path("output/lms405-portfolio-lifecycle-20261126/final-a.json")
PORTFOLIO_SHA = "343c648f7e248005dc8109b2f28d7e7d25622040f8e0d12568d3c8c4ecb8574b"
PLAN = Path("01-VPLUS每日复盘/2026-10-27/A5358686423089344.md")
PLAN_HASH = "add29c32af564b02876a11b0901606738ccf07ce9c4ee8ca8c551b22de13e541"
START, END = at("2026-10-27T21:00"), at("2026-10-27T22:12")
REPROTECTION = (Decimal(667), Decimal(671))
RELEASE_PAIRS = ((1, 1), (5, 1), (5, 5))
REPROTECTION_PAIRS = (*RELEASE_PAIRS, (15, 15))
NIGHT_FLOAT_FIELDS = (24920, 5220, 41200, 46500, 44050, -600, 137400, 33600, 2000, 19000)
NIGHT_50 = "WRoEvFgWlh"
VERSION_IMAGES = {
    NIGHT: (Path("02-持仓记录/2026-10-27/RoEvasxQR-position-screen.png"),
            "67854d29d606b65cd88efe9af1fa939e86e20b713325732929b8a5a5aa6f9b0a"),
    NIGHT_50: (Path("02-持仓记录/2026-10-27/RoEvFgWlh-position-screen.png"),
               "3e1aedcdb40d8dde8c0f0d2c765ab4281b908d5d4f78562cae83704632e76aa5"),
}
NIGHT_50_ROWS = {
    "ta": ("LONG", "6536.0", "22.0"), "v": ("LONG", "5160.0", "40.0"),
    "oi": ("SHORT", "10283.0", "41.0"), "pp": ("LONG", "9465.0", "653.0"),
    "cf": ("SHORT", "15770.0", "545.0"), "i": ("SHORT", "694.00", "32.00"),
    "sp": ("SHORT", "4736.0", "180.0"),
}
SNAPSHOT_AUDIT = Path("output/lms405-iron-portfolio-lifecycle-20261126/final-a.json")
SNAPSHOT_AUDIT_SHA = "b2d4f388c019240a9ef0f8bbd6b37d12f9bec3cc87531803ede6cedc7e40504a"


def table_counts(table, footer):
    legs = {
        (contract, side): leg["quantity"]
        for contract, row in table["contracts"].items() for side, leg in row["legs"].items()
    }
    extra = {(contract, side): lot for contract, row in footer["other_legs"].items() for side, lot in row.items()}
    if set(legs) & set(extra) or any(type(lots) is not int or lots <= 0 for lots in (*legs.values(), *extra.values())):
        raise ValueError("IRON_LIFECYCLE_TABLE_FIELDS_INVALID")
    legs.update(extra)
    if (len(legs), sum(legs.values())) != (footer["row_count"], footer["total_lots"]):
        raise ValueError("IRON_LIFECYCLE_TABLE_FOOTER_MISMATCH")
    return legs


def footer_evidence(iron):
    exposure = verified_json(EXPOSURE_PATH, EXPOSURE_SHA256)["tables"]
    footers = {item["source"]: item for item in verified_json(TOTALS, TOTALS_SHA)}
    selected = {row["source"]: row for row in exposure if row["source"] in (LUNCH, CLOSE, NIGHT)}
    counts = {}
    for key in (LUNCH, CLOSE, NIGHT):
        row, image = selected[key], iron["snapshots"][key]["image"]
        if (row["image"] != image or sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]
                or row["table"] != footers[key]["table"]
                or row["contracts"][CONTRACT]["legs"] != iron["snapshots"][key]["displayed_legs"]):
            raise ValueError("IRON_LIFECYCLE_FROZEN_TABLE_CHANGED")
        counts[key] = table_counts(row, footers[key])
    before, after = (Counter(counts[key]) for key in (CLOSE, NIGHT))
    added, removed = after - before, before - after
    if removed != {(CONTRACT, "long"): 16} or len(NIGHT_FLOAT_FIELDS) != len(after) or sum(NIGHT_FLOAT_FIELDS) != 353290:
        raise ValueError("IRON_LIFECYCLE_TABLE_DELTA_CHANGED")
    return dict(
        sources={k: dict(rows=len(rows), displayed_gross_lots=sum(rows.values()), binding=selected[k]["binding"])
                 for k, rows in counts.items()},
        night_float_footer_matches_visible_rows=True, iron_long_in_night_table=0, iron_long_in_actual_account=None,
        if_extra_16_lots_were_in_same_total=dict(rows=len(after) + 1, displayed_gross_lots=sum(after.values()) + 16),
        new_display_rows=[dict(contract=c, side=s, quantity=lots) for (c, s), lots in sorted(added.items())],
        removed_display_rows=[dict(contract=c, side=s, quantity=lots) for (c, s), lots in sorted(removed.items())],
        account_continuity_verified=False, filter_scope_verified=False, quote_position_synchronized=None,
    )


def branch(case, observed, *, known_at, test_permission, seed_at, minutes, quotes, partial, tick, totals):
    root = seed(f"I2701:{case}", CONTRACT, seed_at, long=16, short=16, protection=16)
    attempts = ()
    if known_at is not None:
        # Use the completed market evidence plus its conservative reveal lag.
        operation_time = known_at + US
        attempts = (candidate(f"I:{case}", root, "PROTECT_WITHDRAW", 16, operation_time,
                              approve=test_permission),)
    rows, last = replay((root,), attempts, (), cutoff=END, allow_test_fixture=test_permission)
    public_matches, same_scope, displayed_checks = 0, [], []
    for quote in quotes:
        outcomes = {}
        # Full quote minute is a sensitivity bound; intraminute sequencing is unknown.
        for role, cut in (("START_EXCLUSIVE", quote - ONE), ("END_EXCLUSIVE", quote)):
            sliced, state = replay((root,), attempts, (), cutoff=cut, allow_test_fixture=test_permission)
            if rows[:len(sliced)] != sliced:
                raise ValueError("IRON_LIFECYCLE_PREFIX_DIVERGED")
            projection = state[root.episode].position
            observed_short_matches = projection.short == observed["short"]["quantity"]
            outcomes[role] = dict(
                long=projection.long, short=projection.short, visible_short_matches=observed_short_matches,
                visible_table_with_no_long_matches=observed_short_matches and projection.long == 0,
            )
        before = outcomes["START_EXCLUSIVE"]
        public_matches += before["visible_short_matches"]
        same_scope.append(before["visible_table_with_no_long_matches"])
        displayed_checks.append(dict(quote_end=quote, partial_six_quote=quote in partial, **outcomes))
    whole_rebuild, rebuild_high = None, None
    if attempts and rows[-1]["changed"]:
        withdraw_at = attempts[0].at
        # Price sensitivity only; there is no observed replacement leg.
        rebuild_high = max((bar.high for bar in minutes if withdraw_at < bar.start), default=None)
        whole_rebuild = {
            quote.isoformat(): comparison([bar for bar in minutes if bar.end <= quote],
                                           gate_known_at=withdraw_at, lots=16, totals=totals,
                                           tick=tick, band=None)["whole_leg_with_later_prices"] for quote in quotes
        }
    return dict(
        clock=known_at, test_permission_supplied=test_permission, rows=rows,
        ending=asdict(last[root.episode]), compatible_visible_short_before_quote=public_matches,
        compatible_if_same_complete_table_scope_and_quote_sync_before_quote=sum(same_scope),
        quotes=displayed_checks, same_average_rebuild_price_sensitivity=whole_rebuild,
        highest_strict_later_price_before_post=rebuild_high,
        author_action_at=None,
    )


def study(session, market):
    iron = verified_json(LIFETIME, LIFETIME_SHA)
    base = verified_json(PORTFOLIO, PORTFOLIO_SHA)
    tables = footer_evidence(iron)
    if sha((ARCHIVE.parent / PLAN).read_bytes()) != PLAN_HASH:
        raise ValueError("IRON_LIFECYCLE_PROTECTION_TEXT_CHANGED")
    raw, series = read_pair(session, market, CONTRACT, DAYS)
    if {str(p): readback(rows) for p, rows in raw.items()} != iron["market"]:
        raise ValueError("IRON_LIFECYCLE_MARKET_CHANGED")
    minutes = completed(series[1], START, END)
    current_day = read_window(session, market, CONTRACT, DAYS[1])
    if any(digest(current_day[p]) != digest([bar for bar in series[p] if bar.start >= START]) for p in (1, 5)):
        raise ValueError("IRON_LIFECYCLE_REPROTECTION_MARKET_CHANGED")
    refs = iron["overnight_if_missing_long_is_confirmed_zero"]
    quotes, partial = ([datetime.fromisoformat(value) for value in refs[key]]
                       for key in ("iron_quote_minutes", "six_symbol_partial_quote_minutes"))
    if quotes != [b.end for b in minutes if b.low <= Decimal("661.5") <= b.high]:
        raise ValueError("IRON_LIFECYCLE_QUOTE_SCOPE_CHANGED")
    release = {f"{p}m_to_{c}m": signals(series, p, c, side="SHORT", start=START, cut=END)
               for p, c in RELEASE_PAIRS}
    reprotection = {f"{p}m_to_{c}m": signals(current_day, p, c, side="LONG", start=START, cut=END)
                    for p, c in REPROTECTION_PAIRS}
    clocks = {name: datetime.fromisoformat(item["known_at"]) if item["known_at"] is not None else None
              for name, item in refs["timing_sensitivity"].items()}
    for label, rows in release.items():
        if clocks[f"geometry_{label}"] != next((row["available_at"] for row in rows), None):
            raise ValueError("IRON_LIFECYCLE_SHORT_SIGNAL_CHANGED")
    for label, price in (("first_strict_close_below_near", NEAR), ("first_strict_close_below_far", FAR)):
        if clocks[label] != next((bar.end + US for bar in minutes if bar.close < price), None):
            raise ValueError("IRON_LIFECYCLE_PRICE_GATE_CHANGED")
    highs = max(bar.high for bar in minutes)
    specs = dict(seed_at=at("2026-10-27T15:17"), minutes=minutes, quotes=quotes, partial=partial,
                 tick=Decimal(iron["minimum_tick"]), totals=tuple(iron["compatible_integer_tick_totals"]))
    paths = {
        "KEEP": (None, False),
        "PUBLIC_FAST_WITHOUT_PERMISSION": (clocks["geometry_5m_to_1m"], False),
        "FAST_PERMISSION": (clocks["geometry_5m_to_1m"], True),
        "SLOW_PERMISSION": (clocks["geometry_5m_to_5m"], True),
        "NEAR_PERMISSION": (clocks["first_strict_close_below_near"], True),
        "FAR_PERMISSION_UNREACHED": (clocks["first_strict_close_below_far"], False),
    }
    branches = {key: branch(key, iron["snapshots"][NIGHT]["displayed_legs"], known_at=clock,
                            test_permission=allow, **specs) for key, (clock, allow) in paths.items()}
    episodes = [event | dict(mode="IRON_SCOPE_TEST", scenario=key)
                for key, item in branches.items() for event in item["rows"]]
    timeline = sorted([*base["timeline"], *episodes],
                      key=lambda row: (datetime.fromisoformat(str(row["at"])), row["mode"], row.get("episode", "")))
    contracts = base["contracts"] | {CONTRACT: base["contracts"][CONTRACT] | dict(
        conditional_episodes=[item["ending"]["episode"] for item in branches.values()],
        remaining_input="SAME_ACCOUNT_AND_COMPLETE_NIGHT_SCOPE;ACTUAL_RELEASE_OR_REPROTECTION",
    )}
    return dict(
        version=VERSION, contracts=contracts, timeline=timeline, bases=dict(portfolio=PORTFOLIO_SHA, iron=LIFETIME_SHA),
        iron=dict(close_to_night_same_scope_verified=False, table_checks=tables, branches=branches,
                  plan_contains_advance_protection_reference=True, protection_band=REPROTECTION,
                  high_in_night_window=highs, touched_protection=any(
                      b.low <= REPROTECTION[1] and b.high >= REPROTECTION[0] for b in minutes
                  ),
                  reprotection_geometry=reprotection, source_day_series_sha256={
                      f"{period}m": digest(bars) for period, bars in current_day.items()
                  }, actual_reprotection_at=None, actual_release_at=None),
        author_actions_scored=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def anchored_quote_spans(photo):
    rows = photo["per_symbol"]
    quotes = {symbol: tuple(map(datetime.fromisoformat, row["contains"])) for symbol, row in rows.items()}
    if not quotes.get("i") or not all(quotes.values()):
        raise ValueError("IRON_LIFECYCLE_QUOTE_SPAN_INPUT_MISSING")
    other = [ends for symbol, ends in quotes.items() if symbol != "i"]
    by_anchor = {anchor.isoformat(): fixed_quote_span(anchor, other) for anchor in quotes["i"]}
    best = min(by_anchor.values())
    return dict(minimum_label_span_minutes=best, by_iron_label=by_anchor,
                iron_labels_at_minimum=[stamp for stamp, span in by_anchor.items() if span == best])


def cross_version_quote_scope(session, market):
    from app.market_data.catalog import CatalogError
    from app.market_data.market_data_service import MarketDataError

    index = input_sources()
    ref = verified_json(OCT27_QUOTES, FROZEN_COMPARISON_SHA256)
    previous = verified_json(SNAPSHOT_AUDIT, SNAPSHOT_AUDIT_SHA)["iron"]
    quotes_405 = PHOTOS[NIGHT][2]
    quotes_50 = {symbol: str(Decimal(average) + (Decimal(diff) if side == "LONG" else -Decimal(diff)))
                 for symbol, (side, average, diff) in NIGHT_50_ROWS.items()}
    sources = {key: load_source(index, key) for key in (NIGHT, NIGHT_50)}
    post_50 = at("2026-10-27T22:14")
    if (datetime.fromisoformat(sources[NIGHT]["published_at"]) != END
            or datetime.fromisoformat(sources[NIGHT_50]["published_at"]) != post_50
            or any(sha((ARCHIVE.parent / path).read_bytes()) != checksum for path, checksum in VERSION_IMAGES.values())):
        raise ValueError("IRON_LIFECYCLE_CROSS_VERSION_SOURCE_CHANGED")
    series, missing, hashes = {}, {}, {}
    for symbol in sorted(quotes_405.keys() | quotes_50.keys()):
        contract = f"{symbol.upper()}2701"
        try:
            series[symbol] = read_session_series(session, market, symbol, contract, "1m", ONE, (DAYS[1],))
        except (CatalogError, MarketDataError) as exc:
            if symbol not in quotes_405 and exc.code in ("INSTRUMENT_EXCHANGE_MISSING", "DATASET_OR_PARTITION_MISSING"):
                missing[contract] = exc.code
                continue
            raise
        hashes[contract] = readback(series[symbol])[DAYS[1].isoformat()]
        if symbol in quotes_405 and hashes[contract] != ref["market_1m"][symbol][DAYS[1].isoformat()]:
            raise ValueError("IRON_LIFECYCLE_NIGHT_MARKET_CHANGED")
    tables = {
        "4.0.5": photo_comparison(series, START, END, quotes_405),
        "5.0": photo_comparison(series, START, post_50, {s: value for s, value in quotes_50.items() if s in series}),
    }
    if tables["4.0.5"] != ref["photos"][NIGHT]:
        raise ValueError("IRON_LIFECYCLE_NIGHT_QUOTE_SCOPE_CHANGED")
    spans = {version: anchored_quote_spans(rows) for version, rows in tables.items()}
    tighter = set(map(datetime.fromisoformat, spans["4.0.5"]["iron_labels_at_minimum"]))
    branches = {name: sum(row["START_EXCLUSIVE"]["visible_table_with_no_long_matches"]
                          for row in branch["quotes"] if datetime.fromisoformat(row["quote_end"]) in tighter)
                for name, branch in previous["branches"].items()}
    return dict(
        version="lms405-iron-cross-version-quote-scope-v1", sources=sources,
        images={key: dict(path=path, sha256=checksum) for key, (path, checksum) in VERSION_IMAGES.items()},
        night_5_rows=NIGHT_50_ROWS, market=hashes, missing_market=missing, tables=tables, quote_spans=spans,
        replay_sensitivity_at_minimum_405_span=branches,
        denominators=dict(iron_rows=len(spans["4.0.5"]["by_iron_label"]), at_minimum=len(tighter)),
        market_bar_count=sum(row["bars"] for row in hashes.values()),
        price_label_span_is_not_capture_delay=True, cross_version_holdings_merged=False,
        iron_author_long_qty=None, iron_author_action_at=None, same_account_and_filter=None,
        author_actions_scored=0, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cross-version-quote-scope", action="store_true")
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
            result = cross_version_quote_scope(session, market) if args.cross_version_quote_scope else study(session, market)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('IRON_LIFECYCLE_') and code.isidentifier() else 'IRON_LIFECYCLE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
