// Run from repo root: node tools/build_newow_ai_oracle.mjs <public-detail.html> <public-strategy-calc.js>
// Known inspected pure function declarations run in a vm without filesystem/network globals.
import fs from 'node:fs';
import crypto from 'node:crypto';
import vm from 'node:vm';
import ts from '../apps/quant-web/node_modules/typescript/lib/typescript.js';
const html = fs.readFileSync(process.argv[2],'utf8');
const shared = fs.readFileSync(process.argv[3],'utf8');
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
if (sha(html) !== 'b12da74d89a7ac304d7479999d11f13ab53ced834a8472f937d78a0c1bd03709'
  || sha(shared) !== 'a91f3a7685e0dadb95927229c45b7ecffeee052d1269b79207ccb9fa08612a9e') {
  throw new Error('PUBLIC_SOURCE_NOT_THE_INSPECTED_SNAPSHOT');
}
const names=['calcMAFrom','calcYellowBlueBand','runOscBacktest','runTrendBacktest','scoreCombos','calcHHV','calcLLV'];
const bodies=names.map(name=>{ const text=(name==='calcHHV'||name==='calcLLV'?shared:html); const start=text.indexOf('function '+name+'('); if(start<0)throw new Error(name); const ast=ts.createSourceFile('oracle.js',text.slice(start),ts.ScriptTarget.Latest,true,ts.ScriptKind.JS); return ast.statements[0].getText(ast); });
const source=JSON.parse(fs.readFileSync('services/quant-api/tests/newow/fixtures/trend-channel-v3.2.82-30-bars.json','utf8'));
const bars=source.bars.map((b,i)=>({date:String(i),open:+b[0],high:+b[1],low:+b[2],close:+b[3]}));
const cases=[bars,bars.slice(0,11),bars.slice(0,10),[...bars,...bars,...bars],Array.from({length:20},(_,i)=>({date:String(i),open:100,high:110,low:90,close:i%2?100:90})), Array.from({length:15},(_,i)=>({date:String(i),open:100,high:100,low:100,close:100}))];
const context=vm.createContext({cases}); vm.runInContext(bodies.join('\n')+`;this.results=cases.map(k=>({bars:k, oscillation:runOscBacktest(k,calcHHV(k,10,'high'),calcLLV(k,10,'low'),'day'),trend:runTrendBacktest(k,calcYellowBlueBand(k),'day')}));`,context,{timeout:2000});
const scoreInputs=[{cumReturn:78.6,accuracy:80,maxDrawdown:35.4,tradeCount:5},{cumReturn:45.6,accuracy:70,maxDrawdown:30,tradeCount:10},{cumReturn:106,accuracy:70,maxDrawdown:18.7,tradeCount:10},{cumReturn:73.9,accuracy:54,maxDrawdown:25.1,tradeCount:26},{cumReturn:25.2,accuracy:100,maxDrawdown:0,tradeCount:3},{cumReturn:-5,accuracy:20,maxDrawdown:12,tradeCount:2}];
context.scoreInputs=scoreInputs;
vm.runInContext(`this.ranked=scoreInputs.map((s,i)=>({index:i,c:{summary:s}}));scoreCombos(ranked);`,context,{timeout:2000});
const fixture={source_sha256:crypto.createHash('sha256').update(html).digest('hex'),oracle_sha256:crypto.createHash('sha256').update(bodies.join('\n')).digest('hex'),cases:context.results.map(r=>({bars:r.bars,oscillation:r.oscillation?.summary??null,trend:r.trend?.summary??null})),score_inputs:scoreInputs,score_outputs:context.ranked.map(c=>({score:c.score,is_best:c.isBest,confidence:c.confidence}))};
fs.writeFileSync('services/quant-api/tests/newow/fixtures/ai-analysis-public-oracle.json',JSON.stringify(fixture,null,2)+'\n');
console.log(JSON.stringify({cases:fixture.cases.length,source:fixture.source_sha256,oracle:fixture.oracle_sha256,scores:fixture.score_outputs}));
