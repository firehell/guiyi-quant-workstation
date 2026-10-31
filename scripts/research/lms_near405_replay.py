"""Static offline replay for lms-near405-v1; human decisions default, no fills."""

import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
from html import escape
import json
from pathlib import Path
import sys

from lms_confirmed_replay import read_bars, _csv


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        + "\n"
    )


def summarize(result):
    records = result["checkpoint"]["decision_records"]
    return dict(
        mode=result.get(
            "mode",
            "TIMELY_TEST_FIXTURE" if result.get("timely_fixture") else "HUMAN_RESEARCH",
        ),
        evaluation_count=len(result["evaluations"]),
        environment_counts=dict(
            Counter((e.get("environment") or "WARMUP") for e in result["evaluations"])
        ),
        proposal_count=len(result["proposals"]),
        proposal_action_counts=dict(
            Counter(
                p.get("suggested_action", p.get("action")) for p in result["proposals"]
            )
        ),
        proposal_status_counts=dict(Counter(p["status"] for p in result["proposals"])),
        human_decision_count=sum(
            isinstance(d, dict) and d.get("record_kind") == "HUMAN_RESEARCH_DECISION"
            for d in records
        ),
        fixture_decision_count=sum(
            isinstance(d, dict) and d.get("record_kind") == "TEST_FIXTURE"
            for d in records
        ),
        transition_count=len(result["transitions"]),
        invalid_decision_count=sum(
            d.get("status") == "INVALID" for d in result["decisions"]
        ),
        terminal_state=result["current_state"],
    )


