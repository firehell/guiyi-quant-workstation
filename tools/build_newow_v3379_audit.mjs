// Run from repository root with the separately retained inspected public source directory.
// Only selected declarations run in a bounded VM; no page, DOM, network or storage runs.
import fs from 'node:fs';
import crypto from 'node:crypto';
import vm from 'node:vm';
import ts from '../apps/quant-web/node_modules/typescript/lib/typescript.js';

const root = process.argv[2];
const destination = process.argv[3];
if (!root || !destination) throw Error('source directory and output JSON required');
const sha = s => crypto.createHash('sha256').update(s).digest('hex');
const expected = {
  'detail.html': '3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d',
  'strategy-calc.js': 'a91f3a7685e0dadb95927229c45b7ecffeee052d1269b79207ccb9fa08612a9e',
  'composite-decision-v2.js': '522bb42dca07758741b0c9fb25f666c0ae5e79f070c25c32ecc1d08200ff06b2',
  'trend-reversal-core.js': '85a72b64ca9b9a84ee04338cfffeb28b67dfae923699498a80eb71a22faf6f80',
};
const sources = Object.fromEntries(Object.entries(expected).map(([name, digest]) => {
  const value = fs.readFileSync(`${root}/${name}`, 'utf8');
  if (sha(value) !== digest) throw Error(`source identity mismatch: ${name}`);
  return [name, value];
}));
const names = ['calcMAFrom', 'calcEMAFrom', 'calcVolumeMA', 'calcYellowBlueBand', 'calcMainRiseBand',
  'runOscBacktest', 'runTrendBacktest', '_computeAllSignals', '_isOscFamily', '_isOscTest',
  '_isOscTargetExit', '_isOscMaGate', '_isOscConfirmExit', '_oscStopPct',
  'localXichouLagaoBacktestIdeal', 'localHuangLantaiBacktestIdeal',
  'localZhushenglangBacktestIdeal', 'filterBacktestByDate', 'calcHHV', 'calcLLV',
  '_groupFusionByBar', 'runDualFusionBacktest', 'runDualFusionBacktestIdeal'];
const declarations = names.map(name => {
  const source = sources[name === 'calcHHV' || name === 'calcLLV' ? 'strategy-calc.js' : 'detail.html'];
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw Error(`missing declaration ${name}`);
  const ast = ts.createSourceFile('public.js', source.slice(start), ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const declaration = ast.statements[0];
  if (!ts.isFunctionDeclaration(declaration) || declaration.name.text !== name) throw Error(name);
  return declaration.getText(ast);
});
const old = JSON.parse(fs.readFileSync('services/quant-api/tests/newow/fixtures/ai-analysis-public-oracle.json'));
const date = i => new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10);
const normal = old.cases.map((c, j) => ({name: `retained-input-${j}`, provenance: 'retained OHLC fixture; constructed sequential dates and volume=100; not fresh market evidence',
  bars: c.bars.map((b, i) => ({...b, date: date(i), volume: 100}))}));
const wave = Array.from({length: 150}, (_, i) => {
  const close = i < 35 ? 100 : +(100 + 25 * Math.sin((i - 35) / 9)).toFixed(5);
  return {date: date(i), open: close, high: close + 2, low: close - 2, close, volume: 100};
});
const preEntry = Array.from({length: 11}, (_, i) => ({date: date(i), open: 100,
  high: i === 0 ? 200 : i === 10 ? 199 : 105, low: i === 9 ? 90 : 95, close: 100, volume: 100}));
const cases = [...normal, {name: 'main-rise-theory-entry', provenance: 'constructed boundary witness, not market evidence', bars: wave},
  {name: 'oscillation-pre-entry-high', provenance: 'constructed boundary witness, not market evidence', bars: preEntry}];
