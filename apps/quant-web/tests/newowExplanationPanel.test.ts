import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick } from 'vue'

import type { NewowProductSectionResponse } from '../src/types/newowProduct.ts'
import * as viewModels from '../src/utils/newowProductViewModel.ts'

const buildExplanation = (viewModels as unknown as {
  buildNewowExplanationPanelViewModel: (response: NewowProductSectionResponse<'explanation'>) => ExplanationModel
}).buildNewowExplanationPanelViewModel
const buildComparator = (viewModels as unknown as {
  buildNewowComparatorPanelViewModel: (response: NewowProductSectionResponse<'comparator'>) => ComparatorModel
}).buildNewowComparatorPanelViewModel
const resolvePanelState = (viewModels as unknown as {
  resolveNewowPanelRenderState: (lifecycle: string, response: { meta: { read_at: string } } | null, error: string | null) => PanelState
}).resolveNewowPanelRenderState
const componentUrl = new URL('../src/components/market/detail/newow/NewowExplanationPanel.vue', import.meta.url)
const workspaceUrl = new URL('../src/components/market/detail/newow/NewowProductWorkspace.vue', import.meta.url)
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

interface ExplanationModel {
  readonly contextRows: readonly Array<{ readonly frequency: string; readonly barEnd: string; readonly state: string; readonly reason: string }>
  readonly sourceRows: readonly Array<{ readonly role: string; readonly frequency: string; readonly barEnd: string; readonly formulas: string; readonly evidence: string; readonly reason: string }>
  readonly composite: {
    readonly positionRange: string
    readonly direction: string
    readonly directionPoints: string
    readonly certainty: string
    readonly volatility: string
    readonly firstActionToken: string
    readonly firstActionDetail: string
    readonly evidenceReason: string
  }
  readonly evidenceGaps: readonly Array<{ readonly area: string; readonly name: string; readonly reason: string }>
}
interface ComparatorModel {
  readonly label: string
  readonly physicalContract: string
  readonly segmentId: string
  readonly windows: readonly Array<{ readonly window: number; readonly returnText: string; readonly syntheticTerminal: boolean }>
  readonly syntheticTerminalIsReferenceExit: false
  readonly disclosure: string
}
interface PanelState { readonly showValue: boolean; readonly message: string; readonly staleAt: string | null }

test('explanation projects rule, source time, exposure, scores, ATR and first action without recomputation', () => {
  const model = buildExplanation(explanationResponse())

  assert.deepEqual(model.contextRows.map((row) => [row.frequency, row.barEnd, row.state]), [
    ['1w', '—', 'evidence_required'],
    ['1d', '2026-08-14T07:00:00Z', 'BUILD'],
    ['60m', '2026-08-15T06:00:00Z', 'HOLD'],
  ])
  assert.deepEqual(model.sourceRows.map((row) => [row.role, row.frequency, row.barEnd, row.formulas]), [
    ['daily-direction', '1d', '2026-08-14T07:00:00Z', 'daily-rule-v1'],
    ['weekly-context', '1w', '—', 'weekly-rule-v1'],
  ])
  assert.deepEqual(model.composite, {
    positionRange: '30%-50%', direction: 'LONG_BIAS', directionPoints: '2', certainty: '7',
    volatility: '1.2500% · medium · 非 Wilder ATR', firstActionToken: 'WAIT_CONFIRM', firstActionDetail: '等待已完成周期确认', evidenceReason: '—',
  })
  assert.deepEqual(model.evidenceGaps, [
    { area: 'composite', name: 'private-score', reason: 'NEWOW_PRIVATE_SCORE_UNPROVEN' },
    { area: 'target_absorb', name: 'target_absorb', reason: 'NEWOW_TARGET_SOURCE_UNPROVEN' },
  ])
})

test('evidence gaps show exact reasons rather than zero or a current-state substitute', () => {
  const response = explanationResponse()
  response.value!.composite = {
    ...response.value!.composite, status: 'evidence_required', evidence_status: 'EVIDENCE_REQUIRED',
    reason_code: 'NEWOW_COMPOSITE_SOURCE_UNPROVEN', value: null,
  }
  const model = buildExplanation(response)

  assert.equal(model.composite.direction, '—')
  assert.equal(model.composite.certainty, '—')
  assert.equal(model.composite.volatility, '—')
  assert.equal(model.composite.evidenceReason, 'NEWOW_COMPOSITE_SOURCE_UNPROVEN')
  assert.equal(model.sourceRows[1]!.reason, 'NEWOW_WEEKLY_FACT_UNAVAILABLE')
})

