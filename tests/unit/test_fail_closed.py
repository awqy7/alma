from engine.extraction.facts import extract_facts


def test_unscoped_total_is_not_requisition_total():
    parsed={'sha256':'a'*64,'pages':[{'page':1,'method':'NATIVE','text':'Valor total: R$ 8.957,93'}]}
    assert extract_facts(parsed,{'id':'x','name':'x'},'x','x')==[]


def test_unreadable_money_does_not_become_zero():
    parsed={'sha256':'a'*64,'pages':[{'page':1,'method':'OCR','text':'IRPF: R$ 37O,OO'}]}
    assert extract_facts(parsed,{'id':'x','name':'x'},'x','x')==[]


def test_scope_requires_unique_document_identifiers():
    for header, expected in [('',False),('Processo: p\nRequisição: r\n',True),
                              ('Processo: p\nRequisição: r\nRequisição: other\n',False)]:
        parsed={'sha256':'a'*64,'pages':[{'page':1,'method':'NATIVE','text':header+'Total da requisição: R$ 1,00'}]}
        facts=extract_facts(parsed,{'id':'x','name':'x'},'p','r')
        assert facts[0]['scope_verified'] is expected
