<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import BacktestWorkbench from '@/components/backtest/BacktestWorkbench.vue'
import BacktestConfiguration from '@/components/backtest/BacktestConfiguration.vue'
import BacktestRunDetails from '@/components/backtest/BacktestRunDetails.vue'
import BacktestExperiments from '@/components/backtest/BacktestExperiments.vue'
import './backtestCenter.css'

const route = useRoute()
const runId = computed(() => typeof route.params.runId === 'string' ? route.params.runId : '')
const views = [
  ['workbench', '工作台'], ['config', '配置'], ['experiments', '参数实验'], ['validation', '样本外验证'],
] as const
const view = computed(() => views.find(([key]) => key === route.query.view)?.[0] ?? 'workbench')
</script>

<template>
  <div class="backtest-shell">
    <main class="backtest-center">
      <div class="bt-heading">
        <h1>回测中心</h1>
        <RouterLink v-if="!runId && view === 'workbench'" class="bt-button bt-primary" :to="{ name: 'backtests', query: { view: 'config' } }">新建回测</RouterLink>
        <RouterLink v-else-if="runId" class="bt-button" :to="{ name: 'backtests' }">返回工作台</RouterLink>
      </div>
      <nav class="bt-tabs" aria-label="回测中心导航">
        <RouterLink v-for="[key, label] in views" :key="key"
          :to="{ name: 'backtests', query: key === 'workbench' ? {} : { view: key } }"
          :aria-current="view === key && !runId ? 'page' : undefined">{{ label }}</RouterLink>
        <RouterLink class="bt-legacy" :to="{ name: 'research' }">盘后参考研究</RouterLink>
      </nav>
      <BacktestRunDetails v-if="runId" :key="runId" :run-id="runId" />
      <BacktestWorkbench v-else-if="view === 'workbench'" />
      <BacktestConfiguration v-else-if="view === 'config'" />
      <BacktestExperiments v-else :key="view" :validation="view === 'validation'" />
    </main>
  </div>
</template>
