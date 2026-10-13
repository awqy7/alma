"""Read-only navigation and document acquisition from observed DOM links."""
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from engine.extraction import normalizers
from engine.ipc.contracts import AlmaError, ErrorCode, FieldValue, Requisition, RpvSnapshot
from .selectors import SelectorRegistry, PageFingerprint
from .session import SessionAdapter
from .navigation import existing_links,checked_link,canonical_process,go


class EprocAdapter:
    def __init__(self, session: SessionAdapter):
        self.session = session
        self.registry = SelectorRegistry()
        self.documents = {}
        self.process_page = None
        self.requisition_page = None
        self.process_links = {}
        self.current_process = None

    async def connect(self, **kwargs):
        return await self.session.connect(**kwargs)

    async def check_session(self):
        return await self.session.check_session()

    async def scope(self):
        await self.session.require_session()
        candidates = []
        # A manually opened RPV often lives in a new tab. Never choose by tab order.
        for page in self.session.context.pages:
            if page.is_closed():
                continue
            for frame in page.frames:
                parts = urlsplit(frame.url)
                if f"{parts.scheme}://{parts.netloc}" != self.session.origin:
                    continue
                has_total = await frame.locator('#txtValorTotal').count() > 0
                has_form = (
                    await frame.locator('#frmOficioRequisitorio').count() > 0
                    or 'oficio_requisitorio_requisicoes_' in frame.url
                )
                has_proc = (
                    await frame.locator('#txtNumProcessoOrigem, #txtNumProcessoView, #txtNumProcesso').count() > 0
                    or 'txtNumProcesso' in frame.url
                )
                if (has_total or has_form) and has_proc:
                    candidates.append((page, frame))

        if len(candidates) != 1:
            raise AlmaError(ErrorCode.UI_CHANGED if not candidates else ErrorCode.FIELD_AMBIGUOUS, "requisition")
        page, frame = candidates[0]
        self.session.page = page
        await self.session.require_session()
        await PageFingerprint().verify(frame, self.registry)
        return frame

    async def read_process(self):
        scope = await self.scope()
        el = await self.registry.resolve(scope, "process_number")
        if el is not None:
            val = (await el.input_value()).strip()
            if val:
                return {"process_number": val}
        from urllib.parse import parse_qs
        qs = parse_qs(urlsplit(scope.url).query)
        if "txtNumProcesso" in qs and qs["txtNumProcesso"][0]:
            return {"process_number": qs["txtNumProcesso"][0]}
        return {"process_number": ""}

    async def read_requisition(self):
        scope = await self.scope()
        fields = {}
        for key in ("process_number", "subject", "entity", "filing_date", "transition_date", "total_value"):
            el = await self.registry.resolve(scope, key)
            if el is None:
                if key == "process_number":
                    from urllib.parse import parse_qs
                    qs = parse_qs(urlsplit(scope.url).query)
                    val = qs.get("txtNumProcesso", [""])[0]
                    if val:
                        fields[key] = FieldValue(raw=val, normalized=val, presence="present")
                        continue
                fields[key] = FieldValue(presence="unknown")
                continue
            raw = (await el.locator('option:checked').inner_text()) if await el.evaluate('el=>el.tagName.toLowerCase()') == 'select' else await el.input_value()
            normalized = None
            presence = "present" if raw.strip() else "missing"
            if presence == "present":
                try:
                    normalized = (str(normalizers.money(raw)) if key == "total_value" else
                                  normalizers.date(raw) if key.endswith('_date') else raw.strip())
                except ValueError:
                    presence = "unknown"
            fields[key] = FieldValue(raw=raw, normalized=normalized, presence=presence)
        req = await self.registry.resolve(scope, 'requisition_id')
        req_id = (await req.input_value()).strip() if req else ""
        if not req_id:
            from urllib.parse import parse_qs
            qs = parse_qs(urlsplit(scope.url).query)
            req_id = qs.get("numIdOficioRequisitorio", [""])[0] or qs.get("id_oficio_requisitorio", [""])[0]
        if not req_id:
            raise AlmaError(ErrorCode.REQUISITION_NOT_FOUND, 'requisition_identity')
        return RpvSnapshot(process_id=fields['process_number'].raw or "", requisition_id=req_id,
            requisition=Requisition(fields=fields), captured_at=datetime.now(timezone.utc).isoformat(),
            coverage={"requisition": "read", "beneficiaries": "unknown", "fees": "unknown"}).model_dump()

    async def _discovery(self, stage):
        await self.session.require_session()
        raise AlmaError(ErrorCode.DISCOVERY_REQUIRED, stage)

    async def open_localizer(self, name):
        from .queue_navigation import open_localizer
        return await open_localizer(self, name)

    async def list_processes(self):
        from .queue_navigation import list_processes
        return await list_processes(self)

    async def discover_all_processes(self, localizer_name=None):
        from .queue_navigation import discover
        return await discover(self, localizer_name or 'Concluso Decisão RPV')

    async def open_process(self, number):
        from .queue_navigation import open_process
        return await open_process(self, number)

    async def list_requisitions(self):
        from .queue_navigation import list_requisitions
        return await list_requisitions(self)

    async def open_requisition(self, requisition_id=None):
        from .queue_navigation import open_requisition
        return await open_requisition(self, requisition_id)

    async def read_beneficiaries(self):
        scope = await self.scope()
        container = scope.locator("#divConteudoBeneficiarios")
        if await container.count() == 0:
            return []
        rows = container.locator("table tbody tr")
        if await rows.count() == 0:
            rows = container.locator("tr")
        count = await rows.count()
        beneficiaries = []
        for i in range(count):
            row = rows.nth(i)
            if await row.locator("th").count() > 0:
                continue
            cells = row.locator("td")
            cell_count = await cells.count()
            if cell_count < 2:
                continue
            texts = [ (await cells.nth(j).inner_text()).strip() for j in range(cell_count) ]
            beneficiaries.append({
                "index": i,
                "cells": texts,
                "text": " | ".join(t for t in texts if t)
            })
        return beneficiaries

    async def read_fees(self):
        scope = await self.scope()
        container = scope.locator("#divConteudoHonorarios")
        if await container.count() == 0:
            # Fallback to secondary table in beneficiary container if eproc groups them
            container = scope.locator("#divConteudoBeneficiarios table:nth-of-type(2)")
            if await container.count() == 0:
                return []
        rows = container.locator("tr")
        count = await rows.count()
        fees = []
        for i in range(count):
            row = rows.nth(i)
            if await row.locator("th").count() > 0:
                continue
            cells = row.locator("td")
            cell_count = await cells.count()
            if cell_count < 2:
                continue
            texts = [ (await cells.nth(j).inner_text()).strip() for j in range(cell_count) ]
            fees.append({
                "index": i,
                "cells": texts,
                "text": " | ".join(t for t in texts if t)
            })
        return fees

    async def apply_real_plan(self, plan: dict, emit=lambda event: None):
        from .automation import apply_eproc_plan
        return await apply_eproc_plan(self, plan, emit)

    async def index_documents(self):
        await self.session.require_session()
        if not self.session.fixture_mode:
            return await self._index_live_documents()
        self.documents.clear()
        for anchor in await self.session.page.locator('a[data-document]').all():
            url = urljoin(self.session.page.url, await anchor.get_attribute('href') or '')
            parts = urlsplit(url)
            if f"{parts.scheme}://{parts.netloc}" != self.session.origin or parts.query or parts.fragment:
                raise AlmaError(ErrorCode.UI_CHANGED, "document_index")
            document = {"id": str(uuid4()), "name": await anchor.inner_text(),
                "event": await anchor.get_attribute('data-event'), "mime_type": "application/pdf", "url": url}
            self.documents[document['id']] = document
        # URLs are kept inside worker, not persisted in audit/logs.
        return [{k: v for k, v in doc.items() if k != 'url'} for doc in self.documents.values()]

    async def _index_live_documents(self):
        self.documents.clear()
        target=canonical_process((await self.read_process())['process_number'])
        pages=[]
        from urllib.parse import parse_qs
        for page in self.session.context.pages:
            query=parse_qs(urlsplit(page.url).query)
            if f'{urlsplit(page.url).scheme}://{urlsplit(page.url).netloc}'==self.session.origin and query.get('acao')==['processo_selecionar'] and canonical_process(query.get('num_processo',[''])[0])==target:
                pages.append(page)
        if len(pages)!=1:raise AlmaError(ErrorCode.PROCESS_NOT_FOUND,'document_process_page')
        links=await existing_links(pages[0],self.session.origin,{'acessar_documento'})
        for url,(query,element) in links.items():
            if canonical_process(query.get('numProcesso',[''])[0])!=target:continue
            name=(await element.inner_text()).strip()
            if not name:continue
            event=query.get('numSeqEvento',[None])[0]
            if event is not None and not event.isdigit():event=None
            item={'id':str(uuid4()),'name':name,'event':event,'mime_type':query.get('MimeType',['unknown'])[0],'url':url}
            self.documents[item['id']]=item
        return [{k:v for k,v in d.items() if k!='url'} for d in self.documents.values()]

    async def download_document(self, document_id, destination):
        await self.session.require_session()
        if document_id not in self.documents:
            raise AlmaError(ErrorCode.DOCUMENT_NOT_FOUND, "download")
        from .documents import fetch_indexed
        target = (await self.read_process())['process_number']
        return await fetch_indexed(self.session, self.documents[document_id], destination, target)

    async def close_process(self):
        self.documents.clear()
