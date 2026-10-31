"""Freeze protection/restoration suggestions for independent hypothetical states."""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
import hashlib
import json
from pathlib import Path
import sys

from guiyi_quant.lms405 import Bar, Position
from guiyi_quant import lms_protection_proposals as policy
from guiyi_quant.lms_keybar_approx import replay
from lms_keybar_approx_replay import build_report as keybar_report, render_chart, _csv


LABELS = {
    "DIRECTIONAL_LONG": "单向多头前像",
    "DIRECTIONAL_SHORT": "单向空头前像",
    "LOCKED_LONG": "已锁定、原方向多",
    "LOCKED_SHORT": "已锁定、原方向空",
}


def preview_states(bars: list[Bar]) -> list[dict]:
    if not bars:
        raise ValueError("BARS_REQUIRED")
    frames, _ = replay(bars)
    seed_time = bars[0].start - timedelta(microseconds=1)
    result = []
    for locked in (False, True):
        for side in ("LONG", "SHORT"):
            state = policy.ResearchState(
                Position(
                    bars[0].contract,
                    Decimal(int(locked or side == "LONG")),
                    Decimal(int(locked or side == "SHORT")),
                ),
                side,
                seed_time,
                seed_time,
            )
            evaluations = []
            for i, following in enumerate(bars[1:], 1):
                if frames[i - 1].has_pattern:
                    evaluations.append(
                        policy.recommend(
                            state,
                            frames[i - 1],
                            following,
                            as_of=following.end + timedelta(microseconds=1),
                        )
                    )
            sid = f"{state.phase}_{side}"
            result.append(
                dict(
                    scenario_id=sid,
                    label=LABELS[sid],
                    unit_position={
                        "long": str(state.position.long),
                        "short": str(state.position.short),
                    },
                    state_since=seed_time.isoformat(),
                    evaluations=evaluations,
                    proposal_count=sum(e["status"] == "PROPOSAL" for e in evaluations),
                )
            )
    return result


