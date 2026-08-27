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

export function inspectAlertRuleOwnership(sources, expectedOwnership) {
  const expected = normalizeExpectedOwnership(expectedOwnership)
  const activeRuleCodes = Object.keys(expected).sort()
  const occurrences = new Map(activeRuleCodes.map((code) => [code, new Map()]))
  const violations = []
  const parsedSources = Object.entries(sources)
    .sort(([left], [right]) => compareText(left, right))
    .map(([path, source]) => ({ path, source, parsed: parseSource(path, source) }))

  for (const { parsed } of parsedSources) {
    violations.push(...parsed.violations)
  }

  const checker = createInspectionProgram(
    parsedSources.flatMap(({ parsed }) => parsed.units),
  ).getTypeChecker()

  for (const { path, source, parsed } of parsedSources) {
    if (parsed.violations.length > 0) continue
    for (const unit of parsed.units) {
      inspectTypeScriptUnit({
        path,
        fullSource: source,
        unit,
        checker,
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
  checker,
  activeRuleCodes,
  occurrences,
  violations,
}) {
  const staticPropertyText = (node) => {
    return evaluateStaticString(node, checker, new Set())
  }

  const runtimePropertyName = (node) => {
    if (ts.isComputedPropertyName(node)) return staticPropertyText(node.expression)
    if (
      ts.isIdentifier(node)
      || ts.isStringLiteral(node)
      || ts.isNoSubstitutionTemplateLiteral(node)
    ) return node.text
    return null
  }

  const isDestructuringAssignmentProperty = (node) => {
    let current = node
    while (current.parent) {
      const parent = current.parent
      if (
        ts.isBinaryExpression(parent)
        && parent.operatorToken.kind === ts.SyntaxKind.EqualsToken
      ) {
        return node.pos >= parent.left.pos && node.end <= parent.left.end
      }
      if (ts.isFunctionLike(parent) || ts.isSourceFile(parent) || ts.isStatement(parent)) {
        return false
      }
      current = parent
    }
    return false
  }

  const isRuntimeRuleCodeRead = (node) => {
    if (ts.isPropertyAccessExpression(node)) return node.name.text === 'rule_code'
    if (ts.isElementAccessExpression(node)) {
      return staticPropertyText(node.argumentExpression) === 'rule_code'
    }
    if (ts.isBindingElement(node) && ts.isObjectBindingPattern(node.parent)) {
      return runtimePropertyName(node.propertyName ?? node.name) === 'rule_code'
    }
    if (
      (ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node))
      && isDestructuringAssignmentProperty(node)
    ) return runtimePropertyName(node.name) === 'rule_code'
    return false
  }

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
      && isRuntimeRuleCodeRead(node)
    ) {
      const location = sourceLocation(fullSource, unit.baseOffset + node.getStart(unit.sourceFile))
      violations.push({ path, ...location, code: 'ALERT_RULE_DIRECT_ROUTING' })
    }

    ts.forEachChild(node, visit)
  }

  visit(unit.sourceFile)
}

function createInspectionProgram(units) {
  const options = {
    allowImportingTsExtensions: true,
    baseUrl: WEB_ROOT,
    jsx: ts.JsxEmit.Preserve,
    module: ts.ModuleKind.ESNext,
    moduleDetection: ts.ModuleDetectionKind.Force,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    noEmit: true,
    noLib: true,
    paths: { '@/*': ['src/*'] },
    target: ts.ScriptTarget.Latest,
  }
  const sourceFiles = new Map(units.map(({ sourceFile }) => [
    resolve(sourceFile.fileName),
    sourceFile,
  ]))
  const sourceDirectories = new Set()
  for (const fileName of sourceFiles.keys()) {
    let directory = dirname(fileName)
    while (!sourceDirectories.has(directory)) {
      sourceDirectories.add(directory)
      const parent = dirname(directory)
      if (parent === directory) break
      directory = parent
    }
  }
  const baseHost = ts.createCompilerHost(options, true)
  const host = {
    ...baseHost,
    directoryExists: (directoryName) => sourceDirectories.has(resolve(directoryName)),
    fileExists: (fileName) => sourceFiles.has(resolve(fileName)),
    getCurrentDirectory: () => REPOSITORY_ROOT,
    getDirectories: () => [],
    getSourceFile: (fileName) => sourceFiles.get(resolve(fileName)),
    readFile: (fileName) => sourceFiles.get(resolve(fileName))?.text,
    realpath: (fileName) => resolve(fileName),
  }
  return ts.createProgram({
    rootNames: [...sourceFiles.keys()],
    options,
    host,
  })
}

function evaluateStaticString(node, checker, resolvingSymbols) {
  if (!node) return null
  const expression = ts.skipOuterExpressions(node, ts.OuterExpressionKinds.All)
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return expression.text
  }
  if (
    ts.isBinaryExpression(expression)
    && expression.operatorToken.kind === ts.SyntaxKind.PlusToken
  ) {
    const left = evaluateStaticString(expression.left, checker, resolvingSymbols)
    if (left === null) return null
    const right = evaluateStaticString(expression.right, checker, resolvingSymbols)
    return right === null ? null : left + right
  }
  if (!ts.isIdentifier(expression)) return null

  let symbol = checker.getSymbolAtLocation(expression)
  if (!symbol) return null
  if ((symbol.flags & ts.SymbolFlags.Alias) !== 0) {
    symbol = checker.getAliasedSymbol(symbol)
  }
  if (!symbol || resolvingSymbols.has(symbol)) return null

  const declarations = (symbol.declarations ?? []).filter(ts.isVariableDeclaration)
  if (declarations.length !== 1) return null
  const [declaration] = declarations
  const declarationList = declaration.parent
  if (
    !ts.isIdentifier(declaration.name)
    || !declaration.initializer
    || !ts.isVariableDeclarationList(declarationList)
    || (declarationList.flags & ts.NodeFlags.Const) === 0
  ) return null

  resolvingSymbols.add(symbol)
  try {
    return evaluateStaticString(declaration.initializer, checker, resolvingSymbols)
  } finally {
    resolvingSymbols.delete(symbol)
  }
}

function parseSource(path, source) {
  if (extname(path) === '.vue') return parseVue(path, source)
  return parseTypeScript(
    path,
    source,
    0,
    extname(path) === '.tsx',
    source,
    resolve(REPOSITORY_ROOT, path),
  )
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
  for (const [blockName, block] of [
    ['script', descriptor.script],
    ['script-setup', descriptor.scriptSetup],
  ]) {
    if (!block) continue
    const extension = block.lang === 'tsx' ? 'tsx' : 'ts'
    const parsed = parseTypeScript(
      path,
      block.content,
      block.loc.start.offset,
      block.lang === 'tsx',
      source,
      resolve(REPOSITORY_ROOT, `${path}.__${blockName}.${extension}`),
    )
    if (parsed.violations.length > 0) return parsed
    units.push(...parsed.units)
  }
  return { units, violations: [] }
}

function parseTypeScript(path, source, baseOffset, isTsx, fullSource, programPath) {
  const sourceFile = ts.createSourceFile(
    programPath,
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
