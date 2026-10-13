"""Exercise the production link validator with a local authenticated browser."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest
from engine.browser.eproc.session import SessionAdapter
from engine.browser.eproc.documents import fetch_indexed
from engine.ipc.contracts import AlmaError

PROCESS = '00000000020260000001'


@pytest.fixture
def document_site():
    visits = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            kind = query.get('kind', ['home'])[0]
            visits.append(kind)
            if kind == 'home':
                self.send_response(200)
                self.send_header('Set-Cookie', 'synthetic_session=authorized; HttpOnly; SameSite=Strict')
                body = b'<body data-alma-session="authenticated"><select id="selInfraUnidades"><option>Unidade ficticia</option></select></body>'
            elif 'synthetic_session=authorized' not in self.headers.get('Cookie', ''):
                self.send_response(401); body = b''
            elif kind == 'redirect':
                self.send_response(302); self.send_header('Location', '/?kind=must_not_visit'); body = b''
            else:
                self.send_response(429 if kind == 'rate' else 200)
                body = {'html': '<html><body><p>Valor dos atrasados: R$ 2.400,00</p></body></html>',
                        'login': '<html><body><input type="password"></body></html>',
                        'wrapper': '<html><body><iframe src="/unknown"></iframe></body></html>'}.get(kind, '').encode()
            self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', visits
    server.shutdown(); server.server_close(); thread.join()


async def test_authorized_cookie_reuse_and_fail_closed_responses(document_site, tmp_path):
    url, visits = document_site
    session = SessionAdapter(fixture_mode=True)
    try:
        await session.connect(url, headless=True)
        session.fixture_mode = False  # Real DOM/link/authentication validation, no external eproc.
        document = {'id': 'test', 'name': 'PROACORDO1', 'event': '15'}
        def target(kind, process=PROCESS):
            return {**document, 'url': f'{url}/?acao=acessar_documento&numProcesso={process}&kind={kind}'}
        path = tmp_path / 'document'
        result = await fetch_indexed(session, target('html'), path, PROCESS)
        assert result['format'] == 'HTML' and b'2.400,00' in path.read_bytes()
        for kind, code in [('redirect', 'REAUTH_REQUIRED'), ('login', 'REAUTH_REQUIRED'),
                           ('wrapper', 'DISCOVERY_REQUIRED'), ('rate', 'RATE_LIMITED')]:
            path.unlink(missing_ok=True)
            with pytest.raises(AlmaError) as error:
                await fetch_indexed(session, target(kind), path, PROCESS)
            assert error.value.code == code
            assert not path.exists()
        before = len(visits)
        with pytest.raises(AlmaError) as error:
            await fetch_indexed(session, target('html', '999'), path, PROCESS)
        assert error.value.code == 'PROCESS_NOT_FOUND' and len(visits) == before
        assert 'must_not_visit' not in visits and 'unknown' not in visits
    finally:
        await session.close()
