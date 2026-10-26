import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeCautionDisplay, cautionDisplayTitle } from '../src/utils/newowCautionDisplay.ts'
const event = () => ({event_id:'a'.repeat(64), frequency:'1d',bar_end:'2026-10-20T07:00:00Z',peak_day:'2026-10-21',peak_bar_end:'2026-10-21T07:00:00Z',first_visible_at:'2026-10-20T07:00:00Z',confirmed_at:null,as_of:'2026-10-21T07:00:00Z',tentative:true,display_state:'tentative',age_bars:1,home_visible:true,detail_visible:true,max_tentative_age_bars:10,visibility_basis:'completed_bar',display_policy_version:'guiyi_caution_completed_anchor_v1',physical_contract:'RB2701',segment_id:'s',calculation_segment_id:'c',formula_version:'newow_zhaoyao_mirror_repainting_page_v2',repainting:true,page_parity:false,executable:false})
test('fixed event and moving peak have independent dates and explicit certainty', () => {
  const e=normalizeCautionDisplay(event());assert.notEqual(e.bar_end,e.peak_bar_end);assert.match(cautionDisplayTitle(e),/首次/);assert.match(cautionDisplayTitle(e),/暂定/);assert.doesNotMatch(cautionDisplayTitle(e),/已确认|不会撤回/)
})
test('missing policy, contradictory certainty, future peak, wrong window and expiry fail closed', () => {
  for(const patch of [{display_policy_version:undefined},{confirmed_at:'2026-10-21T07:00:00Z'},{peak_bar_end:'2026-10-22T07:00:00Z'},{home_visible:false},{age_bars:11,home_visible:false},{tentative:undefined},{display_state:'confirmed'}])assert.throws(()=>normalizeCautionDisplay({...event(),...patch}))
})
