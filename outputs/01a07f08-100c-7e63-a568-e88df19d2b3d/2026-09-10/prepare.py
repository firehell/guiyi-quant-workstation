from pathlib import Path
base=Path(__file__).resolve().parent.parent
prev=base/'2026-09-09';out=Path(__file__).resolve().parent
s=(prev/'push_review_20260909.py').read_text().replace("OUT=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/01a07f08-100c-7e63-a568-e88df19d2b3d/2026-09-09')","OUT=Path(__file__).resolve().parent")
s=s.replace("source={'cutoff':NOW", "assert not (OUT/'source.json').exists(),'SNAPSHOT_ALREADY_EXISTS'\n source={'cutoff':NOW")
s=s.replace("if history_days:\n      try:bars.extend(md.query_contract_trading_days(ContractTradingDayQuery(symbol=symbol,contract=contract,frequency='1m',since=history_days[0],through=history_days[-1])).bars)\n      except Exception as exc:item['errors'].append({'part':'historical','code':safe(exc)})", "for history_day in history_days:\n      try:bars.extend(md.query_contract_trading_days(ContractTradingDayQuery(symbol=symbol,contract=contract,frequency='1m',since=history_day,through=history_day)).bars)\n      except Exception as exc:item['errors'].append({'part':'historical','day':str(history_day),'code':safe(exc)})")
s=s.replace("ROOT=Path(roots['alert']);", "loaded={}\nfor service in roots:\n r=subprocess.run(['launchctl','print',f'gui/{os.getuid()}/com.guiyi.quant-{service}'],capture_output=True,text=True)\n found=re.search(r'^\\s*GUIYI_PROJECT_ROOT => (.+)$',r.stdout,re.M)\n assert r.returncode==0 and found and found.group(1).strip()==roots[service],'LOADED_RUNTIME_ROOT_MISMATCH'\n loaded[service]={'root':found.group(1).strip(),'running':bool(re.search(r'^\\s*pid = [0-9]+$',r.stdout,re.M))}\nROOT=Path(roots['alert']);")
s=s.replace("'runtime_roots':roots,", "'runtime_roots':roots,'loaded':loaded,")
(out/'collect.py').write_text(s)
a=(prev/'push_analyze_20260909.py').read_text().replace("P=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/01a07f08-100c-7e63-a568-e88df19d2b3d/2026-09-09')","P=Path(__file__).resolve().parent").replace("OLD=Path('/Users/zhangzhao/.codex/visualizations/2026/09/08/01a07f08-100c-7e63-a568-e88df19d2b3d/outputs/push-review-close/analysis.json')","OLD=P.parent/'2026-09-09'/'analysis.json'")
a=a.replace("else '周初夜盘补入'","else '其他新增'")
(out/'analyze.py').write_text(a)
f=(prev/'push_formula_20260909.py').read_text().replace('import push_review_20260909 as q','import collect as q')
(out/'formula.py').write_text(f)
(out/'delivery_evidence.json').write_bytes((prev/'delivery_evidence.json').read_bytes())
print(out)
