// Public function excerpts; strategy-calc SHA256 f490dcf6e24a60a2e4e0c178d153a4ff58442e3727181a1c449e18dd68491ea0
function clampPriceGuard(value, prevClose) {
  if (value == null || !isFinite(value)) return 0;
  var v = parseFloat(value);
  if (!isFinite(v)) return 0;
  if (!prevClose || prevClose <= 0) {
    // 无昨收基准：仅过滤非正 / NaN / Infinity，保持原值（不误伤正常值）
    return v > 0 ? parseFloat(v.toFixed(2)) : 0;
  }
  var lo = prevClose * 0.5;
  var hi = prevClose * 2;
  var clamped = v < lo ? lo : (v > hi ? hi : v);
  return parseFloat(clamped.toFixed(2));
}

function calcAbsorbPrice(item, currentPrice, period, prevClose) {
  if (!item) return 0;
  // v3.1.6 FIX (Bug B): 读取昨收基准（优先入参，其次 item 自带字段），用于价格护栏
  var _prevClose = prevClose || item.prev_close || item.pre_close || item.yesterday_close || item.preclose || item.prevClose || 0;
  // v2.9.449: 不强制默认'day'
  //   stock_detail.html 显式传 'day'/'week' → 严格模式
  //   index.html 不传 → undefined → 最佳可用模式
  // v2.9.514: 恢复返回 0（非 null），保持下游算术运算安全
  //   前端 fallback 通过 rawCost > 0 判断有效性即可

  var sd = (item.signal_daily || 'wait').toString().toLowerCase();
  var sw = (item.signal_weekly || 'wait').toString().toLowerCase();

  var dayAbove  = !(sd === 'wait' || sd === 'sell');
  var weekAbove = !(sw === 'wait' || sw === 'sell');

  // v2.9.449: 辅助函数 — 判断是否允许周线降级
  function _allowWeekFallback() {
    return period !== 'day';  // 仅严格日线模式阻断
  }

  // v3.3.81 FIX (蓝带吸筹价>现价 止血): 吸筹价(支撑位)语义上必须 <= 现价。
  // 根因：后端 computeHHVLLVFromKlineData 的 LLV10 = min(末10根 low)，含仍在形成的当日 bar low；
  //   盘中 tick 跌破当日 bar 已记录 low 时，cost_daily(LLV10) > 现价（实测 网宿科技 13.52 > 13.50、创业板指 2997.9 > 2992.13），
  //   蓝带显「吸筹价>现价」失真。此处统一收敛到现价（price 已破支撑时显「吸筹价=现价」），
  //   既满足产品规则「蓝带目标价不应>现价」，也恢复 LLV10 的真实下界(随实时价对齐)。
  function _guardSupport(v) {
    if (!v || v <= 0) return v;
    if (currentPrice && currentPrice > 0 && v > currentPrice) {
      return parseFloat(currentPrice.toFixed(2));
    }
    return v;
  }

  var rawCost = 0;
  if (dayAbove && weekAbove) {
    // v3.2.09 FIX: 用户在看周K（period==='week'）时优先返回周线吸筹价
    if (period === 'week' && item.cost_weekly && item.cost_weekly > 0) rawCost = clampPriceGuard(item.cost_weekly, _prevClose);
    // v1.0.8: buy>hold 优先级 — 完全镜像 calcTargetPrice 逻辑
    var isDayBuy  = (sd === 'buy');
    var isWeekBuy = (sw === 'buy');
    if (!rawCost && isDayBuy && item.cost_daily && item.cost_daily > 0) rawCost = clampPriceGuard(item.cost_daily, _prevClose);
    if (!rawCost && isWeekBuy && item.cost_weekly && item.cost_weekly > 0) rawCost = clampPriceGuard(item.cost_weekly, _prevClose);
    if (!rawCost && item.cost_daily  && item.cost_daily  > 0) rawCost = clampPriceGuard(item.cost_daily, _prevClose);
    if (!rawCost && _allowWeekFallback() && item.cost_weekly && item.cost_weekly > 0) rawCost = clampPriceGuard(item.cost_weekly, _prevClose);
  } else if (dayAbove) {
    if (item.cost_daily  && item.cost_daily  > 0) rawCost = clampPriceGuard(item.cost_daily, _prevClose);
    if (!rawCost && _allowWeekFallback() && item.cost_weekly && item.cost_weekly > 0) rawCost = clampPriceGuard(item.cost_weekly, _prevClose);
  } else if (weekAbove) {
    // 日线空仓+周线持股 → 优先日线（更敏感止损位），无日线则用周线
    if (item.cost_daily  && item.cost_daily  > 0) rawCost = clampPriceGuard(item.cost_daily, _prevClose);
    if (!rawCost && item.cost_weekly && item.cost_weekly > 0) rawCost = clampPriceGuard(item.cost_weekly, _prevClose);
  } else {
    // 双空仓
    if (_allowWeekFallback() && item.cost_weekly && item.cost_weekly > 0) rawCost = clampPriceGuard(item.cost_weekly, _prevClose);
    if (!rawCost && item.cost_daily  && item.cost_daily  > 0) rawCost = clampPriceGuard(item.cost_daily, _prevClose);
  }

  if (!rawCost && item.cost && item.cost > 0) rawCost = clampPriceGuard(item.cost, _prevClose);
  return _guardSupport(rawCost);
}


const cases = JSON.parse(require("fs").readFileSync(0,"utf8"));
console.log(JSON.stringify(cases.map(c => calcAbsorbPrice(c.item, c.current, c.period, c.prev))));
