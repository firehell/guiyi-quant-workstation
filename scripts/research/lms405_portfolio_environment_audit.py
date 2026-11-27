"""Compare archived author context with the unchanged short-window research context."""

import argparse
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_managed_portfolio import BASELINE, BASELINE_SHA256
from lms405_minute_recovery_context import study as study_minute_context
from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, DAYS, FIVE, LOCAL, input_sources
from lms405_protection_shape_audit import price_digest
from lms405_protection_timeframes import read_window
from lms405_replay import ohlc, read_session_series
from lms405_right_side_study import US
from lms_near405_replay import encoded, sha

# Only normalize explicit descriptions in the existing article tables.
# Qualified cycle descriptions and the PVC chapter that mentions 5.0 are visible separately.
PLANS = {
    23: ("A5357264059367516", "A5357264793370945",
         ("RANGE", "RANGE_MIXED", "UP_CYCLE", "RANGE", "UP_CYCLE", "UP_PVC_CONTEXT", None, "DOWN", "RANGE")),
    26: ("A5358325549629506", "A5358325972992140",
         ("RANGE", "RANGE", "RANGE", "RANGE", "RANGE", "RANGE", None, "DOWN", "RANGE")),
    27: ("A5358686423089344", "A5358686695981271",
         ("RANGE", "DOWN", "RANGE", "RANGE", "UP_CYCLE", "RANGE", None, "DOWN", "RANGE")),
}
BACKUP = {"RU2701", "TA2701", "SH2701"}
MINUTE_CONTEXT = (Path("output/lms405-minute-recovery-context-20261126/replay-a.json"),
                  "4d4d3f6ec34603c4542bfb451cf860236e7ac1289cc76f61df6cd28bede7d48c")
LABEL_CUES = {"RANGE": ("盘整",), "RANGE_MIXED": ("盘整与循环交替",), "DOWN": ("空头趋势",),
              "UP_CYCLE": ("多循环", "多头循环"), "UP_PVC_CONTEXT": ("多趋势",), None: ("建模",)}


def archive_case(index, source_id, session_date, contract, author_class):
    source = index[source_id]
    published = datetime.fromisoformat(source["published_at"]).astimezone(LOCAL)
    if published.date() != session_date or not time(15) < published.time() < time(21):
        raise ValueError("ENVIRONMENT_SOURCE_WINDOW_CHANGED")
    path = ARCHIVE.parent / source["archive_path"]
    raw = path.read_bytes()
    lines = [line for line in raw.decode().splitlines() if line.startswith(f"|{contract}|")]
    if len(lines) != 1:
        raise ValueError("ENVIRONMENT_SOURCE_ROW_CHANGED")
    label = lines[0].split("|")[2]
    if not any(cue in label for cue in LABEL_CUES[author_class]):
        raise ValueError("ENVIRONMENT_SOURCE_LABEL_CHANGED")
    return source | dict(archived_label=label, sha256=sha(raw))


def clocks(bars, session_date):
    day_close = datetime.combine(session_date, time(15), LOCAL)
    night_start = datetime.combine(session_date, time(21), LOCAL)
    close_index = next(i for i, bar in enumerate(bars) if bar.end == day_close)
    close = candidate.context(bars[:close_index + 1], close_index)
    if close is None:
        raise ValueError("DAY_CLOSE_CONTEXT_MISSING")
    night = [(i, bar) for i, bar in enumerate(bars) if night_start < bar.end <= night_start + 7 * FIVE]
    expected = [night_start + i * FIVE for i in range(1, 8)]
    if [bar.end for _, bar in night] != expected:
        raise ValueError("NIGHT_CONTEXT_WINDOW_INCOMPLETE")
    contexts = []
    for i, bar in night[1:]:
        context = candidate.context(bars[:i + 1], i)
        if context is None or context != candidate.context(bars, i):
            raise ValueError("ENVIRONMENT_PREFIX_DIVERGED")
        contexts.append(dict(clock=bar.end, environment=context["environment"],
                             input_first=context["window_start"], input_last=context["window_end"]))
    return dict(day_close=close, opening_clocks=contexts,
                opening_flips=sum(a["environment"] != b["environment"] for a, b in zip(contexts, contexts[1:])))


def summarize(rows):
    clear = [r for r in rows if r["author_class"] in ("RANGE", "DOWN")]
    coarse = [r for r in rows if r["author_class"] is not None]
    for row in coarse:
        label = row["author_class"].split("_")[0]
        sequence = [x["environment"] for x in row["opening_clocks"]]
        row.update(coarse_class=label, close_agrees=row["day_close"]["environment"] == label,
                   first_open_agrees=sequence[0] == label, all_open_agree=all(state == label for state in sequence))
    columns = ("close_agrees", "first_open_agrees", "all_open_agree")
    return {name: dict(count=len(group), labels=dict(Counter(r["coarse_class"] for r in group)),
                       **{key: sum(r[key] for r in group) for key in columns},
                       opening_flips=sum(r["opening_flips"] > 0 for r in group))
            for name, group in (("clear_wording", clear), ("include_qualified_contexts", coarse))}


