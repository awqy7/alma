"""Fetch only document links indexed from the authenticated process DOM.

No endpoint construction, cookie export, automatic redirect or script execution.
HTML wrappers with embedded viewers require further mapping instead of being
mistaken for the document itself.
"""
import re
from urllib.parse import urlsplit

from engine.ipc.contracts import AlmaError, ErrorCode
from .navigation import checked_link, canonical_process

MAX_BYTES = 32 * 1024 * 1024


async def fetch_indexed(session, document, destination, process):
    await session.require_session()
    url = document['url']
    if not session.fixture_mode:
        _, query = checked_link(session.origin, session.page.url, url, {'acessar_documento'})
        if not process or query.get('numProcesso') != [canonical_process(process)]:
            raise AlmaError(ErrorCode.PROCESS_NOT_FOUND, 'document_identity')
    elif f'{urlsplit(url).scheme}://{urlsplit(url).netloc}' != session.origin:
        raise AlmaError(ErrorCode.UI_CHANGED, 'document_origin')
    response = await session.context.request.get(url, max_redirects=0, timeout=30_000)
    try:
        if response.status in {301, 302, 303, 307, 308, 401, 403}:
            # A redirect can be an expired session. Never follow it with credentials.
            raise AlmaError(ErrorCode.REAUTH_REQUIRED, 'document_response')
        if response.status == 429:
            raise AlmaError(ErrorCode.RATE_LIMITED, 'download', True)
        if response.status >= 500:
            raise AlmaError(ErrorCode.HTTP_ERROR, 'download', True)
        if response.status != 200:
            raise AlmaError(ErrorCode.DOWNLOAD_FAILED, 'download')
        length = response.headers.get('content-length')
        if length and (not length.isdigit() or int(length) > MAX_BYTES):
            raise AlmaError(ErrorCode.DOWNLOAD_FAILED, 'document_size')
        body = await response.body()
        if not body or len(body) > MAX_BYTES:
            raise AlmaError(ErrorCode.DOWNLOAD_FAILED, 'document_size')
        content_type = response.headers.get('content-type', '').lower()
        if body.startswith(b'%PDF-'):
            kind = 'PDF'
        elif content_type.split(';')[0].strip() == 'text/html':
            if len(body) > 8 * 1024 * 1024:
                raise AlmaError(ErrorCode.DOWNLOAD_FAILED, 'html_size')
            charset = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type)
            encoding = charset.group(1) if charset else 'utf-8-sig'
            if encoding not in {'utf-8', 'utf-8-sig', 'iso-8859-1', 'windows-1252'}:
                raise AlmaError(ErrorCode.NOT_VERIFIABLE, 'html_encoding')
            try:
                html = body.decode(encoding)
            except UnicodeError:
                raise AlmaError(ErrorCode.NOT_VERIFIABLE, 'html_encoding') from None
            from engine.documents.html_parser import Reader, Node
            reader = Reader()
            try:
                reader.feed(html); reader.close()
            except ValueError:
                raise AlmaError(ErrorCode.NOT_VERIFIABLE, 'html_structure') from None
            def nodes(node):
                yield node
                for child in node.children:
                    if isinstance(child, Node):
                        yield from nodes(child)
            elements = list(nodes(reader.root))
            if any(n.tag == 'input' and n.attrs.get('type', '').lower() == 'password' for n in elements):
                raise AlmaError(ErrorCode.REAUTH_REQUIRED, 'document_login')
            if any(n.tag in {'iframe', 'embed', 'object'} for n in elements):
                raise AlmaError(ErrorCode.DISCOVERY_REQUIRED, 'document_viewer')
            kind = 'HTML'
        else:
            raise AlmaError(ErrorCode.DOWNLOAD_FAILED, 'document_format')
        # Re-check the controlling RPV tab; a login page must not become evidence.
        await session.require_session()
        destination.write_bytes(body)
        return {**document, 'format': kind, 'encoding': encoding if kind == 'HTML' else None}
    finally:
        await response.dispose()
