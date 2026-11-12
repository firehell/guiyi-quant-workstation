import { buildNewowFixtureEnvelopeForTest } from '../newow-product.helpers.mjs'

// Reuse the ordinary chart's exact times and physical ownership for both packets.
const bars = buildNewowFixtureEnvelopeForTest('chart').chart.value.bars
const sha256 = 'a'.repeat(64)

export async function installDetailExperimentSessionFixtures(page, options={}) {
  const experiments = []
  await page.route('**/api/v1/market/newow/experiments?**', route => {
    const query = Object.fromEntries(new URL(route.request().url()).searchParams)
    experiments.push(query)
    const isTrueup=query.kind==='osc-test5'
    const formula_version = isTrueup?'newow_oscillation_trueup_kernel111_v1':`newow_${query.kind.replace('-', '_')}_page_v3379_v1`
    const dates = bars.map(bar => bar.bar_end)
    const trade = { segment_id:'exp',physical_contract:'RB2605',entry_bar_end:dates[0],exit_bar_end:dates.at(-1),entry_reference_price:'100',exit_reference_price:'101',return_percentage_points:'1',force_close:false,stop_loss:false,confirm_exit:false }
    const model = ideal => ({ model_version:isTrueup?(ideal?'newow_trueup_posterior_peak_v1':'newow_trueup_reference_zero_cost_v1'):(ideal?'newow_base_oscillation_ideal_v3379_v1':'newow_oscillation_experiment_ordinary_v3379_v1'),hindsight:ideal,page_parity:!isTrueup,...(isTrueup?{kernel_parity:true,return_policy:'guiyi_unified_trueup'}:{}),executable:false,dates,equity:dates.map((_,index)=>index===dates.length-1?'1':'0'),total_count:1,summary:{trade_count:1,cum_return_percentage_points:'1',accuracy_pct:'100',max_drawdown_percentage_points:'0'},trades:[trade] })
    const profile_id=isTrueup?'newow_experiment_trueup_v1':'guiyi_newow_experiment_completed_physical_v1',input_policy_version='policy'
    return route.fulfill({json:{...query,schema_version:'newow_experiment_detail_v3',input_snapshot_hash:sha256,profile_id,input_policy_version,formula_version,page_parity:!isTrueup,...(isTrueup?{kernel_parity:true,return_policy:'guiyi_unified_trueup'}:{}),executable:false,
      meta:{identity:{product:query.product,frequency:query.frequency,kind:query.kind,strategy:query.kind,series_kind:'actual_dominant',as_of:query.as_of,formula_version,profile_id,input_policy_version},as_of:query.as_of,read_at:query.as_of,input_content_sha256:sha256,data_revision_identity:'b'.repeat(64),snapshot_token:'test-token',result_hash:'c'.repeat(64),completed_only:true,executable:false,auto_order:false,last_completed_bar_end:dates.at(-1),last_trading_day:bars.at(-1).trading_day},
      window:{since:bars[0].trading_day,through:bars.at(-1).trading_day},readiness:{status:'READY',reason_code:null},
      breakout_events:isTrueup?options.breakoutEvents?.(bars.map(bar=>({...bar,segment_id:'exp'})),query.frequency)??[]:[],bars:bars.map(bar=>({...bar,segment_id:'exp',channel_high:'120',channel_low:'90'})),markers:[],segments:[{segment_id:'exp',physical_contract:'RB2605',status:'CURRENT',ordinary:model(false),theoretical:model(true)}]}})
  })
  return {experiments}
}
