import assert from 'node:assert/strict'
import test from 'node:test'

test('interrupted closeout is not displayed as completed maintenance', async () => {
  const { runtimeStatusPresentation } = await import('../src/utils/runtimePresentation.ts')
  const payload = runtimeHealth()
  Object.assign(payload.components.after_market, {
    status: 'degraded', run_state: 'interrupted', current_run: null,
    last_run: { status: 'interrupted', attempts: null, finished_at: '2026-09-10T00:00:00Z' },
  })
  const item = runtimeStatusPresentation(payload).find(item => item.key === 'after_market')!
  assert.equal(item.state, '运行已中断')
  assert.match(item.timestamp, /收尾/)
  assert.doesNotMatch(item.timestamp, /完成/)
  assert.match(item.detail, /未证明更新完成.*次数未知/)
  assert.equal(item.tone, 'warning')
})

function runtimeHealth(overrides: Record<string, unknown> = {}) {
  return {
    status: 'degraded',
    generated_at: '2026-08-24T10:15:00+00:00',
    readonly: true,
    would_start_services: false,
    would_enqueue_jobs: false,
    would_send_notifications: false,
    components: {
      db: { status: 'ok', latency_ms: 1.2, error_type: null, error_message: null },
      redis: { status: 'ok', latency_ms: 0.8, error_type: null, error_message: null },
      live_market: {
        status: 'ok', configured_enabled: true, operational_count: 60, subscribed_count: 60,
        last_heartbeat_at: '2026-08-24T10:14:58+00:00', last_bar_at: '2026-08-24T10:14:00+00:00',
        phase_counts: { closed: 60 }, error_type: null, error_message: null,
      },
      alert: {
        status: 'ok', configured_enabled: true,
        notification: { transport: 'pushplus', configured: true, audience_count: 2, would_send: false },
        last_heartbeat_at: '2026-08-24T10:14:57+00:00', enabled_rule_count: 2, scope_product_count: 60,
        processing_state: 'ok', notification_state: 'provider_accepted',
        last_processed_bar_at: '2026-08-24T10:00:00+00:00',
        last_processing_success_at: '2026-08-24T10:00:01+00:00', last_processing_failure_at: null,
        processing_error_type: null, last_event_at: '2026-08-24T10:00:01+00:00',
        last_transport_attempt_at: '2026-08-24T10:00:02+00:00',
        last_provider_accepted_at: '2026-08-24T10:00:02+00:00', last_notification_failure_at: null,
        notification_error_type: null, consecutive_notification_failures: 0, error_type: null,
      },
      after_market: {
        status: 'degraded', configured_enabled: true, run_state: 'stuck', expected_trading_day: '2026-08-24',
        current_run: { scheduled_date: '2026-08-24', started_at: '2026-08-24T10:05:00+00:00', products: ['jm'] },
        last_run: null, last_successful_trading_day: '2026-08-23', last_failure: null,
        error_type: 'after_market_run_stuck', error_message: null,
      },
    },
    ...overrides,
  }
}

test('after-market v3 displays attempt, phase and operation counts without a fabricated percentage', async () => {
  const { runtimeStatusPresentation } = await import('../src/utils/runtimePresentation.ts')
  const payload = runtimeHealth()
  Object.assign(payload.components.after_market.current_run, {
    attempt: 2, stage: 'reading', current_symbol: 'au',
    updated_at: '2026-08-24T10:14:00+00:00',
    current_partition: { dataset: ['contract', 'au', 'AU2612', '1m'], year: 2026, month: 8 },
    elapsed_seconds: 64.2,
    counters: { reading: { completed: 7 }, publishing: { completed: 2 } },
  })
  const item = runtimeStatusPresentation(payload).find(item => item.key === 'after_market')!
  assert.match(item.detail, /第 2 次.*读取.*au.*7 次/)
  assert.doesNotMatch(item.detail, /%|分区已完成/)
  assert.match(item.timestamp, /更新 2026-08-24 18:14/)
  assert.match(item.detail, /contract\/AU2612.*1m.*2026-08/)
  assert.match(item.detail, /累计 64.2 秒/)
  assert.match(item.detail, /已提交发布 2 次操作/)
  payload.components.after_market.run_state = 'running'
  assert.match(runtimeStatusPresentation(payload).find(item => item.key === 'after_market')!.detail, /运行结果待确认/)
})

test('optional weekly history audit shows unknown and the audited cutoff independently', async () => {
  const { runtimeStatusPresentation } = await import('../src/utils/runtimePresentation.ts')
  const payload = runtimeHealth()
  payload.components.weekly_audit = { status: 'not_run', through: null, finding_count: null,
    updated_at: null, readonly: true, scope: 'operational_full_history' }
  assert.equal(runtimeStatusPresentation(payload).at(-1)!.state, '尚未审计')
  Object.assign(payload.components.weekly_audit, { status: 'passed', through: '2026-08-21', finding_count: 0 })
  const audit = runtimeStatusPresentation(payload).at(-1)!
  assert.equal(audit.state, '审计通过')
  assert.match(audit.detail, /全历史.*2026-08-21/)
  assert.doesNotMatch(audit.detail, /实时正常|今日完整/)
})

test('runtime presentation distinguishes accepted, unobserved, failed, running, missed and stuck states', async () => {
  const module = await import('../src/utils/runtimePresentation.ts').catch(() => null)
  assert.ok(module, 'runtime presentation helper must exist')

  assert.equal(module.alertNotificationLabel('provider_accepted'), '服务商已接受（不代表送达）')
  assert.equal(module.alertNotificationLabel('unobserved'), '未获自然验证')
  assert.equal(module.alertNotificationLabel('failed'), '通知失败')
  assert.equal(module.afterMarketRunLabel('running'), '运行中')
  assert.equal(module.afterMarketRunLabel('missed'), '未按时运行')
  assert.equal(module.afterMarketRunLabel('stuck'), '运行卡住')
  assert.equal(module.afterMarketRunLabel('failed'), '运行失败')
})

