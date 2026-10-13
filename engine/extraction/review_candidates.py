"""Document observations, not decisions. Variations are explicit and testable."""
import re
import unicodedata
from datetime import datetime
from engine.extraction.normalizers import money, date

MONEY = r'(?<![\d.,])(?:r\$\s*)?-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}(?![\d.,])'
DATES = r'\d{2}/\d{2}/\d{4}|\d{2}/\d{4}|\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}'
MONTHS = dict(zip(['janeiro','fevereiro','marco','abril','maio','junho','julho','agosto','setembro','outubro','novembro','dezembro'],range(1,13)))
PATTERNS = {
    'arrears_amount': r'(?:total (?:dos |de )?atrasados|valor (?:dos |de )?atrasados|montante (?:das )?parcelas vencidas|total (?:das )?parcelas vencidas)',
    'agreement_amount': r'(?:valor (?:total )?do acordo|valor (?:total )?da proposta)',
    'expert_amount': r'(?:valor requisitado ao perito|valor solicitado (?:para |de )?pagamento (?:do |ao )perito|honorarios periciais|pagamento (?:do |ao )perito)',
    'base_date': r'(?:data[ -]base(?: (?:do calculo|dos calculos|de atualizacao))?|competencia[ -]base)',
    'proposal_date': r'(?:data da proposta|proposta (?:de acordo )?datada de|proposta apresentada em)',
    'payment_date': r'(?:data do pagamento|pago em)',
}


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower()) if not unicodedata.combining(c))


def normalize_date(raw):
    text=fold(raw.strip())
    if re.fullmatch(r'\d{2}/\d{4}',text):
        return datetime.strptime(text,'%m/%Y').strftime('%Y-%m'), 'month'
    if re.fullmatch(r'\d{2}/\d{2}/\d{4}',text):
        return date(text), 'day'
    match=re.fullmatch(r'(\d{1,2}) de ([a-z]+) de (\d{4})',text)
    if not match or match[2] not in MONTHS: raise ValueError('Invalid date')
    return datetime(int(match[3]),MONTHS[match[2]],int(match[1])).date().isoformat(), 'day'


def collect_candidates(parsed, document_id, name, profile='unclassified'):
    observations=[]
    for page in parsed['pages']:
        # Layout rows come from word geometry; no joining across pages/paragraphs.
        rows=page.get('rows') or [{'text':line,'bbox':None} for line in page['text'].splitlines()]
        for index,row in enumerate(rows):
            raw=row['text'].strip(); text=fold(raw)
            patterns=dict(PATTERNS)
            if profile=='expert_payment':patterns['expert_amount']=r'(?:valor requisitado)(?! ao perito)|'+patterns['expert_amount']
            for field, pattern in patterns.items():
                label=re.search(pattern,text)
                if not label: continue
                tail=text[label.end():]
                value_pattern=DATES if field.endswith('_date') else MONEY
                found=list(re.finditer(value_pattern,tail))
                source_text=raw
                source_box=row.get('bbox')
                token_offset=label.end()
                if not found and re.fullmatch(r'[\s:|=\-]*',tail) and index+1<len(rows):
                    following=rows[index+1]
                    next_text=following['text'].strip()
                    near=(not source_box or not following.get('bbox') or
                          0<=following['bbox'][1]-source_box[3]<=28)
                    if near and re.fullmatch(value_pattern,fold(next_text)):
                        tail=fold(next_text);found=list(re.finditer(value_pattern,tail));token_offset=0
                        source_text=raw+'\n'+next_text
                        raw_value=next_text
                        if source_box and following.get('bbox'):
                            box=following['bbox'];source_box=[min(source_box[0],box[0]),min(source_box[1],box[1]),max(source_box[2],box[2]),max(source_box[3],box[3])]
                    else: raw_value=raw
                else: raw_value=raw
                indeterminate=bool(re.search(r'\b(?:a apurar|a calcular|valor indefinido)\b',text))
                if not found and indeterminate:
                    observations.append({'field':field,'raw':raw,'normalized':None,'precision':None,
                        'confidence':'NATIVE_TEXT' if page['method']!='OCR' else 'OCR_LOW','ambiguous_context':True,
                        'document_id':document_id,'document_name':name,'page':page['page'],'text':source_text,
                        'bbox':source_box,'sha256':parsed['sha256'],'html_location':row.get('html_location'),
                        'section':row.get('section'),'source_kind':'indeterminate'})
                for match in found:
                    token=raw_value[token_offset+match.start():token_offset+match.end()]
                    try:
                        value,precision=normalize_date(token) if field.endswith('_date') else (str(money(token)), 'cent')
                    except (ValueError,ArithmeticError): continue
                    blocked=bool(re.search(r'\b(nao|sem|cancelad[oa]|revogad[oa]|anterior|substituid[oa]|pag[oa]s?)\b',text))
                    request_context=bool(re.search(r'requisitad|solicitad|solicita.se|requer.se|requer o pagamento',text))
                    observations.append({'field':field,'raw':token,'normalized':value,'precision':precision,
                        'confidence':'OCR_LOW' if page['method']=='OCR' else 'NATIVE_TEXT',
                        'ambiguous_context':indeterminate or blocked or value.startswith('-') or value=='0.00' or len(found)!=1 or (field=='expert_amount' and not request_context),
                        'document_id':document_id,'document_name':name,'page':page['page'],
                        'text':source_text,'bbox':source_box,'sha256':parsed['sha256'],
                        'html_location':row.get('html_location'),'section':row.get('section'),'source_kind':'label'})
    return observations
