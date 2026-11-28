<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { CHART_PROFILES, DISPLAY_CATALOG, type ChartProfileId } from '@guiyi/quant-chart'
import PricePeriodPane from './PricePeriodPane.vue'
import { captureObservationPane, fixedParameters, freezeObservation } from '@/utils/observationCapture'
import { chartLayerStatusLabels } from '@/utils/chartLayerStatus'
import { saveObservation } from '@/api/journalObservations'
import { type DetailChartSession, type ManualChartLevel } from '@/utils/detailChartSession'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import { MARKET_FREQUENCIES, type BarData, type MarketFrequency } from '@/types/market'
import type { ProductOption } from '@/utils/productSearch'

const props = defineProps<{
  identity: MarketDetailIdentity
  session: DetailChartSession
  bars: BarData[]
  products: ProductOption[]
  preferences: Record<string, unknown>
  status: string
}>()
const emit = defineEmits<{
  select: [option: ProductOption]
  period: [frequency: MarketFrequency]
  single: [visible: boolean]
}>()
const router = useRouter()
let viewGeneration = 0
let mounted = true
watch(
  router.currentRoute,
  () => {
    viewGeneration++
    dialog.value?.close()
    frozen.value = null
  },
  { flush: 'sync' },
)
onBeforeUnmount(() => {
  mounted = false
})
function read(key: string): unknown {
  try {
    return JSON.parse(localStorage.getItem('guiyi.workstation.desk.v1.' + key) || 'null')
  } catch {
    return null
  }
}
function persist(key: string, value: unknown) {
  try {
    localStorage.setItem('guiyi.workstation.desk.v1.' + key, JSON.stringify(value))
  } catch {
    /* Layout preferences are optional. */
  }
}
const initialDock = read('dock')
const dock = ref<'watch' | 'layers' | ''>(
  initialDock === 'layers' || initialDock === '' ? initialDock : 'watch',
)
const storedWidth = read('dockWidth')
const dockWidth = ref(
  typeof storedWidth === 'number' && Number.isFinite(storedWidth)
    ? Math.min(400, Math.max(160, storedWidth))
    : 214,
)
function setDockWidth(width: number) {
  dockWidth.value = Math.round(Math.max(160, Math.min(400, width)))
}
function resizeDock(event: PointerEvent) {
  const handle = event.currentTarget as HTMLElement
  const start = event.clientX
  const before = dockWidth.value
  handle.setPointerCapture(event.pointerId)
  const move = (e: PointerEvent) => setDockWidth(before + start - e.clientX)
  const stop = () => {
    handle.removeEventListener('pointermove', move)
    persist('dockWidth', dockWidth.value)
  }
  handle.addEventListener('pointermove', move)
  handle.addEventListener('lostpointercapture', stop, { once: true })
}
function resizeWithKey(event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  setDockWidth(dockWidth.value + (event.key === 'ArrowLeft' ? 16 : -16))
  persist('dockWidth', dockWidth.value)
}
const names = read('favorites')
const favorites = ref<string[]>(
  Array.isArray(names) ? names.filter((n): n is string => typeof n === 'string') : [],
)
const onlyFavorites = ref(favorites.value.length > 0),
  search = ref(''),
  layerSearch = ref('')
const products = computed(() =>
  props.products.filter(
    (p) =>
      (!onlyFavorites.value || favorites.value.includes(p.symbol)) &&
      (p.name + p.symbol + (p.contract ?? '')).toLowerCase().includes(search.value.trim().toLowerCase()),
  ),
)
const quad = ref(read('quad') === true),
  periods = ['1w', '1d', '15m', '5m'] as const
const lastQuadPeriod = read('activeQuadPeriod')
const activePeriod = ref<MarketFrequency>(
  periods.find((p) => p === lastQuadPeriod) ?? periods.find((p) => p === props.identity.frequency) ?? '15m',
)
watch(activePeriod, (value) => persist('activeQuadPeriod', value))
watch(quad, (value) => emit('single', !value), { immediate: true, flush: 'sync' })
const charts = ref<InstanceType<typeof PricePeriodPane>[]>([])
const message = ref(''),
  note = ref(''),
  drawing = ref(false),
  busy = ref(false)
