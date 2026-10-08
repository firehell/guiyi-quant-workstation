// Frozen public functions only. This tool never reads Catalog/DB or market files.
// Usage: node tools/newow_v3379_market_oracle.mjs PUBLIC_SOURCE INPUT.json OUTPUT.json
import fs from 'node:fs';
import crypto from 'node:crypto';
import vm from 'node:vm';
import ts from '../apps/quant-web/node_modules/typescript/lib/typescript.js';

const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const SOURCE = {
  'detail.html': '3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d',
  'strategy-calc.js': 'a91f3a7685e0dadb95927229c45b7ecffeee052d1269b79207ccb9fa08612a9e',
  'composite-decision-v2.js': '522bb42dca07758741b0c9fb25f666c0ae5e79f070c25c32ecc1d08200ff06b2',
  'trend-reversal-core.js': '85a72b64ca9b9a84ee04338cfffeb28b67dfae923699498a80eb71a22faf6f80',
};
const NAMES = ['calcMAFrom', 'calcEMAFrom', 'calcVolumeMA', 'calcYellowBlueBand', 'calcMainRiseBand',
  'runOscBacktest', 'runTrendBacktest', '_computeAllSignals', '_isOscFamily', '_isOscTest',
  '_isOscTargetExit', '_isOscMaGate', '_isOscConfirmExit', '_oscStopPct',
  'localXichouLagaoBacktestIdeal', 'localHuangLantaiBacktestIdeal',
  'localZhushenglangBacktest', 'localZhushenglangBacktestIdeal', 'filterBacktestByDate',
  'calcHHV', 'calcLLV', '_groupFusionByBar', 'runDualFusionBacktest', 'runDualFusionBacktestIdeal'];
const PERIODS = { '5m': '5min', '15m': '15min', '30m': '30min', '60m': '60min', '1d': 'day', '1w': 'week' };

