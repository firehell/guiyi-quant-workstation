"""Initialize only the explicit, isolated development SuBing database."""
from pathlib import Path
import os,argparse
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.engine import make_url
from app.private_settings import load_private_execution_settings
from app.db.url import normalize_database_url
from app.subing_model.store import ModelStore

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--test-only',action='store_true');args=parser.parse_args()
    name='guiyi_subing_development_test' if args.test_only else 'guiyi_subing_development'
    settings,_=load_private_execution_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    origin=make_url(normalize_database_url(settings['DATABASE_URL']))
    if origin.host not in ('127.0.0.1','localhost','::1'):raise ValueError('LOCAL_DATABASE_REQUIRED')
    admin=create_engine(origin.set(database='postgres'),isolation_level='AUTOCOMMIT',connect_args={'connect_timeout':5})
    try:
        with admin.connect() as c:
            exists=c.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=:name)'),dict(name=name))
            if not exists:c.execute(text('CREATE DATABASE guiyi_subing_development_test' if args.test_only else 'CREATE DATABASE guiyi_subing_development'))
    finally:admin.dispose()
    url=origin.set(database=name).render_as_string(hide_password=False)
    store=ModelStore(url,test_only=args.test_only)
    try:
        existing=set(inspect(store.engine).get_table_names())
        if not existing<= {'subing_development_runs','subing_development_events'}:raise ValueError('DEVELOPMENT_DATABASE_NOT_ISOLATED')
        store.initialize()
    finally:store.engine.dispose()
    path=Path('.run/subing-model-test-database.url' if args.test_only else '.run/subing-model-database.url');path.parent.mkdir(exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_text()!=url:raise ValueError('DEVELOPMENT_CONFIGURATION_CONFLICT')
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:f.write(url)
    print('SUBING_DEVELOPMENT_DATABASE_INITIALIZED')
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('DEVELOPMENT_SETUP_FAILED:'+type(exc).__name__);raise SystemExit(2) from None
