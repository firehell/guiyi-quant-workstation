import assert from 'node:assert/strict'
import test from 'node:test'
import { visualDonchian, visibleBuildStop, readVisualOverlayPreferences, saveVisualOverlayPreferences } from '../src/utils/newowVisualOverlays.ts'
test('display channel is independently configurable and never spans an owner segment',()=>{
 const bars=Array.from({length:25},(_,i)=>({time:String(i),high:i+10,low:i,owner:i<22?'old':'new'}))
 const twenty=visualDonchian(bars,20),five=visualDonchian(bars,5)
 assert.equal(twenty[18]!.upper,null);assert.deepEqual(twenty[19],{time:'19',upper:29,lower:0})
 assert.equal(five[19]!.lower,15);assert.equal(twenty[22]!.upper,null)
 assert.deepEqual(visualDonchian(bars,4),[]);assert.deepEqual(visualDonchian(bars,121),[])
 assert.equal(bars[0]!.high,10)
})
test('stop anchors are visible owner BUILD references, CLEAR never becomes an entry, invalid values clear',()=>{
 const visible=[{time:'2026-01-01',owner:'a'},{time:'2026-01-02',owner:'a'}]
 const anchors=[{...visible[0]!,price:'100',action:'BUILD'},{...visible[1]!,price:'180',action:'CLEAR'}]
 assert.equal(visibleBuildStop(anchors,visible,0.07),93);assert.equal(visibleBuildStop(anchors,visible,0.12),88)
 assert.equal(visibleBuildStop(anchors,visible.slice(1),0.07),null)
 assert.equal(visibleBuildStop(anchors,[{time:'2026-01-03',owner:'b'}],0.07),null)
 assert.equal(visibleBuildStop([{...anchors[0]!,price:'NaN'}],visible,0.07),null)
})
test('overlay preferences default off and persist independently from business inputs',()=>{
 const original=Object.getOwnPropertyDescriptor(globalThis,'localStorage');const store=new Map<string,string>()
 Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(key:string)=>store.get(key)??null,setItem:(key:string,value:string)=>store.set(key,value)}})
 try{assert.deepEqual(readVisualOverlayPreferences(),{donchian:false,window:20,stop:false});saveVisualOverlayPreferences({donchian:true,window:120,stop:true});assert.deepEqual(readVisualOverlayPreferences(),{donchian:true,window:120,stop:true});store.set([...store.keys()][0]!,'{"window":121}');assert.equal(readVisualOverlayPreferences().window,20)}finally{if(original)Object.defineProperty(globalThis,'localStorage',original);else Reflect.deleteProperty(globalThis,'localStorage')}
})
