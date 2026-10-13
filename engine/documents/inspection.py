from pathlib import Path
import pymupdf
from engine.documents.parser import parse_pdf
from engine.extraction.review_candidates import collect_candidates
from engine.ipc.contracts import AlmaError, ErrorCode
from engine.documents.html_parser import parse_html
from engine.extraction.document_profile import describe, process_number


def inspect_documents(items, allowed_root):
    documents=[]; candidates=[]
    for index,item in enumerate(items):
        path=Path(item['path']).resolve()
        if not path.is_relative_to(allowed_root.resolve()) or not path.is_file():
            raise AlmaError(ErrorCode.DOCUMENT_NOT_FOUND,'local_inspection')
        parsed=parse_html(path) if path.suffix=='.html' else parse_pdf(path,enable_ocr=False)
        described=inspect_parsed(parsed,item.get('id',f'document-{index}'),item['name'],item.get('event'))
        candidates.extend(described['candidates'])
        documents.extend(described['documents'])
    return {'documents':documents,'candidates':candidates}


def inspect_parsed(parsed, identity, name, event=None):
    description=describe(parsed,identity,name)
    found=collect_candidates(parsed,identity,name,description['profile'])+description['closing_candidates']
    for candidate in found:
        candidate['event']=event
    is_html=parsed.get('format')=='HTML'
    document={'id':identity,'name':name,'event':event,'sha256':parsed['sha256'],
        'pages':None if is_html else len(parsed['pages']), 'format':'HTML' if is_html else 'PDF',
        'profile':description['profile'],'metadata':description['metadata'],
        'unreadable_pages':[p['page'] for p in parsed['pages'] if p['method']=='UNREADABLE' or not p['text'].strip()],
        'methods':sorted({p['method'] for p in parsed['pages']}),'candidate_count':len(found)}
    return {'documents':[document],'candidates':found}


def sample_documents(root, variant):
    if variant in {'recording','wrong_process','multiple_experts'}:
        return recording_documents(root,variant)
    # Synthetic PDFs are actually rendered, parsed and reconciled. No canned reports.
    proposal=['Proposta de acordo - EXEMPLO FICTICIO','Total dos atrasados: R$ 2.400,00',
              'Data da proposta: 21/09/2026','Data-base do calculo: 09/2026']
    if variant=='table': proposal=['Proposta de acordo - EXEMPLO FICTICIO','Montante das parcelas vencidas | R$ 2.400,00',
                                  'Proposta apresentada em 21 de setembro de 2026','Competencia-base: 09/2026']
    if variant=='conflict': proposal.append('Total dos atrasados: R$ 2.500,00')
    if variant=='no_base_date': proposal=proposal[:-1]
    expert=['Solicitacao de pagamento - EXEMPLO FICTICIO',
            'Solicita-se o pagamento do perito no valor de R$ 390,00']
    result=[]
    for index,lines in enumerate([proposal,expert]):
        path=root/f'sample-{index}.pdf'
        with pymupdf.open() as pdf:
            page=pdf.new_page()
            for line_index,line in enumerate(lines): page.insert_text((40,50+line_index*30),line,fontsize=11)
            pdf.save(path)
        result.append({'path':str(path),'name':['Proposta ficticia.pdf','Pedido do perito ficticio.pdf'][index]})
    return result


def recording_documents(root,variant):
    """Synthetic structure from the supplied specification; no real party data."""
    proposal=root/'agreement.html'
    proposal.write_text('''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><body>
<h1>PROPOSTA DE ACORDO — EXEMPLO FICTÍCIO</h1>
<p>NÚMERO: 0000000-00.2026.0.00.0001 (REF: 0000000-00.2026.0.00.0001)</p>
<h2>TABELA COM DADOS PARA CUMPRIMENTO</h2>
<table><tr><td>DIB</td><td>09/07/2026</td></tr><tr><td>DIP</td><td>01/09/2026</td></tr></table>
<h2>TABELA COM DADOS PARA CÁLCULO</h2>
<table><tr><td>Valor dos atrasados</td><td>R$ 2.400,00 (valores devidos entre a DIB/Restabelecimento e a DIP)</td></tr>
<tr><td>Honorários Advocatícios</td><td>Cláusula fictícia para conferência humana.</td></tr></table>
<h2>REQUERIMENTOS</h2><p>Texto sintético para teste. Nenhum processo real.</p>
<p>Belo Horizonte, 12 de setembro de 2026.</p><p>PROCURADOR FEDERAL</p>
</body></html>''',encoding='utf-8')
    result=[{'path':str(proposal),'name':'Proposta HTML fictícia.html'}]
    for index in range(2 if variant=='multiple_experts' else 1):
        path=root/f'expert-{index}.pdf'
        number=process_number('0000000-00.2026.0.00.0002' if variant=='wrong_process' else '0000000-00.2026.0.00.0001')
        lines=['AJG - Sistema Assistencia Judiciaria Gratuita','Solicitacao de Pagamento - EXEMPLO FICTICIO',
               'OFICIO REQUISITORIO DE PAGAMENTO DE HONORARIOS','Tipo de solicitacao: Pagamento',
               'Valor requisitado: 390,00',f'N. do processo: {number}',
               'Tipo de atuacao: PERITAS(OS)','Reu: INSS','Beneficiario: Perito Exemplo']
        with pymupdf.open() as pdf:
            page=pdf.new_page()
            for offset,line in enumerate(lines):page.insert_text((40,50+offset*24),line,fontsize=10)
            pdf.save(path)
        result.append({'path':str(path),'name':f'Solicitação AJG fictícia {index+1}.pdf'})
    return result
