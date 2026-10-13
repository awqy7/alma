"""Test real eproc DOM automation: header, beneficiary, fee subforms, alerts and readback."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import pytest

from engine.browser.eproc.adapter import EprocAdapter
from engine.browser.eproc.session import SessionAdapter
from engine.ipc.contracts import AlmaError, ErrorCode


MAIN_HTML = """<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>:: eproc - Ofício Requisitório ::</title></head>
<body data-alma-session="authenticated">
<form id="frmOficioRequisitorio">
  <input id="txtNumProcessoView" value="0000000-00.2026.0.00.0001" readonly>
  <input id="txtNumRequisicao" value="REQ-2026-001" type="hidden">
  <input id="txtValorTotal" value="2.400,00">
  <button id="btnSalvar" type="button" onclick="saveHeader()">Salvar</button>
  
  <fieldset id="fldBeneficiarios">
    <legend><span>Beneficiários</span><span><a href="javascript:void(0)" onclick="openSub('B')">Novo</a></span></legend>
    <div id="divConteudoBeneficiarios">
      <table border="1">
        <thead><tr><th>Beneficiário</th><th>Valor</th><th>Ações</th></tr></thead>
        <tbody>
          <tr>
            <td>Autor Fictício</td>
            <td>R$ 2.400,00</td>
            <td><a href="javascript:void(0)">Ver</a> <a href="javascript:void(0)" onclick="openSub('B')">Alterar</a></td>
          </tr>
        </tbody>
      </table>
    </div>
  </fieldset>

  <fieldset id="fldHonorarios">
    <legend id="legHonorarios"><span>Honorários</span><span><a href="javascript:void(0)" onclick="openSub('H')">Novo</a></span></legend>
    <div id="divConteudoHonorarios">
      <table border="1">
        <thead><tr><th>Tipo</th><th>Valor</th></tr></thead>
        <tbody id="tbHonorarios">
        </tbody>
      </table>
    </div>
  </fieldset>
</form>

<iframe id="ifrSubFrm" name="ifrSubFrm" style="display:none;width:600px;height:400px;"></iframe>

<script>
function saveHeader() {
  window.headerSaved = document.getElementById('txtValorTotal').value;
}
function openSub(type) {
  const ifr = document.getElementById('ifrSubFrm');
  ifr.style.display = 'block';
  ifr.src = '/subform?type=' + type;
}
window.addEventListener('message', function(e) {
  if (e.data === 'closeSub') {
    document.getElementById('ifrSubFrm').style.display = 'none';
  }
});
</script>
</body>
</html>
"""

SUBFORM_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Subformulário</title></head>
<body>
<div id="subContainer"></div>
<script>
const params = new URLSearchParams(window.location.search);
const type = params.get('type');
const container = document.getElementById('subContainer');

if (type === 'B') {
  container.innerHTML = `
    <form id="frmRequisicaoBeneficiario">
      <select id="selPrecRpv"><option value="">-</option><option value="R">RPV</option></select>
      <select id="selEspecieRequisicao"><option value="">-</option><option value="1">Original</option></select>
      <input id="txtValorTotal" value="">
      <input id="txtValorPrincipal" value="">
      <input id="txtDtaBase" value="">
      <select id="selTipoJurosMora"><option value="1">Não incidem</option></select>
      <select id="selIrra"><option value="N">Não</option></select>
      <select id="selHonDestac"><option value="N">Não</option></select>
      <button id="btnSalvarFecharBeneficiario" type="button" onclick="salvarBeneficiario()">Salvar e Fechar</button>
    </form>
  `;
} else {
  container.innerHTML = `
    <form id="frmRequisicaoHonorario">
      <select id="selNumCodTipoHonorario"><option value="">-</option><option value="51">Devolução</option></select>
      <select id="selPrecRpvHono"><option value="">-</option><option value="R">RPV</option></select>
      <select id="selEspecieRequisicaoHono"><option value="">-</option><option value="1">Original</option></select>
      <input id="txtValorTotalHono" value="">
      <input id="txtValorPrincipalHono" value="">
      <input id="txtDtaBaseHono" value="">
      <select id="selTipoJurosMoraHono"><option value="1">Não incidem</option></select>
      <button id="btnSalvarFecharHonorario" type="button" onclick="salvarHonorario()">Salvar e Fechar</button>
    </form>
  `;
}

function salvarBeneficiario() {
  alert('Beneficiário salvo com sucesso');
  window.parent.postMessage('closeSub', '*');
}

function salvarHonorario() {
  alert('Honorário salvo com sucesso');
  window.parent.postMessage('closeSub', '*');
}
</script>
</body>
</html>
"""


