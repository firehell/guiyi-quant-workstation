"""Single owned worker, bounded RSS and fail-closed monitoring failures."""
import argparse,ctypes,json,os,re,struct,subprocess,time
from pathlib import Path
R=Path(__file__).resolve().parent;M=1024**2;lib=ctypes.CDLL('/usr/lib/libproc.dylib')
def rss(pid):
 b=ctypes.create_string_buffer(128);n=lib.proc_pidinfo(pid,4,0,b,128)
 return struct.unpack_from('Q',b.raw,8)[0] if n==96 else None
def system_memory():
 v=subprocess.run(['/usr/bin/vm_stat'],capture_output=True,text=True,timeout=3,check=True).stdout;size=int(re.search(r'page size of (\d+)',v)[1]);pages=sum(int(re.search(r'Pages '+k+r':\s+(\d+)',v)[1]) for k in ['free','inactive']);pressure=subprocess.run(['/usr/bin/memory_pressure','-Q'],capture_output=True,text=True,timeout=3,check=True);m=re.search(r'free percentage:\s+(\d+)',pressure.stdout)
 if m is None:raise ValueError('PRESSURE_STATUS_MISSING')
 return size*pages,int(m[1])
def monitor(child,env,logpath,*,read_system=system_memory,grace=10,interval=.2):
 peak=0;low=0;last=0;stop=None;stoptime=None
 try:
  with Path(logpath).open('a') as out:
   while child.poll() is None:
    try:
     x=rss(child.pid)
     if x is None:
      if child.poll() is not None:break
      try:
       child.wait(timeout=.05);break
      except subprocess.TimeoutExpired:pass
      raise ValueError('RSS_MONITOR_UNAVAILABLE')
     peak=max(peak,x)
     if x>=384*M:Path(env['TASK_SOFT_FILE']).touch()
     if x>=512*M:stop='WORKER_RSS_512_MIB'
     if time.monotonic()-last>=5:
      last=time.monotonic();free,pct=read_system();low=low+1 if free<512*M else 0
      if low>=3 or pct<=10:stop='SYSTEM_MEMORY_PRESSURE'
      out.write(json.dumps({'time':time.time(),'pid':child.pid,'rss':x,'peak_rss':peak,'free_inactive':free,'system_free_pct':pct,'low_samples':low,'stop':stop})+'\n');out.flush()
    except Exception as ex:
     detail=str(ex) if isinstance(ex,ValueError) and str(ex) in ['RSS_MONITOR_UNAVAILABLE','PRESSURE_STATUS_MISSING'] else ''
     stop='MONITOR_FAILED:'+type(ex).__name__+(':'+detail if detail else '')
    if stop:
     Path(env['TASK_STOP_FILE']).write_text(stop)
     if stoptime is None:stoptime=time.monotonic()
     if stop=='WORKER_RSS_512_MIB' or time.monotonic()-stoptime>=grace:child.terminate()
    time.sleep(interval)
  code=child.wait();return {'peak_rss_bytes':peak,'exit_code':code,'stop':stop}
 finally:
  if child.poll() is None:
   child.terminate()
   try:child.wait(timeout=5)
   except subprocess.TimeoutExpired:child.kill();child.wait()
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--name',required=True);a.add_argument('command',nargs=argparse.REMAINDER);args=a.parse_args();env=os.environ.copy()
 for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','ARROW_NUM_THREADS']:env[k]='1'
 env['PYTHONDONTWRITEBYTECODE']='1';env['TASK_STOP_FILE']=str(R/('STOP-'+args.name));env['TASK_SOFT_FILE']=str(R/('SOFT-'+args.name))
 for name in ['TASK_STOP_FILE','TASK_SOFT_FILE']:Path(env[name]).unlink(missing_ok=True)
 child=subprocess.Popen(args.command,env=env);result=monitor(child,env,R/('resource-'+args.name+'.jsonl'));result={'name':args.name,**result};(R/('resource-'+args.name+'-summary.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True);raise SystemExit(result['exit_code'] if result['exit_code']>=0 and result['stop'] is None else 3)
