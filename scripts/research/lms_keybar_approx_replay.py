"""Offline, hash-bound JM2509 5m keybar approximation; no market/network access."""

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from html import escape
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys

from guiyi_quant.lms405 import Bar
from guiyi_quant import lms_keybar_approx as core
from lms405_july22_geometry import INPUT_SHA256, audit

SOURCE = 'https://weibo.com/1885745060/PCeX7pZ6t'


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    return value


def build_report(path: Path) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUT_SHA256:
        raise ValueError('FROZEN_INPUT_HASH_MISMATCH')
    bars = []
    for row in csv.DictReader(StringIO(raw.decode('utf-8'))):
        end = datetime.fromisoformat(row['bar_end_shanghai'])
        if (row['frequency'] != '5m' or row['contract'] != 'JM2509'
                or end != datetime.fromisoformat(row['bar_end_utc'])):
            raise ValueError('FROZEN_BAR_IDENTITY_MISMATCH')
        bars.append(Bar(
            row['contract'], end,
            *(Decimal(row[k]) for k in ('open', 'high', 'low', 'close')),
            start=end - timedelta(minutes=5),
        ))
    frames, observations = core.replay(bars)
    records = []
    for frame in frames:
        record = _json_value(asdict(frame))
        bar = record.pop('bar')
        previous = record.pop('previous')
        record.update({k: bar[k] for k in ('contract', 'open', 'high', 'low', 'close')})
        record.update(
            bar_end=bar['end'], confirmed_at=bar['end'],
            previous_bar_end=previous['end'] if previous else None,
            previous_high=previous['high'] if previous else None,
            previous_low=previous['low'] if previous else None,
        )
        records.append(record)
    return dict(
        rule_version=core.VERSION, contract='JM2509', frequency='5m',
        input_sha256=INPUT_SHA256, bar_count=len(bars),
        code_sha256={
            'core': hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),
            'replay': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        rule_basis={
            'author_local_constraint': 'I10: long wick at least 3x body; local, not a full formula',
            'assumptions': [
                'Adjacent strict high/low containment; equals excluded; no mother-Bar recursion',
                'Nonzero body; other wick <= body; wick direction independent of candle colour',
                'Morphology confirmed at completed 5m close; no active-signal lifetime',
                'Next supplied-row close strictly outside signal high/low; observation, not permission',
            ],
        },
        local_pattern_counts=dict(
            ibar=sum(f.ibar is True for f in frames),
            pinbar_long=sum(f.pinbar == 'LONG' for f in frames),
            pinbar_short=sum(f.pinbar == 'SHORT' for f in frames),
        ),
        frames=records, next_close_observations=[_json_value(asdict(o)) for o in observations],
        terminal_pattern_pending=frames[-1].has_pattern if frames else False,
        frozen_geometry=audit(path),
        author_comparison=[
            dict(category='EXPLAINABLE', source_id='H06;H10', url=SOURCE,
                 status='PROVISIONAL_VISUAL_SEQUENCE_ONLY',
                 detail='本地09:10严格内包、09:15收盘下破能解释一种几何机制；仅暂定视觉对应，不证明作者Bar或保护规则。'),
            dict(category='DIFFERENCE', source_id='H06', url=SOURCE,
                 detail='作者图顶1034.5，本地暂定峰1035，相差+0.5；保留未解释差异。'),
            dict(category='UNALIGNABLE', source_id='I10;J02;N03;N04',
                 url='https://weibo.com/ttarticle/p/show?id=2309405226775914610782',
                 detail='其他图解缺唯一作者Bar、完整OHLC或周期；无法对齐，不能统计逐根命中。结构仅保留作者图注，不自动选点。'),
        ],
        eligible_author_samples=0, author_match_rate=None,
        original_formula_identified=False, version_405_confirmed=False,
        executable=False, fill=None, performance=None,
    )


