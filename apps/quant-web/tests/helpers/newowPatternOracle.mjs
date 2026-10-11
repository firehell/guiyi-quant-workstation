import { readFileSync } from 'node:fs'
import vm from 'node:vm'
// The frozen public page is deliberately external to Git; only named pure functions execute.
export function publicPatternOracle(sourcePath, bars, frequency) {
  const source = readFileSync(sourcePath, 'utf8')
  const names = ['calcOniellScore','detectCupHandlePattern','detectSaucerWithHandlePattern','detectDoubleBottomPattern','detectFlatBasePattern','detectAscendingBasesPattern','detectConsolidationPattern','detectTightArea','detectAllPatternsMS']
  const extracted = names.map(name => {
    const start = source.indexOf(`function ${name}(`)
    if (start < 0) throw new Error(`Missing frozen function ${name}`)
    const opening = source.indexOf('{', start)
    let depth = 1, end = opening + 1
    for (; depth && end < source.length; end++) {
      if (source[end] === '{') depth++
      if (source[end] === '}') depth--
    }
    return source.slice(start, end)
  }).join('\n')
  const context = vm.createContext({ window: {currentPeriod: frequency}, performance: {now: () => 0}, console: {log(){}}, bars })
  return JSON.parse(JSON.stringify(vm.runInContext(`${extracted}\ndetectAllPatternsMS(bars)`, context, {timeout: 15000})))
}
