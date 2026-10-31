"""Offline confirmed research replay. No service, fills, orders or market mutation."""

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys

from guiyi_quant.lms405 import Bar


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_bars(path, expected_hash):
    raw = path.read_bytes()
    if sha(raw) != expected_hash:
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    bars = []
    for row in csv.DictReader(StringIO(raw.decode("utf-8"))):
        if row["frequency"] != "5m":
            raise ValueError("FIVE_MINUTE_INPUT_REQUIRED")
        end = datetime.fromisoformat(row["bar_end_shanghai"])
        if "completed" in row and row["completed"].lower() not in ("true", "1"):
            raise ValueError("COMPLETED_INPUT_REQUIRED")
        for field in ("start", "bar_start_shanghai", "bar_start_utc"):
            if field in row and datetime.fromisoformat(row[field]) != end - timedelta(
                minutes=5
            ):
                raise ValueError("FIVE_MINUTE_INPUT_REQUIRED")
        if "bar_end_utc" in row and end != datetime.fromisoformat(row["bar_end_utc"]):
            raise ValueError("BAR_TIMESTAMP_MISMATCH")
        bars.append(
            Bar(
                row["contract"],
                end,
                *(Decimal(row[k]) for k in ("open", "high", "low", "close")),
                start=end - timedelta(minutes=5),
            )
        )
    if not bars:
        raise ValueError("BARS_REQUIRED")
    return bars


def _json(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        + "\n"
    )


def _csv(rows):
    fields = list(dict.fromkeys(k for row in rows for k in row)) or ["status"]
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(
        {
            k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            for k, v in row.items()
        }
        for row in rows
    )
    return stream.getvalue()


def summarize(result):
    records = result["checkpoint"]["decision_records"]
    result["summary"] = dict(
        proposal_count=len(result["proposals"]),
        proposal_status_counts={
            status: sum(p["status"] == status for p in result["proposals"])
            for status in ("PENDING", "EXPIRED", "ACCEPTED", "REJECTED")
        },
        human_decision_count=sum(
            isinstance(d, dict) and d.get("record_kind") == "HUMAN_RESEARCH_DECISION"
            for d in records
        ),
        test_fixture_decision_count=sum(
            isinstance(d, dict) and d.get("record_kind") == "TEST_FIXTURE"
            for d in records
        ),
        transition_count=len(result["transitions"]),
        invalid_decision_count=sum(
            d["status"] == "INVALID" for d in result["decisions"]
        ),
    )
    return result


