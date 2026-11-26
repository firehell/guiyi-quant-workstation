<script setup lang="ts">
import type { LayerDiagnostics, LayerStatus } from '@guiyi/quant-chart'
import { shallowRef } from 'vue'

const props = defineProps<{ inspect: () => readonly LayerDiagnostics[] }>()
const layers = shallowRef<readonly LayerDiagnostics[]>([])
const labels: Record<LayerStatus, string> = {
  ready: '就绪',
  hidden: '已隐藏',
  loading: '加载中',
  missing_input: '缺少输入',
  warming: '预热中',
  invalid_source: '来源无效',
  compute_error: '计算错误',
  catalog_mismatch: '指标目录不匹配',
  renderer_failure: '渲染错误',
  retired: '已退役',
}

function refresh() {
  layers.value = props.inspect()
}
</script>

<template>
  <details class="chart-layer-diagnostics" @toggle="refresh">
    <summary>图层诊断</summary>
    <div class="chart-layer-diagnostics__panel">
      <button v-if="layers.length" type="button" @click="refresh">刷新诊断</button>
      <p v-else>当前没有挂载的图层。</p>
      <details v-for="(layer, index) in layers" :key="index" class="chart-layer-diagnostics__row">
        <summary>{{ layer.indicatorId }} · {{ labels[layer.status] }}</summary>
        <dl>
          <dt>版本 / 公式</dt><dd>{{ layer.packageVersion }} / {{ layer.formulaVersion ?? '—' }}</dd>
          <dt>面板 / 渲染器</dt>
          <dd>{{ typeof layer.pane === 'string' ? layer.pane : layer.pane.auxiliary }} / {{ layer.renderer }}</dd>
          <dt>来源</dt><dd>{{ layer.sourceIdentity ?? '—' }}</dd>
          <dt>周期 / 数据截止</dt><dd>{{ layer.frequency ?? '—' }} / {{ layer.dataCutoff ?? '—' }}</dd>
          <dt>预热 / 缓存</dt>
          <dd>{{ layer.warmup ? `${layer.warmup.available}/${layer.warmup.required}` : '—' }} / {{ layer.cacheState ?? '—' }}</dd>
          <dt>最后错误</dt><dd>{{ layer.lastError ?? '—' }}</dd>
          <dt>错误记录时间</dt>
          <dd><time v-if="layer.lastErrorAt" :datetime="layer.lastErrorAt">{{ layer.lastErrorAt }}</time><template v-else>—</template></dd>
          <dt>更新时间</dt><dd>{{ layer.updatedAt }}</dd>
        </dl>
      </details>
    </div>
  </details>
</template>

<style scoped>
.chart-layer-diagnostics { color: var(--gy-text-secondary); font-size: 12px; }
.chart-layer-diagnostics summary { cursor: pointer; white-space: nowrap; }
.chart-layer-diagnostics__panel {
  max-height: 320px; width: 330px; overflow: auto; padding: 8px 10px;
  color: var(--gy-text-primary); background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border); border-radius: 4px;
}
.chart-layer-diagnostics__panel button { color: inherit; }
.chart-layer-diagnostics__row { margin-top: 6px; }
.chart-layer-diagnostics__row dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 3px 8px; }
.chart-layer-diagnostics__row dd { margin: 0; overflow-wrap: anywhere; }
</style>
