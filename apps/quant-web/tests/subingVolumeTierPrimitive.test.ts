import test from 'node:test'
import assert from 'node:assert/strict'
import { SubingVolumeTierPrimitive, SUBING_VOLUME_TIER_COLORS } from '../src/components/kline/subingVolumeTierPrimitive.ts'
function fixture(){
 let offset=0,updates=0
 const drawn:any[]=[],context:any={save(){},restore(){},beginPath(){},rect(){},clip(){},closePath(){},arc(...v:any[]){drawn.push(['circle',...v])},moveTo(...v:any[]){drawn.push(['move',...v])},lineTo(...v:any[]){drawn.push(['line',...v])},fill(){drawn.push(['fill',context.fillStyle])}}
 const primitive=new SubingVolumeTierPrimitive()
 primitive.attached({chart:{timeScale:()=>({options:()=>({barSpacing:6}),timeToCoordinate:(t:number)=>t+offset})},series:{priceToCoordinate:(value:number)=>180-value/10},requestUpdate(){updates++}} as any)
 const render=()=>primitive.paneViews()[0]!.renderer()!.draw({useMediaCoordinateSpace(fn:any){fn({context,mediaSize:{width:200,height:200}})}} as any)
 return {primitive,render,drawn,offset:(v:number)=>{offset=v},updates:()=>updates}
}
test('tier two is a blue circle and tier three a purple diamond above the native volume top',()=>{
 const f=fixture();f.primitive.setData([{time:20 as any,volume:100,tier:2},{time:40 as any,volume:300,tier:3}]);f.render()
 assert.deepEqual(f.drawn.find(v=>v[0]==='circle').slice(1,4),[20,164.5,2.5])
 assert.deepEqual(f.drawn.filter(v=>v[0]==='fill').map(v=>v[1]),[SUBING_VOLUME_TIER_COLORS.light[2],SUBING_VOLUME_TIER_COLORS.light[3]])
 assert.equal(f.drawn.filter(v=>v[0]==='line').length,3)
 assert.ok(f.drawn.find(v=>v[0]==='move'&&v[1]===40))
})
test('marks follow native scrolling and theme; offscreen and detached marks are not drawn',()=>{
 const f=fixture();f.primitive.setData([{time:20 as any,volume:100,tier:2}],'dark');f.offset(10);f.render()
 assert.equal(f.drawn[0][1],30);assert.equal(f.drawn.at(-1)[1],SUBING_VOLUME_TIER_COLORS.dark[2])
 f.drawn.length=0;f.offset(-100);f.render();assert.equal(f.drawn.length,0)
 f.offset(0);f.primitive.detached();f.render();assert.equal(f.drawn.length,0)
 f.primitive.setData([]);assert.equal(f.updates(),1)
})