test('runtime presentation exposes four compact operational items and useful timestamps', async () => {
  const module = await import('../src/utils/runtimePresentation.ts').catch(() => null)
  assert.ok(module, 'runtime presentation helper must exist')

  const items = module.runtimeStatusPresentation(runtimeHealth())
  assert.deepEqual(items.map((item) => item.key), ['overall', 'live', 'alert', 'after_market'])
  assert.deepEqual(items.map((item) => item.label), ['运行概况', '实时行情', '提醒服务', '盘后维护'])
  assert.deepEqual(items.map((item) => item.state), ['整体降级', '实时正常', '处理正常', '运行卡住'])
  assert.match(items[0].timestamp, /2026-08-24 18:15/)
  assert.match(items[1].timestamp, /最近 K 线 2026-08-24 18:14/)
  assert.match(items[2].detail, /服务商已接受（不代表送达）/)
  assert.match(items[3].timestamp, /开始 2026-08-24 18:05/)
})

test('disabled Alert is explicit instead of being mislabeled as natural observation unavailable', async () => {
  const module = await import('../src/utils/runtimePresentation.ts').catch(() => null)
  assert.ok(module, 'runtime presentation helper must exist')
  const payload = runtimeHealth()
  payload.components.alert.status = 'disabled'
  payload.components.alert.configured_enabled = false
  payload.components.alert.processing_state = 'unobserved'
  payload.components.alert.notification_state = 'unobserved'

  const alert = module.runtimeStatusPresentation(payload).find((item) => item.key === 'alert')
  assert.equal(alert.state, '提醒未启用')
  assert.doesNotMatch(alert.detail, /未获自然验证/)
})

test('after-market failure notification acceptance is explicit that delivery is not proven', async () => {
  const module = await import('../src/utils/runtimePresentation.ts').catch(() => null)
  assert.ok(module, 'runtime presentation helper must exist')
  const payload = runtimeHealth()
  payload.components.after_market.status = 'failed'
  payload.components.after_market.run_state = 'failed'
  payload.components.after_market.current_run = null
  payload.components.after_market.last_run = {
    trading_day: '2026-08-24', status: 'failed', attempts: 2,
    started_at: '2026-08-24T10:05:00+00:00', finished_at: '2026-08-24T10:10:00+00:00',
    products: ['jm'], error_code: 'UPDATE_FAILED',
    failure_notification: {
      attempted_at: '2026-08-24T10:10:01+00:00', state: 'provider_accepted', error_type: null,
    },
  }

  const afterMarket = module.runtimeStatusPresentation(payload).find((item) => item.key === 'after_market')
  assert.match(afterMarket.detail, /失败通知：服务商已接受（不代表送达）/)
})

test('latest-resource generations retain success on current failure and ignore stale completions', async () => {
  const module = await import('../src/composables/useLatestResource.ts').catch(() => null)
  assert.ok(module, 'latest-resource composable must exist')

  let rejectFirst!: (reason?: unknown) => void
  let resolveSecond!: (value: string) => void
  const first = new Promise<string>((_resolve, reject) => { rejectFirst = reject })
  const second = new Promise<string>((resolve) => { resolveSecond = resolve })
  let attempt = 0
  const resource = module.useLatestResource({
    fetch: () => {
      const currentAttempt = attempt++
      if (currentAttempt === 0) return first
      if (currentAttempt === 1) return second
      return Promise.reject(new Error('current failure'))
    },
  })

  const older = resource.refresh()
  const newer = resource.refresh()
  rejectFirst(new Error('old failure'))
  await older
  assert.equal(resource.loading.value, true)
  assert.equal(resource.failed.value, false)

  resolveSecond('new')
  await newer
  assert.equal(resource.data.value, 'new')
  assert.equal(resource.loading.value, false)
  assert.equal(resource.failed.value, false)

  const failedRefresh = resource.refresh()
  await failedRefresh
  assert.equal(resource.data.value, 'new')
  assert.equal(resource.failed.value, true)
})

for (const classification of ['not_verified_missing', 'verified_match']) {
  test(`v5 interruption ${classification} remains visible during later runs`, async () => {
    const { runtimeStatusPresentation } = await import('../src/utils/runtimePresentation.ts')
    const payload = runtimeHealth()
    Object.assign(payload.components.after_market, {
      status: 'degraded', run_state: 'interrupted', current_run: null,
      last_run: { status: 'interrupted', attempts: null, finished_at: '2026-09-10T00:00:00Z' },
      last_interruption: {
        trading_day: '2026-09-09', started_at: '2026-09-09T18:05:00+08:00',
        closed_at: '2026-09-10T08:00:00+08:00', snapshot_checked_at: '2026-09-10T08:00:00+08:00',
        snapshot_classification: classification, reconciliation_verified: classification === 'verified_match',
      },
    })
    for (const later of [false, true]) {
      if (later) Object.assign(payload.components.after_market, {
        status: 'ok', run_state: 'completed',
        last_run: { status: 'passed', attempts: 1, finished_at: '2026-09-11T00:00:00Z' },
      })
      const item = runtimeStatusPresentation(payload).find(item => item.key === 'after_market')!
      assert.match(item.detail, /2026-09-09.*中断/)
      assert.match(item.detail, classification === 'not_verified_missing'
        ? /原日 Live 快照缺失.*对账未核验/ : /核验时点.*Live 对账匹配/)
      assert.doesNotMatch(item.detail, /从未生成|TTL|已修复|全窗口/)
      if (later) assert.equal(item.state, '已完成')
    }
  })
}
