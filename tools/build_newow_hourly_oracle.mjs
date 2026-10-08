// Reproduce the separately inspected hourly oracle; old whole-page oracle remains unchanged.
// Usage: node tools/build_newow_hourly_oracle.mjs <public-detail-3.3.79.html>
import fs from 'node:fs';import crypto from 'node:crypto';import vm from 'node:vm';import ts from '../apps/quant-web/node_modules/typescript/lib/typescript.js';
const html=fs.readFileSync(process.argv[2],'utf8'),sha=s=>crypto.createHash('sha256').update(s).digest('hex');
if(sha(html)!=='3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d')throw Error('snapshot mismatch');
const decl=name=>{const start=html.indexOf(name);const ast=ts.createSourceFile('source.js',html.slice(start),ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);return ast.statements[0].getText(ast)};
const matrix=decl('const AI_ADVICE_MATRIX ='),score=decl('function scoreCombos(');
const source=JSON.parse(fs.readFileSync('services/quant-api/tests/newow/fixtures/ai-analysis-public-oracle.json'));
const inputs=source.score_inputs;
const cases=[inputs, inputs.map((_,i)=>({cumReturn:-5,accuracy:0,maxDrawdown:10,tradeCount:i===0?3:i===5?2:10})),inputs.map((_,i)=>({cumReturn:20,accuracy:100,maxDrawdown:0,tradeCount:i===0?9:10})),inputs.map(()=>({cumReturn:0,accuracy:0,maxDrawdown:0,tradeCount:2}))];
const c=vm.createContext({cases});vm.runInContext(matrix+'\n'+score+`;this.matrix=AI_ADVICE_MATRIX;this.results=cases.map(input=>{const combos=input.map((s,i)=>({index:i,c:{summary:s}}));const best=scoreCombos(combos);return {input,best:best?.index??null,output:combos.map(c=>({score:c.score??null,is_best:c.isBest??false,confidence:c.confidence??null}))}});`,c,{timeout:1000});
const fixture={source_url:'https://www.v8848.cn/stock_detail.html?code=688702.SH',source_version:'3.3.79',source_sha256:sha(html),matrix_sha256:sha(matrix),score_sha256:sha(score),matrix:c.matrix,cases:c.results};
fs.writeFileSync('services/quant-api/tests/newow/fixtures/hourly-public-oracle.json',JSON.stringify(fixture,null,2)+'\n');
fs.writeFileSync('apps/quant-web/src/utils/newowOscillationMatrix.ts',`// Public AI_ADVICE_MATRIX, snapshot 3.3.79, SHA256 ${sha(matrix)}.\n// Historical 27-row explanation only; never changes strategy/exposure or adopts newer page decisions.\nexport const OSCILLATION_MATRIX = ${JSON.stringify(c.matrix,null,2)} as const\n`);
console.log(JSON.stringify({source:sha(html),score:sha(score),matrix:sha(matrix),rows:Object.keys(c.matrix).length,cases:c.results.length}));
