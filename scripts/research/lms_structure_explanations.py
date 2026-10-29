"""Source-linked reading aids, not automatic pivot or trading rules."""

import csv
import hashlib
from html import escape
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

VERSION = 'lms-structure-explanation-v1'
ADMISSION = Path(__file__).resolve().parents[2] / 'docs/research/lms405/evidence/keybar-sample-admission-20261028.csv'
ADMISSION_SHA256 = '0be665b006c0e5bc2fedc0440ab323bc4c9f559d3e512d0e64e1c49e3a6ce2b0'

# Key by existing sample identity. This adds interpretation, not a second source registry.
NOTES = {
    'KB04': (
        'HOLD_AND_GAP_CONTINUATION',
        '作者将开盘pinbar低点未破、后续两低一高及GAP延续放在同一持有解释中。',
        '全天未破是事后观察；不能在开盘就知道，也不证明任意GAP都能延续。',
    ),
    'KB07': (
        'NESTED_STRUCTURE_AND_RECOVERY',
        'RB图注把嵌套两高一低与后续ebar、十字pinbar的恢复语境并列。',
        '嵌套层级、选点和完成时刻未定义，不能据此设为固定AND门槛。',
    ),
    'KB09': (
        'PROTECTION_EXCHANGE_AND_M',
        'JM图注区分pinbar保护、ibar换手和嵌套两高一低相关的后续抓M解释。',
        '1263.5是图中参考节点，不是已确认Fill；保护、恢复与抓M不能合成一个动作。',
    ),
    'KB10': (
        'PROTECTION_AND_OPTIONAL_M',
        '该图将ebar加速、GAP完成两高一低与锁定联系，同时讨论另做短向M的可能。',
        '这是当次保护语境，不是GAP统一锁定规则；抓M许可须单独判断。',
    ),
    'KB12': (
        'NESTED_BEARISH_STRUCTURE_AND_TRIAL',
        '作者在空头嵌套两高一低图中讨论试错和恢复，形态与风险语境并存。',
        '不能从结构名称反算波段选点、订单方向或试错数量。',
    ),
    'KB14': (
        'SPACE_SIGNAL_AND_REPEATED_RECOVERY',
        '图注区分较早信号而空间未满足、随后ibar锁定以及ibar配合两高一低的恢复叙述。',
        '时间信号与空间位置分开；相邻画法不证明算法条件同时满足。',
    ),
    'KB15': (
        'CROSS_PRODUCT_CONTEXT_AND_M',
        '图注先讲1048–1052附近pinbar保护，再等待两低一高及铁矿、螺纹强势后讨论抓M多向。',
        '跨品种背景是本图作者语境，不能擅自成为普遍共振公式；保留左/右侧转录冲突。',
    ),
    'KB16': (
        'RIGHT_SIDE_SKIPPED_GAP_ALTERNATIVE',
        '两个V+ ibar之后仍处于多头结构的M段；作者因两低一高右侧突破风险高而跳过该参与方式，另谈GAP追随。',
        '跳过是参与限制，不是形态不成立；白天收盘未突破与夜盘GAP是不同阶段。',
    ),
    'KB18': (
        'PINBAR_UNLOCK_AND_STRUCTURE',
        '图注把1012.5附近pinbar突破与解锁多向相连，再提两低一高和后续参与机会。',
        '没有作者时间轴；不得把图中相对位置强行贴到本地09:10或拼成唯一成交链。',
    ),
}


