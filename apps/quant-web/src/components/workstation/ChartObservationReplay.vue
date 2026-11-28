<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { getMarketBarsPage } from '@/api/market'
import type { ObservationSnapshot } from '@/api/journalObservations'
import { historicalDisplayBar } from '@/utils/marketBarDisplay'
import { validObservationBars, verifiedObservationPoints } from '@/utils/observationReplay'
import type { NewowObservationSource } from '@/utils/observationCapture'
import { isRecordingTradingDay } from '@/utils/newowRecording'
import { NEWOW_PRODUCT_STRATEGIES } from '@/types/newowProduct'
import type { BarData } from '@/types/market'

const props = defineProps<{ snapshot: ObservationSnapshot; imageUrl: string }>()
const selected = ref(''),
  status = ref(''),
  zoom = ref(1),
  cursor = ref(0)
const points = shallowRef<{ x: number; bar: BarData }[]>([])
const pane = computed(() => props.snapshot.panes.find((p) => p.id === selected.value))
const newowSource = computed(() => {
  const value = pane.value?.source.newow as Partial<NewowObservationSource> | undefined
  return value && (value.kind === 'canonical_recompute' || value.kind === 'formal_archive')
    && isRecordingTradingDay(value.trading_day) && typeof value.revision === 'string' ? value : null
})
const sameInput = computed(() => {
  const p = pane.value, evidence = newowSource.value
  const strategy = NEWOW_PRODUCT_STRATEGIES.find(s => s === p?.source.strategy)
  if (!p || !strategy || evidence?.kind !== 'canonical_recompute' || !evidence.revision || !/^[0-9a-f]{64}$/.test(evidence.revision)) return null
  return { path: '/market/chart', query: { view: 'newow', symbol: props.snapshot.product.toLowerCase(),
    series_kind: p.series_kind, frequency: p.frequency, strategy, newow_source: 'canonical-recompute',
    trading_day: evidence.trading_day, source_revision: evidence.revision } }
})
const rect = computed(() => pane.value?.ranges.image_rect as number[] | undefined)
const point = computed(() => points.value[cursor.value])
let request: AbortController | null = null
function reset() {
  request?.abort()
  points.value = []
  cursor.value = 0
  status.value = ''
  zoom.value = 1
}
watch(
  () => props.snapshot,
  () => {
    reset()
    selected.value = props.snapshot.active_pane
  },
  { immediate: true },
)
watch(selected, reset)
onBeforeUnmount(reset)
async function verify() {
  reset()
  const p = pane.value
  if (!p || !Array.isArray(p.source.bars) || !p.source.bars.length || !p.source.historical) {
    status.value = '当前观察只保留原图。可见窗口含预览数据，或缺少可逐根核对的历史身份。'
    return
  }
  const keys = p.source.bars
  if (!validObservationBars(keys)) {
    status.value = '历史身份记录不完整，保留原图。'
    return
  }
  const current = new AbortController()
  request = current
  status.value = '正在逐根校验原始行情…'
  try {
    const query = {
      symbol: props.snapshot.product,
      series_kind: p.series_kind,
      contract: p.series_kind === 'contract' ? p.physical_contract : undefined,
      frequency: p.frequency,
      limit: keys.length,
    }
    let page = await getMarketBarsPage(query, current.signal)
    if (current.signal.aborted) return
    const end = Date.parse(p.window.to)
    if (Date.parse(page.bars.at(-1)?.bar_end ?? '') > end) {
      page = await getMarketBarsPage({ ...query, before: new Date(end + 1).toISOString() }, current.signal)
    }
    if (current.signal.aborted) return
    const bars = page.bars.map((b) => historicalDisplayBar(page, b))
    const verified = verifiedObservationPoints(bars, keys)
    if (!verified) throw new Error()
    points.value = verified
    status.value = '可见行情已逐根核验。移动光标查看当时的 Bar，指标和画线保留截图时的状态。'
  } catch {
    if (!current.signal.aborted) status.value = '无法验证相同历史版本，保留当时原图。'
  }
}
function inspect(event: PointerEvent) {
  if (!points.value.length || !rect.value?.length) return
  const box = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const x = ((event.clientX - box.left) / box.width - rect.value[0]!) / rect.value[2]!
  cursor.value = points.value.reduce(
    (best, p, i) => (Math.abs(p.x - x) < Math.abs(points.value[best]!.x - x) ? i : best),
    0,
  )
}
</script>
<template>
  <section aria-label="观察原图与复核">
    <div class="actions">
      <strong>观察原图</strong>
      <span v-if="newowSource">{{ newowSource.kind === 'canonical_recompute' ? 'Canonical 历史复算' : '盘后归档' }} ·
        {{ newowSource.trading_day }} · {{ newowSource.revision?.slice(0, 12) }}</span>
      <RouterLink v-if="sameInput" :to="sameInput">打开同日同版本图表</RouterLink>
      <select v-if="snapshot.panes.length > 1" v-model="selected" aria-label="回看周期">
        <option v-for="p in snapshot.panes" :key="p.id" :value="p.id">{{ p.frequency }}</option>
      </select>
      <button type="button" @click="verify">核验历史并回看</button>
      <label>原图缩放 <input v-model.number="zoom" type="range" min="1" max="3" step=".25" /></label>
    </div>
    <div class="viewport">
      <div class="sheet" :style="{ width: zoom * 100 + '%' }" @pointermove="inspect">
        <img :src="imageUrl" alt="保存观察时的行情图、图层和人工画线" />
        <i
          v-if="point && rect"
          :style="{
            left: (rect[0]! + point.x * rect[2]!) * 100 + '%',
            top: rect[1]! * 100 + '%',
            height: rect[3]! * 100 + '%',
          }"
        ></i>
      </div>
    </div>
    <p role="status">{{ status }}</p>
    <label v-if="point"
      >定位 Bar
      <input aria-label="定位历史 Bar" v-model.number="cursor" type="range" min="0" :max="points.length - 1"
    /></label>
    <p v-if="point">
      {{ point.bar.time }} · {{ point.bar.physicalContract }}　开 {{ point.bar.open }}　高
      {{ point.bar.high }}　低 {{ point.bar.low }}　收 {{ point.bar.close }}　成交量 {{ point.bar.volume }}
    </p>
  </section>
</template>
<style scoped>
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 8px 0;
}
.viewport {
  overflow: auto;
  max-height: 75vh;
}
.sheet {
  position: relative;
  line-height: 0;
}
.sheet img {
  width: 100%;
  display: block;
}
.sheet i {
  position: absolute;
  pointer-events: none;
  border-left: 1px dashed #e7bb77;
}
</style>
