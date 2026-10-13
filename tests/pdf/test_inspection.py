from pathlib import Path
import pymupdf
import pytest
from engine.documents.inspection import sample_documents, inspect_documents
from engine.extraction.review_candidates import collect_candidates,normalize_date


@pytest.mark.parametrize('variant',['standard','table','conflict','no_base_date'])
def test_variations_are_extracted_from_actual_pdf(tmp_path,variant):
    result=inspect_documents(sample_documents(tmp_path,variant),tmp_path)
    fields={c['field'] for c in result['candidates']}
    assert {'arrears_amount','expert_amount','proposal_date'}<=fields
    assert ('base_date' in fields)==(variant!='no_base_date')
    assert all(c['bbox'] and len(c['sha256'])==64 for c in result['candidates'])
    assert next(c for c in result['candidates'] if c['field']=='expert_amount')['normalized']=='390.00'
    assert len([c for c in result['candidates'] if c['field']=='arrears_amount'])==(2 if variant=='conflict' else 1)


def candidates(text):
    return collect_candidates({'sha256':'a'*64,'pages':[{'page':1,'text':text,'method':'NATIVE'}]},'d','test')


def test_paid_cancelled_and_multiple_amounts_are_not_requested_values():
    for text in ['Honorários periciais pagos: R$ 390,00','Não se solicita pagamento do perito: R$ 390,00',
                 'Total dos atrasados: R$ 2.400,00 ou R$ 2.500,00','Honorários periciais: R$ 390,00']:
        found=candidates(text)
        assert found and all(c['ambiguous_context'] for c in found)


def test_bad_money_not_partially_recognized():
    assert candidates('Total dos atrasados: R$ 1.23,45')==[]
    assert candidates('Total dos atrasados: R$ 1.234,567')==[]


def test_dates_keep_precision_and_role():
    assert normalize_date('09/2026')==('2026-09','month')
    assert normalize_date('21 de setembro de 2026')==('2026-09-21','day')
    with pytest.raises(ValueError): normalize_date('31/02/2026')
    found=candidates('Data da proposta: 21/09/2026')
    assert len(found)==1 and found[0]['field']=='proposal_date'


def test_label_and_value_on_adjacent_lines():
    found=candidates('Total dos atrasados:\nR$ 2.400,00')
    assert len(found)==1 and found[0]['normalized']=='2400.00'
    assert found[0]['text']=='Total dos atrasados:\nR$ 2.400,00'
    assert candidates('Total dos atrasados:\nOutro assunto\nR$ 2.400,00')==[]


def test_separate_table_cells_join_by_geometry(tmp_path):
    path=tmp_path/'table.pdf'
    with pymupdf.open() as pdf:
        page=pdf.new_page();page.insert_text((40,80),'Total dos atrasados');page.insert_text((330,80),'R$ 2.400,00');pdf.save(path)
    found=inspect_documents([{'path':str(path),'name':'table.pdf'}],tmp_path)['candidates']
    assert len(found)==1 and found[0]['normalized']=='2400.00'
