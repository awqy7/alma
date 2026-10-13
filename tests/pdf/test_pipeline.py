import pymupdf
import pytest
from engine.documents.parser import parse_pdf
from engine.extraction.facts import extract_facts
from engine.ipc.contracts import AlmaError


def test_native_pdf_evidence(tmp_path):
    path = tmp_path / 'synthetic.pdf'
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50,50), 'Total da requisição: R$ 8.957,93\nIRPF: R$ 370,00\nData-base: 01/02/2026')
        pdf.save(path)
    parsed = parse_pdf(path)
    facts = extract_facts(parsed, {'id':'synthetic','name':'MEMORIA_CALCULO','event':'83'}, 'ficticio', 'RPV-1')
    assert parsed['pages'][0]['method'] == 'NATIVE'
    assert len(facts) == 3
    assert facts[0]['value_normalized'] == '8957.93'
    assert facts[1]['value_normalized'] == '370.00'
    assert facts[1]['source']['page'] == 1
    assert facts[1]['source']['sha256'] == parsed['sha256']


def test_blank_and_corrupt_pdf(tmp_path):
    path = tmp_path / 'blank.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    parsed = parse_pdf(path)
    assert parsed['pages'][0]['method'] == 'UNREADABLE'
    assert extract_facts(parsed, {'id':'x','name':'x'}, 'x','x') == []
    path.write_text('invalid')
    with pytest.raises(AlmaError): parse_pdf(path)
