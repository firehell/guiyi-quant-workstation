<script setup lang="ts">
import { NCard, NTabs, NTabPane } from 'naive-ui'
</script>

<template>
  <NCard title="复盘分析">
    <NTabs type="line" animated>
      <NTabPane name="daily" tab="每日复盘">
        <p>每日交易复盘 — 盈亏归因分析。</p>
      </NTabPane>
      <NTabPane name="weekly" tab="周复盘">
        <p>周度复盘 — 策略表现汇总。</p>
      </NTabPane>
      <NTabPane name="trade" tab="逐笔复盘">
        <p>逐笔交易详情回放。</p>
      </NTabPane>
    </NTabs>
  </NCard>
</template>
