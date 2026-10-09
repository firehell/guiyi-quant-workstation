import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { cases } from './newowPatternCases.mjs'
import { publicPatternOracle } from './newowPatternOracle.mjs'
const source = process.argv[2]
if (!source) throw new Error('Usage: node tests/helpers/generateNewowPatternGoldens.mjs /absolute/path/to/frozen/detail.html')
const goldens = cases.map(({name,bars})=>({name,bars,day:publicPatternOracle(source,bars,'day'),week:publicPatternOracle(source,bars,'week')}))
writeFileSync(fileURLToPath(new URL('../fixtures/newowPublicPatterns.v3379.json',import.meta.url)),JSON.stringify({sourceSha256:createHash('sha256').update(readFileSync(source)).digest('hex'),goldens},null,2)+'\n')
console.log(`Generated ${goldens.length} public-source cases for both frequencies`)
