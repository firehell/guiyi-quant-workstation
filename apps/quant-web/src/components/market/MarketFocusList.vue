<script setup lang="ts">
import { computed, reactive } from 'vue'
import type {
  MarketTrendFocusItem,
  MarketTrendFocusResponse,
  MarketTrendFocusStage,
} from '@/types/market'

type FocusGroupKey = 'long' | 'short' | 'running' | 'weakening'

const props = withDefaults(defineProps<{
  snapshot: MarketTrendFocusResponse | null
  loading?: boolean
  stale?: boolean
}>(), {
  loading: false,
  stale: false,
})

const emit = defineEmits<{
  open: [item: MarketTrendFocusItem]
}>()

const expanded = reactive<Record<FocusGroupKey, boolean>>({
  long: false,
  short: false,
  running: false,
  weakening: false,
})

const groups = computed(() => [
  { key: 'long' as const, label: '多头', items: props.snapshot?.long_opportunities ?? [] },
  { key: 'short' as const, label: '空头', items: props.snapshot?.short_opportunities ?? [] },
  { key: 'running' as const, label: '运行', items: props.snapshot?.running_trends ?? [] },
  { key: 'weakening' as const, label: '转弱', items: props.snapshot?.weakening_trends ?? [] },
])

const opportunityGroups = computed(() => groups.value.slice(0, 2))
const trackingGroups = computed(() => groups.value.slice(2))

const meta = computed(() => {
  if (!props.snapshot) return props.loading ? '读取当前快照…' : '当前快照不可用'
  const observedAt = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(props.snapshot.observed_at))
  return `${props.stale ? '上一份 · ' : ''}观察时点 ${observedAt}`
})

const stageLabels: Record<MarketTrendFocusStage, string> = {
  setup: '准备',
  breakout: '突破',
  retest: '回踩',
  ready: '就绪',
  running: '运行',
  weakening: '转弱',
}

const hourlyLabels = {
  continuation: '延续',
  pullback: '回撤',
  reversal_block: '反转阻断',
} as const

const hotLabels: Record<string, string> = {
  price_move_up: '价格 Hot',
  price_move_down: '价格 Hot',
  volume_expansion: '成交量 Hot',
  high_volatility: '波动 Hot',
}

function visibleItems(key: FocusGroupKey, items: MarketTrendFocusItem[]) {
  return expanded[key] ? items : items.slice(0, 3)
}

function remaining(items: MarketTrendFocusItem[]) {
  return Math.max(0, items.length - 3)
}

function formatLevel(value: number | null) {
  return value === null
    ? '未形成'
    : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
}
</script>

<template>
  <section class="market-focus" aria-labelledby="market-focus-heading" data-testid="market-focus">
    <header class="market-focus__heading">
      <div>
        <span>Trend Focus</span>
        <h2 id="market-focus-heading">优先检查</h2>
      </div>
      <small>{{ meta }}</small>
    </header>

    <div v-if="!snapshot" class="market-focus__empty market-focus__empty--warning">
      <strong>{{ loading ? 'Trend Focus 读取中' : 'Trend Focus 暂不可用' }}</strong>
      <span>{{ loading ? '正在读取 completed-bar 当前快照。' : '全市场研究仍可独立使用；稍后可随 Radar 一并重试。' }}</span>
    </div>

    <div v-else-if="snapshot.status === 'degraded'" class="market-focus__empty market-focus__empty--warning">
      <strong>Trend Focus 暂不可用：当前快照已降级。</strong>
      <span>{{ snapshot.unavailable.map((item) => item.code).join('、') || '数据完整性不足' }}</span>
    </div>

    <template v-else>
      <div v-if="stale" class="market-focus__stale" role="status">
        Trend Focus 刷新失败，当前显示上一份成功快照。
      </div>

      <section class="market-focus__section" aria-labelledby="market-focus-opportunities">
        <h3 id="market-focus-opportunities">新的机会</h3>
        <div class="market-focus__groups">
          <section
            v-for="group in opportunityGroups"
            :key="group.key"
            class="market-focus__group"
            :data-testid="`market-focus-group-${group.key}`"
          >
            <h4>{{ group.label }} {{ group.items.length }}</h4>
            <div v-if="group.items.length === 0" class="market-focus__group-empty">暂无</div>
            <div v-else class="market-focus__cards">
              <article
                v-for="item in visibleItems(group.key, group.items)"
                :key="item.symbol"
                class="market-focus__card"
                data-testid="market-focus-card"
              >
                <div class="market-focus__card-heading">
                  <div>
                    <strong>{{ item.symbol.toUpperCase() }} {{ item.product_name }}</strong>
                    <span :class="`market-focus__direction market-focus__direction--${item.direction}`">
                      {{ item.direction === 'long' ? '多头' : '空头' }}
                    </span>
                    <span>{{ stageLabels[item.stage] }}</span>
                  </div>
                  <button type="button" :aria-label="`检查 ${item.symbol.toUpperCase()}`" @click="emit('open', item)">检查</button>
                </div>
                <div class="market-focus__facts">
                  <span>60m {{ hourlyLabels[item.hourly_state] }}</span>
                  <span v-for="condition in item.hot_conditions" :key="condition">{{ hotLabels[condition] ?? 'Hot' }}</span>
                  <span>{{ item.volume_confirmed ? '15m 量能已确认' : '15m 量能未确认' }}</span>
                  <span>{{ item.five_minute_confirmed ? '5m 已确认' : '5m 未确认' }}</span>
                </div>
                <dl>
                  <div><dt>下一条件</dt><dd>{{ formatLevel(item.next_level) }}</dd></div>
                  <div><dt>失效条件</dt><dd>{{ formatLevel(item.invalidation_level) }}</dd></div>
                </dl>
              </article>
            </div>
            <button
              v-if="remaining(group.items) > 0"
              type="button"
              class="market-focus__expand"
              @click="expanded[group.key] = !expanded[group.key]"
            >
              {{ expanded[group.key] ? '收起' : `查看更多 ${remaining(group.items)}` }}
            </button>
          </section>
        </div>
      </section>

      <section class="market-focus__section" aria-labelledby="market-focus-tracking">
        <h3 id="market-focus-tracking">趋势跟踪</h3>
        <div class="market-focus__groups">
          <section
            v-for="group in trackingGroups"
            :key="group.key"
            class="market-focus__group"
            :data-testid="`market-focus-group-${group.key}`"
          >
            <h4>{{ group.label }} {{ group.items.length }}</h4>
            <div v-if="group.items.length === 0" class="market-focus__group-empty">暂无</div>
            <div v-else class="market-focus__cards">
              <article
                v-for="item in visibleItems(group.key, group.items)"
                :key="item.symbol"
                class="market-focus__card"
                data-testid="market-focus-card"
              >
                <div class="market-focus__card-heading">
                  <div>
                    <strong>{{ item.symbol.toUpperCase() }} {{ item.product_name }}</strong>
                    <span :class="`market-focus__direction market-focus__direction--${item.direction}`">
                      {{ item.direction === 'long' ? '多头' : '空头' }}
                    </span>
                    <span>{{ stageLabels[item.stage] }}</span>
                  </div>
                  <button type="button" :aria-label="`检查 ${item.symbol.toUpperCase()}`" @click="emit('open', item)">检查</button>
                </div>
                <div class="market-focus__facts">
                  <span>60m {{ hourlyLabels[item.hourly_state] }}</span>
                  <span v-for="condition in item.hot_conditions" :key="condition">{{ hotLabels[condition] ?? 'Hot' }}</span>
                  <span>{{ item.volume_confirmed ? '15m 量能已确认' : '15m 量能未确认' }}</span>
                  <span>{{ item.five_minute_confirmed ? '5m 已确认' : '5m 未确认' }}</span>
                </div>
                <dl>
                  <div><dt>下一条件</dt><dd>{{ formatLevel(item.next_level) }}</dd></div>
                  <div><dt>失效条件</dt><dd>{{ formatLevel(item.invalidation_level) }}</dd></div>
                </dl>
              </article>
            </div>
            <button
              v-if="remaining(group.items) > 0"
              type="button"
              class="market-focus__expand"
              @click="expanded[group.key] = !expanded[group.key]"
            >
              {{ expanded[group.key] ? '收起' : `查看更多 ${remaining(group.items)}` }}
            </button>
          </section>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.market-focus { display: flex; flex-direction: column; gap: 14px; padding: 16px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); box-shadow: var(--gy-shadow-panel); }
