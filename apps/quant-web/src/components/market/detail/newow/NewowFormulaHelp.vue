<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NEWOW_FORMULA_HELP, type NewowFormulaTopic } from '@/utils/newowFormulaHelp'
const props = defineProps<{ topic: NewowFormulaTopic; formulaVersions?: readonly string[]; asOf?: string }>()
const selected = ref<NewowFormulaTopic>(props.topic)
watch(() => props.topic, value => { selected.value = value })
const entry = computed(() => NEWOW_FORMULA_HELP[selected.value])
</script>
<template>
  <section class="newow-formula-help" aria-label="公开公式速查">
    <label>指标 / 策略 <select v-model="selected" aria-label="公式速查主题"><option v-for="(item, key) in NEWOW_FORMULA_HELP" :key="key" :value="key">{{ item.title }}</option></select></label>
    <h3>{{ entry.title }}</h3>
    <p>H / L / C 为当前 Bar 的高 / 低 / 收；[-k] 为前 k 根；MAp 为可用部分窗口均值。以下为公式资料，不在浏览器重算。</p>
    <details open><summary>公式与阈值</summary><pre>{{ entry.formula }}</pre></details>
    <details open><summary>初始化与使用边界</summary><p>{{ entry.boundary }}</p></details>
    <details><summary>资料与当前结果来源</summary><p>{{ entry.source }} · 牛哇详情 v3.3.59 公开源码审计，2026-09-26。</p><p>当前所示策略 / 副图的响应版本：{{ formulaVersions?.join(' / ') || '尚未读取' }}；截至 {{ asOf || '—' }}。切换速查主题只切换资料，不切换图表结果。</p><p>资料原式与归一实际公式以各自版本区分；图形、过程提示、参考交易不代表账户成交。</p></details>
  </section>
</template>
<style scoped>
.newow-formula-help { display:grid; gap:10px; color:#475467; font-size:12px; line-height:1.65; }
h3,p { margin:0; } h3 { color:#20242b; font-size:15px; }
label { display:flex; align-items:center; gap:12px; } select { flex:1; min-width:0; min-height:40px; background:#fff; border:1px solid #d0d5dd; border-radius:8px; padding:0 8px; color:#344054; }
details { border:1px solid #ebedf0; border-radius:8px; padding:10px 12px; } summary { cursor:pointer; font-weight:600; color:#344054; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; font-family:ui-monospace,monospace; padding:10px; background:#f8fafc; border-radius:6px; }
</style>