test('comparator remains a separately labelled theoretical five-window result', () => {
  const model = buildComparator(comparatorResponse())

  assert.equal(model.label, '五窗口页面比较器（独立理论结果）')
  assert.equal(model.physicalContract, 'JM2601')
  assert.equal(model.segmentId, 'segment-1')
  assert.deepEqual(model.windows.map((item) => item.window), [10, 20, 24, 30, 52])
  assert.deepEqual(model.windows.map((item) => item.returnText), ['1.0%', '2.0%', '2.4%', '3.0%', '5.2%'])
  assert.equal(model.windows.every((item) => item.syntheticTerminal), true)
  assert.equal(model.syntheticTerminalIsReferenceExit, false)
  assert.match(model.disclosure, /不改变 ReferenceTrade 的 OPEN\/CLEAR/)
  assert.match(model.disclosure, /不自动选择策略参数/)
})

test('comparator selects only the exact default segment and fails closed on ambiguous ownership', () => {
  const response = comparatorResponse()
  const second = structuredClone(response.value!.result!.value!.segments[0]!)
  second.segment_id = 'segment-2'
  second.physical_contract = 'JM2605'
  second.results = second.results.map((item) => ({ ...item, page_display: { ...item.page_display, cumulative_return_pct: '99.0' } }))
  response.value!.result!.value!.segments.push(second)

  const model = buildComparator(response)
  assert.equal(model.physicalContract, 'JM2601')
  assert.deepEqual(model.windows.map((item) => item.returnText), ['1.0%', '2.0%', '2.4%', '3.0%', '5.2%'])

  response.value!.result!.value!.default_segment_id = 'missing-segment'
  assert.throws(() => buildComparator(response), /NEWOW_COMPARATOR_DEFAULT_SEGMENT_CONFLICT/)
})

test('first-load error clears values while retained same-identity failure exposes stale timestamp', () => {
  assert.deepEqual(resolvePanelState('unavailable', null, 'NEWOW_API_UNAVAILABLE'), {
    showValue: false, message: '加载失败（服务暂不可用，可重试本面板（NEWOW_API_UNAVAILABLE）），没有可显示的已验证数值。', staleAt: null,
  })
  assert.deepEqual(resolvePanelState('stale', explanationResponse(), 'NEWOW_API_UNAVAILABLE'), {
    showValue: true, message: '刷新失败（服务暂不可用，可重试本面板（NEWOW_API_UNAVAILABLE））；以下为同一身份上次成功的 stale 数值。', staleAt: '2026-08-15T07:00:01Z',
  })
  assert.deepEqual(resolvePanelState('input_conflict', null, 'NEWOW_SHARED_BAR_CONFLICT'), {
    showValue: false, message: 'DATA_CONFLICT（NEWOW_SHARED_BAR_CONFLICT）：冲突事实已清空，不能继续展示旧数值。', staleAt: null,
  })
  assert.deepEqual(resolvePanelState('not_applicable', {
    meta: { read_at: '2026-08-15T07:00:01Z' },
  }, 'NEWOW_COMPARATOR_NOT_APPLICABLE'), {
    showValue: false, message: '当前功能不适用（NEWOW_COMPARATOR_NOT_APPLICABLE）。', staleAt: null,
  })
})

