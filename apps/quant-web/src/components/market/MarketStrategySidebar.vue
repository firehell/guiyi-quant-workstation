<script setup lang="ts">
/** 行情页右侧栏：策略观察摘要、信号/Stage9 通知与 Live Target 紧凑入口（展示型）。 */
import { computed } from 'vue'
import { NAlert, NButton, NSpin, NTag } from 'naive-ui'
import LiveTargetPanel from '@/components/market/LiveTargetPanel.vue'
import type { BacktestReport } from '@/types/backtest'
import type { SignalEventRecord, Stage9WechatNotification, StrategySignalRecord } from '@/types/signal'

const props = defineProps<{
  isLiveMode: boolean
  strategyStatus: { label: string; type: 'default' | 'success' | 'warning' | 'error' | 'info'; text: string }
  barsCount: number
  signalCount: number
  qualityStatus?: string | null
  selectedContract?: string | null
  selectedPeriod?: string | null
  linkedReport?: BacktestReport | null
  latestSignal?: StrategySignalRecord | null
  selectedEvent?: SignalEventRecord | null
  notification?: Stage9WechatNotification | null
  notificationLoading?: boolean
  notificationError?: string | null
}>()

const emit = defineEmits<{
  openReport: []
  openSignal: []
}>()

const contractSummary = computed(() => {
  const signal = props.latestSignal
  if (!signal) {
    return {
      continuous: '—',
      actual: props.selectedContract || '—',
    }
  }
  return {
    continuous: signal.features?.continuous_contract || signal.contract,
    actual: signal.actual_contract || signal.features?.actual_contract || '—',
  }
})

const signalSummary = computed(() => {
  const signal = props.latestSignal
  if (!signal) return null
  const price = signal.signal_price ?? signal.price ?? signal.current_price
  return {
    strategy: signal.strategy_code || signal.strategy_id || signal.strategy_name,
    version: signal.strategy_version_id || signal.strategy_version || '-',
    period: signal.entry_interval || signal.interval || signal.period,
    direction: directionText(signal.direction),
    directionType: directionType(signal.direction),
    stage: signal.strategy_status || '-',
    bucket: `${signal.score_bucket || '-'} ${signal.bucket_label || ''}`.trim(),
    triggerPrice: formatNumber(price),
    stopLossPrice: formatOptionalNumber(signal.stop_loss_price),
    riskAmount: formatOptionalNumber(signal.risk_amount),
    quality: String(signal.quality_status?.status || props.qualityStatus || '-'),
  }
})

const eventSummary = computed(() => {
  const event = props.selectedEvent
  if (!event) return null
  return {
    id: event.id,
    type: event.event_type,
    barEnd: event.bar_end || event.signal_time || '-',
    triggerPrice: formatOptionalNumber(event.trigger_price),
    quality: String(event.quality_status?.status || '-'),
  }
})

const notificationSummary = computed(() => {
  const notification = props.notification
  if (!notification) return null
  return {
    status: notification.status,
    statusType: notificationStatusType(notification.status),
    attempts: `${notification.attempt_count}/${notification.max_attempts}`,
    httpStatus: notification.response_status_code == null ? '-' : String(notification.response_status_code),
    errorType: notification.last_error_type || '-',
    sentAt: formatDateTime(notification.sent_at),
    nextRetryAt: formatDateTime(notification.next_retry_at),
  }
})

function directionText(direction: string) {
  if (direction === 'long') return '多'
  if (direction === 'short') return '空'
  return '观察'
}

function directionType(direction: string) {
  if (direction === 'long') return 'error' as const
  if (direction === 'short') return 'success' as const
  return 'default' as const
}

function qualityType(status: string | null | undefined) {
  if (status === 'passed') return 'success' as const
  if (status === 'warning') return 'warning' as const
  if (status === 'failed') return 'error' as const
  return 'default' as const
}

