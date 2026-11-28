<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listObservations, readObservation, readObservationImage, type ObservationInput, type ObservationRow } from '@/api/journalObservations'
import type { Period } from '@/api/tradeJournal'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import JournalObservationLinks from './JournalObservationLinks.vue'
import ChartObservationReplay from '@/components/workstation/ChartObservationReplay.vue'

const props = defineProps<{ anchor: string; period: Period }>()
const route = useRoute()
const router = useRouter()
const rows = shallowRef<ObservationRow[]>([])
const detail = shallowRef<ObservationInput & { id: string; recorded_at: string }>()
const sourceUrl = ref('')
const listError = ref('')
const detailError = ref('')
const imageError = ref('')
const loading = ref(false)
const offset = ref(0)
const next = ref<number | null>(null)
const retry = ref(0)
const detailRetry = ref(0)

watch(() => [props.anchor, props.period], () => { offset.value = 0 }, { flush: 'sync' })
watch(() => [props.anchor, props.period, offset.value, retry.value], async (_, __, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  listError.value = ''
  rows.value = []
  next.value = null
  loading.value = false
  if (!props.anchor) return
  loading.value = true
  try {
    const result = await listObservations(props.anchor, props.period, offset.value, controller.signal)
    if (controller.signal.aborted) return
    rows.value = result.items
    next.value = result.next_offset
  } catch {
    if (!controller.signal.aborted) listError.value = '观察笔记暂时无法读取。'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

watch(() => [route.query.observation, detailRetry.value], async (_, __, cleanup) => {
  const controller = new AbortController()
  let objectUrl = ''
  cleanup(() => {
    controller.abort()
    if (objectUrl) URL.revokeObjectURL(objectUrl)
  })
  detail.value = undefined
  sourceUrl.value = detailError.value = imageError.value = ''
  const id = route.query.observation
  if (!id) return
  if (typeof id !== 'string' || !/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(id)) {
    detailError.value = '观察笔记标识无效。'
    return
  }
  try {
    const { observation } = await readObservation(id, controller.signal)
    if (controller.signal.aborted) return
    detail.value = observation
  } catch {
    if (!controller.signal.aborted) detailError.value = '无法打开这条观察笔记。'
    return
  }
  try {
    const png = await readObservationImage(id, controller.signal)
    if (controller.signal.aborted) return
    if (png.type !== 'image/png' || !png.size) throw new Error()
    objectUrl = URL.createObjectURL(png)
    sourceUrl.value = objectUrl
  } catch {
    if (!controller.signal.aborted) imageError.value = '原图读取失败。'
  }
}, { immediate: true })

function close() {
  const { observation: _observation, ...query } = route.query
  void router.push({ query })
}
</script>

<template>
  <section class="observations" aria-labelledby="observation-heading">
    <h2 id="observation-heading">行情观察笔记</h2>
    <template v-if="route.query.observation">
      <button type="button" @click="close">返回笔记列表</button>
      <p v-if="detailError" role="alert">{{ detailError }} <button type="button" @click="detailRetry++">重试</button></p>
      <article v-else-if="detail">
        <header><h3>{{ detail.snapshot.physical_contract }}</h3><time>{{ formatBeijingInstant(detail.snapshot.captured_at) }}</time></header>
        <p class="note">{{ detail.note }}</p>
        <div class="meta">交易日 {{ detail.trading_day }} · {{ detail.snapshot.panes.length }} 个视窗</div>
        <ChartObservationReplay v-if="sourceUrl" :snapshot="detail.snapshot" :image-url="sourceUrl" />
        <p v-else-if="imageError" role="alert">{{ imageError }} <button type="button" @click="detailRetry++">重试</button></p>
        <p v-else role="status">正在读取原图…</p>
        <JournalObservationLinks :observation-id="detail.id" />
        <template v-for="pane in detail.snapshot.panes" :key="pane.id">
          <div v-if="pane.id === detail.snapshot.active_pane" class="current">
            <RouterLink :to="{ name: 'market-chart', query: { view: 'free', symbol: detail.snapshot.product.toLowerCase(), series_kind: 'contract', contract: pane.physical_contract, frequency: pane.frequency } }">
              查看 {{ pane.physical_contract }} 当前行情
            </RouterLink>
          </div>
        </template>
      </article>
      <p v-else role="status">正在读取观察笔记…</p>
    </template>
    <template v-else>
      <p v-if="listError" role="alert">{{ listError }} <button type="button" @click="retry++">重试</button></p>
      <p v-else-if="loading" role="status">正在读取观察笔记…</p>
      <p v-else-if="!rows.length" class="meta">本{{ period === 'day' ? '日' : '周' }}没有行情观察笔记。</p>
      <ul v-else>
        <li v-for="item in rows" :key="item.id">
          <RouterLink :to="{ query: { ...route.query, observation: item.id } }">{{ item.physical_contract }} · {{ item.frequency }} · {{ item.note }}</RouterLink>
          <time>{{ formatBeijingInstant(item.captured_at) }}</time>
        </li>
      </ul>
      <nav v-if="next !== null || offset > 0" aria-label="观察笔记翻页">
        <button v-if="offset > 0" type="button" @click="offset = Math.max(0, offset - 30)">上一页</button>
        <button v-if="next !== null" type="button" @click="offset = next">下一页</button>
      </nav>
    </template>
  </section>
</template>

<style scoped>
.observations { min-width: 0; background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: 9px; padding: 19px; margin-bottom: 16px; }
h2 { margin: 0 0 12px; font-size: 17px; }
h3 { margin: 0; font-size: 16px; }
header, li, nav { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
article { margin-top: 1rem; }
.note, li a { overflow-wrap: anywhere; white-space: pre-wrap; }
li { padding: 8px 0; border-bottom: 1px solid var(--gy-border); }
ul { margin: 0; padding: 0; }
.meta, time { color: var(--gy-text-secondary); font-size: 13px; }
time { white-space: nowrap; }
.meta { margin-bottom: 1rem; }
a { color: var(--gy-link); }
.current, nav { margin-top: .75rem; }
button { color: var(--gy-text-primary); cursor: pointer; background: var(--gy-bg-panel); border: 1px solid var(--gy-border-strong); border-radius: 5px; padding: .3rem .55rem; }
</style>
