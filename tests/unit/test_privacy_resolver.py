from engine.browser.eproc.diagnostics import redact_url
from engine.documents.resolver import DocumentResolver


def test_url_redaction_removes_path_credentials_query_and_fragment():
    value=redact_url('https://user:SECRET@example.invalid/pessoa/000.000.000-00?token=SECRET&nome=Maria#SECRET')
    assert value=='https://example.invalid/[REDACTED]'
    assert redact_url('data:SECRET')=='[REDACTED]'


def test_resolver_is_not_limited_to_recorded_examples():
    docs=[{'id':str(i),'name':name} for i,name in enumerate(['MEMÓRIA DE CÁLCULO','CONTRATO','SENTENÇA','PROACORDO1','PGTOPERITO1','AVISO'])]
    selected=DocumentResolver().rank(docs)
    assert len(selected)==5
    assert selected[0]['possible_types']==['calculation']
