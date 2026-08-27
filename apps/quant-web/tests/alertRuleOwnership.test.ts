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
  subing_strategy_v1: {
    [ALERT_RULES_PATH]: 1,
    [MARKET_TYPES_PATH]: 8,
  },
}

describe('Alert Rule AST ownership guard', () => {
  test('accepts exact direct literal ownership', () => {
    assert.deepEqual(inspectAlertRuleOwnership(validSources(), EXPECTED_OWNERSHIP), [])
  })

  test('rejects a direct literal and a split alias routing comparison separately', () => {
    const sources = validSources({
      'apps/quant-web/src/rogue.ts': [
        "const target = 'subing_strategy_v1'",
        'event.rule_code === target',
      ].join('\n'),
    })

    assert.deepEqual(
      inspectAlertRuleOwnership(sources, EXPECTED_OWNERSHIP).map(({ code, path }) => ({ code, path })),
      [
        { code: 'ALERT_RULE_LITERAL_UNEXPECTED', path: 'apps/quant-web/src/rogue.ts' },
        { code: 'ALERT_RULE_DIRECT_ROUTING', path: 'apps/quant-web/src/rogue.ts' },
      ],
    )
  })

  test('uses cooked values for every supported ECMAScript escape and quote form', () => {
    const variants = [
      String.raw`const value = '\x73ubing_strategy_v1'`,
      String.raw`const value = "\u0073ubing_strategy_v1"`,
      "const value = `\\u{73}ubing_strategy_v1`",
      "const value = `\\u{0000073}ubing_strategy_v1`",
    ]

    for (const [index, source] of variants.entries()) {
      const path = `apps/quant-web/src/escape-${index}.ts`
      const violations = inspectAlertRuleOwnership(validSources({ [path]: source }), EXPECTED_OWNERSHIP)
      assert.deepEqual(
        violations.map(({ code, path: violationPath }) => ({ code, path: violationPath })),
        [{ code: 'ALERT_RULE_LITERAL_UNEXPECTED', path }],
      )
    }
  })

  test('rejects direct rule_code routing in TSX without a complete Rule literal', () => {
    const path = 'apps/quant-web/src/Rogue.tsx'
    const source = [
      "const prefix = 'subing'",
      "const target = prefix + '_strategy_v1'",
      'export const view = <p>{event.rule_code === target}</p>',
    ].join('\n')

    const violations = inspectAlertRuleOwnership(validSources({ [path]: source }), EXPECTED_OWNERSHIP)
    assert.deepEqual(
      violations.map(({ code, path: violationPath }) => ({ code, path: violationPath })),
      [{ code: 'ALERT_RULE_DIRECT_ROUTING', path }],
    )
  })

  test('rejects local assignment and destructuring aliases in TS, TSX, and Vue', () => {
    const attacks = {
      'apps/quant-web/src/alias.ts': [
        "const target = 'subing' + '_strategy_v1'",
        'const code = event.rule_code',
        'code === target',
      ].join('\n'),
      'apps/quant-web/src/Alias.tsx': [
        "const target = 'subing' + '_strategy_v1'",
        'let code',
        'code = event.rule_code',
        'export const view = <p>{target !== code}</p>',
      ].join('\n'),
      'apps/quant-web/src/Alias.vue': [
        '<script lang="ts">',
        "const target = 'subing' + '_strategy_v1'",
        'const { rule_code: code } = event',
        'target === code',
        '</script>',
        '<script setup lang="ts">',
        "const target = 'htdy_' + 'original_15m'",
        'let code',
        '({ rule_code: code } = event)',
        'code !== target',
        '</script>',
      ].join('\n'),
    }

    const violations = inspectAlertRuleOwnership(validSources(attacks), EXPECTED_OWNERSHIP)
    assert.deepEqual(
      violations.map(({ code, path }) => ({ code, path })),
      [
        { code: 'ALERT_RULE_DIRECT_ROUTING', path: 'apps/quant-web/src/Alias.tsx' },
        { code: 'ALERT_RULE_DIRECT_ROUTING', path: 'apps/quant-web/src/Alias.vue' },
        { code: 'ALERT_RULE_DIRECT_ROUTING', path: 'apps/quant-web/src/Alias.vue' },
        { code: 'ALERT_RULE_DIRECT_ROUTING', path: 'apps/quant-web/src/alias.ts' },
      ],
    )
  })

  test('allows local rule_code aliases inside the routing owner helper', () => {
    const sources = validSources({
      [ALERT_RULES_PATH]: [
        "export const HTDY = 'htdy_original_15m'",
        "export const SUBING = 'subing_strategy_v1'",
        'export function matchesAlertRuleCode(event, ruleCode) {',
        '  const code = event.rule_code',
        '  return code === ruleCode',
        '}',
      ].join('\n'),
    })

    assert.deepEqual(inspectAlertRuleOwnership(sources, EXPECTED_OWNERSHIP), [])
  })

  test('rejects rule_code routing through every transparent TypeScript wrapper', () => {
    const attacks = [
      '(event.rule_code) === target',
      'event.rule_code! === target',
      '(event.rule_code as string) === target',
      '<string>event.rule_code === target',
      '(event.rule_code satisfies string) === target',
      'target !== (event.rule_code)',
    ]

    for (const [index, source] of attacks.entries()) {
      const path = `apps/quant-web/src/wrapped-${index}.ts`
      assert.deepEqual(
        inspectAlertRuleOwnership(validSources({ [path]: source }), EXPECTED_OWNERSHIP)
          .map(({ code, path: violationPath }) => ({ code, path: violationPath })),
        [{ code: 'ALERT_RULE_DIRECT_ROUTING', path }],
      )
    }
  })

  test('rejects nested transparent rule_code wrappers in TSX', () => {
    const path = 'apps/quant-web/src/Wrapped.tsx'
    const source = 'export const view = <p>{((event.rule_code as string)!) === target}</p>'

    assert.deepEqual(
      inspectAlertRuleOwnership(validSources({ [path]: source }), EXPECTED_OWNERSHIP)
        .map(({ code, path: violationPath }) => ({ code, path: violationPath })),
      [{ code: 'ALERT_RULE_DIRECT_ROUTING', path }],
    )
  })

  test('rejects transparent rule_code wrappers in both Vue script blocks', () => {
    const path = 'apps/quant-web/src/Wrapped.vue'
    const source = [
      '<script lang="ts">',
      '(event.rule_code as string) === target',
      '</script>',
      '<script setup lang="ts">',
      'target !== event.rule_code!',
      '</script>',
    ].join('\n')

    assert.deepEqual(
      inspectAlertRuleOwnership(validSources({ [path]: source }), EXPECTED_OWNERSHIP)
        .map(({ code, line, path: violationPath }) => ({ code, line, path: violationPath })),
      [
        { code: 'ALERT_RULE_DIRECT_ROUTING', line: 2, path },
        { code: 'ALERT_RULE_DIRECT_ROUTING', line: 5, path },
      ],
    )
  })

  test('parses both Vue script blocks as TypeScript', () => {
    const path = 'apps/quant-web/src/Rogue.vue'
    const source = [
      '<script>',
      "const htdy = 'htdy_original_15m'",
      '</script>',
      '<script setup lang="ts">',
      "type Rule = 'subing_strategy_v1'",
      '</script>',
    ].join('\n')

    assert.deepEqual(
      inspectAlertRuleOwnership(validSources({ [path]: source }), EXPECTED_OWNERSHIP)
        .map(({ code, line, path: violationPath }) => ({ code, line, path: violationPath })),
      [
        { code: 'ALERT_RULE_LITERAL_UNEXPECTED', line: 2, path },
        { code: 'ALERT_RULE_LITERAL_UNEXPECTED', line: 5, path },
      ],
    )
  })

  test('ignores comments but counts executable and type string literals', () => {
    const path = 'apps/quant-web/src/owned.ts'
    const sources = {
      [path]: [
        "// 'subing_strategy_v1' and 'subing_entry_signal_v1' are prose only",
        "const executable = 'subing_strategy_v1'",
        "type Rule = 'subing_strategy_v1'",
      ].join('\n'),
    }
    const expected = {
      htdy_original_15m: {},
      subing_strategy_v1: { [path]: 2 },
    }

    assert.deepEqual(inspectAlertRuleOwnership(sources, expected), [])
  })

  test('forbids the retired Rule literal in executable code', () => {
    const path = 'apps/quant-web/src/retired.ts'
    const violations = inspectAlertRuleOwnership(
      { [path]: "const retired = 'subing_entry_signal_v1'" },
      { htdy_original_15m: {}, subing_strategy_v1: {} },
    )

    assert.deepEqual(
      violations.map(({ code, path: violationPath }) => ({ code, path: violationPath })),
      [{ code: 'ALERT_RULE_RETIRED_LITERAL', path }],
    )
  })

  test('fails closed on malformed TypeScript and malformed Vue', () => {
    const violations = inspectAlertRuleOwnership(
      {
        'apps/quant-web/src/broken.ts': 'const value: = 1',
        'apps/quant-web/src/broken.vue': '<script setup lang="ts">const value =',
      },
      { htdy_original_15m: {}, subing_strategy_v1: {} },
    )

    assert.deepEqual(
      violations.map(({ code, path }) => ({ code, path })),
      [
        { code: 'ALERT_RULE_TYPESCRIPT_PARSE_ERROR', path: 'apps/quant-web/src/broken.ts' },
        { code: 'ALERT_RULE_VUE_PARSE_ERROR', path: 'apps/quant-web/src/broken.vue' },
      ],
    )
  })

  test('sorts violations by path, line, column, then fixed code', () => {
    const violations = inspectAlertRuleOwnership(
      {
        'apps/quant-web/src/z.ts': "event.rule_code !== 'subing_entry_signal_v1'",
        'apps/quant-web/src/a.ts': "\nconst rule = 'subing_strategy_v1'",
      },
      { htdy_original_15m: {}, subing_strategy_v1: {} },
    )

    assert.deepEqual(
      violations.map(({ code, path, line }) => ({ code, path, line })),
      [
        { code: 'ALERT_RULE_LITERAL_UNEXPECTED', path: 'apps/quant-web/src/a.ts', line: 2 },
        { code: 'ALERT_RULE_DIRECT_ROUTING', path: 'apps/quant-web/src/z.ts', line: 1 },
        { code: 'ALERT_RULE_RETIRED_LITERAL', path: 'apps/quant-web/src/z.ts', line: 1 },
      ],
    )
  })

  test('assertion output exposes only location and fixed public codes', () => {
    const path = 'apps/quant-web/src/secret.ts'
    const secretSource = "const privatePayload = 'subing_strategy_v1'"

    assert.throws(
      () => assertAlertRuleOwnership(
        { [path]: secretSource },
        { htdy_original_15m: {}, subing_strategy_v1: {} },
      ),
      (error: unknown) => {
        assert.ok(error instanceof Error)
        assert.doesNotMatch(error.message, /privatePayload|subing_strategy_v1/)
        assert.match(error.message, new RegExp(`^${path}:\\d+:\\d+ ALERT_RULE_LITERAL_UNEXPECTED$`))
        return true
      },
    )
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
    [ALERT_RULES_PATH]: [
      "export const HTDY = 'htdy_original_15m'",
      "export const SUBING = 'subing_strategy_v1'",
    ].join('\n'),
    [MARKET_TYPES_PATH]: [
      "export type HtdyRule = 'htdy_original_15m'",
      ...Array.from(
        { length: 8 },
        (_, index) => `export type SubingIdentity${index} = 'subing_strategy_v1'`,
      ),
    ].join('\n'),
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
