const {chromium,expect}=require('../../apps/quant-web/node_modules/@playwright/test');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.goto('http://127.0.0.1:5174/market/chart?symbol=au&view=newow&strategy=trend&frequency=1d&series_kind=actual_dominant');
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state','ready',{timeout:120000});
  const response=page.waitForResponse(r=>r.url().includes('component=zhaoyao_mirror'));
  await page.getByRole('button',{name:'照妖镜',exact:true}).click();
  const r=await response;expect(r.status()).toBe(200);const b=await r.json();
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-auxiliary-state','ready');
  await page.getByTestId('newow-product-chart-stage').scrollIntoViewIfNeeded();
  await page.screenshot({path:'.run/single-worker/browser-auxiliary-current.png'});
  fs.writeFileSync('.run/single-worker/auxiliary-current.json',JSON.stringify({params:Object.fromEntries(new URL(r.url()).searchParams),meta:b.meta,status:b.auxiliary.status,segments:b.auxiliary.value.segments.map(s=>({contract:s.physical_contract,bars:s.bar_ends.length,first:s.bar_ends[0],last:s.bar_ends.at(-1),keys:Object.keys(s.data)}))},null,2));
  console.log('current auxiliary ready, screenshot captured');
 }finally{await browser.close()}
})().catch(e=>{console.error(e.message);process.exit(1)});
