"""Real Rust binary -> Python subprocess -> Chromium -> PDF -> Rust -> SQLite."""
import json
from pathlib import Path
import sqlite3
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pymupdf
import pytest


@pytest.mark.parametrize('document_total,status,blank_page',[('8.957,93','VALIDATED',False),('8.957,94','DIVERGENT',False),('8.957,93','NOT_VERIFIABLE',True)])
def test_rust_worker_browser_pdf_audit(tmp_path, document_total, status, blank_page):
    root = Path(__file__).resolve().parents[2]
    binary = root / 'target/debug/alma-core'
    assert binary.exists(), 'Compile first: cargo test'
    html = (root / 'tests/fixtures/requisition.html').read_bytes()
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50,50), f'Processo: 0000000-00.2026.0.00.0001\nRequisição: RPV-FICTICIA-001\nTotal da requisição: R$ {document_total}\nIRPF: R$ 370,00')
        if blank_page: pdf.new_page()
        data = pdf.tobytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type','application/pdf' if self.path.endswith('.pdf') else 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(data if self.path.endswith('.pdf') else html)
        def do_POST(self):
            raise AssertionError('Official mutations forbidden')
        def log_message(self,*args): pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = Thread(target=server.serve_forever,daemon=True); thread.start()
    db = tmp_path / 'audit.sqlite'
    try:
        result = subprocess.run([str(binary),'fixture',str(root),f'http://127.0.0.1:{server.server_port}',str(db)],
                                capture_output=True,text=True,timeout=30,check=True)
        report=json.loads(result.stdout)
        total=next(field for field in report['fields'] if field['field']=='total_value')
        assert total['status']==status
        assert total['evidence'][0]['page']==1
        assert total['evidence'][0]['event']=='83'
        assert len(total['evidence'][0]['sha256'])==64
        with sqlite3.connect(db) as connection:
            assert connection.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
            saved=json.loads(connection.execute('SELECT payload FROM reports').fetchone()[0])
            assert saved==report
            assert connection.execute('SELECT count(*) FROM facts').fetchone()[0]==2
            assert connection.execute('SELECT state FROM processes').fetchone()[0]=='"VALIDATED"'
    finally:
        server.shutdown(); server.server_close(); thread.join()