test('explanation component renders evidence gaps and comparator in a separate theoretical panel', async () => {
  const Panel = await loadComponent()
  const explanation = explanationResponse()
  explanation.value!.composite = {
    ...explanation.value!.composite, status: 'evidence_required', evidence_status: 'EVIDENCE_REQUIRED',
    reason_code: 'NEWOW_COMPOSITE_SOURCE_UNPROVEN',
  }
  const Host = defineComponent({ setup: () => () => h(Panel, {
    response: explanation, lifecycle: 'evidence_required', error: null, chartState: { state: 'HOLD', barEnd: '2026-01-05T07:00:00Z', historical: true },
    comparatorResponse: comparatorResponse(), comparatorLifecycle: 'ready', comparatorError: null,
  }) })
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(Host)
  app.mount(root)
  await nextTick()

  const explanationPanel = findNode(root, (node) => node.props['data-testid'] === 'newow-explanation-panel')!
  const comparatorPanel = findNode(root, (node) => node.props['data-testid'] === 'newow-comparator-panel')!
  assert.ok(explanationPanel)
  assert.ok(comparatorPanel)
  const historicalState = findNode(root, node => node.props['data-testid'] === 'newow-window-state')!
  assert.match(nodeText(historicalState), /所示历史.*持有/)
  assert.doesNotMatch(nodeText(historicalState), /当前/)
  assert.doesNotMatch(nodeText(explanationPanel), /策略当前为持有状态|历史 Bar 的策略状态为/)
  assert.match(nodeText(explanationPanel), /当前快照截至/)
  const readable = findNode(root, node => node.props['data-testid'] === 'newow-readable-facts')!
  assert.doesNotMatch(nodeText(readable), /LONG_BIAS|WAIT_CONFIRM|NEWOW_/)
  const sources = findNode(root, node => node.type === 'details' && node.props.class === 'newow-explanation__sources')!
  assert.match(nodeText(sources), /NEWOW_COMPOSITE_SOURCE_UNPROVEN/)
  assert.match(nodeText(sources), /as_of/)

  assert.match(nodeText(explanationPanel), /NEWOW_COMPOSITE_SOURCE_UNPROVEN/)
  assert.match(nodeText(explanationPanel), /NEWOW_WEEKLY_FACT_UNAVAILABLE/)
  assert.match(nodeText(explanationPanel), /NEWOW_PRIVATE_SCORE_UNPROVEN/)
  assert.doesNotMatch(nodeText(explanationPanel), /当前策略.*开仓依据/)
  assert.match(nodeText(comparatorPanel), /独立理论结果/)
  assert.match(nodeText(comparatorPanel), /不改变 ReferenceTrade 的 OPEN\/CLEAR/)
  assert.match(nodeText(comparatorPanel), /10/)
  assert.match(nodeText(comparatorPanel), /52/)
  app.unmount()
})

test('workspace uses a disclosure and dialog while keeping one selected signal authority', () => {
  const source = readFileSync(workspaceUrl, 'utf8')
  assert.match(source, /:aria-expanded="detailsOpen"/)
  assert.match(source, /aria-controls="newow-details"/)
  assert.match(source, /<NewowDetailDialog/)
  assert.doesNotMatch(source, /role="tablist"|researchTab/)
  assert.match(source, /<NewowReferencePanel/)
  assert.match(source, /<NewowExplanationPanel/)
  assert.match(source, /@locate="locateReferenceTrade"/)
  assert.doesNotMatch(source, /selectedTradeId|selectedReferenceSignalId/)
})