.market-focus__heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; }
.market-focus__heading span, .market-focus__heading small { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.market-focus__heading h2, .market-focus__section h3, .market-focus__group h4 { margin: 0; }
.market-focus__heading h2 { margin-top: 3px; font-size: var(--gy-font-size-lg); }
.market-focus__heading small { text-align: right; }
.market-focus__section { display: flex; flex-direction: column; gap: 9px; }
.market-focus__section h3 { font-size: var(--gy-font-size-md); }
.market-focus__groups { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.market-focus__group { display: flex; min-width: 0; flex-direction: column; gap: 8px; padding: 11px; border-radius: var(--gy-radius-md); background: var(--gy-bg-app); }
.market-focus__group h4 { font-size: var(--gy-font-size-sm); }
.market-focus__cards { display: flex; flex-direction: column; gap: 8px; }
.market-focus__card { min-width: 0; padding: 10px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.market-focus__card-heading, .market-focus__card-heading > div { display: flex; align-items: center; gap: 8px; }
.market-focus__card-heading { justify-content: space-between; }
.market-focus__card-heading > div { min-width: 0; flex-wrap: wrap; }
.market-focus__direction { font-size: var(--gy-font-size-xs); font-weight: 500; }
.market-focus__direction--long { color: var(--gy-up); }
.market-focus__direction--short { color: var(--gy-down); }
.market-focus__card button, .market-focus__expand { border: 0; background: none; color: var(--gy-accent); cursor: pointer; }
.market-focus__facts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.market-focus__facts span { padding: 2px 7px; border-radius: var(--gy-radius-pill); background: var(--gy-accent-soft); color: var(--gy-blue-700); font-size: var(--gy-font-size-xs); }
.market-focus__card dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 9px 0 0; }
.market-focus__card dl div { min-width: 0; }
.market-focus__card dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.market-focus__card dd { margin: 2px 0 0; color: var(--gy-text-primary); font-size: var(--gy-font-size-sm); }
.market-focus__expand { align-self: flex-start; padding: 2px 0; }
.market-focus__empty, .market-focus__stale, .market-focus__group-empty { color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
.market-focus__empty { display: flex; flex-direction: column; gap: 4px; padding: 12px; border-radius: var(--gy-radius-md); background: var(--gy-bg-app); }
.market-focus__empty--warning, .market-focus__stale { background: var(--gy-status-warning-soft); }
.market-focus__stale { padding: 8px 10px; border-radius: var(--gy-radius-md); color: var(--gy-status-warning); }
@media (max-width: 900px) { .market-focus__groups { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .market-focus__heading { align-items: flex-start; flex-direction: column; } .market-focus__heading small { text-align: left; } }
</style>