def build_explanations(path: Path = ADMISSION) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ADMISSION_SHA256:
        raise ValueError('STRUCTURE_SOURCE_HASH_MISMATCH')
    groups = {}
    count = 0
    used = set()
    for row in csv.DictReader(StringIO(raw.decode('utf-8'))):
        label = row['author_label']
        kind = ('TWO_HIGH_ONE_LOW' if '两高一低' in label else
                'TWO_LOW_ONE_HIGH' if '两低一高' in label else None)
        if kind is None:
            continue
        count += 1
        url = urlparse(row['url'])
        if (url.scheme != 'https' or url.netloc != 'weibo.com'
                or row['morphology_admitted'] != 'true'):
            raise ValueError('STRUCTURE_SOURCE_IDENTITY_INVALID')
        key = (row['event_group'], kind)
        sid = row['sample_id']
        canonical = 'KB16' if sid == 'KB17' else sid
        used.add(canonical)
        context, explanation, boundary = NOTES[canonical]
        if key not in groups:
            groups[key] = dict(
                explanation_id=f'{VERSION}:{row["event_group"]}:{kind}',
                event_group=row['event_group'], structure_type=kind,
                contract=row['contract'], context=context,
                explanation=explanation, boundary=boundary,
                conflicts=row['conflicts'], sources=[],
                evidence_kind='AUTHOR_ANNOTATION_WITH_RESEARCH_EXPLANATION',
                local_bar_end=None, selection_formula=None, completion_formula=None,
                trading_permission=None, executable=False,
            )
        groups[key]['sources'].append({k: row[k] for k in (
            'sample_id', 'source_refs', 'url', 'image_identity', 'author_label',
            'version_configuration', 'period', 'time_axis', 'price_legibility',
        )})
    if used != set(NOTES):
        raise ValueError('STRUCTURE_ANNOTATION_COVERAGE_MISMATCH')
    cases = list(groups.values())
    return dict(
        version=VERSION, admission_sha256=ADMISSION_SHA256,
        attachment_count=count, cases=cases,
        type_counts={kind: sum(c['structure_type'] == kind for c in cases)
                     for kind in ('TWO_HIGH_ONE_LOW', 'TWO_LOW_ONE_HIGH')},
        eligible_author_bar_samples=0, author_match_rate=None, executable=False,
    )


def render_explanations(result: dict) -> str:
    cards = []
    for case in result['cases']:
        name = '两高一低' if case['structure_type'] == 'TWO_HIGH_ONE_LOW' else '两低一高'
        refs = []
        for source in case['sources']:
            refs.append(
                f'<li><a href="{escape(source["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
                f'{escape(source["sample_id"])} · {escape(source["source_refs"])}</a>'
                f'<br><small>原图身份：{escape(source["image_identity"])}；'
                f'原图标注：{escape(source["author_label"])}；周期：{escape(source["period"])}；'
                f'版本：{escape(source["version_configuration"])}</small></li>'
            )
        conflict = f'<p><strong>保留冲突：</strong>{escape(case["conflicts"])}</p>' if case['conflicts'] else ''
        cards.append(
            f'<article class="structure-case"><h3>{escape(case["contract"])} · {name}</h3>'
            f'<p>{escape(case["explanation"])}</p><p><strong>使用边界：</strong>{escape(case["boundary"])}</p>'
            f'{conflict}<details><summary>查看来源与原图身份</summary><ul>{"".join(refs)}</ul></details></article>'
        )
    # A count-only schematic: no connected timeline, price axis, pivot selection or threshold.
    schematic = '''<svg viewBox="0 0 720 180" role="img" aria-label="两高一低与两低一高的数量示意，不表达点序或价差">
<g font-family="system-ui" font-size="16" text-anchor="middle">
<rect x="5" y="5" width="345" height="165" rx="10" fill="#edf3fa"/>
<rect x="370" y="5" width="345" height="165" rx="10" fill="#f3eef8"/>
<text x="177" y="32">两高一低：两个高点、一个低点</text>
<text x="95" y="75">高点 H1</text><text x="260" y="75">高点 H2</text>
<text x="177" y="130">低点 L</text>
<text x="542" y="32">两低一高：两个低点、一个高点</text>
<text x="542" y="75">高点 H</text><text x="460" y="130">低点 L1</text>
<text x="625" y="130">低点 L2</text></g></svg>'''
    return f'''<section id="structure-explanations"><h2>两高一低／两低一高：图解解释</h2>
<p>仅作阅读示意：H/L表示高低点称谓；数字用于区分点，不表达点序、价差或完成阈值。本页没有自动选点，不把这些示意叠加到本地K线上。</p>
{schematic}<p>既有{result['attachment_count']}条结构附件记录，重复事件合并后{len(result['cases'])}组（两高一低5组、两低一高4组）。这是作者图注解释卡，不是自动识别结果、交易数或准确率。</p>
<p>阅读时分别看：作者标了什么结构、用于哪种语境、还缺什么规则。GAP、pinbar、ibar和结构同图出现，不自动等于AND条件或买卖许可。</p>
<div class="structure-grid">{''.join(cards)}</div></section>'''
