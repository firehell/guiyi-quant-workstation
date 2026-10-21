import assert from 'node:assert/strict'
import test from 'node:test'
import { parseMarketDetailRoute, serializeMarketDetailIdentity, resolveViewSwitchIdentity } from '../src/utils/marketDetailRoute.ts'
import { futuresVariant, switchFuturesModel, originalNewowCombinationSupported } from '../src/utils/newowFutures.ts'
const base = { view:'newow', symbol:'jm', strategy:'main_rise', series_kind:'actual_dominant', frequency:'5m' }
test('futures route roundtrip and switch off preserve unsupported original period without enabling it', () => {
  const parsed = parseMarketDetailRoute({...base,strategy_model:'futures_bidir_v1'})
  assert.equal(parsed.kind,'valid'); if(parsed.kind!=='valid')return
  assert.equal(parsed.identity.strategyModel,'futures_bidir_v1')
  assert.equal(futuresVariant(parsed.identity),'main_rise')
  const original=switchFuturesModel(parsed.identity,false)
  assert.equal(original.frequency,'5m'); assert.equal(originalNewowCombinationSupported(original),false)
  assert.equal(parseMarketDetailRoute(serializeMarketDetailIdentity(original)).kind,'valid')
  assert.deepEqual(parseMarketDetailRoute(serializeMarketDetailIdentity(parsed.identity)),parsed)
})
test('test and dual variants survive refresh, product and view switches', () => {
  for(const newow_test of ['osc-test','osc-test2','osc-test3','osc-test4']) {
    const result=parseMarketDetailRoute({...base,strategy:'oscillation',newow_test,strategy_model:'futures_bidir_v1'})
    assert.equal(result.kind,'valid');if(result.kind!=='valid')continue
    assert.equal(futuresVariant(result.identity),newow_test)
    assert.deepEqual(parseMarketDetailRoute(serializeMarketDetailIdentity({...result.identity,symbol:'rb'})),{kind:'valid',identity:{...result.identity,symbol:'rb'}})
    const restored=resolveViewSwitchIdentity('newow','jm',result.identity,{newow:{strategy:'trend',frequency:'1d'}} as any)
    assert.equal(restored.newowTest,newow_test);assert.equal(restored.strategyModel,'futures_bidir_v1')
  }
  const dual=parseMarketDetailRoute({...base,strategy:'trend',newow_mode:'dual',strategy_model:'futures_bidir_v1'})
  assert.equal(dual.kind,'valid');if(dual.kind==='valid')assert.equal(futuresVariant(dual.identity),'dual_fusion')
})
test('old URLs stay original and malformed model/variant identities fail closed',()=>{
  const old=parseMarketDetailRoute({...base,strategy:'trend'})
  assert.equal(old.kind,'valid');if(old.kind==='valid')assert.equal(old.identity.strategyModel,undefined)
  for(const query of [{...base,strategy_model:'unknown'},{...base,view:'free',strategy_model:'futures_bidir_v1'},{...base,series_kind:'contract',contract:'JM2601',strategy_model:'futures_bidir_v1'},{...base,newow_test:'osc-test'},{...base,frequency:'1m',strategy_model:'futures_bidir_v1'}])assert.equal(parseMarketDetailRoute(query).kind,'invalid')
})
