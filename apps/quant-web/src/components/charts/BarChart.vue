<script setup lang="ts">
/** 柱状图快捷封装：categories + values → ECharts option */
import BaseChart from './BaseChart.vue'
import type { EChartsOption } from 'echarts'

defineProps<{
  categories: string[]
  values: number[]
  title?: string
}>()

/** 构建柱状 option */
function buildOption(categories: string[], values: number[], title?: string): EChartsOption {
  return {
    title: title ? { text: title, left: 'center' } : undefined,
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: categories },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: values }],
  }
}
</script>

<template>
  <BaseChart :option="buildOption($props.categories, $props.values, $props.title)" />
</template>
