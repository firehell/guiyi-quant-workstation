import json
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
from bisect import bisect_right
from decimal import Decimal
p=Path(__file__).resolve().parent
a=json.loads((p/'analysis.json').read_text());m=json.loads((p/'market_history.json').read_text());s=json.loads((p/'source.json').read_text())
groups=defaultdict(list)
for r in a['records']:groups[(r['contract'],r['rule_code'],r['frequency'],r['direction'])].append(r)
for key,rs in groups.items():
 times=[datetime.fromisoformat(t) for t,d in m[key[0]]['expected']]
 last=-1;cluster=None
 for r in sorted(rs,key=lambda x:x['notification_attempted_at'] or x['detected_at']):
  if not r['notification_attempted_at']:
   r['cluster_id']='不可判定';r['cluster_first']=None;continue
  idx=bisect_right(times,datetime.fromisoformat(r['notification_attempted_at']))
  if idx+60>=len(times):r['cluster_id']='不可判定';r['cluster_first']=None;continue
  first=idx>last
  if first:cluster='C'+str(r['id'])
  last=max(last,idx+60);r['cluster_id']=cluster;r['cluster_first']=int(first)
reps=[r for r in a['records'] if r['cluster_first']==1]
vals=[Decimal(r['return_60']) for r in reps if r['return_60'] is not None]
a['clusters']={'count':len(reps),'repeated':sum(r['cluster_first']==0 for r in a['records']),'unknown':sum(r['cluster_first'] is None for r in a['records']),'n60':len(vals),'win60':sum(v>0 for v in vals),'missing60':sum(r['return_60'] is None for r in reps),'hit60':sum(v>0 for v in vals)/len(vals) if vals else None,'method':'同物理合约×策略×周期×方向的60交易分钟窗口相互重叠归为同组，取首条代表；仅用于相关性敏感性检查，不等于独立交易。'}
a['unavailable_since_previous']=dict(Counter(str(x['horizon']) for x in a['recheck_unavailable']))
a['new_event_count']=sum(r['cohort'] in ('当日新增','其他新增') for r in a['records'])
a['notes']=[
 f"统计截止北京时间 {datetime.fromisoformat(a['cutoff']).strftime('%Y-%m-%d')} 15:13。今天0条新增，不代表运行正常且无信号。",
 '五个交易所Calendar均确认今天开盘，但60个运行品种的有效Session和当日rank1映射均缺失。',
 '预警处理与最后发送尝试仍停在9月10日10:15。苏冰保留evaluation_failed状态，今天未出现新的发送证据。',
 '本次全周窗口查询在54个合约上失败。另行只读核验截至9月10日的历史窗口，保留可独立证明完整的旧样本。',
 '历史读取：9月9日50个合约、9月10日54个合约返回DATASET_OR_PARTITION_MISSING。没有补数、填零或缩短窗口。',
 f"本周190条：15m可评估{a['total']['n15']}条，缺{a['total']['missing15']}条；30m可评估{a['total']['n30']}条，缺{a['total']['missing30']}条；60m可评估{a['total']['n60']}条，缺{a['total']['missing60']}条。",
 '当前可重算子集不能代表完整周表现，也不能与昨天不同覆盖范围的比例直接比较。',
 f"昨天79条未决记录今天均未补齐；另有{a['unavailable_since_previous'].get('60',0)}条昨天可评估的60m结果今天无法重算。旧快照保留。",
 '旧190条Event关键身份全部一致。本次新成熟窗口0个，可重算旧窗口的数值修订0个。读取失败单列，不能当作价格修订。',
 '本次没有新预警，未重新执行策略公式复算；明细W列明确标识旧结论，不据此声明当前公式已验证。',
 '发送证据沿用已保存逐条证据和当前共享状态。provider接受不证明微信送达；正文按Event和模板复原。',
 '基准为发送尝试之后首个严格晚于该时点的completed 1m收盘价。方向变化=方向系数×（终点价÷基准价−1）。',
 '使用同一物理合约，按权威交易分钟计时。全部应有分钟存在才可评估；缺失与未满窗口分开。',
 a['clusters']['method'],
 f"窗口分组：{a['clusters']['count']}组，重复成员{a['clusters']['repeated']}条，无法分组{a['clusters']['unknown']}条。首条代表中60m有利{a['clusters']['win60']}/{a['clusters']['n60']}，另有{a['clusters']['missing60']}组缺数据。",
 '方向有利比例不等于含费用、滑点的交易胜率或账户收益。当前覆盖不足，不调整或淘汰策略。',
 '唯一下一步：针对60品种Session与当日rank1缺失，形成现有维护流程的受控修复范围。当前复盘不执行生产修复。'
]
for stat in [a['total'],a['today_total']]+a['strategy_summary']+a['product_summary']+a['day_summary']+a['direction_summary']:
 for h in ['15','30','60']:
  assert stat['win'+h]+stat['loss'+h]+stat['flat'+h]==stat['n'+h]
  assert stat['n'+h]+stat['pending'+h]+stat['missing'+h]==stat['count']
assert len(a['records'])==len({r['id'] for r in a['records']})==s['control_count']
assert a['clusters']['count']+a['clusters']['repeated']+a['clusters']['unknown']==len(a['records'])
(p/'analysis.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
print('VERIFIED',len(a['records']),'unique events',a['unavailable_since_previous'],a['clusters'])
