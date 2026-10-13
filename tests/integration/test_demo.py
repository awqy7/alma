import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4


def test_demo_runs_dom_saves_reload_and_separate_audit(tmp_path):
    root=Path(__file__).resolve().parents[2];db=tmp_path/'demo.sqlite'
    result=subprocess.run([str(root/'target/debug/alma-core'),'demo',str(root),str(db)],text=True,capture_output=True,timeout=45,check=True)
    report=json.loads(result.stdout)
    assert report['mode']=='DEMO' and report['official_changes']==0
    stored=report['execution']['stored']
    assert stored['saves']==3
    assert stored['header']['total']=='2790,00'
    assert stored['beneficiary']['base']==stored['fee']['base']=='09/2026'
    assert len(report['events'])==3
    assert report['execution']['screenshot'].startswith('data:image/png;base64,')
    with sqlite3.connect(db) as connection:
        status,payload=connection.execute('SELECT status,report FROM demo_runs').fetchone()
        assert status=='COMPLETED' and json.loads(payload)==report


def test_production_worker_rejects_demo_write_commands():
    messages=[{'version':1,'id':str(uuid4()),'type':'COMMAND','name':name,'payload':{}} for name in ['START_DEMO','APPLY_DEMO']]
    result=subprocess.run([sys.executable,'-m','engine.worker'],input=''.join(json.dumps(m)+'\n' for m in messages),text=True,capture_output=True,timeout=15,check=True)
    responses=[json.loads(line) for line in result.stdout.splitlines()]
    assert all(r['type']=='ERROR' and r['code']=='DISCOVERY_REQUIRED' for r in responses)