function notificationStatusType(status: string | null | undefined) {
  if (status === 'sent') return 'success' as const
  if (status === 'retry_pending') return 'warning' as const
  if (status === 'failed') return 'error' as const
  if (status === 'skipped') return 'default' as const
  return 'info' as const
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function formatOptionalNumber(value: number | null | undefined) {
  return value == null ? '-' : formatNumber(value)
}

function formatDateTime(value: string | null | undefined) {
  return value ? value.replace('T', ' ').slice(0, 16) : '-'
}
</script>

<template>
  <aside class="strategy-sidebar">
    <LiveTargetPanel compact />

    <section class="side-panel">
      <div class="side-panel__title">
        <span>{{ isLiveMode ? 'Live 策略观察' : '策略状态' }}</span>
        <NTag size="small" :type="strategyStatus.type">{{ strategyStatus.label }}</NTag>
      </div>
      <p>{{ strategyStatus.text }}</p>
      <div class="signal-row">
        <span>K线数量</span>
        <strong>{{ barsCount.toLocaleString('zh-CN') }}</strong>
      </div>
      <div class="signal-row">
        <span>周期 / 质量</span>
        <strong>{{ selectedPeriod || '-' }} / <NTag size="small" :type="qualityType(qualityStatus)">{{ qualityStatus || '-' }}</NTag></strong>
      </div>
      <div class="signal-row">
        <span>主连 / 真实</span>
        <strong>{{ contractSummary.continuous }} / {{ contractSummary.actual }}</strong>
      </div>
      <div class="signal-row">
        <span>匹配信号</span>
        <strong>{{ signalCount.toLocaleString('zh-CN') }}</strong>
      </div>

      <div v-if="signalSummary" class="signal-card">
        <div class="signal-card__head">
          <strong>{{ signalSummary.strategy }}</strong>
          <NTag size="small" :type="signalSummary.directionType">{{ signalSummary.direction }}</NTag>
        </div>
        <div class="signal-row">
          <span>版本 / 周期</span>
          <strong>{{ signalSummary.version }} / {{ signalSummary.period }}</strong>
        </div>
        <div class="signal-row">
          <span>阶段 / 分层</span>
          <strong>{{ signalSummary.stage }} / {{ signalSummary.bucket }}</strong>
        </div>
        <div class="signal-row">
          <span>触发 / 止损</span>
          <strong>{{ signalSummary.triggerPrice }} / {{ signalSummary.stopLossPrice }}</strong>
        </div>
        <div class="signal-row">
          <span>风险 / 质量</span>
          <strong>{{ signalSummary.riskAmount }} / {{ signalSummary.quality }}</strong>
        </div>
      </div>
      <div v-else class="empty-note">当前合约与周期暂无匹配信号。</div>

      <NAlert type="warning" :bordered="false">观察提醒，非交易指令，不自动下单。</NAlert>
      <NButton v-if="latestSignal" size="small" block @click="emit('openSignal')">查看关联信号</NButton>
      <NButton v-if="linkedReport" size="small" secondary block @click="emit('openReport')">返回报告 #{{ linkedReport.id }}</NButton>
    </section>

    <section class="side-panel">
      <div class="side-panel__title">
        <span>Stage9 通知状态</span>
        <NTag size="small" :type="notificationStatusType(notification?.status)">
          {{ notification?.status || 'readonly' }}
        </NTag>
      </div>

      <div v-if="eventSummary" class="signal-card">
        <div class="signal-card__head">
          <strong>事件 #{{ eventSummary.id }}</strong>
          <NTag size="small">{{ eventSummary.type }}</NTag>
        </div>
        <div class="signal-row">
          <span>bar_end</span>
          <strong>{{ eventSummary.barEnd.replace('T', ' ').slice(0, 16) }}</strong>
        </div>
        <div class="signal-row">
          <span>触发 / 质量</span>
          <strong>{{ eventSummary.triggerPrice }} / {{ eventSummary.quality }}</strong>
        </div>
      </div>
      <div v-else class="empty-note">选择信号 marker 后显示关联事件。</div>

      <NSpin :show="notificationLoading">
        <div v-if="notificationSummary" class="signal-card">
          <div class="signal-row">
            <span>发送状态</span>
            <strong><NTag size="small" :type="notificationSummary.statusType">{{ notificationSummary.status }}</NTag></strong>
          </div>
          <div class="signal-row">
            <span>尝试 / HTTP</span>
            <strong>{{ notificationSummary.attempts }} / {{ notificationSummary.httpStatus }}</strong>
          </div>
          <div class="signal-row">
            <span>失败类型</span>
            <strong>{{ notificationSummary.errorType }}</strong>
          </div>
          <div class="signal-row">
            <span>发送时间</span>
            <strong>{{ notificationSummary.sentAt }}</strong>
          </div>
          <div class="signal-row">
            <span>下次重试</span>
            <strong>{{ notificationSummary.nextRetryAt }}</strong>
          </div>
        </div>
        <div v-else-if="notificationError" class="empty-note">{{ notificationError }}</div>
        <div v-else class="empty-note">尚无企业微信通知记录。</div>
      </NSpin>
    </section>
  </aside>
</template>

<style scoped>
.strategy-sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-3);
}

.side-panel {
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
  padding: var(--gy-space-3);
}

.side-panel__title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.side-panel p {
  color: var(--gy-text-muted);
  font-size: 13px;
  margin-bottom: 8px;
}

.signal-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  margin-bottom: 6px;
}

.signal-row span {
  color: var(--gy-text-muted);
  white-space: nowrap;
}

.signal-row strong {
  min-width: 0;
  color: var(--gy-text);
  font-weight: 600;
  text-align: right;
  overflow-wrap: anywhere;
}

.signal-card {
  margin: 10px 0;
  padding: 10px;
  border: 1px solid var(--gy-border);
  border-radius: 6px;
  background: var(--gy-bg-panel-strong);
}

.signal-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--gy-text);
}

.empty-note {
  margin: 8px 0 10px;
  color: var(--gy-text-muted);
  font-size: 13px;
}
</style>