def render_html(result):
    sections = []
    for key, label in [
        ("summary", "统计与末端状态"),
        ("evaluations", "逐Bar环境、区域、形态与评估"),
        ("proposals", "建议（未应用不等于无信号）"),
        ("decisions", "决定与拒绝理由"),
        ("transitions", "研究状态转换（不是成交）"),
    ]:
        sections.append(
            f"<section><h2>{label}</h2><pre>{escape(encoded(result.get(key, [])))}</pre></section>"
        )
    return (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>LMS近似完整策略静态回放</title>
<style>body{font:15px system-ui;max-width:1250px;margin:28px auto;padding:0 18px;color:#203040}.note{background:#fff0db;padding:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:14px}section{margin:28px 0}a{margin-right:16px}</style>
<h1>lms-near405-v1 完整近似研究策略</h1><p class="note">本报告为全段回看静态报告，不表示当时已知全部未来行情。规则与所有参数在本轮回放前冻结。本候选补全≠作者原版公式；executable=false，Fill、收益、成本与保证金均null。人工模式没有ACCEPT不推进研究状态；明确启用的TIMELY_TEST_FIXTURE只是“假设所有建议及时确认”的演示，不是用户操作、作者交易、Paper或盈利。</p>
<p>"""
        + escape(str(result.get("mode", "HUMAN_RESEARCH")))
        + """</p><p><a href="report.json">完整JSON</a><a href="evaluations.csv">逐Bar评估</a><a href="proposals.csv">建议</a><a href="decisions.csv">决定</a><a href="transitions.csv">转换</a><a href="checkpoint.json">checkpoint</a><a href="state-timeline.json">状态时间线</a></p>"""
        + "".join(sections)
        + """<p>UI实际点击未验：既有宿主禁止file://并明确禁止替代路径绕过；本轮未开发交互页面或启动HTTP服务。CLI与静态产物验证不能冒充浏览器交互验收。</p></html>"""
    )


def validate_provenance(bars, input_hash, provenance):
    """Supplied authoritative Session export must cover the exact frozen rows."""
    if provenance.get("csv_sha256") != input_hash:
        raise ValueError("PROVENANCE_SNAPSHOT_MISMATCH")
    identity = provenance["request_identity"]
    if identity["frequency"] != "5m" or any(
        b.contract != identity["contract"] for b in bars
    ):
        raise ValueError("PROVENANCE_IDENTITY_MISMATCH")
    expected = set()
    for sessions in provenance["sessions"].values():
        for session in sessions:
            start = datetime.fromisoformat(session["start"])
            end = datetime.fromisoformat(session["end"])
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                raise ValueError("PROVENANCE_SESSION_INVALID")
            cursor = start + timedelta(minutes=5)
            while cursor <= end:
                expected.add(cursor)
                cursor += timedelta(minutes=5)
    if expected != {b.end for b in bars} or len(expected) != len(bars):
        raise ValueError("PROVENANCE_SESSION_COVERAGE_MISMATCH")


def write_report(
    source,
    output,
    input_hash,
    decisions,
    as_of,
    checkpoint=None,
    *,
    timely_fixture=False,
    decision_file_sha256=None,
    checkpoint_file_sha256=None,
    provenance=None,
    provenance_file_sha256=None,
):
    if output.exists() or output.is_symlink():
        raise FileExistsError("OUTPUT_ALREADY_EXISTS")
    bars = read_bars(source, input_hash)
    if provenance is not None:
        validate_provenance(bars, input_hash, provenance)
    from guiyi_quant import lms_near405 as core
    from guiyi_quant import lms_keybar_approx as keybar

    cutoff = as_of or bars[-1].end + timedelta(microseconds=3)
    result = core.replay(
        bars,
        decisions,
        as_of=cutoff,
        checkpoint=checkpoint,
        timely_fixture=timely_fixture,
    )
    result["mode"] = "TIMELY_TEST_FIXTURE" if timely_fixture else "HUMAN_RESEARCH"
    result["summary"] = summarize(result)
    result["artifact_identity"] = dict(
        input_sha256=input_hash,
        decisions_semantic_sha256=sha(encoded(decisions).encode()),
        decision_file_sha256=decision_file_sha256,
        checkpoint_file_sha256=checkpoint_file_sha256,
        checkpoint_semantic_sha256=sha(encoded(checkpoint).encode())
        if checkpoint
        else None,
        core_sha256=sha(Path(core.__file__).read_bytes()),
        cli_sha256=sha(Path(__file__).read_bytes()),
        keybar_sha256=sha(Path(keybar.__file__).read_bytes()),
        provenance_file_sha256=provenance_file_sha256,
    )
    result["input_provenance"] = provenance
    result["input_validation"] = (
        "EXACT_AUTHORITATIVE_SESSION_COVERAGE"
        if provenance is not None
        else "FROZEN_SNAPSHOT_HASH_ONLY_NO_NEW_SESSION_CLAIM"
    )
    timeline = [
        dict(
            kind="EXPLICIT_FLAT_INITIAL_RESEARCH_STATE",
            state=result["checkpoint"].get("initial_state"),
        )
    ] + result["transitions"]
    payloads = {
        "index.html": render_html(result),
        "checkpoint.json": encoded(result["checkpoint"]),
        "state-timeline.json": encoded(timeline),
    }
    for key in ("evaluations", "proposals", "decisions", "transitions"):
        payloads[key + ".csv"] = _csv(result[key])
    output.mkdir(parents=True, exist_ok=False)
    (output / "INCOMPLETE").write_text(
        "Construction in progress; not a complete report\n"
    )
    for name, value in payloads.items():
        (output / name).write_text(value, encoding="utf-8")
    (output / "report.json").write_text(encoded(result), encoding="utf-8")
    (output / "COMPLETE").write_text(sha((output / "report.json").read_bytes()) + "\n")
    (output / "INCOMPLETE").unlink()
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--input-sha256", required=True)
    p.add_argument("--decisions", type=Path)
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--as-of", type=datetime.fromisoformat)
    p.add_argument("--timely-fixture", action="store_true")
    p.add_argument("--provenance", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        raw_decisions = a.decisions.read_bytes() if a.decisions else None
        raw_checkpoint = a.checkpoint.read_bytes() if a.checkpoint else None
        raw_provenance = a.provenance.read_bytes() if a.provenance else None
        decisions = json.loads(raw_decisions) if raw_decisions is not None else []
        if not isinstance(decisions, list):
            raise ValueError("DECISION_LIST_REQUIRED")
        result = write_report(
            a.input,
            a.output,
            a.input_sha256,
            decisions,
            a.as_of,
            json.loads(raw_checkpoint) if raw_checkpoint else None,
            timely_fixture=a.timely_fixture,
            decision_file_sha256=sha(raw_decisions) if raw_decisions else None,
            checkpoint_file_sha256=sha(raw_checkpoint) if raw_checkpoint else None,
            provenance=json.loads(raw_provenance) if raw_provenance else None,
            provenance_file_sha256=sha(raw_provenance) if raw_provenance else None,
        )
    except FileExistsError:
        print("OUTPUT_ALREADY_EXISTS", file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, OSError, ImportError):
        print("NEAR405_REPLAY_FAILED_INPUT_OUTPUT_OR_DEPENDENCY", file=sys.stderr)
        return 2
    print(
        json.dumps(
            dict(
                status="RESEARCH_REPLAY_WRITTEN",
                version=result["version"],
                mode=result["mode"],
                summary=result["summary"],
                executable=False,
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