const dialog = ref<HTMLDialogElement>()
const frozen = shallowRef<Awaited<ReturnType<typeof freezeObservation>> | null>(null)
const attempted = ref(false)
let captureId = ''
const key = computed(() =>
  [
    props.identity.symbol,
    props.identity.seriesKind,
    props.identity.contract || 'rank1',
    props.identity.frequency,
  ].join('/'),
)
const levels = shallowRef<ManualChartLevel[]>([])
watch(
  key,
  () => {
    drawing.value = false
    props.session.startPricePick()
    message.value = ''
    const saved = read('lines.' + key.value)
    levels.value = Array.isArray(saved)
      ? saved
          .filter(
            (v) => v && typeof v.contract === 'string' && typeof v.at === 'string' && Number.isFinite(v.price),
          )
          .slice(-32)
      : []
  },
  { immediate: true },
)
watch(
  levels,
  (l) => {
    props.session.setAnnotations(l)
    persist('lines.' + key.value, l)
  },
  { immediate: true, flush: 'post' },
)
onBeforeUnmount(() => {
  props.session.startPricePick()
  props.session.setAnnotations([])
})
const profile = computed<ChartProfileId>(() =>
  props.identity.view === 'newow'
    ? props.identity.newowMode === 'dual'
      ? 'newow_dual'
      : props.identity.strategy === 'main_rise'
        ? 'newow_main_rise'
        : props.identity.strategy === 'oscillation'
          ? 'newow_oscillation'
          : 'newow_trend'
    : props.identity.view === 'subing'
      ? 'subing'
      : props.identity.view === 'htdy'
        ? 'htdy'
        : 'free',
)
const catalog = computed(() =>
  CHART_PROFILES[profile.value].allowed
    .map((id) => ({ id, d: DISPLAY_CATALOG[id] }))
    .filter(
      ({ id, d }) => d && !d.retired && (id + d.label).toLowerCase().includes(layerSearch.value.toLowerCase()),
    ),
)
function toggleDock(kind: 'watch' | 'layers') {
  dock.value = dock.value === kind ? '' : kind
  persist('dock', dock.value)
}
function favorite(symbol: string) {
  favorites.value = favorites.value.includes(symbol)
    ? favorites.value.filter((v) => v !== symbol)
    : [...favorites.value, symbol]
  persist('favorites', favorites.value)
}
const layerFacts = shallowRef<ReturnType<DetailChartSession['inspectDisplayedLayers']>>([])
function refreshLayers() {
  layerFacts.value = props.session.inspectDisplayedLayers()
}
function pick() {
  if (quad.value) return
  drawing.value = !drawing.value
  message.value = drawing.value ? '点击主图上的价格位置。' : ''
  props.session.startPricePick(
    drawing.value
      ? (level) => {
          levels.value = [...levels.value.slice(-31), level]
          drawing.value = false
          message.value = '已标记 ' + level.contract + ' · ' + level.price.toFixed(2)
        }
      : undefined,
  )
}
function layout() {
  drawing.value = false
  props.session.startPricePick()
  quad.value = !quad.value
  persist('quad', quad.value)
}
function expand(p: MarketFrequency) {
  if (quad.value) layout()
  emit('period', p)
}
function writePlan() {
  const frequency = quad.value ? activePeriod.value : props.identity.frequency
  const day = quad.value
    ? charts.value.find((c) => c.$props.period === frequency)?.tradingDay()
    : props.bars.at(-1)?.trading_day
  if (!day) {
    message.value = '当前周期还没有可核对的交易日。'
    return
  }
  void router.push({
    name: 'trade-journal',
    query: { day, compose: 'plan', product: props.identity.symbol, frequency },
    state: { sourceChart: router.currentRoute.value.fullPath },
  })
}
async function capture() {
  if (busy.value) return
  const generation = viewGeneration
  busy.value = true
  message.value = ''
  try {
    const rows = quad.value
      ? periods.map((p) => {
          const chart = charts.value.find((c) => c.$props.period === p)
          if (!chart) throw new Error('等待四周期图表就绪。')
          return chart.capture()
        })
      : [captureObservationPane(props.session, props.identity, props.bars, levels.value, props.preferences)]
    const result = await freezeObservation(
      props.identity.symbol,
      rows,
      quad.value ? activePeriod.value : props.identity.frequency,
    )
    if (!mounted || generation !== viewGeneration) return
    frozen.value = result
    note.value = ''
    captureId = crypto.randomUUID()
    attempted.value = false
    await nextTick()
    dialog.value?.showModal()
  } catch (e) {
    message.value = e instanceof Error ? e.message : '无法生成当前观察原图。'
  } finally {
    busy.value = false
  }
}
async function save() {
  const f = frozen.value
  if (!f || busy.value || !note.value.trim()) return
  const generation = viewGeneration
  busy.value = true
  attempted.value = true
  message.value = ''
  try {
    const result = await saveObservation(
      captureId,
      { note: note.value.trim(), trading_day: f.tradingDay, snapshot: f.snapshot },
      f.png,
    )
    if (!mounted || generation !== viewGeneration || frozen.value !== f) return
    dialog.value?.close()
    frozen.value = null
    await router.push({ name: 'trade-journal', query: { observation: result.id, day: f.tradingDay } })
  } catch {
    if (mounted && generation === viewGeneration) message.value = '保存结果未确认。重试会核对同一笔观察。'
  } finally {
    busy.value = false
  }
}
function keys(event: KeyboardEvent) {
  if (
    event.altKey ||
    event.metaKey ||
    event.ctrlKey ||
    event.repeat ||
    dialog.value?.open ||
    (event.target instanceof HTMLElement &&
      event.target.closest('input,select,textarea,dialog,[contenteditable=true]'))
  )
    return
  if (event.key.toLowerCase() === 'w') toggleDock('watch')
  if (event.key.toLowerCase() === 'i') toggleDock('layers')
  const i = Number(event.key) - 1
  if (/^[1-7]$/.test(event.key) && MARKET_FREQUENCIES[i]) expand(MARKET_FREQUENCIES[i]!)
}
onMounted(() => document.addEventListener('keydown', keys))
onBeforeUnmount(() => document.removeEventListener('keydown', keys))
</script>
<template>
  <section class="chart-desk" aria-label="我的看盘">
    <div class="desk-tools">
      <div>
        <strong>我的看盘</strong><span>{{ identity.symbol.toUpperCase() }} · {{ identity.frequency }}</span>
      </div>
      <button type="button" :aria-pressed="dock === 'watch'" @click="toggleDock('watch')">自选列表 W</button>
      <button type="button" :aria-pressed="dock === 'layers'" @click="toggleDock('layers')">指标库 I</button>
      <button type="button" :aria-pressed="quad" @click="layout">{{ quad ? '返回单图' : '四周期' }}</button>
      <button type="button" :disabled="quad" :aria-pressed="drawing" @click="pick">水平线</button>
      <button v-if="levels.length && !quad" type="button" @click="levels = levels.slice(0, -1)">
        撤销画线
      </button>
      <button type="button" @click="writePlan">写计划</button>
      <button class="save" type="button" :disabled="busy" @click="capture">保存观察</button>
    </div>
    <p v-if="message && !dialog?.open" role="status">{{ message }}</p>
    <div class="desk-columns" :class="{ 'has-dock': dock }" :style="{ '--desk-dock-width': dockWidth + 'px' }">
      <div class="desk-plot">
        <div v-if="quad" class="four">
          <PricePeriodPane
            v-for="p in periods"
            :key="p"
            ref="charts"
            :identity="identity"
            :period="p"
            :active="p === activePeriod"
            @activate="activePeriod = p"
            @expand="expand(p)"
          />
        </div>
        <slot v-else />
      </div>
      <aside v-if="dock">
        <div
          role="separator"
          aria-label="调整侧栏宽度"
          aria-orientation="vertical"
          :aria-valuenow="dockWidth"
          :aria-valuemin="160"
          :aria-valuemax="400"
          tabindex="0"
          class="desk-resize"
          @pointerdown.prevent="resizeDock"
          @keydown="resizeWithKey"
        ></div>
        <header>
          <strong>{{ dock === 'watch' ? '品种列表' : '指标与图层' }}</strong
          ><button aria-label="收起侧栏" @click="toggleDock(dock)">×</button>
        </header>
        <template v-if="dock === 'watch'"
          ><div class="switch">
            <button :aria-pressed="!onlyFavorites" @click="onlyFavorites = false">全市场</button
            ><button :aria-pressed="onlyFavorites" @click="onlyFavorites = true">
              自选 {{ favorites.length }}
            </button>
          </div>
          <input v-model="search" aria-label="搜索列表" placeholder="品种、代码或合约" />
          <div class="list">
            <div v-for="p in products" :key="p.symbol" class="item">
              <button :aria-pressed="p.symbol === identity.symbol" @click="emit('select', p)">
                {{ p.name }} <small>{{ p.contract ?? p.symbol.toUpperCase() }}</small></button
              ><button
                :aria-label="(favorites.includes(p.symbol) ? '移出' : '加入') + '自选 ' + p.name"
                @click="favorite(p.symbol)"
              >
                {{ favorites.includes(p.symbol) ? '★' : '☆' }}
              </button>
            </div>
            <p v-if="!products.length">
              {{
                status === 'loading'
                  ? '读取品种目录…'
                  : status === 'error'
                    ? '品种目录不可用'
                    : '当前列表没有匹配品种'
              }}
            </p>
          </div></template
        >
        <p v-else-if="quad">四周期显示价格与成交量。双击一个周期可进入单图设置指标。</p>
        <template v-else
          ><slot name="settings" /><input
            v-model="layerSearch"
            aria-label="查找指标"
            placeholder="查找指标或来源 ID"
          />
          <div class="list">
            <details v-for="{ id, d } in catalog" :key="id" @toggle="refreshLayers">
              <summary>
                {{ d!.label }}
                <small>{{ { main: '主图', volume: '量能轨', auxiliary: '副图' }[d!.pane] }}</small>
              </summary>
              <code>{{ id }}</code>
              <p>
                {{
                  d!.source.type === 'quant_feature'
                    ? '量化计算中心 · ' + d!.source.featureId
                    : d!.source.type === 'business_fact'
                      ? d!.source.owner
                      : d!.source.version
                }}
              </p>
              <p v-if="Object.keys(fixedParameters(id)).length">
                固定参数
                {{
                  Object.entries(fixedParameters(id))
                    .map(([k, v]) => k + ' ' + v)
                    .join(' / ')
                }}
              </p>
              <template
                v-for="fact in layerFacts.filter((f) => f.indicatorId === id)"
                :key="fact.indicatorId + String(fact.pane)"
              >
                <p>{{ chartLayerStatusLabels[fact.status] }} · {{ fact.formulaVersion || '未提供公式版本' }}</p>
                <p>截止 {{ fact.dataCutoff || '尚无输出' }}</p>
                <p v-if="fact.lastError">{{ fact.lastError }}</p>
              </template>
              <p v-if="!layerFacts.some((f) => f.indicatorId === id)">当前图未挂载</p>
              <p v-if="d!.retrospective">回看重绘 · 仅供观察</p>
              <button type="button" @click="refreshLayers">刷新状态</button>
            </details>
          </div></template
        >
      </aside>
    </div>
    <dialog ref="dialog" @cancel="busy && $event.preventDefault()">
      <form @submit.prevent="save">
        <h3>保存观察到复盘</h3>
        <p v-if="frozen">
          {{ frozen.snapshot.physical_contract }} ·
          {{ frozen.snapshot.panes.map((p) => p.frequency).join(' / ') }} · {{ frozen.tradingDay }}
        </p>
        <label
          >观察依据<textarea
            v-model="note"
            maxlength="2000"
            required
            :readonly="attempted"
            placeholder="记下现在看到了什么，以及后续要核对什么。"
          ></textarea>
        </label>
        <p v-if="message" role="status">{{ message }}</p>
        <div>
          <button type="button" :disabled="busy" @click="dialog?.close()">取消</button
          ><button type="submit" :disabled="busy || !note.trim()">
            {{ attempted ? '核对并保存' : '保存原图与观察' }}
          </button>
        </div>
      </form>
    </dialog>
  </section>