function explanationResponse(): Mutable<NewowProductSectionResponse<'explanation'>> {
  const dailyIdentity = { product: 'jm', strategy: 'trend' as const, frequency: '1d' as const, series_kind: 'actual_dominant' as const, profile_id: 'profile-daily', formula_versions: ['daily-rule-v1'] }
  const slot = (frequency: '1w' | '1d' | '60m', barEnd: string | null, state: 'BUILD' | 'HOLD' | null) => ({
    frequency, as_of: '2026-08-15T07:00:00Z', availability: barEnd === null ? evidenceRequired('NEWOW_WEEKLY_FACT_UNAVAILABLE') : ready(), confirmation_status: barEnd === null ? evidenceRequired('NEWOW_WEEKLY_FACT_UNAVAILABLE') : ready(),
    identity: barEnd === null ? null : { ...dailyIdentity, frequency, profile_id: `profile-${frequency}` }, bar_end: barEnd,
    source_identity: barEnd === null ? null : `canonical:jm:JM2601:${frequency}`, physical_contract: barEnd === null ? null : 'JM2601', segment_id: barEnd === null ? null : 'segment-1',
    formula_versions: barEnd === null ? [] : [`${frequency}-rule-v1`], main_state: state,
  })
  return {
    meta: meta(), section: 'explanation', status: ready(), value: {
      context: {
        as_of: '2026-08-15T07:00:00Z', weekly: slot('1w', null, null), daily: slot('1d', '2026-08-14T07:00:00Z', 'BUILD'), hourly: slot('60m', '2026-08-15T06:00:00Z', 'HOLD'),
        missing_frequencies: ['1w'], recompute_mode: 'strict_before', historical_database_knowledge_reconstructed: false,
      },
      composite: {
        status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null, as_of: '2026-08-15T07:00:00Z', formula_versions: ['composite-v1'], source_bars: [],
        value: {
          decision: { source_key: 'k', selected_key: 'long', label: '偏多', position_range: '30%-50%', fallback_used: false, warning_branches_unreachable: true, position_is_target: false, position_is_hand_count: false, formula_version: 'decision-v1' },
          direction: { token: 'LONG_BIAS', certainty_points: 2, formula_version: 'direction-v1' },
          certainty: { trend: 2, oscillation: 2, alignment: 1, direction: 2, uncapped_total: 7, total: 7, cap: null, is_probability: false, is_win_rate: false, formula_version: 'certainty-v1' },
          volatility: { value_pct: '1.2500', level: 'medium', true_range_count: 20, method: 'ATR20_CLOSE', is_wilder_atr: false, formula_version: 'vol-v1' },
          first_action: { rule_token: 'WAIT_CONFIRM', level: 'notice', page_title: '等待', page_detail: '等待已完成周期确认', token_owner: 'guiyi', token_is_page_native: false, page_formula_version: 'action-v1' },
          week_day_matrix: { key: 'k', name: '组合', risk: '中', position: '30%-50%', formula_version: 'matrix-v1' },
          subfeatures: [{ name: 'private-score', status: evidenceRequired('NEWOW_PRIVATE_SCORE_UNPROVEN'), value: null }], input_facts: [], warning_branches_unreachable: true, diagnostic_tokens: null, ai_copy: null, six_combo_ranking: null,
          evidence_manifest_sha256: 'd'.repeat(64), page_source_sha256: 'e'.repeat(64), reachability_sha256: 'f'.repeat(64), ai_template_evidence_sha256: '1'.repeat(64), frozen_results_sha256: '2'.repeat(64),
        },
      },
      target_absorb: { status: 'evidence_required', evidence_status: 'EVIDENCE_REQUIRED', reason_code: 'NEWOW_TARGET_SOURCE_UNPROVEN', as_of: '2026-08-15T07:00:00Z', display_surface: null, formula_versions: [], source_bars: [], decision_facts: [], value: null },
      sources: [
        { role: 'daily-direction', source_category: 'canonical', adapter_version: 'v1', formula_versions: ['daily-rule-v1'], frequency: '1d', bar_end: '2026-08-14T07:00:00Z', physical_contract: 'JM2601', segment_id: 'segment-1', as_of: '2026-08-15T07:00:00Z', dependency_sha256: '3'.repeat(64), status: 'ready', reason_code: null },
        { role: 'weekly-context', source_category: 'canonical', adapter_version: 'v1', formula_versions: ['weekly-rule-v1'], frequency: '1w', bar_end: null, physical_contract: null, segment_id: null, as_of: '2026-08-15T07:00:00Z', dependency_sha256: null, status: 'evidence_required', reason_code: 'NEWOW_WEEKLY_FACT_UNAVAILABLE' },
      ],
      page_parity: false, allowed_uses: ['research_explanation', 'product_display'],
    },
  }
}

function comparatorResponse(): NewowProductSectionResponse<'comparator'> {
  const windows = [10, 20, 24, 30, 52].map((window) => ({
    window, cumulative_return_pct: `${window / 10}.0`, max_drawdown_pct: '-1.0', trade_count: 1, win_count: 1, loss_count: 0, win_rate_pct: '100', force_closed_at_end: true, score: '1',
    page_display: { cumulative_return_pct: `${window / 10}.0`, max_drawdown_pct: '-1.0', win_rate_pct: '100' },
    trades: [{ entry_bar_end: '2026-01-01T07:00:00Z', entry_price: '100', exit_bar_end: '2026-08-15T07:00:00Z', exit_price: '101', return_pct: '1', won: true, synthetic_terminal: true }],
  }))
  return {
    meta: meta(), section: 'comparator', status: ready(), value: {
      result: {
        identity: meta().identity, status: 'ready', evidence_status: 'RESEARCH_EVIDENCE_ONLY', reason_code: null, as_of: '2026-08-15T07:00:00Z', formula_versions: ['comparator-v1'], source_bars: [],
        value: {
          segments: [{
            physical_contract: 'JM2601', segment_id: 'segment-1', frequency: '1d', authoritative_start_trading_day: '2026-01-01', authoritative_end_trading_day: '2026-08-15',
            source_bars: { count: 100, first_trading_day: '2026-01-01', last_trading_day: '2026-08-15', first_bar_end: '2026-01-01T07:00:00Z', last_bar_end: '2026-08-15T07:00:00Z', source_identities: ['canonical'], snapshot_kind: 'canonical', fact_identity_fields: ['bar_end'] },
            as_of: '2026-08-15T07:00:00Z', in_sample: true, repainting: false, repaint_status: ready(), input_snapshot_status: ready(), status: ready(), results: windows, ranked_windows: [52, 30, 24, 20, 10],
          }],
          default_segment_id: 'segment-1', candidate_windows: [10, 20, 24, 30, 52], page_formula_version: 'comparator-v1', futures_adapter_version: 'adapter-v1', page_source_kernel_page_parity: true, futures_adapter_page_parity: false, in_sample: true, executable: false, input_mode: 'canonical', subfeatures: [],
        },
      },
      executable: false, page_parity: false, synthetic_terminal_is_reference_exit: false, allowed_uses: ['in_sample_comparison'],
    },
  }
}

