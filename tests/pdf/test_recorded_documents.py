from pathlib import Path
import pytest
from engine.documents.inspection import sample_documents, inspect_documents
from engine.documents.html_parser import parse_html
from engine.extraction.document_profile import process_number
from engine.extraction.review_candidates import collect_candidates
from engine.ipc.contracts import AlmaError


def test_recording_extracts_table_footer_and_ajg_with_context(tmp_path):
    result=inspect_documents(sample_documents(tmp_path,'recording'),tmp_path)
    assert [d['profile'] for d in result['documents']]==['agreement','expert_payment']
    candidates={c['field']:c for c in result['candidates']}
    assert candidates['arrears_amount']['normalized']=='2400.00'
    assert candidates['arrears_amount']['page'] is None
    assert 'CÁLCULO' in candidates['arrears_amount']['section']
    assert candidates['arrears_amount']['html_location'].endswith('/tr[1]')
    assert candidates['expert_amount']['normalized']=='390.00'
    assert candidates['expert_amount']['page']==1
    assert candidates['proposal_date']['normalized']=='2026-09-12'
    assert 'base_date' not in candidates
    expected=process_number('0000000-00.2026.0.00.0001')
    assert len(expected)==20
    for doc in result['documents']:
        assert {v['normalized'] for v in doc['metadata']['process_number']}=={expected}


def test_generic_requested_value_requires_ajg_context():
    parsed={'sha256':'a'*64,'pages':[{'page':1,'method':'NATIVE','text':'Valor requisitado: 390,00'}]}
    assert collect_candidates(parsed,'x','x')==[]
    assert collect_candidates(parsed,'x','x','expert_payment')[0]['normalized']=='390.00'


def test_html_excludes_executable_hidden_and_remote_resources(tmp_path):
    path=tmp_path/'proposal.html'
    path.write_text('''<html><body><script>Valor dos atrasados: R$ 9.999,00</script>
    <p hidden>Valor dos atrasados: R$ 8.888,00</p><p style="display: none">Valor dos atrasados: R$ 7.777,00</p>
    <iframe src="https://example.invalid/private"></iframe><img src="https://example.invalid/image">
    <p>Valor dos atrasados: R$ 2.400,00</p></body></html>''')
    parsed=parse_html(path)
    values=collect_candidates(parsed,'x','x')
    assert [v['normalized'] for v in values]==['2400.00']
    assert '9999' not in parsed['pages'][0]['text']


def test_html_encoding_is_not_silently_corrupted(tmp_path):
    path=tmp_path/'invalid.html';path.write_bytes(b'<html><p>\xff</p></html>')
    with pytest.raises(AlmaError):parse_html(path)


def test_zero_is_not_a_payment_candidate():
    result=collect_candidates({'sha256':'a'*64,'pages':[{'page':1,'method':'NATIVE','text':'Valor requisitado: 0,00'}]},'x','x','expert_payment')
    assert result[0]['ambiguous_context'] is True


def test_indeterminate_amount_keeps_its_evidence():
    result=collect_candidates({'sha256':'a'*64,'pages':[{'page':1,'method':'NATIVE','text':'Valor dos atrasados: a apurar'}]},'x','x')
    assert result[0]['normalized'] is None
    assert result[0]['ambiguous_context'] is True
    assert result[0]['text']=='Valor dos atrasados: a apurar'
