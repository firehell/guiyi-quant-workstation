"""Read-only local physical-contract path replay; no provider/download/runtime."""

import argparse
import hashlib
import json
from datetime import date, datetime, UTC, timedelta
from pathlib import Path

from guiyi_quant.lms405 import Bar, inspect_bar, VERSION

WINDOWS = [
    ("fg", "FG2609", "2026-08-10", "2026-08-21"),
    ("fg", "FG2701", "2026-09-21", "2026-10-09"),
    ("jm", "JM2701", "2026-09-21", "2026-10-09"),
]


def read_local(market, symbol, contract, frequency, since, through):
    from app.market_data.domain import BarFrequency, ContractTradingDayQuery

    result = market.query_contract_trading_days(
        ContractTradingDayQuery(
            symbol, contract, BarFrequency(frequency), since, through
        )
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--frequency",
        choices=["1m", "5m", "15m", "30m", "60m", "1d", "1w"],
        default="1m",
    )
    parser.add_argument("--mode", choices=["author", "independent"], default="author")
    args = parser.parse_args()
    from dotenv import load_dotenv

    if not args.env_file.is_file():
        parser.error("ENV_FILE_MISSING")
    load_dotenv(args.env_file, override=False)
    # Imports occur only after existing host configuration loads. Never log it.
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError

    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    # No current source proves an author zone was known before these windows.
    zones = []
    for symbol, contract, start, end in WINDOWS:
        row = {
            "contract": contract,
            "frequency": args.frequency,
            "window": [start, end],
            "status": "BLOCKED",
            "bar_count": 0,
            "prefix_status": "NOT_EVALUATED",
            "source_timeframe": "UNKNOWN",
            "k_signal_eligible": False,
            "behavior_matches": None,
            "eligible_behavior_cases": 0,
        }
        try:
            with (
                SessionLocal() as session,
                readonly_transaction(session, timeout_seconds=120),
            ):
                market = build_market_data_service(session)
                result = read_local(
                    market,
                    symbol,
                    contract,
                    args.frequency,
                    date.fromisoformat(start),
                    date.fromisoformat(end),
                )
                bars = result.bars
                output = [
                    {
                        "time": b.bar_end.isoformat(),
                        "open": str(b.open),
                        "high": str(b.high),
                        "low": str(b.low),
                        "close": str(b.close),
                        "observation": inspect_bar(
                            Bar(contract, b.bar_end, b.open, b.high, b.low, b.close),
                            zones,
                            mode=args.mode,
                        ),
                    }
                    for b in bars
                ]
                encoded = json.dumps(
                    output, ensure_ascii=False, separators=(",", ":")
                ).encode()
                (args.output / f"{contract}.json").write_bytes(encoded)
                row.update(
                    status="WINDOW_READABLE",
                    bar_count=len(bars),
                    coverage=[x.isoformat() for x in result.coverage]
                    if result.coverage
                    else None,
                    input_snapshot_hash=hashlib.sha256(
                        json.dumps(
                            [
                                {k: v for k, v in item.items() if k != "observation"}
                                for item in output
                            ],
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                    replay_output_hash=hashlib.sha256(encoded).hexdigest(),
                    request_identity=dict(result.request_identity),
                    reason=None,
                )
                # Exact lifecycle prefix; no implicit shortening or replacement.
                try:
                    prefix = read_local(
                        market,
                        symbol,
                        contract,
                        args.frequency,
                        market.catalog.contract_fact(symbol, contract).listed_date,
                        date.fromisoformat(start) - timedelta(days=1),
                    )
                    row.update(
                        prefix_status="WINDOW_READABLE",
                        prefix_count=len(prefix.bars),
                        prefix_coverage=[x.isoformat() for x in prefix.coverage]
                        if prefix.coverage
                        else None,
                    )
                except MarketDataError as exc:
                    row.update(prefix_status="BLOCKED", prefix_reason=exc.code)
        except MarketDataError as exc:
            row.update(
                status="BLOCKED",
                bar_count=0,
                reason=exc.code,
                prefix_status="BLOCKED",
                prefix_reason=exc.code,
            )
        except Exception as exc:
            row.update(
                status="BLOCKED",
                bar_count=0,
                reason="LOCAL_READ_UNVERIFIED",
                prefix_status="BLOCKED",
                prefix_reason="LOCAL_READ_UNVERIFIED",
            )
            row["error_type"] = type(exc).__name__
        rows.append(row)
    report = {
        "version": VERSION,
        "mode": args.mode,
        "observed_at": datetime.now(UTC).isoformat(),
        "results": rows,
        "conclusion": "PARTIAL_RECONSTRUCTION",
        "causal_research": "EXECUTION_FACTS_MISSING",
        "performance": None,
        "signal_precision": None,
        "signal_recall": None,
        "node_tick_error": None,
        "unresolved": [
            "AUTHOR_ZONES_NOT_VERIFIABLY_AVAILABLE_IN_WINDOW",
            "COMPLETE_ACTION_TIMELINE_MISSING",
            "BBB_FORMULA_UNKNOWN",
            "SCREENSHOT_PERIOD_UNKNOWN",
        ],
        "no_download": True,
        "no_production_write": True,
    }
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    render_chart(args.output, rows)
    print(
        json.dumps(
            {"output": str(args.output), "results": rows},
            ensure_ascii=False,
            default=str,
        )
    )


def render_chart(output, rows):
    """Standalone SVG price paths, never labels geometric touches as fills."""
    from html import escape

    parts = [
        '<!doctype html><meta charset="utf-8"><title>LMS405 evidence paths</title><h1>LMS405 本地价格路径</h1><p>仅价格路径；作者动作、周期与事前节点不足，不表示成交或信号匹配。</p>'
    ]
    for row in rows:
        contract = row["contract"]
        parts.append(f"<h2>{escape(contract)}</h2>")
        if row["status"] != "WINDOW_READABLE":
            parts.append(f"<p>缺口：{escape(row['reason'])}</p>")
            continue
        bars = json.loads((output / f"{contract}.json").read_text())
        if not bars:
            parts.append("<p>无 Bar</p>")
            continue
        values = [float(b["close"]) for b in bars]
        lower = min(values)
        upper = max(values)
        span = upper - lower or 1
        points = " ".join(
            f"{20 + i * 960 / max(1, len(values) - 1):.2f},{250 - (v - lower) * 220 / span:.2f}"
            for i, v in enumerate(values)
        )
        parts.append(
            f'<p>{escape(bars[0]["time"])} 至 {escape(bars[-1]["time"])}；{len(bars)} Bar；close {lower}–{upper}</p><svg viewBox="0 0 1000 280" width="100%"><polyline fill="none" stroke="#357" stroke-width="1" points="{points}"/></svg>'
        )
        if contract == "FG2609":
            parts.append(
                "<p>E43：8月18日事后说明前日防御 870–875、回补失败。未确认原发布时点与动作时间，未放入此前决策。</p>"
            )
        else:
            parts.append(
                "<p>现有持仓快照无法重建进入—锁定—解锁时序。10月9日17:22节点在本窗口收盘后发布，未参与重放。</p>"
            )
    (output / "comparison.html").write_text("\n".join(parts))


if __name__ == "__main__":
    main()
