<script setup lang="ts">
/** JM V1-B 快捷回测：一键创建固定任务，WebSocket + 轮询跟踪直至完成。 */
import { onUnmounted, ref } from 'vue'
import { NAlert, NButton, NCard, NProgress, useMessage } from 'naive-ui'
import {
  createJmV1bDailyEma21Task,
  createJmV1bDailyScore2of4Task,
  createJmV1bDailyTrendCrossScore2Task,
  createJmV1bEntryTask,
  describeBacktestApiError,
  getBacktestTask,
} from '@/api/backtestApi'
import type { BacktestTask } from '@/types/backtest'
import { WsClient } from '@/websocket/WsClient'
import { backtestTaskWsUrl } from '@/websocket'

const emit = defineEmits<{
  taskCompleted: [task: BacktestTask]
}>()

const message = useMessage()
const runningKey = ref<string | null>(null)
const currentTask = ref<BacktestTask | null>(null)
let ws: WsClient | null = null
let pollTimer: number | null = null

const quickTasks = [
  { key: '15m', label: '15m 快入', action: () => createJmV1bEntryTask('15m') },
  { key: '5m', label: '5m 快入', action: () => createJmV1bEntryTask('5m') },
  { key: 'daily-ema21', label: '日线 EMA21+MACD', action: () => createJmV1bDailyEma21Task() },
  { key: 'daily-score2', label: '日线 Score2/4', action: () => createJmV1bDailyScore2of4Task() },
  { key: 'daily-trend', label: '日线趋势交叉', action: () => createJmV1bDailyTrendCrossScore2Task() },
]

function stopTracking() {
  ws?.disconnect()
  ws = null
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

/** 轮询兜底：WS 未推送终态时仍能 emit taskCompleted。 */
async function pollTask(taskNo: string) {
  try {
    const task = await getBacktestTask(taskNo)
    currentTask.value = task
    if (['success', 'completed', 'failed', 'partial_failed'].includes(task.status)) {
      stopTracking()
      runningKey.value = null
      emit('taskCompleted', task)
      if (task.status === 'failed' || task.status === 'partial_failed') {
        message.warning(`任务 ${taskNo} 结束：${task.status}`)
      } else {
        message.success(`任务 ${taskNo} 已完成`)
      }
    }
  } catch {
    // ignore transient poll errors
  }
}

/** 订阅任务 WS 并启动 3s 轮询，终态时通知父组件刷新报告。 */
function trackTask(task: BacktestTask) {
  stopTracking()
  currentTask.value = task
  ws = new WsClient(backtestTaskWsUrl(task.task_no))
  ws.on('message', (payload) => {
    if (payload && typeof payload === 'object') {
      currentTask.value = { ...task, ...(payload as BacktestTask) }
      const status = (payload as BacktestTask).status
      if (status && ['success', 'completed', 'failed', 'partial_failed'].includes(status)) {
        stopTracking()
        runningKey.value = null
        emit('taskCompleted', currentTask.value)
      }
    }
  })
  ws.connect()
  pollTimer = window.setInterval(() => void pollTask(task.task_no), 3000)
}

async function runTask(key: string, action: () => Promise<BacktestTask>) {
  if (runningKey.value) return
  runningKey.value = key
  try {
    const task = await action()
    message.success(`已创建任务 ${task.task_no}`)
    trackTask(task)
  } catch (err) {
    runningKey.value = null
    message.error(describeBacktestApiError(err, '创建 JM V1-B 任务失败'))
  }
}

onUnmounted(() => stopTracking())
</script>

<template>
  <NCard title="JM V1-B 快捷回测" size="small">
    <p class="v1b-quick__hint">一键创建固定 JM V1-B 回测任务，完成后自动刷新报告列表。</p>
    <div class="v1b-quick__actions">
      <NButton
        v-for="item in quickTasks"
        :key="item.key"
        size="small"
        type="primary"
        secondary
        :loading="runningKey === item.key"
        :disabled="Boolean(runningKey && runningKey !== item.key)"
        @click="runTask(item.key, item.action)"
      >
        {{ item.label }}
      </NButton>
    </div>
    <div v-if="currentTask" class="v1b-quick__progress">
      <div class="v1b-quick__progress-head">
        <span>{{ currentTask.task_no }}</span>
        <span>{{ currentTask.status }}</span>
      </div>
      <NProgress type="line" :percentage="Math.round((currentTask.progress || 0) * 100)" :show-indicator="true" />
    </div>
    <NAlert type="info" :bordered="false">研究回测，不代表实盘结果。</NAlert>
  </NCard>
</template>

<style scoped>
.v1b-quick__hint {
  margin-bottom: 10px;
  color: var(--gy-text-muted, #94a3b8);
  font-size: 13px;
}

.v1b-quick__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.v1b-quick__progress {
  margin-bottom: 12px;
}

.v1b-quick__progress-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 6px;
  color: var(--gy-text-muted, #94a3b8);
}
</style>
