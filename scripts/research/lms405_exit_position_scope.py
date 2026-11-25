"""Bound reported exit candidates with reconciled display tables and quote windows."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_i2701_case import FROZEN_COMPARISON_SHA256
from lms405_night_close_alignment import IMAGE, IMAGE_SHA, ROWS as NIGHT_CLOSE_ROWS
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_position_continuity import EXPOSURE, INPUTS, PVC, SNAPSHOTS, snapshot_sources
from lms405_protection_lot_timing import verified_json
from lms405_replay import photo_comparison, read_session_series
from lms405_right_side_study import ONE, at
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

EARLY, MIDDAY, FIRST_NIGHT, NIGHT_CLOSE = "WRoql30FdC", "WRoqSWwLTg", "WRov1j6e10", "WRovrUdwHi"
NEXT_EARLY, LUNCH, CLOSE = "WRozNbg3en", "WRoAkcEppg", "U03"
PHOTOS = Path("output/lms-v-ta-oct-20261125/comparison.json")
PHOTOS_SHA = "fcb5f1f9252afa59346910ef843e4d4ddfae682f4580b6acc13935fab22998af"
NIGHT = Path("output/lms405-night-close-alignment-20261125/final.json")
NIGHT_SHA = "ccb400e96f33a8b944addefc314f1ad3b5e0b84bd8b8bc997bfbbcfae8f9087c"
IRON = Path("output/lms-i2701-oct-20261125/comparison.json")
GLASS = Path("output/lms405-fg-exit-20261125/final.json")
GLASS_SHA = "42263c39dfe67167ede40436e5f0f50cd35e33225e2c4cd4ac899fffa21ef78f"
DAY, FOLLOWING = date(2026, 10, 26), date(2026, 10, 27)
# Image transcription: contract, direction, total, today, opening average, and displayed price difference.
DAY_ROWS = {
    EARLY: (
        ("IM2612", "short", 4, 4, "6616", None), ("TA2701", "long", 34, 34, "6548", "54"),
        ("V2701", "long", 40, 0, "5045", "178"), ("SA2701", "short", 20, 20, "962.9", "10.9"),
        ("JM2701", "short", 20, 20, "1406.17", "6.17"), ("J2701", "short", 10, None, None, None),
        ("RB2701", "short", 40, 0, "3068.3", "28.3"), ("SH2701", "short", 20, 0, "1720", "173"),
        ("I2701", "short", 16, 0, "682.5", "14"), ("RU2701", "long", 20, 20, "19800", "-40"),
    ),
    MIDDAY: (
        ("IM2612", "long", 4, 4, "6527.75", None), ("IM2612", "short", 4, 4, "6616", None),
        ("FG2701", "short", 20, 20, "835", "-1"), ("SA2701", "short", 20, 20, "962.9", "7.9"),
        ("JM2701", "short", 20, 20, "1406.17", "17.67"), ("J2701", "short", 10, None, None, None),
        ("RB2701", "short", 40, 0, "3068.3", "32.3"), ("SH2701", "short", 20, 0, "1720", "177"),
        ("I2701", "short", 16, 0, "682.5", "13.5"),
    ),
}
DAY_IMAGES = {
    EARLY: ("Roql30FdC-position-screen.png", "a04a15ffe26365621b062208cfc8cd808c56e624ee2bdaae5444c0641eada52c"),
    MIDDAY: ("RoqSWwLTg-iiflkl0ci5-screen.png", "b68ee9819018c8b288f78e532b810797fd648134e464cd921953905f3aad03a0"),
}
EXTRA = {
    FIRST_NIGHT: (("J2701", "short", 10), ("RB2701", "short", 40)),
    NEXT_EARLY: (("IM2612", "short", 4), ("RB2701", "short", 40)),
    LUNCH: (("IM2612", "short", 8), ("J2701", "long", 10), ("RB2701", "long", 40), ("RB2701", "short", 40)),
    CLOSE: (("J2701", "long", 10),),
}
DISPLAY_TOTALS = {EARLY: (10, 224), MIDDAY: (9, 154), FIRST_NIGHT: (10, 246), NIGHT_CLOSE: (7, 176),
                  NEXT_EARLY: (9, 200), LUNCH: (13, 310), CLOSE: (8, 182)}
CASES = {
    "pvc_daytime": ("V2701", "long", EARLY, MIDDAY, FIRST_NIGHT, DAY),
    "pvc_night": ("V2701", "long", FIRST_NIGHT, NIGHT_CLOSE, LUNCH, FOLLOWING),
    "glass_afternoon": ("FG2701", "short", LUNCH, CLOSE, None, FOLLOWING),
    "soda_morning": ("SA2701", "short", NIGHT_CLOSE, LUNCH, None, FOLLOWING),
}


def leg(quantity, today=None, average=None):
    return dict(quantity=quantity, today_quantity=today, opening_average=average)


def checked_table(source, rows):
    expected_rows, expected_lots = DISPLAY_TOTALS[source]
    if (len(rows) != expected_rows or sum(row["quantity"] for row in rows.values()) != expected_lots
            or any(row["quantity"] <= 0 for row in rows.values())):
        raise ValueError("EXIT_SCOPE_DISPLAY_RECONCILIATION_FAILED")
    return rows


def display_rows(tables):
    rows = {source: {f"{contract}/{side}": leg(q, today, avg) for contract, side, q, today, avg, _ in raw}
            for source, raw in DAY_ROWS.items()}
    rows[NIGHT_CLOSE] = {
        f"{s.upper()}2701/short": leg(q, {"fg": 20, "oi": 40, "sa": 20, "i": None}.get(s, 0), avg)
        for s, (q, avg, _) in NIGHT_CLOSE_ROWS.items()
    }
    for source, auxiliary in EXTRA.items():
        rows[source] = {
            f"{contract}/{side}": value for contract, item in tables[source]["contracts"].items()
            for side, value in item["legs"].items()
        } | {f"{contract}/{side}": leg(q) for contract, side, q in auxiliary}
    return {source: checked_table(source, values) for source, values in rows.items()}


def scenario(tables, anchors, *, key, before, gap, after):
    original, intermediate = tables[before].get(key), tables[gap].get(key)
    later = tables[after].get(key) if after else None
    if original is None or intermediate is not None or (after and later is None):
        raise ValueError("EXIT_SCOPE_EXPECTED_LEG_VISIBILITY_CHANGED")
    left, right = anchors[before], anchors[gap]
    next_quotes = anchors.get(after, ())
    comparable_prices = bool(left and right and max(left) < min(right))
    reopen_order = bool(right and next_quotes and max(right) < min(next_quotes)) if after else None
    shared = []
    for identity in sorted(tables[before].keys() & tables[gap].keys()):
        first, second = tables[before][identity], tables[gap][identity]
        old_avg, new_avg = first["opening_average"], second["opening_average"]
        if old_avg is not None and new_avg is not None and first["quantity"] == second["quantity"] and (
            Decimal(old_avg) == Decimal(new_avg)
        ):
            shared.append(identity)
    return dict(observed_before=original, observed_gap=None, observed_after=later,
                same_scope_hypothesis=dict(
                    requires=("SAME_ACCOUNT", "COMPLETE_ACCOUNT_DISPLAY", "POSITIONS_SYNCHRONIZED_WITH_QUOTES",
                              "CAPTURES_IN_ASSUMED_ORDER"),
                    missing_leg_quantity=0, minimum_prior_lots_closed=original["quantity"],
                    minimum_later_lots_reopened=later["quantity"] if later else None,
                    ordered_quote_bounds_verified=comparable_prices,
                    ordered_reopen_quote_bounds_verified=reopen_order,
                    earliest_before_quote=min(left) if comparable_prices else None,
                    latest_gap_quote=max(right) if comparable_prices else None,
                ), shared_unchanged_quantity_and_open_average=shared,
                account_scope_verified=None, author_action_identity=None, exact_close_lots=None)


def study(session, market):
    docs = {path: verified_json(path, digest) for path, digest in INPUTS.items()}
    known = snapshot_sources(docs[EXPOSURE], docs[SNAPSHOTS])
    rows = display_rows(known)
    index = input_sources()
    evidence = {source: dict(url=index[source]["source_url"], published_at=index[source]["published_at"],
                            path=index[source]["archive_path"]) for source in rows}
    files = {source: (IMAGE.parent / image, digest) for source, (image, digest) in DAY_IMAGES.items()}
    files[NIGHT_CLOSE] = (IMAGE, IMAGE_SHA)
    for source, (path, digest) in files.items():
        if sha(path.read_bytes()) != digest:
            raise ValueError("EXIT_SCOPE_ATTACHMENT_CHANGED")
        evidence[source]["image"] = dict(path=str(path.relative_to(ARCHIVE.parent)), sha256=digest)
    for source in EXTRA:
        evidence[source]["image"] = known[source]["image"]
    photo_refs = verified_json(PHOTOS, PHOTOS_SHA)["photos"]
    night_ref = verified_json(NIGHT, NIGHT_SHA)
    early_ref = verified_json(IRON, FROZEN_COMPARISON_SHA256)["photos"][NEXT_EARLY]
    glass_ref = verified_json(GLASS, GLASS_SHA)["october"]
    series, photo_rows = {}, {}

    def bars(contract, day):
        if (contract, day) not in series:
            series[contract, day] = read_session_series(session, market, contract[:-4].lower(), contract,
                                                        "1m", ONE, (day,))
        return series[contract, day]

    def stamps(raw):
        return [datetime.fromisoformat(x) for x in raw]

    for source, data in DAY_ROWS.items():
        marks = {contract: str(Decimal(avg) + (1 if side == "long" else -1) * Decimal(gain))
                 for contract, side, _, _, avg, gain in data if gain is not None}
        photo_rows[source] = photo_comparison({contract: bars(contract, DAY) for contract in marks},
                                             at("2026-10-26T09:00"),
                                             datetime.fromisoformat(evidence[source]["published_at"]), marks)
    anchors = {source: stamps(photo_rows[source]["joint_contains"]) for source in DAY_ROWS}
    anchors.update({source: stamps([known[source]["quote_anchor"]]) for source in (LUNCH, CLOSE)})
    anchors[NIGHT_CLOSE] = stamps(night_ref["quote_alignment"]["joint_contains"])
    anchors[FIRST_NIGHT] = stamps(photo_refs[FIRST_NIGHT]["joint_contains"])
    anchors[NEXT_EARLY] = stamps(early_ref["joint_contains"])
    pvc_row_anchors = {
        EARLY: stamps(photo_rows[EARLY]["per_symbol"]["V2701"]["contains"]),
        FIRST_NIGHT: stamps(photo_refs[FIRST_NIGHT]["per_symbol"]["v"]["contains"]),
    }
    pvc_fallback_anchors = {source: matches for source, matches in pvc_row_anchors.items() if not anchors[source]}
    cases = {}
    for name, (contract, side, before, gap, after, day) in CASES.items():
        case_anchors = anchors | (pvc_fallback_anchors if contract == "V2701" else {})
        result = scenario(rows, case_anchors, key=f"{contract}/{side}", before=before, gap=gap, after=after)
        earlier, later = (result["same_scope_hypothesis"][k] for k in ("earliest_before_quote", "latest_gap_quote"))
        window = [row for row in bars(contract, day) if earlier and earlier <= row.bar_end <= later]
        price_span = dict(low=min(r.low for r in window), high=max(r.high for r in window)) if window else None
        cases[name] = result | dict(contract=contract, side=side, before_source=before, gap_source=gap,
                                    after_source=after,
                                    before_uses_pvc_quote_only=contract == "V2701" and before in pvc_fallback_anchors,
                                    coarse_price_envelope=price_span)
    software_time = at(f"2026-10-26T{docs[PVC]['software_row']['displayed_time']}")
    night_quotes = pvc_row_anchors[FIRST_NIGHT]
    pvc_software_comparison = dict(assumed_date=DAY, quantity_and_version_verified=False,
                                   earlier_than_complete_quote_candidate_minute_count=sum(
                                       software_time < quote - ONE for quote in night_quotes),
                                   within_quote_candidate_minute_count=sum(
                                       quote - ONE <= software_time < quote for quote in night_quotes))
    return dict(version="lms405-exit-position-scope-v1", sources=evidence, display_totals=DISPLAY_TOTALS,
                quote_anchors=anchors, day_quote_alignment=photo_rows, observed_rows=rows, cases=cases,
                pvc_row_price_anchors=pvc_row_anchors, pvc_software_time_comparison=pvc_software_comparison,
                pvc_software_row=docs[PVC]["software_row"], glass_software_rows=glass_ref["software_rows"],
                quote_evidence_roles={FIRST_NIGHT: "PVC_ROW_ONLY", NEXT_EARLY: "JOINT_MATCH_UNRESOLVED",
                                      LUNCH: "JOINT_DISPLAYED_PRICES", CLOSE: "JOINT_DISPLAYED_PRICES",
                                      NIGHT_CLOSE: "JOINT_DISPLAYED_PRICES"},
                market={f"{c}:{day}": dict(bars=len(b), sha256=bars_sha(b)) for (c, day), b in series.items()},
                reference_sha256={str(path): digest for path, digest in (INPUTS | {
                    PHOTOS: PHOTOS_SHA, NIGHT: NIGHT_SHA, IRON: FROZEN_COMPARISON_SHA256, GLASS: GLASS_SHA,
                }).items()}, admitted_author_action_samples=0, author_matches=None, executable=False,
                fills=None, pnl=None)


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
        parser.exit(2, f"{code if code.startswith('EXIT_SCOPE_') and code.isidentifier() else 'EXIT_SCOPE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
