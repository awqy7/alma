"""Run the frozen worker without a checkout cwd/PYTHONPATH. Synthetic loopback only."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
from threading import Thread
from uuid import uuid4


def verify(executable,browsers):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
            self.wfile.write(b'<html><body data-alma-session="authenticated">ALMA synthetic fixture</body></html>')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='alma-package-test-') as temp:
            env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
            env.update(PLAYWRIGHT_BROWSERS_PATH=str(Path(browsers).resolve()),ALMA_TEMP_ROOT=temp,PYTHONIOENCODING='utf-8')
            commands=[('PING',{}),('INSPECT_LOCAL_DOCUMENTS',{'sample':'recording','expected_process':'0000000-00.2026.0.00.0001'}),
                ('CONNECT',{'url':f'http://127.0.0.1:{server.server_port}','headless':True}),('CHECK_SESSION',{})]
            messages=[{'version':1,'id':str(uuid4()),'type':'COMMAND','name':name,'payload':payload} for name,payload in commands]
            result=subprocess.run([str(Path(executable).resolve()),'--fixture-mode'],cwd=temp,env=env,
                input=''.join(json.dumps(m)+'\n' for m in messages),capture_output=True,text=True,encoding='utf-8',timeout=120,check=True)
            responses=[json.loads(line) for line in result.stdout.splitlines()]
            assert len(responses)==len(messages), 'Unexpected output in JSONL'
            for response,command in zip(responses,messages):
                assert response.get('id')==command['id'] and response.get('ok') is True, response
            facts=responses[1]['payload']['candidates']
            assert {(f['field'],f['normalized']) for f in facts}>={('arrears_amount','2400.00'),('expert_amount','390.00'),('proposal_date','2026-09-12')}
            assert responses[2]['payload']['state']=='AUTHENTICATED'
            assert responses[3]['payload']['state']=='AUTHENTICATED'
            assert not list(Path(temp).glob('alma-docs-*')), 'Temporary files not cleaned'
    finally:
        server.shutdown();server.server_close();thread.join()
    print('PASS: worker empacotado / JSONL / HTML / PDF / Chromium / cleanup')

if __name__=='__main__':verify(sys.argv[1],sys.argv[2])
