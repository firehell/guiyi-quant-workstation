const bar = (p, volume=100) => ({high:p+1,low:p-1,close:p,volume})
export const flat = (n, volumeStep=1) => Array.from({length:n},(_,i)=>bar(100,200-i*volumeStep))
export const cup = flat(70).map((b,i)=> ({...b,high:i<22?80+i:i===22?110:i<40?108:i<60?105:104,low:i<22?75+i:i===22?108:i<40?103-(i-23)*.35:i===40?97:i<60?98+(i-40)*.3:96,close:100}))
export const cases = [
 {name:'constant declining volume',bars:flat(60)},
 {name:'cup and saucer',bars:cup},
 {name:'ascending three bases',bars:Array.from({length:110},(_,i)=>bar(100+i*.25))},
 {name:'double bottom',bars:Array.from({length:65},(_,i)=>bar(i===26||i===46?90:110))},
 ...[0,11,12,14,15,16,19,20,21,24,25,29,30,34,35,40,41,44,45].map(n=>({name:`length ${n}`,bars:flat(n)})),
 ...[-1,0,1].map(step=>({name:`volume step ${step}`,bars:flat(60,step)})),
 ...[8,12,15,15.00001].map(depth=>({name:`consolidation depth ${depth}`,bars:Array.from({length:61},(_,i)=>({high:100+depth,low:100,close:100+i%2*.5,volume:200-i}))})),
 ...[1.5,2.5,3,3.00001].map(depth=>({name:`tight depth ${depth}`,bars:Array.from({length:31},(_,i)=>({high:105,low:95,close:100+(i%2?1:-1)*depth/2,volume:100}))})),
 ...[8,50,50.00001].map(depth=>({name:`cup depth ${depth}`,bars:cup.map((b,i)=>({...b,low:i===40?110*(1-depth/100):b.low}))})),
]
let seed=123456
for(let sample=0;sample<16;sample++){
 const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/2**32}
 const bars=Array.from({length:35+sample*3},()=>bar(90+random()*25,100+random()*200))
 cases.push({name:`seeded ${sample}`,bars})
}
// No 100-point early exit: exercise cached third-base ordering and ties.
cases.push({name:'gentle ascending without lift bonus',bars:Array.from({length:120},(_,i)=>bar(100+i*.0001))})
cases.push({name:'descending excludes ascending',bars:Array.from({length:120},(_,i)=>bar(100-i*.01))})
