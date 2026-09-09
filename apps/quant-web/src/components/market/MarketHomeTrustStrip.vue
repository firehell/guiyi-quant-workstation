<script setup lang="ts">
import { computed } from 'vue'
import type { RuntimeAfterMarketHealth, RuntimeWeeklyAuditHealth } from '@/api/runtime'
import { afterMarketDetail, afterMarketRunLabel, weeklyAuditDetail, weeklyAuditLabel } from '@/utils/runtimePresentation'
const props = defineProps<{ targetAsOf: string | null; asOf: string | null; participants: number | null; active: number | null; staleCount: number | null; unavailableCount: number | null; priceUnavailableCount: number | null; overview: string; runtime: string | null; eventState: string; overviewStale: boolean; runtimeStale: boolean; eventStale: boolean; overviewError: 'request-failed' | 'typed-unavailable' | null; afterMarket?: RuntimeAfterMarketHealth | null; weeklyAudit?: RuntimeWeeklyAuditHealth | null }>()
const runtimeLabel = computed(() => props.runtime === 'ok' ? '汇总正常' : props.runtime === 'degraded' ? '降级' : props.runtime === null || props.runtime === 'unavailable' ? '暂不可用' : props.runtime)
const eventLabel = computed(() => props.eventState === 'ready' ? '可用' : props.eventState === 'empty' ? '暂无事件' : '暂不可用')
</script>

<template>
  <section class="trust" role="status">
    <span>非实时行情 · 截至 {{ asOf ?? '—' }} · 可用 {{ participants ?? '—' }} / {{ active ?? '—' }}</span>
    <span>过期 {{ staleCount ?? '—' }} · 缺失 {{ unavailableCount ?? '—' }}</span>
    <span v-if="(priceUnavailableCount ?? 0) > 0">涨跌不可用 {{ priceUnavailableCount }}</span>
    <span v-if="overview !== 'ready'" class="trust-warning">行情 {{ overview === 'degraded' ? '降级' : '暂不可用' }}</span>
    <span v-if="overviewStale" class="trust-warning">行情 cached stale · 上次成功快照</span>
    <span>Runtime {{ runtimeLabel }}<em v-if="runtimeStale" class="trust-warning"> · cached stale</em></span>
    <span v-if="afterMarket">盘后维护 {{ afterMarketRunLabel(afterMarket.run_state) }} · {{ afterMarketDetail(afterMarket) }}<em v-if="runtimeStale" class="trust-warning"> · cached stale</em></span>
    <span v-if="weeklyAudit">每周历史审计 {{ weeklyAuditLabel(weeklyAudit.status) }} · {{ weeklyAuditDetail(weeklyAudit) }}<em v-if="runtimeStale" class="trust-warning"> · cached stale</em></span>
    <span>研究观察 {{ eventLabel }}<em v-if="eventStale" class="trust-warning"> · cached stale</em></span>
    <details>
      <summary>状态详情</summary>
      <div>目标日期 {{ targetAsOf ?? '—' }} · 数据日期 {{ asOf ?? '—' }}<br>overview {{ overview }} · Runtime {{ runtime ?? 'unavailable' }} · Alert Event {{ eventState }}<span v-if="overviewError"><br>overview {{ overviewError }}</span></div>
    </details>
  </section>
</template>
