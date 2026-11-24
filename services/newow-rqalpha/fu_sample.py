"""Reproduce the approved first FU2603 pair from the hash-verified P0 archive."""

import argparse
import gzip
import hashlib
import io
import json
import pickle
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path

from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.domain import CanonicalBar
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.product_contracts import ProductBar

from frozen_market import ASIA_SHANGHAI, DailyFacts, FrozenMarket, Minute, Session
from runner import Signal, run_proof

D = Decimal
CONTRACT = "FU2603"
DAY = date(2026, 1, 5)
MANIFEST = "fu-15m-manifest.json"
ARCHIVE = "fu-15m-000-FU2603.pickle.gz"
FACTS = "facts-attempt-001/FU2603.json"
MANIFEST_SHA = "589d6dcbfb59d31c48b8fba8c949723cc005df30c73c3c38d40cce0c744e337e"
COMPRESSED_SHA = "ce658bf3d9b672097cf03af660fec27e591c89a675e66a92d9416c02db2fd36f"
PAYLOAD_SHA = "114d2ee9a7da5adcf5113570d80ba4d59bad11302c4f5161fda765c10379d908"
FACTS_SHA = "b28f860978fe2d131001f925233d02ffe10c9f5f50111d9a6bf90671e1bd4335"
ALLOWED_PICKLE_CLASSES = {
    ("datetime", "date"): date, ("datetime", "datetime"): datetime,
    ("datetime", "timedelta"): timedelta, ("datetime", "timezone"): timezone,
    ("decimal", "Decimal"): Decimal,
}


class FrozenFixtureUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        try:
            return ALLOWED_PICKLE_CLASSES[module, name]
        except KeyError as exc:
            raise pickle.UnpicklingError("FROZEN_FIXTURE_TYPE_NOT_ALLOWED") from exc


def clock(hhmmss):
    return datetime.fromisoformat(f"{DAY}T{hhmmss}").replace(tzinfo=ASIA_SHANGHAI)


def checked_bytes(path, expected_sha):
    value = path.read_bytes()
    if hashlib.sha256(value).hexdigest() != expected_sha:
        raise ValueError(f"FROZEN_INPUT_DIGEST_MISMATCH {path.name}")
    return value


def load_market(root):
    manifest = json.loads(checked_bytes(root / MANIFEST, MANIFEST_SHA))
    identity, = (row for row in manifest if row["contract"] == CONTRACT)
    if identity["file"] != ARCHIVE or identity["sha256"] != PAYLOAD_SHA or identity["gaps"]:
        raise ValueError("P0_MANIFEST_NOT_ELIGIBLE")
    raw = gzip.decompress(checked_bytes(root / ARCHIVE, COMPRESSED_SHA))
    if hashlib.sha256(raw).hexdigest() != PAYLOAD_SHA:
        raise ValueError("FROZEN_PAYLOAD_DIGEST_MISMATCH")
    payload = FrozenFixtureUnpickler(io.BytesIO(raw)).load()
    owner_start, owner_end = (date.fromisoformat(identity[key]) for key in ("owner_start", "owner_end"))
    payload_identity = tuple(payload[key] for key in ("product", "frequency", "contract", "owner_start", "owner_end"))
    if payload_identity != ("fu", "15m", CONTRACT, owner_start, owner_end) or payload["gaps"]:
        raise ValueError("P0_PAYLOAD_IDENTITY_MISMATCH")

    sessions = tuple(Session(DAY, clock(start), clock(end)) for start, end in (
        ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00"),
    ))
    windows = {(session.start, session.end) for session in sessions}
    source = tuple(row for row in payload["minutes"] if row["day"] == DAY)
    if len(source) != 225 or any(
        row["eligible"] is not True or row["day_end"] != sessions[-1].end
        or (row["session_start"], row["session_end"]) not in windows
        or not row["session_start"] < row["time"] <= row["session_end"]
        for row in source
    ):
        raise ValueError("P0_M1_SESSION_FACTS_MISSING")
    minutes = tuple(Minute(DAY, row["time"], row["open"], row["high"], row["low"], row["close"], row["volume"])
                    for row in source)

    facts = json.loads(checked_bytes(root / FACTS, FACTS_SHA))
    instrument = facts["instrument"]
    if instrument["order_book_id"] != CONTRACT:
        raise ValueError("P0_INSTRUMENT_IDENTITY_MISMATCH")
    parameters, = (row for row in facts["parameters"] if row["date"] == DAY.isoformat())
    daily, = (row for row in facts["daily"] if row["date"] == DAY.isoformat())
    daily_facts = DailyFacts(DAY, D(daily["prev_settlement"]), D(daily["settlement"]),
                             D(daily["limit_down"]), D(daily["limit_up"]), parameters["commission_type"],
                             D(parameters["open_commission"]), D(parameters["close_commission"]),
                             D(parameters["close_commission_today"]), D(parameters["long_margin_ratio"]),
                             D(parameters["short_margin_ratio"]))
    return FrozenMarket(CONTRACT, "SHFE", owner_start, owner_end, D(instrument["tick_size"]),
                        int(instrument["contract_multiplier"]), sessions, minutes, (daily_facts,))


