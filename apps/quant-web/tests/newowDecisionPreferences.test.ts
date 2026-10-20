import test from 'node:test'
import assert from 'node:assert/strict'
import { readNewowBasis, saveNewowBasis, NEWOW_BASIS_KEY } from '../src/utils/newowDecisionPreferences.ts'
test('basis preference rereads storage, rejects invalid values and tolerates denied storage', () => {
 const descriptor=Object.getOwnPropertyDescriptor(globalThis,'localStorage'), values=new Map<string,string>()
 try {
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>values.set(k,v)}})
  assert.equal(readNewowBasis(),'week'); saveNewowBasis('day'); assert.equal(readNewowBasis(),'day')
  values.set(NEWOW_BASIS_KEY,'week'); assert.equal(readNewowBasis(),'week')
  values.set(NEWOW_BASIS_KEY,'invalid'); assert.equal(readNewowBasis(),'week')
  Object.defineProperty(globalThis,'localStorage',{configurable:true,get(){throw Error('denied')}})
  assert.equal(readNewowBasis(),'week'); assert.doesNotThrow(()=>saveNewowBasis('day'))
 } finally { if(descriptor)Object.defineProperty(globalThis,'localStorage',descriptor);else Reflect.deleteProperty(globalThis,'localStorage') }
})
