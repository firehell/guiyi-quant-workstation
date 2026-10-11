// Extract only audited public pure declarations; no page/network/DOM execution.
import fs from 'node:fs';
import crypto from 'node:crypto';
import vm from 'node:vm';
import ts from '../apps/quant-web/node_modules/typescript/lib/typescript.js';
const [sourceRoot, destination] = process.argv.slice(2);
const html = fs.readFileSync(`${sourceRoot}/detail.html`, 'utf8');
const sha = crypto.createHash('sha256').update(html).digest('hex');
if (sha !== '3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d') throw Error('source hash mismatch');
const other = fs.readFileSync(`${sourceRoot}/strategy-calc.js`, 'utf8');
if (crypto.createHash('sha256').update(other).digest('hex') !== 'a91f3a7685e0dadb95927229c45b7ecffeee052d1269b79207ccb9fa08612a9e') throw Error('channel hash mismatch');
const names = ['calcMAFrom','calcVolumeMA','_computeAllSignals','_isOscFamily','_isOscTest','_isOscTargetExit','_isOscMaGate','_isOscConfirmExit','_oscStopPct','runOscBacktest','localXichouLagaoBacktestIdeal','calcHHV','calcLLV'];
const code=names.map(name=>{
 const src=name==='calcHHV'||name==='calcLLV'?other:html;
 const ast=ts.createSourceFile('source.js',src.slice(src.indexOf(`function ${name}(`)),ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
 if(!ts.isFunctionDeclaration(ast.statements[0])||ast.statements[0].name.text!==name) throw Error(name);
 return ast.statements[0].getText(ast);
}).join('\n');
const dates = i=>new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10);
const flat=Array.from({length:16},(_,i)=>({date:dates(i),open:100,high:110,low:100,close:105,volume:100}));
const wave=Array.from({length:160},(_,i)=>{const c=+(100+15*Math.sin(i/4)+i/7).toFixed(5);return {date:dates(i),open:c,high:c+5,low:c-5,close:c,volume:100+i%7*30};});
const cases=[{name:'same-bar',bars:flat},{name:'wave',bars:wave},
{name:'stop-gap',bars:flat.map((b,i)=>i===10?{...b,open:90,high:120,low:85,close:100}:b)},
{name:'pending-refresh',bars:flat.slice(0,10).concat([{date:dates(10),open:105,high:120,low:100,close:115,volume:100},{date:dates(11),open:110,high:121,low:100,close:118,volume:100},{date:dates(12),open:110,high:119,low:100,close:115,volume:100}])},
{name:'locked-target',bars:flat.map((b,i)=>i===0?{...b,high:120}:i===10?{...b,high:115}:b)}];
const ctx=vm.createContext({cases});
vm.runInContext(code+`
var OSC_STOP_PCT=.07,OSC_STOP_PCT_TEST4=.12,window={},currentPeriod='day',currentStrategy,klineData,hhv10,llv10;
this.results=cases.map(c=>{
klineData=c.bars;hhv10=calcHHV(klineData,10,'high');llv10=calcLLV(klineData,10,'low');
const kinds=['osc-test','osc-test2','osc-test3','osc-test4'];
const opts=[{useStop:true},{useStop:true,targetExit:true},{useStop:true,maGate:true},{useStop:true,confirmExit:true,stopPct:.12}];
return {...c,ideal:localXichouLagaoBacktestIdeal(),experiments:kinds.map((kind,i)=>{currentStrategy=kind;return {kind,markers:_computeAllSignals(klineData),ordinary:runOscBacktest(klineData,hhv10,llv10,'day',opts[i])}})};
});`,ctx,{timeout:5000});
fs.writeFileSync(destination,JSON.stringify({source_version:'3.3.79',source_sha256:sha,provenance:'Constructed OHLC witnesses; direct bounded public-source execution, not market evidence.',cases:ctx.results},null,2)+'\n');
console.log(`wrote ${ctx.results.length} oracle cases`);