def frozen_signal_prefix(market):
    cutoff = clock("09:35:00")
    bars = tuple(CanonicalBar(row.end, row.day, row.open, row.high, row.low, row.close, row.volume, None, None)
                 for row in market.minutes if row.end <= cutoff)
    prefix = aggregate_from_1m(bars, target_frequency="5m", sessions=(SessionWindow(market.sessions[0].start, cutoff),))
    identity = build_product_identity("fu", "trend", "5m")
    segment = f"p0:{market.contract}:{market.window_start}:{market.window_end}"
    result = replay_strategy(identity, tuple(ProductBar(NewowDailyBar(
        "fu", market.contract, segment, bar.trading_day, bar.bar_end, bar.open, bar.high, bar.low, bar.close,
        int(bar.volume), None, f"p0:{PAYLOAD_SHA}", True, True,
    ), "5m") for bar in prefix))
    expected = (
        (clock("09:20:00"), "CLEAR", "INITIAL_CLEAR_NO_ENTRY"),
        (clock("09:30:00"), "BUILD", "ELIGIBLE"),
        (clock("09:35:00"), "CLEAR", "ELIGIBLE"),
    )
    actual = tuple((action.bar_end, action.kind.value, action.trade_eligibility.value) for action in result.actions)
    if (identity.profile_id != "newow_product_trend_5m_v1" or actual != expected
            or result.diagnostics != ("INITIAL_CLEAR_NO_ENTRY",)
            or result.actions[2].related_build_id != result.actions[1].signal_id):
        raise ValueError(f"P0_FROZEN_TREND_ACTIONS_DIVERGED {actual!r}")
    return (
        tuple(Signal(action.signal_id, action.physical_contract, action.trading_day, action.bar_end, action.kind.value)
              for action in result.actions),
        {"profile": identity.profile_id, "formula_versions": identity.formula_versions, "strategy_cutoff": cutoff,
         "m1_signal_inputs": len(bars), "m5_signal_inputs": len(prefix), "diagnostics": result.diagnostics,
         "actions": [{"bar_end": action.bar_end.astimezone(ASIA_SHANGHAI), "kind": action.kind.value,
                      "signal_id": action.signal_id, "related_build_id": action.related_build_id,
                      "eligibility": action.trade_eligibility.value, "reference_price": action.reference_price}
                     for action in result.actions]},
    )


def compare_native(result):
    comparisons = []
    first_mismatch = None

    def record(field, expected, actual):
        nonlocal first_mismatch
        observed = actual
        if isinstance(expected, Decimal) and isinstance(actual, float):
            observed = D(str(actual))
        row = {"field": field, "expected": expected, "observed": observed, "matches": observed == expected}
        if isinstance(expected, Decimal) and isinstance(actual, float):
            exact_binary = D.from_float(actual)
            with localcontext() as context:
                context.prec = max(exact_binary.adjusted(), expected.adjusted()) - min(
                    exact_binary.as_tuple().exponent, expected.as_tuple().exponent
                ) + 2
                row.update(native_float_hex=actual.hex(), native_float_as_exact_decimal=exact_binary,
                           binary_delta=exact_binary - expected)
        comparisons.append(row)
        if first_mismatch is None and not row["matches"]:
            first_mismatch = row

    record("initial_clear.reason", "NO_OPEN_POSITION", result["attempts"][0]["reason"])
    record("fill_count", 2, len(result["fills"]))
    for number, (label, modeled_open, native_at, side, effect, price, fee) in enumerate((
        ("build", "09:31:00", "09:32:00", "BUY", "OPEN", D("2485"), D("1.2425")),
        ("clear", "09:36:00", "09:37:00", "SELL", "CLOSE_TODAY", D("2480"), D("0")),
    ), start=1):
        attempt = result["attempts"][number]
        record(f"{label}.candidate_open_at", clock(modeled_open), attempt["candidate_open_at"])
        record(f"{label}.candidate_raw_open", price, attempt.get("frozen_candidate", {}).get("open"))
        record(f"{label}.native_order_at", clock(modeled_open), attempt.get("native_order_at"))
        fill = next((fill for fill in result["fills"] if fill["signal_id"] == attempt["signal_id"]), {})
        for field, expected in (("side", side), ("position_effect", effect), ("quantity", 1),
                                ("modeled_fill_at", clock(modeled_open)), ("native_event_at", clock(native_at)),
                                ("close_today_quantity", int(effect == "CLOSE_TODAY")),
                                ("price", price), ("commission", fee), ("fee", fee)):
            record(f"{label}.{field}", expected, fill.get(field))
    record("terminal_status", "FLAT", result["terminal_status"])
    before = D("10000")
    gross = (D("2480") - D("2485")) * 10
    fees = D("2485") * 10 * D("0.00005")
    final = before + gross - fees
    for field in ("cash", "equity"):
        record(f"settled.{field}", final, result["settlements"][-1]["after"][field])
    return {"gross_pnl": gross, "fees": fees, "net_pnl": gross - fees, "expected_final_equity": final,
            "comparison": "exact Decimal against the native float's shortest decimal rendering",
            "first_mismatch": first_mismatch, "comparisons": comparisons}


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported evidence type {type(value).__name__}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_directory", type=Path)
    parser.add_argument("output_file", type=Path)
    arguments = parser.parse_args()
    market = load_market(arguments.sample_directory)
    signals, strategy = frozen_signal_prefix(market)
    result = run_proof(market, signals, D("10000"))
    result.update(source={"manifest_sha256": MANIFEST_SHA, "archive_sha256": COMPRESSED_SHA,
                          "decompressed_sha256": PAYLOAD_SHA, "facts_sha256": FACTS_SHA,
                          "contract_owner_start": market.window_start, "contract_owner_end": market.window_end},
                  strategy=strategy, oracle=compare_native(result))
    with arguments.output_file.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2, default=json_value)
        output.write("\n")
    if result["oracle"]["first_mismatch"]:
        print(json.dumps(result["oracle"]["first_mismatch"], default=json_value))
        raise SystemExit(1)
    print(f"FU2603 replay matched the Decimal oracle. Evidence written to {arguments.output_file}")


if __name__ == "__main__":
    main()
