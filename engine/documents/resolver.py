import unicodedata

PATTERNS = {
    "calculation": ("CALC", "MEMORIA", "PLANILHA"),
    "agreement": ("PROACORDO", "PROPOSTA DE ACORDO", "PROPOSTA DE CONCILIACAO"), "expert_payment": ("PGTOPERITO", "PAGAMENTO DO PERITO", "PAGAMENTO PERITO"),
    "fees": ("CONTRATO", "HONORARIO"), "statement": ("MANIFESTACAO",),
    "ruling": ("SENTENCA", "DECISAO", "ACORDAO"),
}


class DocumentResolver:
    def rank(self, documents):
        result = []
        for document in documents:
            name = ''.join(c for c in unicodedata.normalize('NFD', document['name'].upper())
                           if unicodedata.category(c) != 'Mn')
            types = [kind for kind, patterns in PATTERNS.items() if any(p in name for p in patterns)]
            if types:
                # Ranking only schedules perception; never settles conflicting sources.
                score = 100 if "calculation" in types else 50
                result.append({**document, "score": score, "possible_types": types})
        return sorted(result, key=lambda d: (-d['score'], d['id']))
