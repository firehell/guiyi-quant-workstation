<script setup lang="ts">
import type { PositionedCallout } from '@/utils/referenceCalloutLayout'
export interface ReferenceCalloutLabel {
  position: PositionedCallout; title: string; detail?: string; direction: 'up' | 'down' | 'neutral'
  selected?: boolean; origin?: string; labelClass?: string; ariaLabel?: string; tooltip?: string
}
withDefaults(defineProps<{ items: ReferenceCalloutLabel[]; drawLines?: boolean }>(), { drawLines: true })
</script>
<template>
  <svg v-if="drawLines" class="reference-label-lines" aria-hidden="true"><polyline v-for="item in items" :key="`${item.origin ?? ''}:${item.position.callout.id}`" :points="`${item.position.x},${item.position.y} ${item.position.x},${(item.position.y + item.position.lineY) / 2} ${item.position.lineX},${(item.position.y + item.position.lineY) / 2} ${item.position.lineX},${item.position.lineY}`" fill="none" /></svg>
  <div v-for="item in items" :key="`${item.origin ?? ''}:${item.position.callout.id}`" role="img" class="reference-action-label" :class="[item.labelClass, `return-${item.direction}`, item.origin ? `origin-${item.origin}` : '', { 'is-selected': item.selected, 'is-compact': item.position.compact && !item.selected }]"
    :style="{ left: `${item.position.left}px`, top: `${item.position.top}px`, width: `${item.position.width}px`, height: `${item.position.height}px` }"
    :data-action-id="item.position.callout.id" :data-reference-id="item.position.callout.id" :data-reference-price="item.position.callout.price" :data-reference-time="item.position.callout.time" :data-reference-contract="item.position.callout.physicalContract" :data-origin-strategy="item.origin" :data-anchor-y="item.position.y"
    :aria-label="item.ariaLabel ?? `${item.title}，${item.detail ?? ''}`" :title="item.tooltip">
    <template v-if="!item.position.compact || item.selected"><strong>{{ item.title }}</strong><span v-if="item.detail !== undefined">{{ item.detail }}</span></template><template v-else>{{ item.position.callout.above ? '▽' : '△' }}</template>
  </div>
</template>
<style scoped>
.reference-label-lines { position:absolute; inset:0; width:100%; height:100%; stroke:#9B8169; stroke-width:1; pointer-events:none; }
.reference-action-label { position:absolute; pointer-events:none; display:grid; place-content:center; gap:0; box-sizing:border-box; min-height:0; padding:0 4px; overflow:hidden; border:1px solid #AD5734; border-radius:3px; background:var(--gy-bg-panel); color:#665044; font-size:12px; line-height:13px; text-align:center; box-shadow:none; }
.reference-action-label strong { font-size:11px; font-weight:600; }
.reference-action-label strong,.reference-action-label span { display:block; line-height:13px; overflow:hidden; white-space:nowrap; }
.return-up span { color:#ff0000; }.return-down span { color:#008000; }.return-neutral span { color:#665044; }
.is-selected { z-index:5; outline:2px solid #8B653D; background:#FFF3D9; }.is-compact { padding:0; place-items:center; font-size:8px; line-height:8px; }
.origin-trend { pointer-events:auto; color:#0a84ff; border-color:#0a84ff; background:#fffffff0; }.origin-oscillation { pointer-events:auto; color:#ff9500; border-color:#ff9500; background:#fffffff0; }
</style>