function meta() {
  return {
    schema_version: 'newow_product_detail_v1' as const,
    identity: { product: 'jm', strategy: 'trend' as const, frequency: '1d' as const, series_kind: 'actual_dominant' as const, profile_id: 'profile-1', formula_versions: ['daily-rule-v1'] },
    as_of: '2026-08-15T07:00:00Z', read_at: '2026-08-15T07:00:01Z', input_content_sha256: 'a'.repeat(64), data_revision_identity: null, snapshot_token: 'snapshot-1',
    reference_model_version: 'newow_marker_reference_zero_cost_v1' as const, futures_adaptation_version: 'newow_futures_segment_interrupt_v1' as const,
  }
}
function ready() { return { status: 'ready' as const, evidence_status: 'ACTIVE_CODE_VERIFIED' as const, reason_code: null } }
function evidenceRequired(reason: string) { return { status: 'evidence_required' as const, evidence_status: 'EVIDENCE_REQUIRED' as const, reason_code: reason } }
type Mutable<T> = { -readonly [K in keyof T]: T[K] extends readonly (infer U)[] ? Mutable<U>[] : T[K] extends object ? Mutable<T[K]> : T[K] }

async function loadComponent() {
  const source = readFileSync(componentUrl, 'utf8')
  const { descriptor, errors } = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'newow-explanation-panel', inlineTemplate: true })
  const transpiled = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_match, specifier: string) => {
      for (const suffix of ['', '.ts', '.vue']) {
        const path = resolve(sourceRoot, `${specifier}${suffix}`)
        if (existsSync(path)) return `from '${pathToFileURL(path).href}'`
      }
      throw new Error(`cannot resolve source import: ${specifier}`)
    })
  return (await import(`data:text/javascript;base64,${Buffer.from(transpiled).toString('base64')}`)).default
}

interface TestNode { type: string; props: Record<string, unknown>; parent: TestNode | null; children: TestNode[]; text: string }
function element(type: string): TestNode { return { type, props: {}, parent: null, children: [], text: '' } }
function findNode(node: TestNode, match: (candidate: TestNode) => boolean): TestNode | undefined {
  if (match(node)) return node
  for (const child of node.children) { const found = findNode(child, match); if (found) return found }
  return undefined
}
function nodeText(node: TestNode): string { return [node.text, ...node.children.map(nodeText)].join(' ') }
function nodeOperations() {
  return {
    patchProp(node: TestNode, key: string, _previous: unknown, next: unknown) { node.props[key] = next },
    insert(child: TestNode, parent: TestNode, anchor: TestNode | null = null) { child.parent = parent; const index = anchor === null ? -1 : parent.children.indexOf(anchor); if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
    remove(child: TestNode) { if (child.parent === null) return; child.parent.children = child.parent.children.filter((item) => item !== child); child.parent = null },
    createElement: (type: string) => element(type), createText(text: string) { const node = element('#text'); node.text = text; return node }, createComment(text: string) { const node = element('#comment'); node.text = text; return node },
    setText(node: TestNode, text: string) { node.text = text }, setElementText(node: TestNode, text: string) { node.text = text; node.children = [] },
    parentNode(node: TestNode) { return node.parent }, nextSibling(node: TestNode) { if (node.parent === null) return null; const index = node.parent.children.indexOf(node); return node.parent.children[index + 1] ?? null }, querySelector() { return null }, setScopeId() {}, insertStaticContent() { return [element('#static'), element('#static')] as const },
  }
}
