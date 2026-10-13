from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from engine.browser.eproc.session import SessionAdapter
from engine.ipc.contracts import AlmaError


@pytest.fixture
def startup_site():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            self.send_response(503 if self.path == '/unavailable' else 200)
            self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(b'<body data-alma-session="authenticated">Synthetic login shell</body>')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown(); server.server_close(); thread.join()


async def test_blank_startup_tab_is_navigated_and_brought_forward(startup_site, monkeypatch):
    session = SessionAdapter(fixture_mode=True)
    try:
        await session.connect(startup_site, headless=True)
        restored = session.page
        await restored.evaluate("document.body.dataset.restored='keep-this-tab'")
        blank = await session.context.new_page()
        focused = []
        original = blank.bring_to_front
        async def focus():
            focused.append(True)
            await original()
        monkeypatch.setattr(blank, 'bring_to_front', focus)
        await session._open_start_page(startup_site)
        assert session.page is blank and blank.url == startup_site + '/'
        assert len(focused) == 2
        assert await restored.locator('body').get_attribute('data-restored') == 'keep-this-tab'
    finally:
        await session.close()


async def test_reopening_same_browser_preserves_context_and_page(startup_site):
    session = SessionAdapter(fixture_mode=True)
    try:
        await session.connect(startup_site, headless=True)
        context, page = session.context, session.page
        await page.evaluate("document.body.dataset.keep='yes'")
        assert (await session.connect(startup_site, headless=True))['state'] == 'AUTHENTICATED'
        assert session.context is context and session.page is page
        assert len(context.pages) == 1
        assert await page.locator('body').get_attribute('data-keep') == 'yes'
    finally:
        await session.close()


async def test_profile_collision_does_not_delete_lock_or_close_owner(startup_site, tmp_path):
    class PersistentFixture(SessionAdapter):
        async def _create_context(self, headless):
            return await self._launch_persistent(tmp_path, headless=True)
    owner, contender = PersistentFixture(True), PersistentFixture(True)
    try:
        await owner.connect(startup_site, headless=True)
        with pytest.raises(AlmaError) as error:
            await contender.connect(startup_site, headless=True)
        assert error.value.code == 'BROWSER_PROFILE_IN_USE'
        assert contender.context is None and contender.driver is None
        assert (await owner.check_session())['state'] == 'AUTHENTICATED'
        assert not owner.page.is_closed()
        await owner.close()
        assert (await contender.connect(startup_site, headless=True))['state'] == 'AUTHENTICATED'
    finally:
        await contender.close(); await owner.close()


async def test_failed_navigation_is_reported_and_retry_works(startup_site):
    session = SessionAdapter(fixture_mode=True)
    try:
        with pytest.raises(AlmaError) as error:
            await session.connect(startup_site + '/unavailable', headless=True)
        assert error.value.code == 'HTTP_ERROR'
        assert session.context is None and session.driver is None
        assert (await session.connect(startup_site, headless=True))['state'] == 'AUTHENTICATED'
    finally:
        await session.close()
