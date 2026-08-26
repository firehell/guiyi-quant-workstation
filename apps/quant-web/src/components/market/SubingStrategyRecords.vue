<script setup lang="ts">
import { computed } from 'vue'
import { NSpin, NTag } from 'naive-ui'
import type { SubingStrategyEpisode } from '@/types/market'
import { buildSubingStrategyRecordRows } from '@/utils/subingStrategyRecords'

const props = defineProps<{
  episodes: SubingStrategyEpisode[]
  currentEpisode: SubingStrategyEpisode | null
  latestCompletedEpisode: SubingStrategyEpisode | null
  currentLoading: boolean
  currentError: string | null
  loading: boolean
  error: string | null
}>()

const episodes = computed(() => {
  const byId = new Map(props.episodes.map((episode) => [episode.episode_id, episode]))
  for (const episode of [props.latestCompletedEpisode, props.currentEpisode]) {
    if (episode) byId.set(episode.episode_id, episode)
  }
  return [...byId.values()]
})
const rows = computed(() => buildSubingStrategyRecordRows(episodes.value))
</script>

<template>
  <section class="subing-strategy-records" data-testid="subing-strategy-records">
    <header><div><span>苏冰策略 V1</span><strong>策略记录</strong></div><NTag size="small" type="info">15m</NTag></header>
    <NSpin :show="loading" size="small">
      <p v-if="currentLoading">正在读取当前策略状态…</p>
      <p v-else-if="currentError" class="subing-strategy-records__warning">当前策略状态暂不可用；历史策略投影与 K 线保持可用。</p>
      <p v-if="loading">正在读取历史策略投影…</p>
      <p v-else-if="error" class="subing-strategy-records__warning">历史策略投影暂不可用；K 线与当前观察保持可用。</p>
      <p v-else-if="rows.length === 0">当前窗口暂无相交策略记录</p>
      <ol v-else class="subing-strategy-records__list">
        <li v-for="row in rows" :key="row.episodeId" :data-episode-id="row.episodeId">
          <div class="subing-strategy-records__title"><strong>{{ row.directionLabel }}</strong><NTag size="tiny">{{ row.stateLabel }}</NTag></div>
          <dl>
            <div><dt>合约 / 周期</dt><dd>{{ row.contract }} · {{ row.frequencyLabel }}</dd></div>
            <div><dt>建仓</dt><dd>{{ row.entryTime }} · {{ row.entryReferencePrice }}</dd></div>
            <div v-if="row.exitTime"><dt>清仓</dt><dd>{{ row.exitTime }} · {{ row.exitReferencePrice }}</dd></div>
            <div><dt>持有</dt><dd>{{ row.holdingBarCount }} 根 15m Bar</dd></div>
            <div><dt>退出原因</dt><dd>{{ row.exitReasonLabels.join(' · ') || '—' }}</dd></div>
            <div><dt>结构退出</dt><dd>{{ row.structureExitLabel }}</dd></div>
            <div><dt>参考变动</dt><dd>{{ row.referenceChangeLabel }}</dd></div>
          </dl>
          <small>{{ row.disclaimer }}</small>
        </li>
      </ol>
    </NSpin>
  </section>
</template>

<style scoped>
.subing-strategy-records { display: grid; gap: 8px; }
.subing-strategy-records header, .subing-strategy-records__title { display: flex; align-items: start; justify-content: space-between; gap: 8px; }
.subing-strategy-records header span { display: block; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.subing-strategy-records p, .subing-strategy-records small { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); line-height: 1.45; }
.subing-strategy-records__warning { color: var(--gy-status-warning) !important; }
.subing-strategy-records__list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.subing-strategy-records__list li { display: grid; gap: 7px; padding: 9px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-app); }
.subing-strategy-records dl { display: grid; gap: 5px; margin: 0; }
.subing-strategy-records dl > div { display: flex; justify-content: space-between; gap: 8px; }
.subing-strategy-records dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.subing-strategy-records dd { margin: 0; text-align: right; overflow-wrap: anywhere; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-xs); }
</style>
