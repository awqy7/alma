"""Real browser acquisition -> HTML/PDF perception -> Rust comparison -> SQLite."""
import json
import sqlite3
import subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from engine.documents.inspection import recording_documents


@pytest.mark.parametrize('change_total', [False, True])
def test_document_review_and_snapshot_drift(tmp_path, change_total):
    root = Path(__file__).resolve().parents[2]
    docs = recording_documents(tmp_path, 'recording')
    downloads = []
    posts = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            posts.append(self.path); self.send_response(405); self.end_headers()
        def do_GET(self):
            if self.path in ['/proposal.html', '/expert.pdf']:
                index = 0 if self.path.endswith('html') else 1
                body = Path(docs[index]['path']).read_bytes()
                mime = 'text/html; charset=utf-8' if index == 0 else 'application/pdf'
                downloads.append(index)
            else:
                body = b'''<body data-alma-session="authenticated">
<input id="txtNumProcesso" value="0000000-00.2026.0.00.0001">
<input id="txtNumRequisicao" value="RPV-FICTICIA"><input id="txtValorTotal" value="2.400,00">
<a data-document data-event="15" href="/proposal.html">PROACORDO1</a>
<a data-document data-event="11" href="/expert.pdf">PGTOPERITO1</a></body>'''
                if change_total:
                    # A user edit while documents are fetched: poll a synthetic state endpoint.
                    body += b'''<script>setInterval(async()=>{if((await fetch('/changed')).status===201)document.querySelector('#txtValorTotal').value='9.999,00'},20)</script>'''
                mime = 'text/html; charset=utf-8'
                if self.path == '/changed':
                    self.send_response(201 if downloads else 200); self.end_headers(); return
            self.send_response(200); self.send_header('Content-Type', mime); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    db = tmp_path / 'audit.sqlite'
    try:
        result = subprocess.run([str(root/'target/debug/alma-core'), 'fixture', str(root),
                                 f'http://127.0.0.1:{server.server_port}', str(db)],
                                capture_output=True, text=True, timeout=40)
        assert posts == []
        with sqlite3.connect(db) as connection:
            if change_total:
                assert result.returncode != 0 and 'SNAPSHOT_CHANGED' in result.stderr
                assert connection.execute('SELECT count(*) FROM reports').fetchone()[0] == 0
            else:
                assert result.returncode == 0, result.stderr
                report = json.loads(result.stdout)
                review = report['document_review']
                assert review['mode'] == 'READ_ONLY'
                assert review['checks'][0]['status'] == 'DIVERGENT'
                assert review['checks'][0]['expected'] == '2790.00'
                assert review['checks'][1]['expected'] == '2026-09'
                arrears = next(o for o in review['observations'] if o['field'] == 'arrears_amount')
                assert arrears['evidence'][0]['page'] is None
                assert arrears['evidence'][0]['event'] == '15'
                assert arrears['evidence'][0]['html_location'].startswith('/')
                assert json.loads(connection.execute('SELECT payload FROM reports').fetchone()[0]) == report
    finally:
        server.shutdown(); server.server_close(); thread.join()
