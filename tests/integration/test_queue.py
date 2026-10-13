import json
import sqlite3
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[2]
NUMBERS = [f'0000000002026000000{i}' for i in range(1, 4)]


@pytest.fixture
def queue_site():
    state = {'posts': [], 'expired': False, 'max_reads': None, 'reads': []}
    mapping = {'A1': NUMBERS[0], 'A2': NUMBERS[0], 'B1': NUMBERS[1]}
    documents = {}
    for req, number in mapping.items():
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((30, 50), f'Processo: {number}\nRequisição: {req}\nTotal da requisição: R$ 10,00')
            documents[req] = pdf.tobytes()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            state['posts'].append(self.path); self.send_response(405); self.end_headers()
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            action = query.get('acao', ['home'])[0]
            number = query.get('num_processo', query.get('txtNumProcesso', ['']))[0]
            req = query.get('numIdOficioRequisitorio', [''])[0]
            if self.path.startswith('/doc/'):
                key = self.path.split('/')[-1].split('.')[0]
                state['reads'].append(key)
                self.send_response(200); self.send_header('Content-Type', 'application/pdf'); self.end_headers()
                self.wfile.write(documents[key]); return
            if state['expired'] or (state['max_reads'] is not None and len(state['reads']) >= state['max_reads']):
                self.send_response(200); self.end_headers(); self.wfile.write(b'<input type=password>'); return
            if action == 'home':
                content = ''
            elif action == 'usuario_tipo_monitoramento_localizador_listar':
                content = '<table><tr><td>Concluso Decisão RPV - Concluso Decisão RPV</td><td><a href="/?acao=localizador_processos_lista&page=1">3</a></td></tr></table>'
            elif action == 'localizador_processos_lista':
                numbers = NUMBERS[:1] if query.get('page') == ['1'] else NUMBERS[1:]
                content = ''.join(f'<a href="/?acao=processo_selecionar&num_processo={n}">{n}</a>' for n in numbers)
                if query.get('page') == ['1']:
                    content += '<a rel=next href="/?acao=localizador_processos_lista&page=2">Próxima</a>'
            elif action == 'processo_selecionar':
                content = f'<div id=fldAcoes><a href="/?acao=oficio_requisitorio_listar&txtNumProcesso={number}">Ofício Requisitório</a></div>'
            elif action == 'oficio_requisitorio_listar':
                content = ''.join(f'<a href="/?acao=oficio_requisitorio_requisicoes_editar&numIdOficioRequisitorio={key}">RPV {key}</a>' for key, n in mapping.items() if n == number)
            elif action == 'oficio_requisitorio_requisicoes_editar':
                content = f'<input id=txtNumProcesso value="{mapping[req]}"><input id=txtNumRequisicao value="{req}"><input id=txtValorTotal value="10,00"><a data-document data-event="1" href="/doc/{req}.pdf">MEMORIA_CALCULO</a>'
            else: content = ''
            menu = '<a id="btn-meus-localizadores" href="/?acao=usuario_tipo_monitoramento_localizador_listar">all_inbox</a>'
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(('<body data-alma-session="authenticated">' + menu + content + '</body>').encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', state
    server.shutdown(); server.server_close(); thread.join()


def run_queue(url, db, limit=100):
    result = subprocess.run([str(ROOT/'target/debug/alma-core'), 'queue-fixture', str(ROOT), url, str(db), str(limit)],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_paginated_queue_multiple_rpvs_resume_without_duplicates(queue_site, tmp_path):
    url, state = queue_site
    db = tmp_path/'queue.sqlite'
    first = run_queue(url, db, 2)  # discover process 1, then review A1
    assert first['status'] == 'RUNNING'
    assert state['reads'] == ['A1']
    final = run_queue(url, db)
    assert final['id'] == first['id'] and final['status'] == 'COMPLETED'
    assert state['reads'] == ['A1', 'A2', 'B1']
    assert sum(i['kind'] == 'RPV' and i['state'] == 'COMPLETED' for i in final['items']) == 3
    assert any(i['error_code'] == 'REQUISITION_NOT_FOUND' for i in final['items'])
    assert state['posts'] == []
    with sqlite3.connect(db) as connection:
        assert connection.execute('SELECT count(*) FROM reports').fetchone()[0] == 3
        assert connection.execute('SELECT count(*) FROM review_queues').fetchone()[0] == 1


def test_expired_session_pauses_queue_and_preserves_pending_targets(queue_site, tmp_path):
    url, state = queue_site
    state['max_reads'] = 1
    db = tmp_path/'queue.sqlite'
    first = run_queue(url, db)
    assert first['status'] == 'PAUSED' and first['error_code'] == 'REAUTH_REQUIRED'
    assert any(i['state'] == 'PENDING' for i in first['items'])
    state['max_reads'] = None
    final = run_queue(url, db)
    assert final['id'] == first['id'] and final['status'] == 'COMPLETED'
    assert state['posts'] == []