const context = vm.createContext({cases});
vm.runInContext(declarations.join('\n') + `
  var OSC_STOP_PCT = 0.07;
  var window = {}, currentStrategy = 'xichou-lagao', currentPeriod = 'day';
  var klineData, hhv10, llv10, ybBand, mainRiseBand;
  this.results = cases.map(c => {
    klineData = c.bars; hhv10 = calcHHV(klineData,10,'high'); llv10 = calcLLV(klineData,10,'low');
    ybBand = calcYellowBlueBand(klineData); mainRiseBand = calcMainRiseBand(klineData);
    currentStrategy = 'xichou-lagao';
    const chart = _computeAllSignals(klineData).map(s => ({date:s.date,type:s.type,price:s.price}));
    const ordinary = {oscillation:runOscBacktest(klineData,hhv10,llv10,'day'),trend:runTrendBacktest(klineData,ybBand,'day')};
    const ideal = {oscillation:localXichouLagaoBacktestIdeal(),trend:localHuangLantaiBacktestIdeal(),main_rise:localZhushenglangBacktestIdeal()};
    const tests = [{useStop:true},{useStop:true,targetExit:true},{useStop:true,maGate:true},{useStop:true,confirmExit:true,stopPct:.12}]
      .map(opts => runOscBacktest(klineData,hhv10,llv10,'day',opts)?.summary ?? null);
    return {...c,chart,ordinary,ideal,tests,
      trend:{states:ybBand.states,a:ybBand.a,b:ybBand.b,signals:ybBand.signals},
      main_rise:{states:mainRiseBand.states,ma35:mainRiseBand.ma35,ma45:mainRiseBand.ma45,signals:mainRiseBand.signals}};
  });
  this.windowWitness = filterBacktestByDate({period:'day',dates:['2025-01-01','2025-01-02','2025-01-03'],equity:[0,5,10],
    trades:[{buyDate:'2025-01-01',sellDate:'2025-01-03',buyPrice:100,sellPrice:110,pct:10}]},'2025-01-02');
  const fusionBars = [{date:'2026-01-05',open:100,high:110,low:90,close:100},
    {date:'2026-01-06',open:110,high:121,low:99,close:110}];
  const fusionEntry = {date:'2026-01-05',index:0,type:'buy',price:100};
  const fusionExit = {date:'2026-01-06',index:1,type:'sell',price:110};
  this.fusionWitness = {bars:fusionBars,signals:[fusionEntry,fusionExit],
    ordinary:runDualFusionBacktest(fusionBars,[fusionEntry,fusionExit],'day'),
    ideal:runDualFusionBacktestIdeal(fusionBars,[fusionEntry,fusionExit],'day'),
    terminal:runDualFusionBacktest(fusionBars,[fusionEntry],'day')};
`, context, {timeout: 5000});
// The inspected CDV2 module is a pure window export; run without DOM, I/O or timers.
const cdvContext = vm.createContext({window: {}});
vm.runInContext(sources['composite-decision-v2.js'], cdvContext, {timeout: 5000});
vm.runInContext(`
  const states = ['hold','wait',null];
  this.cdvCases = [];
  for (const tw of states) for (const td of states) for (const th of states)
  for (const ow of states) for (const od of states) for (const oh of states) {
    const inputs = {batchSignals:{signal_weekly:tw,signal_daily:td},
      trendTf:{m60:{status:th}},oscTf:{week:{status:ow},day:{status:od},m60:{status:oh}},
      now:new Date('2025-01-03T16:00:00Z')};
    const r = window.CDV2.compute(inputs);
    this.cdvCases.push({trend:{week:tw,day:td,m60:th},oscillation:{week:ow,day:od,m60:oh},
      expected:{action_code:r.actionCode,mismatch:r.mismatchType,resonance:r.resonanceLevel,
        total:r.certTotal,scores:{trend:r.certTrend,oscillation:r.certOsc,resonance:r.certResonance,
          direction:r.certDir,volatility:r.certVolatility},cert_extra:r.certExtra,
        reference_exposure_cap:r.posCap,certainty_cap:r._debug.certCap,resonance_cap:r._debug.resCap,
        bearish_gated:r._debug.gated},period_conflict:r.periodConflict});
  }
`, cdvContext, {timeout: 5000});
fs.writeFileSync(destination, JSON.stringify({source_version:'3.3.79', source_url:'https://www.v8848.cn/stock_detail.html?code=601958.SH&period=week&strategy=huanglantai',
  source_sha256:expected, extracted_declarations_sha256:sha(declarations.join('\n')), cases:context.results,
  window_witness:context.windowWitness,fusion_witness:context.fusionWitness,cdv2_cases:cdvContext.cdvCases}) + '\n');
console.log(JSON.stringify({cases:context.results.length, source_sha256:expected, output:destination}));
