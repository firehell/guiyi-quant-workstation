<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

const props = defineProps<{
  option: EChartsOption
  height?: string
}>()

const chartHeight = props.height || '320px'
</script>

<template>
  <VChart :option="props.option" :style="{ height: chartHeight, width: '100%' }" autoresize />
</template>
