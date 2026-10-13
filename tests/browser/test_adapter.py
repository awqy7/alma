from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pymupdf
import pytest
from engine.browser.eproc.adapter import EprocAdapter
from engine.browser.eproc.session import SessionAdapter
from engine.ipc.contracts import AlmaError, ErrorCode


@pytest.fixture
def site():
    html = (Path(__file__).parents[1] / 'fixtures/requisition.html').read_bytes()
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50,50), 'Total da requisição: R$ 8.957,93\nIRPF: R$ 370,00')
        document = pdf.tobytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf' if self.path == '/calculation.pdf' else 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(document if self.path == '/calculation.pdf' else html)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown(); server.server_close(); thread.join()


async def test_read_only_dom(site, tmp_path):
    session = SessionAdapter(fixture_mode=True)
    adapter = EprocAdapter(session)
    try:
        assert (await adapter.connect(url=site, headless=True))['state'] == 'AUTHENTICATED'
        snapshot = await adapter.read_requisition()
        assert snapshot['requisition']['fields']['total_value']['normalized'] == '8957.93'
        docs = await adapter.index_documents()
        await adapter.download_document(docs[0]['id'], tmp_path / 'doc.pdf')
        assert (tmp_path / 'doc.pdf').read_bytes().startswith(b'%PDF-')
        assert await session.page.locator('body').get_attribute('data-unsafe') is None
        await session.page.locator('#txtValorTotal').evaluate('el => el.remove()')
        with pytest.raises(AlmaError) as error: await adapter.read_requisition()
        assert error.value.code == ErrorCode.UI_CHANGED
        await session.page.locator('body').evaluate('el => el.innerHTML = "<input type=password>"')
        with pytest.raises(AlmaError) as error: await adapter.read_requisition()
        assert error.value.code == ErrorCode.REAUTH_REQUIRED
    finally:
        await session.close()


async def test_edit_form_variant_and_ambiguous_tabs(site):
    session=SessionAdapter(fixture_mode=True);adapter=EprocAdapter(session)
    try:
        await adapter.connect(url=site,headless=True)
        await session.page.locator('#txtNumProcesso').evaluate("e=>{e.id='txtNumProcessoView';}")
        await session.page.evaluate("()=>{const input=document.createElement('input');input.id='txtPessoaRequerido';input.value='Entidade Exemplo';document.body.append(input)}")
        snap=await adapter.read_requisition()
        assert snap['requisition']['fields']['entity']['raw']=='Entidade Exemplo'
        new_page=await session.context.new_page();await new_page.goto(site)
        with pytest.raises(AlmaError) as error:await adapter.read_requisition()
        assert error.value.code==ErrorCode.FIELD_AMBIGUOUS
        await new_page.close()
    finally:await session.close()


async def test_unexpected_confirmation_is_dismissed_not_accepted(site):
    session=SessionAdapter(fixture_mode=True)
    try:
        await session.connect(url=site,headless=True)
        result=await session.page.evaluate("confirm('Confirma a intimação de todas as partes?')")
        assert result is False
        with pytest.raises(AlmaError):await session.require_session()
    finally:await session.close()


async def test_authentication_marker_ignores_hidden_responsive_duplicate(site):
    session=SessionAdapter(fixture_mode=True)
    try:
        await session.connect(url=site,headless=True)
        await session.page.evaluate("()=>{document.body.insertAdjacentHTML('beforeend','<select id=selInfraUnidades><option>Unidade fictícia</option></select><select id=selInfraUnidades style=display:none></select>')}")
        session.fixture_mode=False
        assert (await session.check_session())['state']=='AUTHENTICATED'
    finally:await session.close()
