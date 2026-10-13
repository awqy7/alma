"""Bounded discovery of the configured queue, following existing links only."""
from urllib.parse import parse_qs, urlsplit
from .navigation import checked_link, existing_links, canonical_process, go
from engine.ipc.contracts import AlmaError, ErrorCode


async def open_localizer(adapter, name):
    session = adapter.session
    await session.require_session()
    page = session.page
    links = await existing_links(page, session.origin, {'usuario_tipo_monitoramento_localizador_listar'})
    button = None
    menu = []
    for url, (_, element) in links.items():
        if await element.get_attribute('id') == 'btn-meus-localizadores':
            button = url
        elif 'meus localizadores' in (await element.inner_text()).strip().lower():
            menu.append(url)
    if button:
        # The navbar entry is an icon link; its id is the stable anchor.
        await go(session, page, button)
    elif len(menu) > 1:
        raise AlmaError(ErrorCode.FIELD_AMBIGUOUS, 'localizer_menu')
    elif menu:
        await go(session, page, menu[0])
    # Only rows exposing the localizer's process list are real queue rows; the
    # page also carries hidden selects whose "Nome - Nome" options would match.
    queue = page.locator('tr').filter(has=page.locator('a[href*="acao=localizador_processos_lista"]'))
    rows = queue.filter(has=page.get_by_text(name, exact=True))
    if await rows.count() != 1:
        # eproc labels this table's rows as "Nome - Nome", so the label is not exact.
        rows = queue.filter(has=page.get_by_text(name))
        count = await rows.count()
        try:
            with open('/tmp/alma-localizer-debug.log', 'a', encoding='utf-8') as handle:
                for tr in await page.locator('tr').all():
                    text = (await tr.inner_text()).strip()
                    if name in text:
                        handle.write(f"match tr={tr!r} text={text[:160]!r}\n")
                handle.write(f"queue_rows={await queue.count()} exact={await queue.filter(has=page.get_by_text(name, exact=True)).count()} sub={count}\n")
        except Exception:
            pass
        if count != 1:
            raise AlmaError(ErrorCode.LOCALIZER_NOT_FOUND if count == 0 else ErrorCode.FIELD_AMBIGUOUS,
                            'localizer_row')
    targets = set()
    for link in await rows.locator('a[href]').all():
        try:
            url, _ = checked_link(session.origin, page.url, await link.get_attribute('href'), {'localizador_processos_lista'})
        except AlmaError:
            continue
        targets.add(url)
    if len(targets) != 1:
        raise AlmaError(ErrorCode.UI_CHANGED, 'localizer_link')
    await go(session, page, targets.pop())
    return {'opened': True}


async def list_processes(adapter):
    await adapter.session.require_session()
    links = await existing_links(adapter.session.page, adapter.session.origin, {'processo_selecionar'})
    result = []
    for url, (query, _) in links.items():
        values = query.get('num_processo', [])
        if len(values) != 1 or len(canonical_process(values[0])) != 20:
            continue
        key = canonical_process(values[0])
        if key not in {item['process_number'] for item in result}:
            result.append({'process_number': key})
        adapter.process_links[key] = url  # Signed links may be renewed across pages.
    return result


async def discover(adapter, name):
    adapter.process_links.clear()
    await open_localizer(adapter, name)
    page = adapter.session.page
    visited = set()
    for _ in range(100):
        if page.url in visited:
            raise AlmaError(ErrorCode.UI_CHANGED, 'pagination_cycle')
        visited.add(page.url)
        await list_processes(adapter)
        if len(adapter.process_links) > 10_000:
            raise AlmaError(ErrorCode.DISCOVERY_REQUIRED, 'queue_limit')
        # Semantic next-page links only; a JS-only control needs separate mapping.
        next_links = page.locator('a[rel="next"], a[aria-label="Próxima página"], a[title="Próxima página"]')
        if not await next_links.count():
            next_links = page.get_by_role('link', name='Próxima', exact=True)
        active = []
        for link in await next_links.all():
            if await link.is_visible() and await link.get_attribute('aria-disabled') != 'true':
                active.append(link)
        if not active:
            if await page.get_by_role('button', name='Próxima', exact=True).is_visible():
                raise AlmaError(ErrorCode.DISCOVERY_REQUIRED, 'pagination_control')
            return [{'process_number': number} for number in adapter.process_links]
        targets = set()
        for link in active:
            url, _ = checked_link(adapter.session.origin, page.url, await link.get_attribute('href'), {'localizador_processos_lista'})
            targets.add(url)
        if len(targets) != 1:
            raise AlmaError(ErrorCode.UI_CHANGED, 'pagination_link')
        await go(adapter.session, page, targets.pop())
    raise AlmaError(ErrorCode.DISCOVERY_REQUIRED, 'pagination_limit')


