from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit,parse_qs
import pytest
from engine.browser.eproc.session import SessionAdapter
from engine.browser.eproc.adapter import EprocAdapter
from engine.browser.eproc.navigation import checked_link
from engine.ipc.contracts import AlmaError

PROCESS='00000000020260000001'

@pytest.fixture
def navigation_site():
    posts=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):posts.append(self.path);self.send_response(405);self.end_headers()
        def do_GET(self):
            action=parse_qs(urlsplit(self.path).query).get('acao',['home'])[0]
            content={
                'home':'<a id="btn-meus-localizadores" href="/?acao=usuario_tipo_monitoramento_localizador_listar">all_inbox</a>',
                'usuario_tipo_monitoramento_localizador_listar':'<table><tr><td>Concluso Decisão RPV - Concluso Decisão RPV</td><td><a href="/?acao=localizador_processos_lista">1</a></td></tr></table>',
                'localizador_processos_lista':f'<a href="/?acao=processo_selecionar&num_processo={PROCESS}">{PROCESS}</a>',
                'processo_selecionar':f'<div id="fldAcoes"><a href="/?acao=oficio_requisitorio_listar&txtNumProcesso={PROCESS}">Ofício Requisitório</a></div><a href="/?acao=acessar_documento&numProcesso={PROCESS}&numSeqEvento=15&MimeType=text/html">PROACORDO1</a>',
                'oficio_requisitorio_listar':'<a href="/?acao=oficio_requisitorio_requisicoes_editar&numIdOficioRequisitorio=FICTICIO">RPV fictícia</a>',
                'oficio_requisitorio_requisicoes_editar':f'<input id="txtNumProcessoView" value="{PROCESS}"><input id="txtNumRequisicao" value="FICTICIO"><input id="txtValorTotal" value="2.790,00">',
            }.get(action,'')
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
            self.wfile.write(('<body data-alma-session="authenticated">'+content+'</body>').encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}',posts
    server.shutdown();server.server_close();thread.join()


async def test_existing_links_reach_correct_rpv_and_index_without_writes(navigation_site):
    url,posts=navigation_site;session=SessionAdapter(fixture_mode=True);adapter=EprocAdapter(session)
    try:
        await session.connect(url,headless=True)
        await adapter.open_localizer('Concluso Decisão RPV')
        assert await adapter.list_processes()==[{'process_number':PROCESS}]
        await adapter.open_process(PROCESS);await adapter.open_requisition()
        assert (await adapter.read_process())['process_number']==PROCESS
        docs=await adapter._index_live_documents()
        assert len(docs)==1 and docs[0]['name']=='PROACORDO1' and docs[0]['event']=='15'
        assert all('url' not in doc for doc in docs)
        assert len(session.context.pages)==2
        assert posts==[]
    finally:await session.close()


def test_navigation_rejects_foreign_origin_and_write_actions():
    for href in ['https://foreign.invalid/?acao=processo_selecionar','/?acao=oficio_requisitorio_requisicoes_salvar','javascript:alert(1)']:
        with pytest.raises(AlmaError):checked_link('https://eproc.invalid','https://eproc.invalid/',href,{'processo_selecionar'})
