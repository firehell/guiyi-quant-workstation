# Main 1m pre-2010 Physical Verification (2026-07-14)

- Scope: 19 products `a,al,au,b,c,cf,cu,fu,l,m,p,rb,ru,sr,ta,v,wr,y,zn`
- Effective start policy: `max(listed_date, 2010-01-04)`
- Result: **19/19 OK** (canonical parquet min datetime within 14-day tolerance)
- Action: no P4 re-download required; inventory start floor fixed in `download_pending_inventory.py`
