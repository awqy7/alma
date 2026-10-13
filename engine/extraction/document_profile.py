"""Observed document structure and identifiers; reconciliation belongs to Rust."""
import re
from engine.extraction.review_candidates import fold,normalize_date

CNJ=r'(?<!\d)(?:\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}|\d{20})(?!\d)'

def process_number(raw):
    value=raw.strip()
    if not re.fullmatch(CNJ,value):raise ValueError('Expected CNJ format')
    return re.sub(r'\D','',value)

def describe(parsed,document_id,name):
    rows=[dict(row,page=page['page'],method=page['method']) for page in parsed['pages']
          for row in (page.get('rows') or [{'text':line,'bbox':None} for line in page['text'].splitlines()])]
    full=fold('\n'.join(row['text'] for row in rows))
    proposal='proposta de acordo' in full or 'proposta de conciliacao' in full
    expert=('solicitacao de pagamento' in full and ('assistencia judiciaria gratuita' in full or re.search(r'\bajg\b',full)))
    profile='ambiguous' if proposal and expert else 'agreement' if proposal else 'expert_payment' if expert else 'unclassified'
    metadata={'process_number':[],'request_type':[],'actor_type':[],'defendant':[]}
    for row in rows:
        raw=row['text'];line=fold(raw)
        if re.search(r'(?:n[.º°o]*\s*(?:do\s+)?processo|numero\s*:|processo\s*:)',line):
            for match in re.finditer(CNJ,raw):
                metadata['process_number'].append({'raw':match[0],'normalized':process_number(match[0]),'text':raw,'page':row['page'],'html_location':row.get('html_location')})
        for key,pattern in [('request_type',r'tipo de solicitacao'),('actor_type',r'tipo de atuacao'),('defendant',r'reu')]:
            match=re.search(rf'\b{pattern}\s*[:|]\s*([^|]+)',line)
            if match:
                metadata[key].append({'raw':raw[match.start(1):match.end(1)].strip(),'normalized':match[1].strip(),'text':raw,'page':row['page'],'html_location':row.get('html_location')})
    closing=[]
    if profile=='agreement':
        # A closing date is not a base date. Restrict to the final document segment.
        for row in rows[-12:]:
            match=re.fullmatch(r'\s*[A-Za-zÀ-ÿ .\-]+,\s*(\d{1,2} de [A-Za-zçÇ]+ de \d{4})\.?\s*(?:PROCURADOR(?:A)? FEDERAL\.?)?\s*',row['text'],re.I)
            if not match:continue
            try:value,_=normalize_date(match[1])
            except ValueError:continue
            closing.append({'field':'proposal_date','raw':match[1],'normalized':value,'precision':'day',
                'confidence':'OCR_LOW' if row['method']=='OCR' else 'NATIVE_TEXT','ambiguous_context':False,
                'document_id':document_id,'document_name':name,'page':row['page'],'text':row['text'],
                'bbox':row.get('bbox'),'html_location':row.get('html_location'),'section':'Fecho da proposta',
                'sha256':parsed['sha256'],'source_kind':'closing_date'})
    return {'profile':profile,'metadata':metadata,'closing_candidates':closing}