@pytest.fixture
def mock_eproc_server():
    server_state = {"header": "2.400,00"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path == "/" or self.path.startswith("/controlador.php"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                # Update with latest header if reloaded
                current_html = MAIN_HTML.replace('value="2.400,00"', f'value="{server_state["header"]}"')
                self.wfile.write(current_html.encode("utf-8"))
            elif self.path.startswith("/subform"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(SUBFORM_HTML.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.asyncio
async def test_apply_real_plan_full_execution(mock_eproc_server):
    session = SessionAdapter(fixture_mode=True)
    adapter = EprocAdapter(session)
    try:
        conn = await adapter.connect(url=mock_eproc_server, headless=True)
        assert conn["state"] == "AUTHENTICATED"

        plan = {
            "expected_process": "0000000-00.2026.0.00.0001",
            "total": "2790.00",
            "arrears": "2400.00",
            "expert": "390.00",
            "base_date": "2026-09",
        }

        events_emitted = []
        result = await adapter.apply_real_plan(plan, emit=lambda ev: events_emitted.append(ev))

        assert result["ok"] is True
        assert result["mode"] == "REAL"
        assert result["official_changes"] == 3
        assert result["execution"]["header"]["total"] == "2.790,00"
        assert result["execution"]["beneficiary"]["arrears"] == "2.400,00"
        assert result["execution"]["beneficiary"]["base_date"] == "09/2026"
        assert result["execution"]["fee"]["expert"] == "390,00"
        assert result["execution"]["fee"]["base_date"] == "09/2026"
        assert result["execution"]["screenshot"].startswith("data:image/png;base64,")

        phases = [e["payload"]["phase"] for e in events_emitted]
        assert "HEADER_SAVED" in phases
        assert "BENEFICIARY_SAVED" in phases
        assert "FEE_SAVED" in phases
        assert "VERIFIED" in phases

    finally:
        await session.close()


@pytest.mark.asyncio
async def test_apply_real_plan_rejects_process_mismatch(mock_eproc_server):
    session = SessionAdapter(fixture_mode=True)
    adapter = EprocAdapter(session)
    try:
        await adapter.connect(url=mock_eproc_server, headless=True)
        plan = {
            "expected_process": "9999999-99.2026.0.00.9999",
            "total": "2790.00",
            "arrears": "2400.00",
            "expert": "390.00",
            "base_date": "2026-09",
        }
        with pytest.raises(AlmaError) as exc:
            await adapter.apply_real_plan(plan)
        assert exc.value.code == ErrorCode.PROCESS_NOT_FOUND
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_read_beneficiaries_and_fees(mock_eproc_server):
    session = SessionAdapter(fixture_mode=True)
    adapter = EprocAdapter(session)
    try:
        await adapter.connect(url=mock_eproc_server, headless=True)
        beneficiaries = await adapter.read_beneficiaries()
        assert len(beneficiaries) == 1
        assert "Autor Fictício" in beneficiaries[0]["text"]
        assert "2.400,00" in beneficiaries[0]["text"]

        fees = await adapter.read_fees()
        assert isinstance(fees, list)
    finally:
        await session.close()
