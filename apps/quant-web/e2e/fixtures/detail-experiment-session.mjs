import { buildNewowFixtureEnvelopeForTest, NEWOW_AS_OF } from '../newow-product.helpers.mjs'

// Reuse the ordinary chart's exact times and physical ownership for both packets.
const bars = buildNewowFixtureEnvelopeForTest('chart').chart.value.bars
const sha256 = 'a'.repeat(64)

export async function installDetailExperimentSessionFixtures(page) {
  const experiments = [], futures = []
  await page.route('**/api/v1/market/newow/experiments?**', route => {
    const query = Object.fromEntries(new URL(route.request().url()).searchParams)
    experiments.push(query)
    const formula_version = `newow_${query.kind.replace('-', '_')}_page_v3379_v1`
    const dates = bars.map(bar => bar.bar_end)
    const trade = { segment_id:'exp',physical_contract:'RB2605',entry_bar_end:dates[0],exit_bar_end:dates.at(-1),entry_reference_price:'100',exit_reference_price:'101',return_percentage_points:'1',force_close:false,stop_loss:false,confirm_exit:false }
    const model = ideal => ({ model_version:ideal?'newow_base_oscillation_ideal_v3379_v1':'newow_oscillation_experiment_ordinary_v3379_v1',hindsight:ideal,page_parity:true,executable:false,dates,equity:dates.map((_,index)=>index===dates.length-1?'1':'0'),total_count:1,summary:{trade_count:1,cum_return_percentage_points:'1',accuracy_pct:'100',max_drawdown_percentage_points:'0'},trades:[trade] })
    const profile_id='guiyi_newow_experiment_completed_physical_v1',input_policy_version='policy'
    return route.fulfill({json:{...query,schema_version:'newow_experiment_detail_v2',input_snapshot_hash:sha256,profile_id,input_policy_version,formula_version,page_parity:true,executable:false,
      meta:{identity:{product:query.product,frequency:query.frequency,kind:query.kind,strategy:query.kind,series_kind:'actual_dominant',as_of:query.as_of,formula_version,profile_id,input_policy_version},as_of:query.as_of,read_at:query.as_of,input_content_sha256:sha256,data_revision_identity:'b'.repeat(64),snapshot_token:'test-token',result_hash:'c'.repeat(64),completed_only:true,executable:false,auto_order:false,last_completed_bar_end:dates.at(-1),last_trading_day:bars.at(-1).trading_day},
      window:{since:bars[0].trading_day,through:bars.at(-1).trading_day},readiness:{status:'READY',reason_code:null},
      bars:bars.map(bar=>({...bar,segment_id:'exp',channel_high:'120',channel_low:'90'})),markers:[],segments:[{segment_id:'exp',physical_contract:'RB2605',status:'CURRENT',ordinary:model(false),theoretical:model(true)}]}})
  })
  await page.route('**/api/v1/research/newow-futures/**', route => {
    const url = new URL(route.request().url())
    futures.push(url)
    const strategy=url.searchParams.get('strategy')??'trend',frequency=url.searchParams.get('frequency')??'1d',product=url.searchParams.get('product')??'rb'
    const run_id=`${product}-${strategy}-${frequency}`
    if(url.pathname.endsWith('/snapshot')) return route.fulfill({json:{schema_version:1,run_id,sha256,
      metadata:{run_id,strategy_model:'futures_bidir_v1',strategy,product:product.toUpperCase(),frequency,scenario:'baseline',as_of:NEWOW_AS_OF,status:'COMPLETED',input_snapshot_hash:'b'.repeat(64),execution_facts_hash:'c'.repeat(64),profile_id:`newow_futures_${strategy}_${frequency}_100k_v1`,auto_order:false,source:'historical_replay'},
      summary:{status:'COMPLETED',initial_cash:'100000.00',final_equity:'101000.00',account_return_pct:'1.00',max_drawdown_pct:'0.50',total_fees:'50.00',ending_qty:0},
      reference:{summary:{status:'COMPLETED',closed_trades:0,reference_return_pct:'0',executable:false},snapshot:{side:'FLAT',reason:'HOLD'},actions:[],trades:[],equity:[]},
      chart:{bars:bars.map(bar=>({...bar,owner_segment_id:bar.segment_id,volume:String(bar.volume)})),frames:[]},diagnostics:{rejections:[]}}})
    const run=decodeURIComponent(url.pathname.split('/').at(-2))
    if(url.pathname.endsWith('/equity-curve')) {const kind=url.searchParams.get('kind');return route.fulfill({json:{run_id:run,sha256,kind,status:'COMPLETED',sampled:true,total_points:2,points:[{at:bars[0].bar_end,value:kind==='equity'?'100000':'0'},{at:bars.at(-1).bar_end,value:kind==='equity'?'101000':'1'}]}})}
    return route.fulfill({json:{run_id:run,sha256,part:url.pathname.split('/').at(-1),items:[],offset:0,total:0,limit:50,next_offset:null}})
  })
  return {experiments,futures}
}