def build_report(path: Path) -> dict:
    base = keybar_report(path)
    bars = []
    for r in base["frames"]:
        end = datetime.fromisoformat(r["bar_end"])
        bars.append(
            Bar(
                r["contract"],
                end,
                *(Decimal(r[k]) for k in ("open", "high", "low", "close")),
                start=end - timedelta(minutes=5),
            )
        )
    return dict(
        report_version="lms-protection-preview-v1",
        policy_version=policy.VERSION,
        input_mode="FOUR_INDEPENDENT_STATIC_STATE_SCENARIOS",
        seed_kind="COUNTERFACTUAL_UNIT_STATE_BEFORE_FROZEN_WINDOW",
        as_of_kind="DERIVED_RESEARCH_TIME_NEXT_BAR_END_PLUS_ONE_MICROSECOND",
        confirmation_mode="PROPOSAL_ONLY_NO_STATE_APPLICATION",
        code_sha256={
            "policy": hashlib.sha256(Path(policy.__file__).read_bytes()).hexdigest(),
            "preview": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        keybar_report=base,
        scenarios=preview_states(bars),
        author_action_match_rate=None,
        fill=None,
        performance=None,
        executable=False,
    )


def render_html(result: dict, svg: str) -> str:
    sections = []
    for scenario in result["scenarios"]:
        rows = []
        for e in scenario["evaluations"]:
            action = e["suggested_action"] or "无建议"
            after = json.dumps(
                e["hypothetical_unit_position_after"], ensure_ascii=False
            )
            rows.append(
                "<tr>"
                + "".join(
                    f"<td>{escape(str(x))}</td>"
                    for x in (
                        e["signal_bar_end"][5:19].replace("T", " "),
                        e["available_after"][5:19].replace("T", " "),
                        e["status"],
                        action,
                        ", ".join(e["basis"]),
                        after,
                    )
                )
                + "</tr>"
            )
        sections.append(f"""<section><h2>{escape(scenario["label"])}</h2>
<p>每行固定前像：{escape(json.dumps(scenario["unit_position"]))}；{len(scenario["evaluations"])}项独立评估，{scenario["proposal_count"]}条建议。每条建议都未应用，后续行不继承它的假设后像。</p>
<div class="scroll"><table><tr><th>形态K收盘</th><th>确认K收盘后才可读</th><th>判定</th><th>建议</th><th>触发依据</th><th>假设接受后的单位状态</th></tr>{"".join(rows)}</table></div></section>""")
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{policy.VERSION} 保护与恢复建议预览</title>
<style>body{{font:15px system-ui;max-width:1400px;margin:28px auto;padding:0 20px;color:#203040}}.note{{background:#edf3fa;padding:16px}}svg{{width:100%;height:auto}}.scroll{{overflow:auto}}td,th{{padding:8px;border:1px solid #d5dde5;text-align:left}}table{{border-collapse:collapse;width:100%}}section{{margin:28px 0}}code{{overflow-wrap:anywhere}}</style>
<h1>{policy.VERSION}：保护与恢复建议</h1>
<p class="note">四个独立前像，用来检查同一信号对不同研究状态的含义。建议须人工确认，本工具不自动改变研究状态；没有记录任何人的确认，也不是成交、连续持仓链或作者动作还原。executable=false，作者动作匹配率、Fill和收益均为null。</p>
<h2>固定规则</h2><ul>
<li>沿用5m ibar/pinbar。只在下一输入Bar收盘严格越过形态K高低后考虑；ibar按突破方向，pinbar须突破方向与长影形态方向一致。叠加时按各自规则列依据，不把未确认pinbar变成ibar的隐藏否决。</li>
<li>单向状态遇反向确认只建议LOCK，保留原腿；已锁定状态仅在原方向确认时建议UNLOCK_LONG或UNLOCK_SHORT。反向确认不反手、不抓M；空仓不建议新开。</li>
<li>形态K必须晚于输入状态生效时点；as_of须严格晚于确认K收盘且输入状态已知。每条建议绑定精确状态与Bar身份，可重复读取，但从不自动应用。</li></ul>
<p>动作语义参考E41；F05/F06保留人工参与线索。全部信号触发、优先级和单位前像均为我们补全的研究假设，结构解释卡不是隐藏交易Gate。</p>
<p>四个前像均人为设在冻结窗口开始前1微秒；评估时刻为确认K收盘后1微秒，仅为研究可读性代理，不是作者时刻或实际执行时刻。单位1不是实盘手数。输入为原138根冻结JM2509 5m数据，未下载或修复行情。</p>
<p><a href="proposals.csv">全部建议与无建议评估CSV</a> · <a href="report.json">完整JSON、前像与代码指纹</a> · <a href="chart.svg">底层形态SVG</a></p>
{"".join(sections)}<h2>底层形态背景</h2><p>图中只标底层形态，不把建议画成成交；作者图与本地Bar仍仅暂定对应。</p>{svg}
</html>"""


def write_report(source: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("OUTPUT_ALREADY_EXISTS")
    result = build_report(source)
    svg = render_chart(result["keybar_report"])
    rows = []
    for scenario in result["scenarios"]:
        for e in scenario["evaluations"]:
            row = {"scenario_id": scenario["scenario_id"], **e}
            rows.append(
                {
                    k: json.dumps(v, ensure_ascii=False)
                    if isinstance(v, (dict, list))
                    else v
                    for k, v in row.items()
                }
            )
    payloads = {
        "index.html": render_html(result, svg),
        "chart.svg": svg,
        "proposals.csv": _csv(rows, list(rows[0])),
        "report.json": json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    }
    output.mkdir(parents=True, exist_ok=False)
    for name, value in payloads.items():
        with (output / name).open("x", encoding="utf-8") as handle:
            handle.write(value)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = write_report(args.input, args.output)
    except FileExistsError:
        print("OUTPUT_ALREADY_EXISTS", file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, ImportError):
        print(
            "PROPOSAL_PREVIEW_FAILED_INPUT_OUTPUT_OR_RENDER_DEPENDENCY", file=sys.stderr
        )
        return 2
    print(
        json.dumps(
            {
                "status": "RESEARCH_PREVIEW_WRITTEN",
                "policy_version": policy.VERSION,
                "scenarios": len(result["scenarios"]),
                "executable": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
