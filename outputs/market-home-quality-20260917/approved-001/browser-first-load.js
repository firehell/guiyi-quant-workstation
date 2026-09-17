async (page) => {
  const results = [];
  for (const symbol of ['pt','ss']) {
    for (const strategy of ['trend','oscillation','main_rise']) {
      const p = await page.context().newPage();
      const responses = [];
      p.on('response', async response => {
        if (response.url().includes('/market/newow/strategy-detail')) {
          try {
            const body = await response.json();
            responses.push({section:new URL(response.url()).searchParams.get('section'), http:response.status(), status:body.status?.status, reason:body.status?.reason_code});
          } catch {}
        }
      });
      await p.goto(`http://127.0.0.1:5194/market/chart?symbol=${symbol}&view=newow&strategy=${strategy}&frequency=1d&series_kind=actual_dominant`);
      await p.locator('[data-detail-workspace="newow"][data-chart-state="ready"]').waitFor({timeout:60000});
      await p.getByRole('button',{name:'参考记录',exact:true}).click();
      await p.getByTestId('newow-reference-summary').waitFor({timeout:60000});
      const summary = await p.getByTestId('newow-reference-summary').innerText();
      await p.screenshot({path:`outputs/market-home-quality-20260917/approved-001/${symbol}-${strategy}-first-load.png`});
      results.push({symbol,strategy,chart:'ready',reference_summary:summary,responses});
      await p.close();
    }
  }
  console.log(JSON.stringify(results));
}
