#!/usr/bin/env node

import { readdirSync, readFileSync } from 'node:fs'
import { dirname, extname, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parse as parseVueSfc } from '@vue/compiler-sfc'
import ts from 'typescript'

const SCRIPT_PATH = fileURLToPath(import.meta.url)
const WEB_ROOT = resolve(dirname(SCRIPT_PATH), '..')
const REPOSITORY_ROOT = resolve(WEB_ROOT, '../..')
const SOURCE_ROOT = resolve(WEB_ROOT, 'src')
const RULE_ROUTING_OWNER = 'apps/quant-web/src/utils/alertRules.ts'
const RETIRED_RULE_CODE = 'subing_entry_signal_v1'

const DEFAULT_EXPECTED_OWNERSHIP = {
  htdy_original_15m: {
    'apps/quant-web/src/types/market.ts': 1,
    [RULE_ROUTING_OWNER]: 1,
  },
  subing_strategy_v1: {
    'apps/quant-web/src/types/market.ts': 8,
    [RULE_ROUTING_OWNER]: 1,
  },
}

const EQUALITY_OPERATORS = new Set([
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
])

export function inspectAlertRuleOwnership(sources, expectedOwnership) {
  const expected = normalizeExpectedOwnership(expectedOwnership)
  const activeRuleCodes = Object.keys(expected).sort()
  const occurrences = new Map(activeRuleCodes.map((code) => [code, new Map()]))
  const violations = []

  for (const [path, source] of Object.entries(sources).sort(([left], [right]) => (
    compareText(left, right)
  ))) {
    const parsed = parseSource(path, source)
    violations.push(...parsed.violations)
    if (parsed.violations.length > 0) continue

    for (const unit of parsed.units) {
      inspectTypeScriptUnit({
        path,
        fullSource: source,
        unit,
        activeRuleCodes,
        occurrences,
        violations,
      })
    }
  }

  for (const code of activeRuleCodes) {
    const expectedPaths = expected[code]
    const actualPaths = occurrences.get(code)
    const paths = new Set([...Object.keys(expectedPaths), ...actualPaths.keys()])
    for (const path of [...paths].sort()) {
      const expectedCount = expectedPaths[path] ?? 0
      const actual = actualPaths.get(path) ?? []
      for (const occurrence of actual.slice(expectedCount)) {
        violations.push({ ...occurrence, code: 'ALERT_RULE_LITERAL_UNEXPECTED' })
      }
      for (let index = actual.length; index < expectedCount; index += 1) {
        violations.push({ path, line: 1, column: 1, code: 'ALERT_RULE_LITERAL_MISSING' })
      }
    }
  }

  return violations.sort(compareViolations)
}

export function assertAlertRuleOwnership(sources, expectedOwnership) {
  const violations = inspectAlertRuleOwnership(sources, expectedOwnership)
  if (violations.length === 0) return
  throw new Error(violations.map(formatViolation).join('\n'))
}

function inspectTypeScriptUnit({
  path,
  fullSource,
  unit,
  activeRuleCodes,
  occurrences,
  violations,
}) {
  const visit = (node) => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      const location = sourceLocation(fullSource, unit.baseOffset + node.getStart(unit.sourceFile))
      if (node.text === RETIRED_RULE_CODE) {
        violations.push({ path, ...location, code: 'ALERT_RULE_RETIRED_LITERAL' })
      }
      if (activeRuleCodes.includes(node.text)) {
        const byPath = occurrences.get(node.text)
        const pathOccurrences = byPath.get(path) ?? []
        pathOccurrences.push({ path, ...location })
        byPath.set(path, pathOccurrences)
      }
    }

    if (
      path !== RULE_ROUTING_OWNER
      && ts.isBinaryExpression(node)
      && EQUALITY_OPERATORS.has(node.operatorToken.kind)
      && (isRuleCodeProperty(node.left) || isRuleCodeProperty(node.right))
    ) {
      const location = sourceLocation(fullSource, unit.baseOffset + node.getStart(unit.sourceFile))
      violations.push({ path, ...location, code: 'ALERT_RULE_DIRECT_ROUTING' })
    }

    ts.forEachChild(node, visit)
  }

  visit(unit.sourceFile)
}

