"""Run: python -m engine.worker. Stdout contains JSONL only."""
import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from playwright.async_api import TimeoutError as BrowserTimeout
from engine.browser.eproc import EprocAdapter
from engine.browser.eproc.session import SessionAdapter
from engine.browser.eproc.diagnostics import response_metadata
from engine.documents.parser import parse_pdf
from engine.documents.html_parser import parse_html
from engine.documents.resolver import DocumentResolver
from engine.extraction.facts import extract_facts
from engine.documents.inspection import inspect_documents, sample_documents, inspect_parsed
from engine.extraction.normalizers import money
from engine.extraction.review_candidates import normalize_date
from engine.extraction.document_profile import process_number
from engine.ipc.contracts import AlmaError, Command, ErrorCode

MAX_LINE = 1024 * 1024
LOG = logging.getLogger("alma.worker")


class Worker:
    def __init__(self, fixture_mode=False, emit=lambda event: None):
        self.adapter = EprocAdapter(SessionAdapter(fixture_mode))
        self.temp = tempfile.TemporaryDirectory(prefix="alma-docs-", dir=os.environ.get('ALMA_TEMP_ROOT'))
        self.downloads = {}
        self.emit = emit
        self.diagnostic_listener = None
        self.demo = None

    async def dispatch(self, command):
        name, payload = command.name, command.payload
        if name == "START_DEMO":
            from engine.demo.workflow import DemoWorkflow
            if self.demo is not None:raise AlmaError(ErrorCode.IPC_ERROR,'demo_already_started')
            self.demo=DemoWorkflow(self.adapter.session,Path(self.temp.name),self.emit)
            return await self.demo.start(payload.get('show_browser') is True)
        if name == "APPLY_DEMO":
            if self.demo is None:raise AlmaError(ErrorCode.DISCOVERY_REQUIRED,'demo_not_started')
            return await self.demo.apply(payload)
        if name == "PING":
            return {"worker_version": "0.1.0", "protocol_version": 1, "read_only": True}
        if name == 'INSPECT_LOCAL_DOCUMENTS':
            root=Path(os.environ.get('ALMA_TEMP_ROOT', self.temp.name))
            sample=payload.get('sample')
            if sample not in {None,'standard','table','conflict','no_base_date','recording','wrong_process','multiple_experts'}:
                raise AlmaError(ErrorCode.IPC_ERROR,'sample')
            items=sample_documents(root,sample) if sample else payload.get('documents',[])
            if not isinstance(items,list) or not 1<=len(items)<=4:
                raise AlmaError(ErrorCode.IPC_ERROR,'documents')
            result=inspect_documents(items,root)
            result['official_total']=str(money(payload['official_total'])) if payload.get('official_total') else None
            result['official_base_date']=normalize_date(payload['official_base_date'])[0] if payload.get('official_base_date') else None
            result['expected_process']=process_number(payload['expected_process']) if payload.get('expected_process') else None
            return result
        if name == "CONNECT":
            if set(payload) - {'url', 'headless'} or not isinstance(payload.get('url'), str):
                raise AlmaError(ErrorCode.IPC_ERROR, "connect_payload")
            if 'headless' in payload and type(payload['headless']) is not bool:
                raise AlmaError(ErrorCode.IPC_ERROR, "connect_payload")
            return await self.adapter.connect(**payload)
        if name == "CHECK_SESSION": return await self.adapter.check_session()
        if name == "START_DIAGNOSTICS":
            await self.adapter.session.require_session()
            if self.diagnostic_listener is None:
                def on_response(response):
                    self.emit({"version": 1, "type": "EVENT", "name": "HTTP_METADATA", "payload": response_metadata(response)})
                self.diagnostic_listener = on_response
                self.adapter.session.context.on('response', on_response)
            return {"enabled": True, "har": False}
        if name == "STOP_DIAGNOSTICS":
            if self.diagnostic_listener and self.adapter.session.context:
                self.adapter.session.context.remove_listener('response', self.diagnostic_listener)
            self.diagnostic_listener = None
            return {"enabled": False}
        if name == "OPEN_LOCALIZER":
            if not isinstance(payload.get('name'),str):raise AlmaError(ErrorCode.IPC_ERROR,'localizer')
            return await self.adapter.open_localizer(payload['name'])
        if name == "LIST_PROCESSES":return await self.adapter.list_processes()
        if name == "OPEN_PROCESS":
            if not isinstance(payload.get('process_number'),str):raise AlmaError(ErrorCode.IPC_ERROR,'process')
            return await self.adapter.open_process(payload['process_number'])
        if name == "LIST_REQUISITIONS": return await self.adapter.list_requisitions()
        if name == "OPEN_REQUISITION":return await self.adapter.open_requisition(payload.get("requisition_id"))
        if name == "READ_PROCESS": return await self.adapter.read_process()
        if name == "READ_REQUISITION": return await self.adapter.read_requisition()
        if name == "INDEX_DOCUMENTS":
            return {"candidates": DocumentResolver().rank(await self.adapter.index_documents())}
        if name == "DOWNLOAD_DOCUMENT":
            document_id = payload.get('document_id')
            if not isinstance(document_id, str):
                raise AlmaError(ErrorCode.IPC_ERROR, "download_payload")
            path = Path(self.temp.name) / f"{len(self.downloads)}.pdf"
            metadata = await self.adapter.download_document(document_id, path)
            self.downloads[document_id] = (path, metadata)
            return {"document_id": document_id}
        if name == "PARSE_DOCUMENT":
            document_id = payload.get('document_id')
            if not isinstance(document_id, str) or document_id not in self.downloads:
                raise AlmaError(ErrorCode.DOCUMENT_NOT_FOUND, "parse")
            process_id, requisition_id = payload.get('process_id'), payload.get('requisition_id')
            if not isinstance(process_id, str) or not isinstance(requisition_id, str):
                raise AlmaError(ErrorCode.IPC_ERROR, "parse_identity")
            path, metadata = self.downloads[document_id]
            # Serial worker; Rust owns deadlines and kills/restarts on timeout.
            parsed = (parse_html(path, encoding=metadata.get('encoding') or 'utf-8-sig') if metadata.get('format') == 'HTML'
                      else parse_pdf(path, enable_ocr=payload.get('enable_ocr') is True))
            facts = extract_facts(parsed, metadata, process_id, requisition_id)
            self.emit({"version": 1, "type": "EVENT", "name": "DOCUMENT_PARSED",
                       "payload": {"command_id": command.id, "document_id": document_id,
                                   "pages": len(parsed['pages']), "facts": len(facts)}})
            return {"sha256": parsed['sha256'], "facts": facts,
                    "perception": inspect_parsed(parsed, document_id, metadata['name'], metadata.get('event')),
                    "unreadable_pages": [p['page'] for p in parsed['pages'] if p['method'] == 'UNREADABLE']}
        if name == "READ_BENEFICIARIES":
            return await self.adapter.read_beneficiaries()
        if name == "READ_FEES":
            return await self.adapter.read_fees()
        if name == "DISCOVER_PROCESSES":
            localizer = payload.get('localizer') if isinstance(payload, dict) else None
            return await self.adapter.discover_all_processes(localizer)
        if name == "APPLY_REAL_PLAN":
            if not isinstance(payload, dict):
                raise AlmaError(ErrorCode.IPC_ERROR, "apply_plan_payload")
            return await self.adapter.apply_real_plan(payload, self.emit)
        if name == "CLOSE_PROCESS":
            await self.adapter.close_process()
            self.downloads.clear()
            self.temp.cleanup()
            self.temp = tempfile.TemporaryDirectory(prefix="alma-docs-", dir=os.environ.get('ALMA_TEMP_ROOT'))
            return {}
        raise AlmaError(ErrorCode.IPC_ERROR, "unknown_command")

    async def handle(self, line):
        command_id = None
        start = time.monotonic()
        try:
            data = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(data,dict) or type(data.get('version')) is not int or data['version'] != 1:
                raise ValueError('Invalid protocol version')
            if isinstance(data, dict) and isinstance(data.get('id'), str):
                try:
                    UUID(data['id'])
                    command_id = data['id']
                except ValueError:
                    pass
            command = Command.model_validate(data)
            payload = await asyncio.wait_for(self.dispatch(command), timeout=90)
            return {"version": 1, "id": command.id, "type": "RESULT", "ok": True, "payload": payload}
        except (ValueError, TypeError, ValidationError):
            error = AlmaError(ErrorCode.IPC_ERROR, "protocol")
        except (TimeoutError, BrowserTimeout):
            error = AlmaError(ErrorCode.TIMEOUT, "worker", True)
        except AlmaError as exc:
            error = exc
        except Exception:
            error = AlmaError(ErrorCode.NOT_VERIFIABLE, "worker")
        LOG.warning(json.dumps({"component": "worker", "action": "command", "status": "ERROR",
                                "error_code": error.code, "duration_ms": int((time.monotonic()-start)*1000)}))
        return {"version": 1, "id": command_id, "type": "ERROR", "code": error.code,
                "message": error.code, "retryable": error.retryable, "stage": error.stage, "context": {}}

    async def close(self):
        try:
            if self.demo:await self.demo.close()
            await self.adapter.session.close()
        finally:
            self.temp.cleanup()


def emit(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False, allow_nan=False) + '\n')
    sys.stdout.flush()


async def main(fixture_mode=False):
    worker = Worker(fixture_mode, emit)
    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_LINE + 1)
            if not line:
                break
            if len(line) > MAX_LINE:
                emit({"version": 1, "id": None, "type": "ERROR", "code": "IPC_ERROR",
                      "message": "IPC_ERROR", "retryable": False, "stage": "line_size", "context": {}})
                break  # Lose framing -> terminate, never parse the tail as a command.
            emit(await worker.handle(line))
    finally:
        await worker.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture-mode', action='store_true', help='Loopback-only synthetic test browser')
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')
    asyncio.run(main(args.fixture_mode))
