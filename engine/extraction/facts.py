import re
from datetime import datetime, timezone

from engine.extraction.normalizers import money, date
from engine.ipc.contracts import Evidence, ExtractedFact

# Match complete labelled lines, never a loose numeric occurrence in prose.
LABELS = {
    "total_value": r"Total da requisição",
    "principal": r"(?:Valor principal|Principal)",
    "interest": r"(?:Juros|Valor dos juros)",
    "selic": r"(?:SELIC|Parcela SELIC)",
    "irpf": r"IRPF", "pss": r"PSS", "fee_total": r"Honorários",
    "base_date": r"Data[- ]base",
}


def extract_facts(parsed, document, process_id, requisition_id, subject_id=None):
    facts = []
    text='\n'.join(page['text'] for page in parsed['pages'] if page['method'] in {'NATIVE','PDFPLUMBER','HTML_DOM'})
    # Ranking does not prove that a calculation belongs to this RPV. Initially
    # require explicit document identifiers; beneficiary matching needs discovery.
    scope_verified = subject_id is None and all({match.strip() for match in re.findall(
        rf'^[ \t]*{label}[ \t]*:[ \t]*(.+?)[ \t]*$', text, re.MULTILINE | re.IGNORECASE)} == {value}
        for label,value in [('Processo',process_id),('Requisição',requisition_id)])
    for page in parsed['pages']:
        for line in page['text'].splitlines():
            for field, label in LABELS.items():
                match = re.fullmatch(rf"\s*{label}\s*:\s*(.+?)\s*", line, re.IGNORECASE)
                if not match:
                    continue
                raw = match.group(1)
                try:
                    normalized = date(raw) if field == 'base_date' else str(money(raw))
                except ValueError:
                    continue
                source = Evidence(process_id=process_id, requisition_id=requisition_id,
                    document_id=document['id'], document_name=document['name'], event=document.get('event'),
                    page=page['page'], html_location=next((r.get('html_location') for r in page.get('rows',[]) if r['text']==line),None), raw_text=line, normalized_value=normalized, sha256=parsed['sha256'],
                    extracted_at=datetime.now(timezone.utc).isoformat())
                facts.append(ExtractedFact(field=field, subject_id=subject_id, scope_verified=bool(scope_verified), value_raw=raw,
                    value_normalized=normalized, source=source,
                    confidence="OCR_LOW" if page['method'] == 'OCR' else "EXACT_TEXT").model_dump())
    return facts
