#!/usr/bin/env node

import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export function findStaticImportCycles(assetsRoot, chunkPrefix = 'charting-vendor-') {
  const chunks = readdirSync(assetsRoot).filter(
    (name) => name.startsWith(chunkPrefix) && name.endsWith('.js'),
  )
  const chunkSet = new Set(chunks)
  const graph = new Map()
  const staticImport = /(?:^|;)import(?:[^"']*?from\s*)?["']\.\/([^"']+)["']/gm

  for (const chunk of chunks) {
    const source = readFileSync(resolve(assetsRoot, chunk), 'utf8')
    const dependencies = [...source.matchAll(staticImport)]
      .map((match) => match[1])
      .filter((dependency) => chunkSet.has(dependency))
    graph.set(chunk, dependencies)
  }

  const cycles = []
  const visiting = new Set()
  const visited = new Set()
  const path = []

  function visit(node) {
    if (visiting.has(node)) {
      const start = path.indexOf(node)
      cycles.push([...path.slice(start), node])
      return
    }
    if (visited.has(node)) return

    visiting.add(node)
    path.push(node)
    for (const dependency of graph.get(node) ?? []) visit(dependency)
    path.pop()
    visiting.delete(node)
    visited.add(node)
  }

  for (const node of graph.keys()) visit(node)
  return cycles
}

export function assertNoStaticImportCycles(assetsRoot) {
  const cycles = findStaticImportCycles(assetsRoot)
  if (cycles.length > 0) {
    throw new Error(`charting vendor static import cycles:\n${JSON.stringify(cycles)}`)
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const distRoot = resolve(process.argv[2] ?? 'dist')
  try {
    assertNoStaticImportCycles(resolve(distRoot, 'assets'))
    console.log('[bundle-topology] charting vendor static imports are acyclic')
  } catch (error) {
    console.error(`[bundle-topology] ${error instanceof Error ? error.message : String(error)}`)
    process.exit(1)
  }
}
