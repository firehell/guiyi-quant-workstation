<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NGrid, NGridItem, NTag, useMessage } from 'naive-ui'
import { getStrategyRegistry } from '@/api/dashboard'
import { scanJmV1bSignals } from '@/api/signal'
import PageShell from '@/components/common/PageShell.vue'
import type { StrategyRegistryItem } from '@/types/dashboard'

const router = useRouter()
const message = useMessage()
const loading = ref(false)
const error = ref<string | null>(null)
const items = ref<StrategyRegistryItem[]>([])

async function load() {
  loading.value = true
  error.value = null
  try {
    const response = await getStrategyRegistry()
    items.value = response.items
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载策略 registry 失败'
  } finally {
    loading.value = false
  }
}

function goBacktest() {
  void router.push({ name: 'backtest' })
}

async function scanJm() {
  try {
    await scanJmV1bSignals(true)
    message.success('已触发 JM V1-B 扫描')
    void router.push({ name: 'signal' })
  } catch (err) {
    message.error(err instanceof Error ? err.message : '扫描失败')
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageShell title="策略中心" subtitle="只读策略规格与 V1-B 固定任务入口" :error="error" :loading="loading">
    <NGrid :cols="2" :x-gap="16" :y-gap="16">
      <NGridItem v-for="item in items" :key="item.strategy_code">
        <NCard size="small" :title="item.name">
          <template #header-extra>
            <NTag v-if="item.is_v1b" size="small" type="success">V1-B</NTag>
          </template>
          <p class="strategy-card__desc">{{ item.description }}</p>
          <div class="strategy-card__meta">
            <span>{{ item.strategy_code }}</span>
            <span v-if="item.product">品种 {{ item.product }}</span>
            <span v-if="item.periods.length">周期 {{ item.periods.join(' / ') }}</span>
          </div>
          <div class="strategy-card__actions">
            <NButton v-if="item.backtest_endpoints.length" size="small" type="primary" @click="goBacktest">
              去回测中心触发
            </NButton>
            <NButton v-if="item.scan_endpoint" size="small" @click="scanJm">JM 扫描</NButton>
          </div>
        </NCard>
      </NGridItem>
    </NGrid>
  </PageShell>
</template>

<style scoped>
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

.strategy-card__actions {
  display: flex;
  gap: 8px;
}
</style>