function declarationsAt(sourceRoot) {
  const sources = Object.fromEntries(Object.entries(SOURCE).map(([name, digest]) => {
    const value = fs.readFileSync(`${sourceRoot}/${name}`, 'utf8');
    if (sha(value) !== digest) throw Error(`NEWOW_ORACLE_SOURCE_IDENTITY_MISMATCH:${name}`);
    return [name, value];
  }));
  return NAMES.map(name => {
    const source = sources[name === 'calcHHV' || name === 'calcLLV' ? 'strategy-calc.js' : 'detail.html'];
    const start = source.indexOf(`function ${name}(`);
    if (start < 0) throw Error(`NEWOW_ORACLE_DECLARATION_MISSING:${name}`);
    const ast = ts.createSourceFile('public.js', source.slice(start), ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
    const declaration = ast.statements[0];
    if (!ts.isFunctionDeclaration(declaration) || declaration.name.text !== name) throw Error('NEWOW_ORACLE_AST_INVALID');
    return declaration.getText(ast);
  }).join('\n');
}

function positive(value) {
  if ((typeof value !== 'number' && typeof value !== 'string') || (typeof value === 'string' && !value.trim())) {
    throw Error('NEWOW_ORACLE_INPUT_INVALID');
  }
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw Error('NEWOW_ORACLE_INPUT_INVALID');
  return number;
}

function prepare(input) {
  const period = PERIODS[input.frequency] ?? input.period;
  if (!Object.values(PERIODS).includes(period) || !Array.isArray(input.segments) || input.segments.length > 1000) {
    throw Error('NEWOW_ORACLE_INPUT_INVALID');
  }
  const owners = new Set();
  let count = 0;
  const segments = input.segments.map(segment => {
    if (!segment || typeof segment.owner !== 'string' || !segment.owner || owners.has(segment.owner) ||
        typeof segment.terminal_eligible !== 'boolean' || !Array.isArray(segment.bars)) throw Error('NEWOW_ORACLE_INPUT_INVALID');
    owners.add(segment.owner);
    let previous = null, eligibleSeen = false;
    const bars = segment.bars.map(bar => {
      if (!bar || typeof bar.date !== 'string' || !bar.date || (previous !== null && bar.date <= previous) ||
          typeof bar.trading_day !== 'string' || !bar.trading_day || typeof bar.observation_eligible !== 'boolean' ||
          (eligibleSeen && !bar.observation_eligible)) throw Error('NEWOW_ORACLE_INPUT_INVALID');
      previous = bar.date;
      eligibleSeen ||= bar.observation_eligible;
      const high = positive(bar.high), low = positive(bar.low), close = positive(bar.close);
      if (low > close || close > high) throw Error('NEWOW_ORACLE_INPUT_INVALID');
      const open = bar.open === undefined ? close : positive(bar.open);
      if (open < low || open > high) throw Error('NEWOW_ORACLE_INPUT_INVALID');
      const volume = bar.volume === undefined ? 0 : Number(bar.volume);
      if (!Number.isFinite(volume) || volume < 0) throw Error('NEWOW_ORACLE_INPUT_INVALID');
      if (++count > 2_000_000) throw Error('NEWOW_ORACLE_INPUT_BUDGET_EXCEEDED');
      return { ...bar, open, high, low, close, volume };
    });
    return { ...segment, bars };
  });
  return { period, segments };
}

const EXECUTE = `
  var OSC_STOP_PCT = 0.07;
  var window = {}, currentStrategy = 'xichou-lagao', currentPeriod = period;
  var klineData = segment.bars;
  var hhv10 = calcHHV(klineData,10,'high'), llv10 = calcLLV(klineData,10,'low');
  var ybBand = calcYellowBlueBand(klineData), mainRiseBand = calcMainRiseBand(klineData);
  // Independently regenerate public chart signals. No API actions/trades enter this VM.
  var oscillation = _computeAllSignals(klineData);
  var trend = ybBand.signals.map(s => ({index:s.index,date:klineData[s.index].date,type:s.type,price:s.price,st:'trend'}));
  var fusion = oscillation.map(s => ({...s,st:'osc'})).concat(trend);
  this.result = {
    ordinary: {trend:runTrendBacktest(klineData,ybBand,currentPeriod),
      oscillation:runOscBacktest(klineData,hhv10,llv10,currentPeriod),
      main_rise:localZhushenglangBacktest(),fusion:runDualFusionBacktest(klineData,fusion,currentPeriod)},
    ideal: {trend:localHuangLantaiBacktestIdeal(),oscillation:localXichouLagaoBacktestIdeal(),
      main_rise:localZhushenglangBacktestIdeal(),fusion:runDualFusionBacktestIdeal(klineData,fusion,currentPeriod)},
    chart: {oscillation,trend:ybBand,main_rise:mainRiseBand,fusion}
  };
`;

export function runMarketOracle(sourceRoot, inputBytes) {
  if (inputBytes.length > 256_000_000) throw Error('NEWOW_ORACLE_INPUT_BUDGET_EXCEEDED');
  const input = JSON.parse(inputBytes.toString('utf8'));
  const declarations = declarationsAt(sourceRoot);
  const { period, segments } = prepare(input);
  const result = segments.map(segment => {
    // Fresh VM per physical/calculation owner: no state crosses an owner or gap.
    const context = vm.createContext({segment,period}, {codeGeneration:{strings:false,wasm:false}});
    vm.runInContext(declarations + '\n' + EXECUTE, context, {timeout:30_000});
    return {
      owner:segment.owner,physical_contract:segment.physical_contract ?? null,
      calculation_segment_id:segment.calculation_segment_id ?? null,
      bar_count:segment.bars.length,
      adapter_boundary:{terminal_eligible:segment.terminal_eligible,
        warmup_bar_count:segment.bars.filter(b=>!b.observation_eligible).length,
        eligible_bar_count:segment.bars.filter(b=>b.observation_eligible).length,
        raw_source_includes_warmup:true,raw_source_terminal_forceclose:true},
      ...context.result,
    };
  });
  return {schema:'newow_v3379_market_source_raw_v1',source_version:'3.3.79',
    source_sha256:SOURCE,extracted_declarations_sha256:sha(declarations),
    input_bytes_sha256:sha(inputBytes),input_sha256:input.input_sha256 ?? null,
    input_identity:{code_sha:input.code_sha ?? null,product:input.product ?? null,
      frequency:input.frequency ?? null,cutoff:input.cutoff ?? null,
      performance_since:input.performance_since ?? null,performance_through:input.performance_through ?? null,
      source_evidence_sha256:input.source_evidence_sha256 ?? null},
    period,page_parity:true,executable:false,
    semantics:{projection:'raw_public_source_per_owner',futures_aggregate:false,
      warmup:'all physical-prefix bars enter raw source chart and performance',
      terminal:'ordinary source forceClose runs on every raw owner terminal, irrespective of terminal_eligible',
      adapter_comparison_required:['eligible-only actions and curve','genuine input terminal only forceClose',
        'no forceClose across physical/quality boundaries','trading-day window filtering','segment-local drawdown']},
    segments:result};
}

if (process.argv[1]?.endsWith('newow_v3379_market_oracle.mjs')) {
  const [sourceRoot,inputPath,outputPath] = process.argv.slice(2);
  if (!sourceRoot || !inputPath || !outputPath) throw Error('source directory, input JSON and output JSON required');
  const result = runMarketOracle(sourceRoot,fs.readFileSync(inputPath));
  // Exclusive result: rerunning must not overwrite previous acceptance evidence.
  fs.writeFileSync(outputPath,JSON.stringify(result)+'\n',{flag:'wx',mode:0o600});
  console.log(JSON.stringify({output:outputPath,owners:result.segments.length,input_bytes_sha256:result.input_bytes_sha256}));
}
