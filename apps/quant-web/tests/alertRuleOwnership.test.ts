import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, test } from 'node:test'
import {
  assertAlertRuleOwnership,
  inspectAlertRuleOwnership,
} from '../scripts/checkAlertRuleOwnership.mjs'

const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url))
const REPOSITORY_ROOT = fileURLToPath(new URL('../../..', import.meta.url))
const ALERT_RULES_PATH = 'apps/quant-web/src/utils/alertRules.ts'
const MARKET_TYPES_PATH = 'apps/quant-web/src/types/market.ts'
const EXPECTED_OWNERSHIP = {
  htdy_original_15m: {
    [ALERT_RULES_PATH]: 1,
    [MARKET_TYPES_PATH]: 1,
  },
  subing_ths_alert_15m_v1: {
    [ALERT_RULES_PATH]: 1,
    [MARKET_TYPES_PATH]: 1,
  },
}

describe('Alert Rule AST ownership guard', () => {
  test('accepts exact direct literal ownership', () => {
    assert.deepEqual(inspectAlertRuleOwnership(validSources(), EXPECTED_OWNERSHIP), [])
  })

  test('rejects an unexpected rule literal', () => {
    const path = 'apps/quant-web/src/rogue.ts'
    const violations = inspectAlertRuleOwnership(validSources({
      [path]: "const target = 'htdy_original_15m'",
    }), EXPECTED_OWNERSHIP)
    assert.deepEqual(
      violations.map(({ code, path: violationPath }) => ({ code, path: violationPath })),
      [{ code: 'ALERT_RULE_LITERAL_UNEXPECTED', path }],
    )
  })

  test('rejects direct rule_code routing outside the owner', () => {
    const path = 'apps/quant-web/src/rogue.ts'
    const violations = inspectAlertRuleOwnership(validSources({
      [path]: 'event.rule_code === target',
    }), EXPECTED_OWNERSHIP)
    assert.deepEqual(
      violations.map(({ code, path: violationPath }) => ({ code, path: violationPath })),
      [{ code: 'ALERT_RULE_DIRECT_ROUTING', path }],
    )
  })

  test('fails closed on malformed TypeScript and Vue', () => {
    const violations = inspectAlertRuleOwnership({
      'apps/quant-web/src/broken.ts': 'const value: = 1',
      'apps/quant-web/src/broken.vue': '<script setup lang="ts">const value =',
    }, { htdy_original_15m: {} })
    assert.deepEqual(violations.map(({ code }) => code), [
      'ALERT_RULE_TYPESCRIPT_PARSE_ERROR',
      'ALERT_RULE_VUE_PARSE_ERROR',
    ])
  })

  test('accepts the real repository Web sources', () => {
    const sources = Object.fromEntries(
      sourceFiles(join(WEB_ROOT, 'src')).map((path) => [
        relative(REPOSITORY_ROOT, path).split('\\').join('/'),
        readFileSync(path, 'utf8'),
      ]),
    )
    assertAlertRuleOwnership(sources, EXPECTED_OWNERSHIP)
  })
})

function validSources(overrides: Record<string, string> = {}): Record<string, string> {
  return {
    [ALERT_RULES_PATH]: "export const HTDY = 'htdy_original_15m'; export const SUBING = 'subing_ths_alert_15m_v1'",
    [MARKET_TYPES_PATH]: "export type HtdyRule = 'htdy_original_15m'; export type SubingRule = 'subing_ths_alert_15m_v1'",
    ...overrides,
  }
}

function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return ['.ts', '.tsx', '.vue'].includes(extname(entry.name)) ? [path] : []
  })
}