def render_html(result, bars, prefixes):
    # Embedded full history is a downloadable research artifact; the default visible UI
    # renders only its selected prefix. The explicit hindsight toggle reveals all rows.
    data = _json(dict(report=result, bars=bars, prefixes=prefixes)).replace(
        "<", "\\u003c"
    )
    return (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>LMS 人工确认连续研究回放</title><style>
body{font:15px system-ui;max-width:1200px;margin:24px auto;padding:0 18px;color:#203040}button,input{margin:6px;padding:7px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f8;padding:12px}.note{padding:14px;background:#fff1dc}table{border-collapse:collapse}td,th{border:1px solid #ccd5dd;padding:6px}canvas{width:100%;border:1px solid #ddd}</style>
<h1>人工确认连续研究回放</h1><p class="note">独立近似研究，不是作者原版或历史真实操作。executable=false；Fill、收益均null。页面只编辑决定草稿，<b>仅 CLI 验证重算后生效</b>。没有操作即零确认。历史游标决定是用户对历史假设情景的决定；recorded_at另存实际记录时间。</p>
<p>路径：导出决定草稿 → CLI --decisions 文件验证重算至新目录 → 重新打开新报告。导入仅恢复草稿，不改变可信状态。</p>
<label>逐Bar游标 <input id="cursor" type="range" min="0" value="0"></label><span id="time"></span>
<label><input id="hindsight" type="checkbox">回看模式（全段未来走势）</label>
<canvas id="chart" width="1100" height="280"></canvas>
<h2>当前游标已揭示行情</h2><pre id="bars"></pre>
<h2>CLI 验证的状态及时间线</h2><pre id="state"></pre><pre id="timeline"></pre>
<h2>建议视图</h2><div id="proposals"></div>
<h2>确认视图（CLI 已验证输入）</h2><pre id="decisions"></pre>
<h2>转换视图（研究状态，不是成交）</h2><pre id="transitions"></pre>
<h2>决定草稿</h2><label>记录身份 <select id="kind"><option>HUMAN_RESEARCH_DECISION</option><option>TEST_FIXTURE</option></select></label>
<button id="export">导出决定草稿</button><label>导入草稿 <input id="import" type="file" accept="application/json"></label><pre id="drafts"></pre><p id="error"></p>
<p><a href="report.json">完整回看JSON</a> · <a href="evaluations.csv">评估CSV</a> · <a href="proposals.csv">建议CSV</a> · <a href="decisions.csv">确认CSV</a> · <a href="transitions.csv">转换CSV</a> · <a href="checkpoint.json">checkpoint</a> · <a href="state-timeline.json">状态时间线</a></p>
<script id="data" type="application/json">"""
        + data
        + """</script><script>
const data=JSON.parse(document.getElementById('data').textContent), el=id=>document.getElementById(id);
let drafts=[];el('cursor').max=Math.max(0,data.bars.length-1);
const pretty=x=>JSON.stringify(x,null,2);
function draw(rows){const c=el('chart'),x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);if(!rows.length)return;
const lo=Math.min(...rows.map(r=>Number(r.low))),hi=Math.max(...rows.map(r=>Number(r.high))),scale=(v)=>250-(Number(v)-lo)/(hi-lo||1)*220;
rows.forEach((r,i)=>{const px=20+i*(1060/Math.max(rows.length,1));x.strokeStyle=Number(r.close)>=Number(r.open)?'#c66':'#298';x.beginPath();x.moveTo(px,scale(r.high));x.lineTo(px,scale(r.low));x.stroke();x.lineWidth=4;x.beginPath();x.moveTo(px,scale(r.open));x.lineTo(px,scale(r.close));x.stroke();x.lineWidth=1;});}
function render(){const i=Number(el('cursor').value),b=data.bars[i],r=data.prefixes[i]||data.report;
el('time').textContent=b?b.end:'';const rows=el('hindsight').checked?data.bars:data.bars.slice(0,i+1);draw(rows);el('bars').textContent=pretty(rows);
el('state').textContent=pretty(r.current_state);el('timeline').textContent=pretty({version:r.version,executable:false,fill:null,performance:null,summary:r.summary});
el('decisions').textContent=pretty(r.decisions);el('transitions').textContent=pretty(r.transitions);el('proposals').replaceChildren();
(r.proposals||[]).forEach(p=>{const box=document.createElement('div'),text=document.createElement('pre');text.textContent=pretty(p);box.append(text);
if(p.status==='PENDING'&&b){['ACCEPT','REJECT'].forEach(choice=>{const button=document.createElement('button');button.textContent=choice+' 草稿';button.onclick=()=>{
// Python alone applies state. Research timestamp is provided by the CLI prefix.
const t=b.research_decision_time;drafts.push({decision_id:'draft-'+crypto.randomUUID(),proposal_id:p.proposal_id,state_fingerprint:p.state_fingerprint,decision:choice,decided_at:t,known_at:t,record_kind:el('kind').value,recorded_at:new Date().toISOString()});el('drafts').textContent=pretty(drafts);};box.append(button);});}el('proposals').append(box);});}
el('cursor').oninput=render;el('hindsight').onchange=render;
function stableRecord(v){if(Array.isArray(v))return v.map(stableRecord);if(v&&typeof v==='object')return Object.fromEntries(Object.keys(v).sort().map(k=>[k,stableRecord(v[k])]));return v;}
function exportRecords(){const prefix=data.prefixes[Number(el('cursor').value)]||data.report;const records=[...(prefix.checkpoint.decision_records||[]),...drafts];return records.filter((r,i)=>records.findIndex(x=>JSON.stringify(stableRecord(x))===JSON.stringify(stableRecord(r)))===i);}
el('export').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([pretty(exportRecords())+'\\n'],{type:'application/json'}));a.download='research-decisions.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),0);};
el('import').onchange=async()=>{try{const v=JSON.parse(await el('import').files[0].text());if(!Array.isArray(v))throw Error('决定文件必须为JSON数组');drafts=v;el('drafts').textContent=pretty(drafts);el('error').textContent='已导入草稿，尚未验证或应用；导出保留当前 CLI 已验证前缀记录';}catch(e){el('error').textContent='导入失败：'+e.message;}};render();
</script></html>"""
    )


def write_report(
    source,
    output,
    input_hash,
    initial,
    decisions,
    as_of,
    checkpoint=None,
    *,
    decision_file_sha256=None,
    checkpoint_file_sha256=None,
):
    if output.exists() or output.is_symlink():
        raise FileExistsError("OUTPUT_ALREADY_EXISTS")
    from guiyi_quant import lms_confirmed_replay as core
    from guiyi_quant import (
        lms_protection_proposals as proposals,
        lms_keybar_approx as keybar,
    )

    bars = read_bars(source, input_hash)
    state = core.state_from_dict(initial)
    cutoff = as_of or bars[-1].end + timedelta(microseconds=3)
    result = summarize(
        core.replay(bars, state, decisions, as_of=cutoff, checkpoint=checkpoint)
    )
    result["artifact_identity"] = dict(
        input_sha256=input_hash,
        initial_state_sha256=sha(_json(initial).encode()),
        decisions_sha256=sha(_json(decisions).encode()),
        cli_sha256=sha(Path(__file__).read_bytes()),
        core_sha256=sha(Path(core.__file__).read_bytes()),
        proposal_code_sha256=sha(Path(proposals.__file__).read_bytes()),
        keybar_code_sha256=sha(Path(keybar.__file__).read_bytes()),
        decision_file_sha256=decision_file_sha256,
        decision_source="FILE"
        if decision_file_sha256
        else "IN_MEMORY_OR_EMPTY_BASELINE",
        checkpoint_file_sha256=checkpoint_file_sha256,
        checkpoint_sha256=sha(_json(checkpoint).encode()) if checkpoint else None,
    )
    prefix_decisions = result["checkpoint"]["decision_records"]
    prefixes = [
        summarize(
            core.replay(
                bars[: i + 1],
                state,
                prefix_decisions,
                as_of=min(b.end + timedelta(microseconds=3), cutoff),
            )
        )
        for i, b in enumerate(bars)
        if b.end + timedelta(microseconds=1) <= cutoff
    ]
    visible_bars = [
        dict(
            asdict(b),
            research_decision_time=(b.end + timedelta(microseconds=2)).isoformat(),
        )
        for b in bars
        if b.end + timedelta(microseconds=1) <= cutoff
    ]
    payloads = {
        "index.html": render_html(result, visible_bars, prefixes),
        "checkpoint.json": _json(result["checkpoint"]),
        "state-timeline.json": _json(
            [
                dict(
                    known_at=initial["known_at"],
                    state=initial,
                    kind="EXPLICIT_INITIAL_STATE",
                )
            ]
            + [
                dict(
                    known_at=t["known_at"],
                    state=t["after"],
                    kind=t["record_kind"],
                    decision_id=t["decision_id"],
                )
                for t in result["transitions"]
            ]
        ),
    }
    for key in ("evaluations", "proposals", "decisions", "transitions"):
        payloads[key + ".csv"] = _csv(result[key])
    # An interrupted output stays visibly incomplete; report and marker are written last.
    output.mkdir(parents=True, exist_ok=False)
    (output / "INCOMPLETE").write_text("Report construction in progress\n")
    for name, value in payloads.items():
        (output / name).write_text(value, encoding="utf-8")
    (output / "report.json").write_text(_json(result), encoding="utf-8")
    (output / "COMPLETE").write_text(sha((output / "report.json").read_bytes()) + "\n")
    (output / "INCOMPLETE").unlink()
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--input-sha256", required=True)
    p.add_argument("--initial-state", type=Path, required=True)
    p.add_argument("--decisions", type=Path)
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--as-of", type=datetime.fromisoformat)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        initial = json.loads(a.initial_state.read_text())
        decisions = json.loads(a.decisions.read_text()) if a.decisions else []
        if not isinstance(decisions, list):
            raise ValueError("DECISION_LIST_REQUIRED")
        result = write_report(
            a.input,
            a.output,
            a.input_sha256,
            initial,
            decisions,
            a.as_of,
            json.loads(a.checkpoint.read_text()) if a.checkpoint else None,
            decision_file_sha256=sha(a.decisions.read_bytes()) if a.decisions else None,
            checkpoint_file_sha256=sha(a.checkpoint.read_bytes())
            if a.checkpoint
            else None,
        )
    except FileExistsError:
        print("OUTPUT_ALREADY_EXISTS", file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError, OSError, ImportError):
        print("CONFIRMED_REPLAY_FAILED_INPUT_OUTPUT_OR_DEPENDENCY", file=sys.stderr)
        return 2
    print(
        json.dumps(
            dict(
                status="RESEARCH_REPLAY_WRITTEN",
                version=result["version"],
                executable=False,
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