def render_chart(report: dict) -> str:
    # Rendering only: all price geometry and classifications above use Decimal.
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from matplotlib.patches import Rectangle

    rows = report['frames']
    zoom = [r for r in rows if '2025-07-22T09:05' <= r['bar_end'] <= '2025-07-22T09:45:59']
    with matplotlib.rc_context({'svg.hashsalt': core.VERSION, 'font.size': 10}):
        fig, axes = plt.subplots(2, 1, figsize=(15, 9), layout='constrained')
        for ax, subset, title in zip(axes, [rows, zoom], [
            'JM2509 frozen 5m export | adjacent rows; session gaps compressed',
            '09:05-09:45 local sequence | provisional, NOT author-Bar alignment',
        ]):
            low = min(float(r['low']) for r in subset)
            high = max(float(r['high']) for r in subset)
            pad = max((high - low) * .08, 1)
            for i, r in enumerate(subset):
                o, h, low_price, c = (float(r[k]) for k in ('open', 'high', 'low', 'close'))
                colour = '#cd6237' if c >= o else '#267a83'
                ax.vlines(i, low_price, h, color=colour, linewidth=1)
                if c == o:
                    ax.hlines(c, i - .3, i + .3, color=colour)
                else:
                    ax.add_patch(Rectangle((i - .3, min(o, c)), .6, abs(c - o),
                                           facecolor=colour, edgecolor=colour))
                if r['ibar']:
                    ax.scatter(i, h + pad * .25, marker='o', facecolors='none',
                               edgecolors='#245bc0', s=35, zorder=4)
                if r['pinbar']:
                    is_long = r['pinbar'] == 'LONG'
                    ax.scatter(i, low_price - pad * .3 if is_long else h + pad * .6,
                               marker='^' if is_long else 'v', color='#7a3e9d', s=45, zorder=4)
            stride = max(1, len(subset) // 9)
            ticks = list(range(0, len(subset), stride))
            ax.set_xticks(ticks, [subset[i]['bar_end'][5:16].replace('T', ' ') for i in ticks])
            ax.set_ylim(low - pad, high + pad)
            ax.set_xlim(-1, len(subset))
            ax.set_ylabel('Price')
            ax.set_title(title, loc='left', weight='bold')
            ax.grid(axis='y', alpha=.2)
        fig.suptitle(f'{core.VERSION} | circle: ibar | triangle: pinbar direction | NO orders / performance', fontsize=12)
        buf = BytesIO()
        fig.savefig(buf, format='svg', metadata={'Date': None})
        plt.close(fig)
    svg = buf.getvalue().decode('utf-8')
    return '\n'.join(line.rstrip() for line in svg[svg.index('<svg'):].splitlines()) + '\n'


def render_html(report: dict, svg: str) -> str:
    comparisons = ''.join(
        f'<tr><td>{escape(x["category"])}</td><td>{escape(x["source_id"])}</td>'
        f'<td>{escape(x["detail"])}</td></tr>' for x in report['author_comparison']
    )
    rows = ''.join(
        '<tr>' + ''.join(f'<td>{escape(str(r[k]))}</td>' for k in (
            'bar_end', 'ibar', 'pinbar', 'body', 'upper_wick', 'lower_wick', 'confirmed_at')) + '</tr>'
        for r in report['frames']
    )
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{core.VERSION} JM2509图解回放</title>
<style>body{{font:15px system-ui;margin:28px auto;max-width:1400px;padding:0 20px;color:#203040}}svg{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #d5dde5;padding:7px;text-align:left}}.scroll{{overflow:auto}}.note{{background:#edf3fa;padding:16px}}code{{overflow-wrap:anywhere}}</style>
<h1>{core.VERSION}：JM2509 5分钟</h1>
<p class="note">这是明确补全假设的形态研究，不是作者原版、不是交易许可。作者逐根合格样本0，准确率null；成交及收益null，executable=false。没有作者时间轴，09:10只作暂定视觉对应。</p>
<p>输入：138根冻结Bar；哈希 <code>{report['input_sha256']}</code>。横轴按导出行排列，休市间隔压缩；时间为北京时间。没有实时数据读取。</p>
<h2>规则与判定</h2><p>ibar：相邻K高低点严格内包，相等不成立。pinbar：实体非零、长影≥3倍实体、另一影≤实体，不要求K色。仅3倍约束有I10局部作者来源，其余是本候选补全假设；不等于完整BBB规则。两高一低等结构不自动识别。</p>
<p>本根收盘确认形态。下一根收盘突破是独立事后观察，未写回本根；下一根指完整冻结序列中相邻行，不假定盘中触发先后。最后一根形态尚无下一根时保留待观察。</p>
<p>形态计数（不是交易数）：{escape(json.dumps(report['local_pattern_counts'], ensure_ascii=False))}</p>
{svg}<h2>作者图解差异</h2><table><tr><th>分类</th><th>来源</th><th>结论</th></tr>{comparisons}</table>
<h2>逐Bar形态</h2><p><a href="frames.csv">逐Bar CSV</a> · <a href="observations.csv">下一根独立观察CSV</a> · <a href="report.json">完整JSON及规则/代码指纹</a> · <a href="chart.svg">导出SVG</a></p>
<details><summary>展开全部138根的数值与确认时间</summary><div class="scroll"><table><tr><th>Bar end</th><th>ibar</th><th>pinbar</th><th>实体</th><th>上影</th><th>下影</th><th>confirmed_at</th></tr>{rows}</table></div></details>
</html>'''


def _csv(rows: list[dict], fields: list[str]) -> str:
    buf = StringIO(newline='')
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def write_report(source: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError('OUTPUT_ALREADY_EXISTS')
    result = build_report(source)
    svg = render_chart(result)
    payloads = {
        'index.html': render_html(result, svg), 'chart.svg': svg,
        'frames.csv': _csv(result['frames'], list(result['frames'][0])),
        'observations.csv': _csv(result['next_close_observations'],
                                 list(core.NextCloseObservation.__dataclass_fields__)),
        'report.json': json.dumps(result, ensure_ascii=False, indent=2) + '\n',
    }
    # Validate/render everything before exclusive mkdir. Existing dirs are never reused.
    # A disk failure can leave a partial new dir; report.json is written last.
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        with (output / name).open('x', encoding='utf-8') as handle:
            handle.write(data)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = write_report(args.input, args.output)
    except FileExistsError:
        print('OUTPUT_ALREADY_EXISTS', file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, ImportError):
        print('REPLAY_FAILED_INPUT_OUTPUT_OR_RENDER_DEPENDENCY', file=sys.stderr)
        return 2
    print(json.dumps({'status': 'RESEARCH_REPORT_WRITTEN', 'rule_version': core.VERSION,
                      'bars': result['bar_count'], 'executable': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
