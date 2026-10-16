"""Local MDS-only independent candidate replay: no fills, downloads or mutations."""

import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbol", default="jm")
    parser.add_argument("--contract", default="JM2701")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 21))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 9))
    args = parser.parse_args()
    if args.start > args.end or not args.env_file.is_file() or args.output.exists():
        parser.error("INVALID_WINDOW_ENV_OR_EXISTING_OUTPUT")
    root = Path(__file__).resolve().parents[2]
    frozen_paths = [
        root / p
        for p in (
            "packages/quant-core/guiyi_quant/lms_inspired.py",
            "packages/quant-core/guiyi_quant/lms405/__init__.py",
            "docs/research/lms-inspired-v1/STRATEGY.md",
            "scripts/research/lms_inspired_replay.py",
        )
    ]

    def hashes():
        return {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in frozen_paths
        }

    frozen_hashes = hashes()
    from lms405_replay import read_local
    from guiyi_quant.lms405 import Bar
    from guiyi_quant.lms_inspired import VERSION, State, batch, snapshot, restore
    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError

    try:
        with (
            SessionLocal() as session,
            readonly_transaction(session, timeout_seconds=120),
        ):
            market = build_market_data_service(session)
            listed = market.catalog.contract_fact(
                args.symbol, args.contract
            ).listed_date
            prefix = read_local(
                market,
                args.symbol,
                args.contract,
                "15m",
                listed,
                args.start - timedelta(days=1),
            )
            window = read_local(
                market, args.symbol, args.contract, "15m", args.start, args.end
            )

            def convert(result):
                return [
                    Bar(
                        args.contract,
                        b.bar_end,
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        start=b.bar_end - timedelta(minutes=15),
                    )
                    for b in result.bars
                ]

            before, bars = convert(prefix), convert(window)
            identity = dict(window.request_identity)
            coverage = [t.isoformat() for t in window.coverage]
        if len(before) < 50 or not bars:
            raise ValueError("PREFIX_OR_WINDOW_INSUFFICIENT")
        initial, _ = batch(State(args.contract), before, observe_only=True)
        final, frames = batch(initial, bars)
        middle = len(bars) // 2
        checkpoint, first = batch(initial, bars[:middle])
        resumed, second = batch(
            restore(json.loads(encode(snapshot(checkpoint)))), bars[middle:]
        )
        if first + second != frames or snapshot(resumed) != snapshot(final):
            raise ValueError("RESTART_PARITY_FAILED")
    except MarketDataError as exc:
        print(encode(dict(status="BLOCKED", reason=exc.code)))
        return 2
    except Exception as exc:
        print(
            encode(
                dict(
                    status="BLOCKED",
                    reason="READ_OR_REPLAY_UNVERIFIED",
                    error_type=type(exc).__name__,
                )
            )
        )
        return 2

    actions = [f for f in frames if f["action"]]
    raw = [
        [
            b.start.isoformat(),
            b.end.isoformat(),
            str(b.open),
            str(b.high),
            str(b.low),
            str(b.close),
        ]
        for b in before + bars
    ]
    if hashes() != frozen_hashes:
        print(encode(dict(status="BLOCKED", reason="SOURCE_CHANGED_DURING_RUN")))
        return 2
    code_hash = frozen_hashes["packages/quant-core/guiyi_quant/lms_inspired.py"]
    report = dict(
        version=VERSION,
        status="CANDIDATE_ACTION_REPLAY_ONLY",
        contract=args.contract,
        period="15m",
        window=[str(args.start), str(args.end)],
        prefix_bars=len(before),
        bars=len(bars),
        initial_position="FLAT_AFTER_OBSERVATION_ONLY_PREFIX",
        request_identity=identity,
        coverage=coverage,
        dataset_hash=digest(raw),
        code_hash=code_hash,
        source_hashes=frozen_hashes,
        frames_hash=digest(frames),
        counts=dict(Counter(f["action"] for f in actions)),
        environments=dict(Counter(f["features"]["environment"] for f in frames)),
        final_state=snapshot(final),
        restart_parity=True,
        sample_role="DEVELOPMENT_NOT_HOLDOUT",
        original_match_rate=None,
        fills=None,
        pnl=None,
        executable=False,
        actions=actions,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "input.json").write_text(encode(raw) + "\n")
    (args.output / "frames.json").write_text(encode(frames) + "\n")
    lines = [
        "# LMS-inspired v1 焦煤动作重放",
        "",
        f"具体合约 {args.contract}，15m，交易日 {args.start} 至 {args.end}。",
        f"预热 {len(before)} 根（只观察），窗口 {len(bars)} 根；窗口初始空仓。",
        f"动作计数：{report['counts']}；环境计数：{report['environments']}。",
        "批量/中途序列化重启结果一致。自定候选开发样本；没有作者匹配率、成交或收益。",
        "",
        "|信号收盘时间（UTC）|建议动作|原因|参考收盘|多腿|空腿|",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"|{f['known_at']}|{f['action']}|{f['reason']}|{f['reference_close']}|{f['long']}|{f['short']}|"
        for f in actions
    ]
    lines += [
        "",
        "未在样本出现的状态分支只能由合成单元测试覆盖，不代表市场验证。",
        "规则前缀只含过去完整 Bar；决策须到当前收盘才可知，外部执行必须严格晚于该时点。",
        "当根内先止损再恢复等路径不由 OHLC 推断。规则是否盈利、锁仓成本及资金要求未评估。",
    ]
    (args.output / "report.md").write_text("\n".join(lines) + "\n")
    # Completion report is written last; an interrupted partial directory is not success.
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        encode(
            {
                k: report[k]
                for k in (
                    "status",
                    "bars",
                    "prefix_bars",
                    "counts",
                    "restart_parity",
                    "dataset_hash",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
