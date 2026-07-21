<script setup lang="ts">
/** 策略中心：只读展示策略 registry，按能力分类并提供研究入口。 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NEmpty, NTag, useMessage } from 'naive-ui'
import { getStrategyRegistry } from '@/api/dashboard'
import { scanJmV1bSignals } from '@/api/signal'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import PageShell from '@/components/common/PageShell.vue'
import type { StrategyRegistryItem } from '@/types/dashboard'
import { toSafeApiError } from '@/utils/errorRedaction'
import {
  STRATEGY_CAPABILITY_SECTIONS,
  capabilityBadgeForCategory,
  groupRegistryByCapability,
  isRejectedStrategy,
  resolveStrategyCapabilityCategories,
  type StrategyCapabilityCategory,
} from '@/utils/strategyCapability'

const router = useRouter()
const message = useMessage()
const loading = ref(false)
const error = ref<string | null>(null)
const items = ref<StrategyRegistryItem[]>([])

const grouped = computed(() => groupRegistryByCapability(items.value))
const visibleSections = computed(() =>
  STRATEGY_CAPABILITY_SECTIONS.filter((section) => grouped.value[section.key].length > 0),
)

async function load() {
  loading.value = true
  error.value = null
  try {
    const response = await getStrategyRegistry()
    items.value = response.items
  } catch (err) {
    error.value = toSafeApiError(err, '加载策略 registry 失败')
  } finally {
    loading.value = false
  }
}

function goBacktest(item: StrategyRegistryItem) {
  void router.push({
    name: 'backtest',
    query: item.product ? { symbol: item.product } : undefined,
  })
}

function itemBadges(item: StrategyRegistryItem) {
  return resolveStrategyCapabilityCategories(item).map((category) => ({
    category,
    ...capabilityBadgeForCategory(category),
  }))
}

async function scanHistorical(item: StrategyRegistryItem) {
  if (!item.scan_endpoint || isRejectedStrategy(item)) return
  try {
    if (item.scan_endpoint.includes('/v1b/jm/scan')) {
      await scanJmV1bSignals(true)
    } else {
      message.info('请前往信号页配置通用历史研究扫描')
      void router.push({ name: 'signal' })
      return
    }
    message.success('已触发历史研究扫描')
    void router.push({ name: 'signal', query: { signal_layer: 'latest' } })
  } catch (err) {
    message.error(toSafeApiError(err, '历史研究扫描失败'))
  }
}

function sectionAnchor(key: StrategyCapabilityCategory) {
  return `strategy-section-${key}`
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageShell
    title="策略中心"
    subtitle="只读策略规格；Registry ≠ validated，is_v1b 不代表已通过验证"
    :error="error"
    :loading="loading"
    @retry="load"
  >
    <template #badges>
      <CapabilityBadge kind="research-only" label="Registry 只读" />
    </template>
    <template #actions>
      <NButton size="small" :loading="loading" @click="load">刷新</NButton>
    </template>

    <NAlert type="warning" :bordered="false" class="strategy-boundary">
      能力徽章区分历史回测 / 历史扫描 / Live 观察 / 已拒绝候选。无 machine capability 的条目默认「仅研究」。
    </NAlert>

    <section
      v-for="section in visibleSections"
      :id="sectionAnchor(section.key)"
      :key="section.key"
      class="strategy-section"
    >
      <div class="strategy-section__head">
        <div>
          <h2>{{ section.title }}</h2>
          <p>{{ section.hint }}</p>
        </div>
        <CapabilityBadge v-bind="capabilityBadgeForCategory(section.key)" />
      </div>

      <div class="strategy-grid">
        <NCard v-for="item in grouped[section.key]" :key="`${section.key}-${item.strategy_code}`" size="small" :title="item.name">
          <template #header-extra>
            <div class="strategy-card__badges">
              <NTag v-if="item.is_v1b" size="small" type="info">V1-B 样板</NTag>
              <CapabilityBadge
                v-for="badge in itemBadges(item)"
                :key="`${item.strategy_code}-${badge.category}`"
                :kind="badge.kind"
                :label="badge.label"
              />
            </div>
          </template>
          <p class="strategy-card__desc">{{ item.description }}</p>
          <div class="strategy-card__meta">
            <span>{{ item.strategy_code }}</span>
            <span v-if="item.product">品种 {{ item.product }}</span>
            <span v-if="item.periods.length">周期 {{ item.periods.join(' / ') }}</span>
            <span v-if="item.strategy_version">版本 {{ item.strategy_version }}</span>
          </div>
          <div class="strategy-card__actions">
            <NButton
              v-if="item.backtest_endpoints.length && !isRejectedStrategy(item)"
              size="small"
              type="primary"
              @click="goBacktest(item)"
            >
              去回测中心
            </NButton>
            <NButton
              v-if="item.scan_endpoint && !isRejectedStrategy(item)"
              size="small"
              @click="scanHistorical(item)"
            >
              历史研究扫描
            </NButton>
          </div>
        </NCard>
      </div>
    </section>

    <NEmpty v-if="!loading && items.length === 0" description="暂无策略 registry 条目" />
  </PageShell>
</template>

<style scoped>
.strategy-boundary {
  margin-bottom: var(--gy-space-4);
}

.strategy-section {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-3);
  margin-bottom: var(--gy-space-5);
}

.strategy-section__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gy-space-3);
}

.strategy-section__head h2 {
  margin: 0;
  font-size: var(--gy-font-size-lg);
}

.strategy-section__head p {
  margin: 4px 0 0;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.strategy-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gy-space-4);
}

.strategy-card__desc {
  font-size: 13px;
  color: var(--gy-text-muted);
  margin-bottom: 10px;
  min-height: 40px;
}

.strategy-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--gy-text-muted);
  margin-bottom: 12px;
}

.strategy-card__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.strategy-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 1024px) {
  .strategy-grid {
    grid-template-columns: 1fr;
  }
}
</style>
