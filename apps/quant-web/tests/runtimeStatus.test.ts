import assert from 'node:assert/strict'
import test from 'node:test'

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
  assert.deepEqual(items.map((item) => item.state), ['整体降级', 'Live 正常', '处理正常', '运行卡住'])
  assert.match(items[0].timestamp, /2026-08-24 18:15/)
  assert.match(items[1].timestamp, /最近 Bar 2026-08-24 18:14/)
  assert.match(items[2].detail, /服务商已接受（不代表送达）/)
  assert.match(items[3].timestamp, /开始 2026-08-24 18:05/)
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
