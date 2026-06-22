<script setup lang="ts">
import { NCard, NTabs, NTabPane } from 'naive-ui'
</script>

<template>
  <NCard title="行情看板">
    <NTabs type="line" animated>
      <NTabPane name="kline" tab="K线图">
        <p>K线组件区域 — 对接 lightweight-charts 渲染。</p>
      </NTabPane>
      <NTabPane name="depth" tab="盘口深度">
        <p>盘口深度图区域。</p>
      </NTabPane>
      <NTabPane name="tick" tab="逐笔行情">
        <p>逐笔行情表格区域。</p>
      </NTabPane>
    </NTabs>
  </NCard>
</template>
