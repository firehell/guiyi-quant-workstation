"""Compare source roles and account-independent unit task projections for LMS 4.0.5."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.task_roles import ROUTES, TaskBook, assess_task_action
from lms405_counter_m_lot_roles import RETENTION, RETENTION_SHA, exposure
from lms405_exposure_audit import TOTALS, reconcile_display
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import ONE, US
from lms405_sizing_audit import EXPOSURE_SHA256
from lms405_visible_lock_handoff import stamp
from lms_near405_replay import encoded, sha

VERSION = "lms405-task-role-comparison-v1"
SOURCES = ("S5325329692361179", "S5307830937850724", "WR2IUYCQHj")
SH_MARKET = Path("output/lms405-sh2609-price-roles-20261125/report.json")
SH_HASH = "65c6494ad19377baa6cce0261f1cb233a0a7dbe1fe8d327dd7e7ded8671749a3"
JM_MARKET = Path("output/lms405-versioned-lock-20261125/verified.json")
JM_HASH = "e61635c6ca198163dabf2ed9d7dfbcca4b71b38dd322f739f2e01f0b17ec8b74"
OI_MARKET = Path("output/lms-oi2609-june-20261124/comparison.json")
OI_HASH = "b1b35238a8ff776b243dc9b3490865c7339f71ac68aa1cd26559d464acc113dc"
ONE_LOT = Decimal(1)
EXPOSURE_PATH = Path("output/lms405-exposure-20261125/exposure-audit.json")
TOTALS_SHA = "474d797405d0e124d391aa34649d892948a4088f0c9963c0c3401bf8ee56ccd0"
OCT_23 = ("WRnTlEfj1t", "WRnY5bznUE", "WRo00BFM1E", "WRo2KQ43iX")
CHAINS = {
    "soda_oct23": ("SH2701", OCT_23),
    "soda_oct27": ("SH2701", ("WRoAkcEppg", "U03", "WRoEvasxQR")),
    "coal_oct23": ("JM2701", (OCT_23[0], *OCT_23[2:])),
}


def compare_routes(book, source, hypotheses, *, available_at, author_version):
    as_of = book.known_at + 3 * US
    results = {}
    for purpose, hypothetical_block in hypotheses.items():
        scope = book.scope(purpose, ONE_LOT, source, available_at, True)
        fact_at = book.known_at + US
        fixture_facts = tuple(
            Condition(name, scope, book.trend.contract, name != hypothetical_block,
                      fact_at, fact_at + US, "TEST_FIXTURE", "EVENT_TIME") for name in ROUTES[purpose]
        )
        actual = assess_task_action(book, purpose, ONE_LOT, (), as_of=as_of, source=source,
                                    source_available_at=available_at, version_405=author_version)
        boundary = assess_task_action(book, purpose, ONE_LOT, fixture_facts, as_of=fact_at + US, source=source,
                                      source_available_at=available_at, version_405=True)
        fixture = assess_task_action(book, purpose, ONE_LOT, fixture_facts, as_of=as_of, source=source,
                                     source_available_at=available_at, version_405=True)
        if actual["after"] is not None or boundary["after"] is not None:
            raise ValueError("TASK_ROLE_CONDITION_USED_BEFORE_AVAILABLE")
        results[purpose] = dict(public_evidence_only=actual, fixture=fixture,
                                fixture_mode="EXPLICIT_HYPOTHETICAL_TASKS_AND_CONDITIONS")
    return results


def report():
    sh = verified_json(SH_MARKET, SH_HASH)["windows"]
    jm = verified_json(JM_MARKET, JM_HASH)["coal"]
    oi = verified_json(OI_MARKET, OI_HASH)
    index = input_sources()
    sources = {source: index[source] | dict(
        archive_sha256=sha((ARCHIVE.parent / index[source]["archive_path"]).read_bytes()),
    ) for source in SOURCES}
    sh_source, jm_source, oi_source = SOURCES
    sh_version, jm_version = None, True
    sh_available, jm_available, oi_available = (stamp(sources[key]) + ONE for key in SOURCES)
    sh_contract, jm_contract, oi_contract = "SH2609", "JM2609", "OI2609"
    if jm["contract"] != jm_contract or oi["contract"] != oi_contract:
        raise ValueError("TASK_ROLE_MARKET_CONTRACT_DRIFT")

    sh_book = TaskBook(Position(sh_contract, ONE_LOT, ONE_LOT), Position(sh_contract, ONE_LOT),
                       "SHORT", "fixture-old-short", "fixture-distinct-long-m", sh_available + US)
    jm_book = TaskBook(Position(jm_contract, ONE_LOT), Position(jm_contract),
                       "LONG", "fixture-old-long", "fixture-unopened-short-m", jm_available + US)
    cases = {
        "sh_short_trend_and_long_m": dict(
            contract=sh_contract, source=sh_source, version_405=sh_version,
            author_description=dict(original="SHORT_TREND_NOT_YET_ALLOWED_TO_RESUME",
                                    counter_m="LONG_SHORT_TERM_SHOULD_EXIT", action_report_is_instruction=True),
            market=dict(weak_side_extreme_m=sh["jul27_extreme_m"]["levels"]["extreme_m_band"],
                        original_recovery_reference=sh["jul27_no_unlock_reported"]["levels"][
                            "same_day_retrospective_reference"],
                        market_range=sh["jul27_no_unlock_reported"]["range"]),
            projections=compare_routes(sh_book, sh_source,
                                       {"EXIT_COUNTER_M": None, "RESUME_TREND": "ORIGINAL_PLAN_VALID"},
                                       available_at=sh_available, author_version=sh_version),
            actual_book=None, actual_amount=None, actual_action_at=None,
        ),
        "jm_long_trend_protection": dict(
            contract=jm_contract, source=jm_source, version_405=jm_version,
            author_description=dict(original="LOCK_ALREADY_REPORTED", counter_m="FORWARD_SHORT_TERM_GUIDANCE",
                                    counter_m_guidance_version="4.0.5", counter_m_execution_reported=False),
            market=dict(old_band_day=jm["before_night"]["band_observations"],
                        old_band_night=jm["night"]["band_observations"],
                        next_divider=jm["forward_plan_price_only"]["short_divider"]),
            projections=compare_routes(jm_book, jm_source, {"LOCK_TREND": None},
                                       available_at=jm_available, author_version=jm_version),
            actual_book=None, actual_amount=None, actual_action_at=None,
        ),
        "oi_reported_counter_m_handoff": dict(
            contract=oi_contract, source=oi_source, version_405=True, earliest_source_observation=oi_available,
            author_description=dict(original="LONG_PROTECTION_BEFORE_OR_INSIDE_10273_10315",
                                    counter_m="REPORTED_UNLOCK_TO_SHORT_FOR_M",
                                    profit_taking_for_reentered_position_version="5.0"),
            market=oi["price_paths"]["1m"]["2026-06-05"],
            projections=None, actual_book=None, actual_amount=None, actual_action_at=None,
        ),
    }
    return dict(version=VERSION, sources=sources, cases=cases, admitted_author_actions=0,
                author_match_rate=None, executable=False, fills=None, pnl=None,
                market_reference_sha256={str(SH_MARKET): SH_HASH, str(JM_MARKET): JM_HASH, str(OI_MARKET): OI_HASH})


def turnover_bounds(before, after, before_day, after_day, retention):
    """Lower bounds conditional on both tableaux covering the same full position."""
    result = {}
    for side in ("long", "short"):
        prior, later = (snapshot.get(side) for snapshot in (before, after))
        old, new = (row["quantity"] if row else 0 for row in (prior, later))
        minimum, maximum = 0, min(old, new)
        old_today = prior["today_quantity"] if prior else 0
        new_today = later["today_quantity"] if later else 0
        if before_day != after_day:
            if new_today is not None:
                maximum = min(maximum, new - new_today)
        elif new_today is not None:
            minimum = new - new_today
            if minimum > old - (old_today or 0):
                raise ValueError("LMS_TASK_TURNOVER_PRIOR_LOTS_INCREASED_SAME_DAY")
            if old_today is not None:
                maximum = minimum + min(old_today, new_today)
        counts = retention.get(side)
        if counts is not None and (not counts or any(not minimum <= n <= maximum for n in counts)):
            raise ValueError("LMS_TASK_TURNOVER_RETENTION_CONFLICT")
        retained_min, retained_max = (min(counts), max(counts)) if counts is not None else (minimum, maximum)
        result[side] = dict(
            retained_min=retained_min, retained_max=retained_max,
            minimum_close=old - retained_max, minimum_open=new - retained_max,
        )
    return result


def turnover_report():
    tables = verified_json(EXPOSURE_PATH, EXPOSURE_SHA256)["tables"]
    references = verified_json(RETENTION, RETENTION_SHA)
    total_rows = {row["source"]: row for row in verified_json(TOTALS, TOTALS_SHA)}
    table_index = {(row["source"], row["table"]): row for row in tables}
    source_ids = sorted({sid for _, ids in CHAINS.values() for sid in ids})
    evidence, displays = {}, {}
    for sid in source_ids:
        total = total_rows[sid]
        table = table_index[sid, total["table"]]
        source = references["snapshot_sources"][sid]
        picture = source["image"]
        if table["image"] != picture or sha((ARCHIVE.parent / picture["path"]).read_bytes()) != picture["sha256"]:
            raise ValueError("LMS_TASK_TURNOVER_IMAGE_CHANGED")
        evidence[sid] = reconcile_display(table, total) | dict(
            quote_anchor=source["quote_anchor"], trading_day=source["trading_day"],
            archive_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()),
        )
        displays[sid] = table["contracts"]

    results = {}
    for label, (contract, ids) in CHAINS.items():
        rows = [evidence[sid] for sid in ids]
        times = [datetime.fromisoformat(row["published_at"]) for row in rows]
        if times != sorted(set(times)):
            raise ValueError("LMS_TASK_TURNOVER_SOURCE_ORDER_CHANGED")
        legs = [displays[sid][contract]["legs"] for sid in ids]
        checks = {(row["before"], row["after"], row["side"]): row["retained"]
                  for row in references["contracts"][contract]["checks"]}
        transitions = []
        for left, right, before, after in zip(ids[:-1], ids[1:], legs[:-1], legs[1:], strict=True):
            retained = {side: checks.get((left, right, side)) for side in ("long", "short")}
            bounds = turnover_bounds(before, after, evidence[left]["trading_day"],
                                     evidence[right]["trading_day"], retained)
            transitions.append(dict(before=left, after=right, sides=bounds))
        results[label] = dict(
            contract=contract, sources=ids,
            displayed_legs=legs, unlisted_leg_is_unknown=True,
            conditional_exposure=[exposure(Position(contract, *(
                Decimal(snapshot.get(side, {}).get("quantity", 0)) for side in ("long", "short")
            ))) for snapshot in legs],
            conditional_transitions=transitions,
            minimum_total_open_close_lots=sum(
                side["minimum_close"] + side["minimum_open"]
                for transition in transitions for side in transition["sides"].values()
            ),
            author_action_at=None, author_role_assignment=None,
        )
    return dict(
        version="lms405-task-visible-turnover-v1", sources=evidence, cases=results,
        conditional_assumptions=["SAME_ACCOUNT_AND_STRATEGY", "EACH_DISPLAY_COVERS_ALL_ACCOUNT_LEGS",
                                 "CAPTURE_ORDER_MATCHES_SOURCE_ORDER_AND_RESOLVED_TRADING_DATES",
                                 "POSITION_SYNCHRONIZED_WITH_AVAILABLE_QUOTE_ANCHORS",
                                 "TODAY_QUANTITY_USES_RESOLVED_TRADING_DAY"],
        source_order_is_publication_not_execution_time=True,
        references=dict(positions=EXPOSURE_SHA256, retention=RETENTION_SHA, display_totals=TOTALS_SHA),
        admitted_author_actions=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--turnover", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    try:
        data = encoded(turnover_report() if args.turnover else report())
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(data)
    except (OSError, KeyError, ValueError):
        parser.exit(2, "TASK_ROLE_STUDY_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