function parseSource(path, source) {
  if (extname(path) === '.vue') return parseVue(path, source)
  return parseTypeScript(path, source, 0, extname(path) === '.tsx')
}

function parseVue(path, source) {
  const { descriptor, errors } = parseVueSfc(source, { filename: path })
  if (errors.length > 0) {
    const error = errors[0]
    const offset = typeof error === 'object' && error !== null && 'loc' in error
      ? error.loc?.start?.offset ?? 0
      : 0
    return {
      units: [],
      violations: [{
        path,
        ...sourceLocation(source, offset),
        code: 'ALERT_RULE_VUE_PARSE_ERROR',
      }],
    }
  }

  const units = []
  for (const block of [descriptor.script, descriptor.scriptSetup]) {
    if (!block) continue
    const parsed = parseTypeScript(
      path,
      block.content,
      block.loc.start.offset,
      block.lang === 'tsx',
      source,
    )
    if (parsed.violations.length > 0) return parsed
    units.push(...parsed.units)
  }
  return { units, violations: [] }
}

function parseTypeScript(path, source, baseOffset, isTsx, fullSource = source) {
  const sourceFile = ts.createSourceFile(
    path,
    source,
    ts.ScriptTarget.Latest,
    true,
    isTsx ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  )
  const diagnostic = sourceFile.parseDiagnostics[0]
  if (diagnostic) {
    return {
      units: [],
      violations: [{
        path,
        ...sourceLocation(fullSource, baseOffset + (diagnostic.start ?? 0)),
        code: 'ALERT_RULE_TYPESCRIPT_PARSE_ERROR',
      }],
    }
  }
  return { units: [{ sourceFile, baseOffset }], violations: [] }
}

function isRuleCodeProperty(node) {
  const expression = ts.skipOuterExpressions(node, ts.OuterExpressionKinds.All)
  if (ts.isPropertyAccessExpression(expression)) return expression.name.text === 'rule_code'
  return ts.isElementAccessExpression(expression)
    && (ts.isStringLiteral(expression.argumentExpression)
      || ts.isNoSubstitutionTemplateLiteral(expression.argumentExpression))
    && expression.argumentExpression.text === 'rule_code'
}

function sourceLocation(source, offset) {
  const boundedOffset = Math.max(0, Math.min(offset, source.length))
  let line = 1
  let lineStart = 0
  for (let index = 0; index < boundedOffset; index += 1) {
    if (source.charCodeAt(index) === 10) {
      line += 1
      lineStart = index + 1
    }
  }
  return { line, column: boundedOffset - lineStart + 1 }
}

function normalizeExpectedOwnership(expectedOwnership) {
  return Object.fromEntries(
    Object.entries(expectedOwnership).map(([code, paths]) => [
      code,
      Object.fromEntries(Object.entries(paths).map(([path, count]) => [path, Number(count)])),
    ]),
  )
}

function compareViolations(left, right) {
  return compareText(left.path, right.path)
    || left.line - right.line
    || left.column - right.column
    || compareText(left.code, right.code)
}

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0
}

function formatViolation(violation) {
  return `${violation.path}:${violation.line}:${violation.column} ${violation.code}`
}

function repositorySources() {
  return Object.fromEntries(sourceFiles(SOURCE_ROOT).map((path) => [
    relative(REPOSITORY_ROOT, path).split(sep).join('/'),
    readFileSync(path, 'utf8'),
  ]))
}

function sourceFiles(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(root, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return ['.ts', '.tsx', '.vue'].includes(extname(entry.name)) ? [path] : []
  }).sort()
}

if (process.argv[1] && resolve(process.argv[1]) === SCRIPT_PATH) {
  try {
    assertAlertRuleOwnership(repositorySources(), DEFAULT_EXPECTED_OWNERSHIP)
    console.log('[alert-rule-ownership] passed')
  } catch (error) {
    if (error instanceof Error && /^apps\/quant-web\/src\/.+:\d+:\d+ [A-Z_]+(?:\n|$)/.test(error.message)) {
      console.error(error.message)
    } else {
      console.error('apps/quant-web/src:1:1 ALERT_RULE_CHECK_FAILED')
    }
    process.exitCode = 1
  }
}