def context_before(bars, cutoff):
    prefix = [bar for bar in bars if bar.end + US < cutoff]
    return candidate.context_from_window(prefix[-6:])


def known_and(left, right):
    if left is False or right is False:
        return False
    return None if left is None or right is None else True


def opening_alternatives(rows):
    clear = [row for row in rows if row["author_class"] in ("RANGE", "DOWN")]
    totals = {mode: Counter() for mode in ("ROLLING", "HOLD_DAY_CLOSE", "TWO_LOCAL_VOTES")}
    for row in clear:
        rolling = [slot["environment"] for slot in row["opening_clocks"]]
        parked = row["day_close"]["environment"]
        elected, previous = parked, None
        votes = []
        for state in rolling:
            if state == previous:
                elected = state
            votes.append(elected)
            previous = state
        for name, states in zip(totals, (rolling, [parked] * len(rolling), votes), strict=True):
            expected = row["author_class"]
            totals[name].update({
                "cases": 1, "first_agrees": int(states[0] == expected),
                "all_agree": int(all(value == expected for value in states)),
                "cases_with_flip": int(len(set(states)) > 1),
            })
    return totals


def minute_gate_comparison(session, market):
    frozen = verified_json(*MINUTE_CONTEXT)
    local = study_minute_context(session, market)
    if encoded(local) != encoded(frozen):
        raise ValueError("ENVIRONMENT_MINUTE_CONTEXT_CHANGED")
    result = []
    for contract, row in local["cases"].items():
        five = read_window(session, market, contract, date.fromisoformat(row["trading_day"]))[5]
        for item in row["candidates"]:
            contexts = item["context"]
            at_shape = contexts["before_shape"]
            shape, confirmation = (contexts[key]["known_before"] for key in ("before_shape", "before_confirmation"))
            shape_env, confirm_env = (context_before(five, cut) for cut in (shape, confirmation))
            direction = "UP" if item["proposal"]["action"] == "UNLOCK_LONG" else "DOWN"
            aligned = shape_env["environment"] == direction if shape_env else None
            atr_context = at_shape["atr_context"]
            atr = atr_context["exceeds_atr14"]["trading_day_range"] if atr_context else None
            contraction = at_shape["contraction"]
            day = contraction["trading_day"]
            narrowed = day["latest_narrower_than_opening"] if day else None
            segment = contraction["continuous_session"]
            local_narrowed = segment["latest_narrower_than_opening"] if segment else None
            result.append(dict(
                contract=contract, proposal=item["proposal"], shape_context=shape_env,
                pre_confirmation_context=confirm_env, atr_above_prior14=atr,
                session_narrower_than_opening=local_narrowed, day_narrower_than_opening=narrowed,
                same_direction_environment=aligned,
                known_negative_author_case=contract == "V2609",
                hypothetical_admission=dict(
                    direction_context_only=aligned, atr_only=atr, day_narrowing_only=narrowed,
                    direction_context_and_atr=known_and(aligned, atr),
                    direction_context_and_day_narrowing=known_and(aligned, narrowed),
                    direction_context_and_segment_narrowing=known_and(aligned, local_narrowed),
                ),
            ))
    return result


def study(session, market, *, compare_admission=False):
    reference = verified_json(BASELINE, BASELINE_SHA256)
    index = input_sources()
    rows = []
    for number, contract in enumerate(CONTRACTS):
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        bars = [Bar(contract, bar.bar_end, *ohlc(bar), start=bar.bar_end - FIVE) for bar in raw]
        digest = sha(encoded(price_digest(bars)).encode())
        if digest != reference["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("ENVIRONMENT_FROZEN_MARKET_CHANGED")
        for session_date in DAYS[:-1]:
            main, backup, labels = PLANS[session_date.day]
            source_id = backup if contract in BACKUP else main
            author_class = labels[number]
            row = dict(contract=contract, author_class=author_class, source_id=source_id,
                       session_date=session_date, market_sha256=digest,
                       source=archive_case(index, source_id, session_date, contract, author_class))
            rows.append(row | clocks(bars, session_date))
    extra = {}
    if compare_admission:
        extra["admission_comparison"] = dict(
            opening_alternatives=opening_alternatives(rows),
            minute_recovery_candidates=minute_gate_comparison(session, market),
            minute_context_sha256=MINUTE_CONTEXT[1], actual_author_timeframe_labels=0,
        )
    return dict(version="lms405-portfolio-environment-audit-v1", label_comparison=summarize(rows), cases=rows,
                rule_hash=candidate.RULE_HASH, frozen_baseline_sha256=BASELINE_SHA256,
                comparison_role="ARCHIVED_WORDING_VERSUS_RESEARCH_CLOCKS_ONLY",
                admitted_author_action_samples=0, author_action_matches=None, executable=False, fills=None, pnl=None,
                **extra)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare-admission", action="store_true")
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
            report = study(session, build_market_data_service(session), compare_admission=args.compare_admission)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError, StopIteration):
        parser.exit(2, "ENVIRONMENT_AUDIT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