async def open_process(adapter, number):
    key = canonical_process(number)
    if key not in adapter.process_links:
        raise AlmaError(ErrorCode.PROCESS_NOT_FOUND, 'unindexed_process')
    # Reuse two owned pages; never close an employee's unrelated tab.
    if adapter.requisition_page and not adapter.requisition_page.is_closed():
        adapter.session.page = adapter.process_page or adapter.session.page
        await adapter.requisition_page.close()
        adapter.requisition_page = None
    await go(adapter.session, adapter.session.page, adapter.process_links[key])
    adapter.process_page = adapter.session.page
    adapter.current_process = key
    adapter.requisition_links = {}
    return {'opened': True}


async def list_requisitions(adapter):
    session = adapter.session
    await session.require_session()
    page = adapter.process_page
    if not page or page.is_closed():
        raise AlmaError(ErrorCode.PROCESS_NOT_FOUND, 'process_page')
    link = page.locator('#fldAcoes').get_by_role('link', name='Ofício Requisitório', exact=True)
    if await link.count() != 1:
        raise AlmaError(ErrorCode.UI_CHANGED, 'requisition_action')
    url, _ = checked_link(session.origin, page.url, await link.get_attribute('href'),
                          {'oficio_requisitorio_listar', 'oficio_requisitorio_requisicoes_editar'})
    if not adapter.requisition_page or adapter.requisition_page.is_closed():
        adapter.requisition_page = await session.context.new_page()
    await go(session, adapter.requisition_page, url)
    direct = parse_qs(urlsplit(url).query)
    links = ({url: (direct, None)} if direct.get('acao') == ['oficio_requisitorio_requisicoes_editar']
             else await existing_links(adapter.requisition_page, session.origin, {'oficio_requisitorio_requisicoes_editar'}))
    adapter.requisition_links = {}
    for url, (query, _) in links.items():
        ids = query.get('numIdOficioRequisitorio', [])
        if len(ids) != 1 or not ids[0]:
            raise AlmaError(ErrorCode.UI_CHANGED, 'requisition_identity')
        adapter.requisition_links[ids[0]] = url
    if not links:
        raise AlmaError(ErrorCode.REQUISITION_NOT_FOUND, 'requisition_list')
    # Refuse to claim full coverage of an untraversed requisition list.
    if await adapter.requisition_page.locator('a[rel="next"]:visible').count():
        raise AlmaError(ErrorCode.DISCOVERY_REQUIRED, 'requisition_pagination')
    return [{'requisition_id': key} for key in adapter.requisition_links]


async def open_requisition(adapter, requisition_id=None):
    if not getattr(adapter, 'requisition_links', None):
        await list_requisitions(adapter)
    if requisition_id is None:
        if len(adapter.requisition_links) != 1:
            raise AlmaError(ErrorCode.FIELD_AMBIGUOUS, 'choose_requisition')
        requisition_id = next(iter(adapter.requisition_links))
    if requisition_id not in adapter.requisition_links:
        raise AlmaError(ErrorCode.REQUISITION_NOT_FOUND, 'unindexed_requisition')
    await go(adapter.session, adapter.requisition_page, adapter.requisition_links[requisition_id])
    read = await adapter.read_process()
    if canonical_process(read['process_number']) != adapter.current_process:
        raise AlmaError(ErrorCode.PROCESS_NOT_FOUND, 'requisition_identity')
    return {'opened': True}
