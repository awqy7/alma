import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread,Lock

HTML='''<!doctype html><meta charset="utf-8"><title>ALMA • ambiente fictício</title>
<style>body{font:16px system-ui;background:#f4f7fb;color:#173452;max-width:1000px;margin:32px auto}h1{font-size:25px}section{background:white;padding:20px;margin:12px 0;border:1px solid #ccd8e5;border-radius:12px}label{display:inline-grid;gap:5px;margin:8px}input,select,button{padding:10px;border:1px solid #bdcddd;border-radius:5px}button{background:#245cbb;color:white;cursor:pointer}button:disabled{background:#9aa8b8}#result{white-space:pre-wrap}.banner{background:#fff0c3;padding:18px}</style>
<body data-alma-session="authenticated"><h1>Ofício Requisitório • demonstração ALMA</h1>
<div class="banner">AMBIENTE FICTÍCIO LOCAL. Nenhum processo oficial é acessado.</div>
<section id="frmOficioRequisitorio"><label>Processo<input id="txtNumProcessoView" value="0000000-00.2026.0.00.0001" readonly></label><label>Total<input id="txtValorTotal" value="2.400,00"></label><button id="btnSalvar" onclick="save('header')">Salvar ofício fictício</button></section>
<section id="beneficiary"><h2>Beneficiário fictício</h2><label>RPV<select id="selPrecRpv"><option value="">Informe</option><option value="R">Requisição de Pequeno Valor - RPV</option></select></label><label>Espécie<select id="selEspecieRequisicao"><option value="">Informe</option><option value="1">Original</option></select></label><label>Valor<input id="txtValorTotalBenefi"></label><label>Data-base<input id="txtDtaBase" value="10/2026"></label><button id="btnSalvarBeneficiario" onclick="save('beneficiary')">Salvar beneficiário fictício</button></section>
<section id="fee"><h2>Honorário fictício</h2><label>Tipo<select id="selNumCodTipoHonorario"><option value="">Informe</option><option value="51">Devolução à Seção Judiciária</option></select></label><label>Valor<input id="txtValorTotalHono"></label><label>Data-base<input id="txtDtaBaseHono"></label><button id="btnSalvarHonorario" onclick="save('fee')">Salvar honorário fictício</button></section>
<section><h2>Dados persistidos no ambiente de demonstração</h2><pre id="result"></pre><button disabled>Intimar Partes — indisponível</button><p id="notice" role="status"></p></section>
<script>
const input=id=>document.getElementById(id).value;
async function refresh(){const r=await fetch('/state');const state=await r.json();document.querySelector('#result').textContent=JSON.stringify(state,null,2);document.body.dataset.saves=String(state.saves);for(const [section,fields] of Object.entries({header:{total:'txtValorTotal'},beneficiary:{total:'txtValorTotalBenefi',base:'txtDtaBase',rpv:'selPrecRpv',species:'selEspecieRequisicao'},fee:{total:'txtValorTotalHono',base:'txtDtaBaseHono',type:'selNumCodTipoHonorario'}})){for(const [key,id] of Object.entries(fields)){if(state[section][key])document.getElementById(id).value=state[section][key]}}return state}
async function save(section){const fields=section==='header'?{total:input('txtValorTotal')}:section==='beneficiary'?{total:input('txtValorTotalBenefi'),base:input('txtDtaBase'),rpv:input('selPrecRpv'),species:input('selEspecieRequisicao')}:{total:input('txtValorTotalHono'),base:input('txtDtaBaseHono'),type:input('selNumCodTipoHonorario')};
const r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section,fields})});if(!r.ok)throw Error('Save failed');await refresh();document.querySelector('#notice').textContent=section+' salvo no ambiente fictício';}
refresh();
</script></body>'''

class DemoSite:
    def __init__(self):
        state={'header':{'total':'2.400,00'},'beneficiary':{},'fee':{},'saves':0};lock=Lock()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,status,body,mime='application/json'):
                self.send_response(status);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(body)
            def do_GET(self):
                if self.path=='/':return self.send(200,HTML.encode(),'text/html; charset=utf-8')
                if self.path=='/state':
                    with lock: return self.send(200,json.dumps(state).encode())
                return self.send(404,b'{}')
            def do_POST(self):
                origin=f'http://127.0.0.1:{self.server.server_port}'
                if self.path!='/save' or self.headers.get('Origin')!=origin or int(self.headers.get('Content-Length','0'))>4096:return self.send(403,b'{}')
                try:
                    data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if data['section'] not in ('header','beneficiary','fee') or not isinstance(data['fields'],dict):raise ValueError()
                    with lock:
                        state[data['section']]=data['fields'];state['saves']+=1
                    return self.send(200,b'{"ok":true}')
                except (ValueError,KeyError,TypeError):return self.send(400,b'{}')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()
