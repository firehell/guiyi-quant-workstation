<script setup lang="ts">
import { computed } from 'vue'
import type { RuntimeHealthResponse } from '@/api/runtime'
import { runtimeStatusPresentation } from '@/utils/runtimePresentation'

const props = defineProps<{
  snapshot: RuntimeHealthResponse | null
  loading: boolean
  stale: boolean
}>()

const items = computed(() => props.snapshot ? runtimeStatusPresentation(props.snapshot) : [])
</script>

<template>
  <section class="runtime-status" data-testid="market-runtime-status" aria-label="运行状态">
    <div v-if="!snapshot" class="runtime-status__unavailable">
      <strong>{{ loading ? '运行状态读取中' : '运行状态暂不可用' }}</strong>
      <span>{{ loading ? '正在读取只读健康快照。' : '本次读取失败，未获得可用快照。' }}</span>
    </div>
    <template v-else>
      <div v-if="stale" class="runtime-status__stale" role="status">状态已过期：已保留上一份成功快照</div>
      <div class="runtime-status__grid">
        <article v-for="item in items" :key="item.key" class="runtime-status__item" :class="`runtime-status__item--${item.tone}`">
          <span class="runtime-status__label">{{ item.label }}</span>
          <strong>{{ item.state }}</strong>
          <span class="runtime-status__detail">{{ item.detail }}</span>
          <time>{{ item.timestamp }}</time>
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.runtime-status { border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); overflow: hidden; }
.runtime-status__grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.runtime-status__item { min-width: 0; display: flex; flex-direction: column; gap: 3px; padding: 11px 13px; border-left: 3px solid var(--gy-border); }
.runtime-status__item + .runtime-status__item { border-top: 0; }
.runtime-status__item--normal { border-left-color: var(--gy-status-ok); }
.runtime-status__item--warning { border-left-color: var(--gy-status-warning); }
.runtime-status__item--danger { border-left-color: var(--gy-status-error); }
.runtime-status__label { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.runtime-status__item strong { color: var(--gy-text-primary); font-size: var(--gy-font-size-sm); }
.runtime-status__detail, .runtime-status__item time { overflow: hidden; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); text-overflow: ellipsis; white-space: nowrap; }
.runtime-status__stale { padding: 7px 12px; background: var(--gy-status-warning-soft); color: var(--gy-text-primary); font-size: var(--gy-font-size-xs); }
.runtime-status__unavailable { display: flex; gap: 10px; align-items: baseline; padding: 12px 14px; color: var(--gy-text-muted); }
.runtime-status__unavailable strong { color: var(--gy-text-primary); }
@media (max-width: 980px) { .runtime-status__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .runtime-status__item + .runtime-status__item { border-top: .5px solid var(--gy-border); } }
@media (max-width: 640px) { .runtime-status__grid { grid-template-columns: 1fr; } }
</style>