</template>
<style scoped>
.chart-desk {
  min-width: 0;
  color: #d9e3ef;
  background: #101720;
  border: 1px solid #2a3848;
  border-radius: 5px;
  margin-block: 6px;
}
.desk-tools,
.desk-tools > div,
aside header,
.switch,
.item {
  display: flex;
  align-items: center;
  gap: 5px;
}
.desk-tools {
  padding: 6px;
  background: #192432;
  flex-wrap: wrap;
}
.desk-tools > div {
  margin-right: auto;
  gap: 10px;
}
.desk-tools span,
small,
code {
  color: #a7bbd2;
  font-size: 11px;
}
.chart-desk button,
.chart-desk input,
.chart-desk textarea {
  font: inherit;
  color: inherit;
  background: #1b2735;
  border: 1px solid #354457;
  border-radius: 4px;
  padding: 4px 7px;
}
.chart-desk button {
  cursor: pointer;
  font-size: 12px;
  min-height: 28px;
}
.chart-desk button[aria-pressed='true'],
button.save {
  color: #c6ddff;
  background: #283c56;
}
.chart-desk button:disabled {
  opacity: 0.5;
}
.desk-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
}
.desk-columns.has-dock {
  grid-template-columns: minmax(0, 1fr) clamp(175px, 16vw, 255px);
}
.desk-plot {
  min-width: 0;
}
.four {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-width: 0;
}
.four > * {
  min-width: 0;
}
aside {
  background: #151f2b;
  border-left: 1px solid #2a3848;
  min-width: 0;
  padding: 8px;
  overflow-wrap: anywhere;
}
.chart-desk aside header {
  justify-content: space-between;
}
.chart-desk aside input {
  box-sizing: border-box;
  width: 100%;
  margin: 6px 0;
}
.list {
  max-height: 65vh;
  overflow: auto;
}
.item {
  margin: 2px 0;
}
.item button:first-child {
  flex: 1;
  text-align: left;
}
.item small {
  display: block;
}
summary {
  cursor: pointer;
  padding: 5px 0;
}
aside p,
.chart-desk > p {
  font-size: 12px;
  padding: 3px 6px;
}
.chart-desk dialog {
  background: #17222f;
  color: #e3ebf5;
  border: 1px solid #4d6177;
  border-radius: 6px;
  max-width: 460px;
  width: 80%;
}
.chart-desk dialog textarea {
  display: block;
  width: 100%;
  box-sizing: border-box;
  min-height: 85px;
  margin: 5px 0;
}
.desk-columns.has-dock {
  grid-template-columns: minmax(0, 1fr) min(var(--desk-dock-width), 32%);
}
aside {
  position: relative;
}
.desk-resize {
  position: absolute;
  left: -3px;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  touch-action: none;
}
.desk-resize:focus-visible,
.desk-resize:hover {
  background: #4883a7;
}
.chart-desk aside :deep(.desk-generic-studies) {
  border: 0;
  padding: 8px 0;
  margin: 8px 0;
  display: grid;
  gap: 5px;
}
.chart-desk aside :deep(.desk-generic-studies input) {
  width: auto;
  margin-right: 6px;
}
@media (max-width: 920px) {
  .desk-columns.has-dock {
    grid-template-columns: minmax(0, 1fr) min(var(--desk-dock-width), 34%);
  }
}
</style>
