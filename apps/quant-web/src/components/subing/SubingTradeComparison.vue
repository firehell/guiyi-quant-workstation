<script setup lang="ts">
import { ref } from 'vue'
import { label } from './labels'

type Trade = {
  daily_at?: string; hourly_at?: string; daily_direction?: string; hourly_direction?: string
  rule: string; match: string; contract: string; side: string; decision_at: string
  fill_at: string; price: string; handoff_at: string | null; exit_at: string | null
  exit_reasons: string[] | null; net: string | null
}
const trades = ref<Trade[]>([])
const summary = ref('')
const diagnostics = ref('')
const error = ref('')
let latest = 0
async function read(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  const request = ++latest
  trades.value = []
  summary.value = diagnostics.value = error.value = ''
  if (!file) return
  try {
    if (file.size > 16 * 1024 * 1024) throw Error()
    const [header, ...rows] = (await file.text()).trim().split(/\r?\n/).map(line => JSON.parse(line))
    if (request !== latest) return
    if (!['SEEN_JM_DEVELOPMENT_FIXED_ENTRY_LEGACY_WITNESS', 'THREE_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH',
      'SEEN_14_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH'].includes(header.kind) ||
      !Number.isInteger(header.matched) || !Number.isInteger(header.differences) ||
      rows.some(row => !row || !['A', 'B'].includes(row.rule) || typeof row.contract !== 'string' ||
        typeof row.fill_at !== 'string' || (row.exit_reasons !== null && !Array.isArray(row.exit_reasons)))) throw Error()
    if (header.trade_rows !== rows.length || header.matched * 2 !== rows.filter(row => row.match === '同笔对照').length) throw Error()
    diagnostics.value = JSON.stringify(header.accounts ?? header.opportunities, null, 2)
    trades.value = rows
    summary.value = [header.kind, header.window?.join(' 至 '), header.input_id ?? header.hourly_sha256,
      header.variant, '同笔 ' + header.matched + ' 组', '退出分歧 ' + header.differences + ' 组'].filter(Boolean).join(' · ')
  } catch {
    if (request === latest) error.value = '读取失败，请选择逐笔说明命令生成的 JSONL 文件（最大 16 MB）。'
  }
}
function stamp(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) : '—'
}
</script>

<template>
  <details class="panel">
    <summary>比较历史研究规则</summary>
    <details><summary>运行本地焦煤回放</summary>
      <p>在仓库根目录执行。首次准备读取已登记行情，之后可复用同一小时文件。</p>
      <pre>archive='/Volumes/扩展盘/subing-knowledge-foundation-data/third-camp-v2/refined/research/strategy-stage-c-20261108'
work=$(mktemp -d)
scripts/research/subing-replay.sh legacy-hours --source "$archive" --output "$work/hours.json"
scripts/research/subing-replay.sh legacy-pairs --source "$archive" --hours "$work/hours.json" --contract JM2505 --output "$work/pairs.json"
python3 scripts/research/subing_trade_report.py "$work/pairs.json" --archive "$archive" &gt; "$work/trades.jsonl"
echo "$work/trades.jsonl"</pre></details>
    <p>已有回放结果可直接转换成逐笔说明。文件只在当前浏览器读取。</p>
    <code>python3 scripts/research/subing_trade_report.py 结果.json &gt; 逐笔.jsonl</code>
    <p><label>选择逐笔说明 <input type="file" accept=".jsonl" @change="read"></label></p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="summary" style="overflow-wrap:anywhere">{{ summary }}</p>
    <details v-if="diagnostics"><summary>入场机会、拒绝原因与组合统计</summary><pre>{{ diagnostics }}</pre></details>
    <div v-if="trades.length" style="overflow-x:auto"><table>
      <thead><tr><th>合约 / 规则</th><th>已知日线 / 小时方向</th><th>信号 / 模拟成交</th><th>入场价</th><th>小时接管</th><th>退出 / 原因</th><th>净损益（元）</th></tr></thead>
      <tbody><tr v-for="row in trades" :key="[row.rule,row.contract,row.fill_at].join('/')">
        <td>{{ row.contract }} · {{ row.rule }} · {{ label(row.side) }} · {{ row.match }}</td>
        <td>{{ label(row.daily_direction) }} {{ stamp(row.daily_at ?? null) }} /
          {{ label(row.hourly_direction) }} {{ stamp(row.hourly_at ?? null) }}</td>
        <td>{{ stamp(row.decision_at) }} / {{ stamp(row.fill_at) }}</td>
        <td>{{ row.price }}</td><td>{{ stamp(row.handoff_at) }}</td>
        <td>{{ stamp(row.exit_at) }} · {{ row.exit_reasons?.map(label).join('、') ?? '持仓中' }}</td>
        <td>{{ row.net ?? '—' }}</td>
      </tr></tbody>
    </table></div>
  </details>
</template>
