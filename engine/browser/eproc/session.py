from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_path
from playwright.async_api import async_playwright, Error as BrowserError, TimeoutError as BrowserTimeout
from engine.ipc.contracts import AlmaError, ErrorCode, SessionState


class SessionAdapter:
    navigation_timeout_ms = 25_000
    def __init__(self, fixture_mode=False):
        self.fixture_mode = fixture_mode
        self.state = SessionState.DISCONNECTED
        self.driver = self.context = self.page = None
        self.origin = None
        self.dialog_error = None
        self._profile_lease = None

    async def connect(self, url: str, headless=False):
        url = url.strip()
        parts = urlsplit(url)
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise AlmaError(ErrorCode.IPC_ERROR, "connect")
        if self.fixture_mode:
            if parts.scheme != "http" or parts.hostname != "127.0.0.1":
                raise AlmaError(ErrorCode.IPC_ERROR, "connect")
        elif parts.scheme != "https":
            raise AlmaError(ErrorCode.IPC_ERROR, "connect")
        if self.context and (not self.page or self.page.is_closed()):
            await self.close()
        if self.context:
            if self.origin != f"{parts.scheme}://{parts.netloc}":
                raise AlmaError(ErrorCode.IPC_ERROR, "already_connected_other_origin")
            # Reopening the window must not destroy an authenticated session.
            if self.page.url == 'about:blank':
                await self._open_start_page(url)
            else:
                await self.page.bring_to_front()
            return await self.check_session()
        self.state = SessionState.CONNECTING
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.driver = await async_playwright().start()
        try:
            self.context = await self._create_context(headless)
            self.context.on('dialog', self._dialog)
            self.context.set_default_timeout(10_000)
            await self._open_start_page(url)
            return await self.check_session()
        except BrowserTimeout:
            await self.close()
            self.state = SessionState.ERROR
            raise AlmaError(ErrorCode.TIMEOUT, "browser_open", True) from None
        except BrowserError as error:
            # Never expose Playwright's raw error: it may contain profile paths or URLs.
            detail = str(error).lower()
            code = (ErrorCode.BROWSER_PROFILE_IN_USE if any(marker in detail for marker in
                    ('processsingleton', 'singletonlock', 'profile appears to be in use', 'user data directory is already in use'))
                    else ErrorCode.BROWSER_NAVIGATION_FAILED)
            await self.close()
            self.state = SessionState.ERROR
            raise AlmaError(code, "browser_open") from None
        except Exception:
            await self.close()
            self.state = SessionState.ERROR
            raise

    async def _create_context(self, headless):
        if self.fixture_mode:
            browser = await self.driver.chromium.launch(headless=headless)
            return await browser.new_context(accept_downloads=True)
        profile = user_data_path("alma", appauthor=False) / "browser-profile"
        return await self._launch_persistent(profile, headless=False)

    async def _launch_persistent(self, profile, headless=False):
        from .profile_lock import ProfileLease
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._profile_lease = ProfileLease(profile)
        # Also retain Chromium's protection against other applications/older ALMA builds.
        return await self.driver.chromium.launch_persistent_context(
            str(profile), headless=headless, accept_downloads=True, timeout=25_000)

    async def _open_start_page(self, url):
        # Persistent Chrome can restore previous tabs and leave a new blank tab in
        # front. Do not navigate pages[0] blindly or overwrite a restored process.
        blank = [page for page in self.context.pages if not page.is_closed() and page.url == 'about:blank']
        self.page = blank[-1] if blank else await self.context.new_page()
        await self.page.bring_to_front()
        response = await self.page.goto(url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
        if self.page.url == 'about:blank':
            raise AlmaError(ErrorCode.BROWSER_NAVIGATION_FAILED, "blank_start_page")
        if response and response.status >= 400:
            raise AlmaError(ErrorCode.HTTP_ERROR, "browser_open", response.status == 429 or response.status >= 500)
        await self.page.bring_to_front()

    async def _dialog(self, dialog):
        # Known operational alerts in eproc
        allowed_alerts = {
            "Aviso: Tem Evento de Expedição de Requisição Honorários Perito/Dativo.",
            "Beneficiário salvo com sucesso",
            "Honorário salvo com sucesso",
            "Requisição Intimada com Sucesso.",
            "Para imprimir corretamente, utilize o botão no canto superior direito da página"
        }
        msg = dialog.message.strip()
        is_allowed = dialog.type == 'alert' and (
            msg in allowed_alerts or any(
                prefix in msg for prefix in [
                    "Beneficiário salvo",
                    "Honorário salvo",
                    "Aviso: Tem Evento de Expedição",
                    "Para imprimir corretamente"
                ]
            )
        )
        if is_allowed:
            await dialog.accept()
        else:
            self.dialog_error = ErrorCode.UI_CHANGED
            await dialog.dismiss()

    async def check_session(self):
        if not self.page or self.page.is_closed():
            self.state = SessionState.DISCONNECTED
            return {"state": self.state}
        parts = urlsplit(self.page.url)
        if f"{parts.scheme}://{parts.netloc}" != self.origin:
            self.state = SessionState.REAUTH_REQUIRED
        elif await self.page.locator('input[type=password]').count():
            self.state = SessionState.REAUTH_REQUIRED
        else:
            # Fixture uses an explicit authenticated marker. Live profile needs
            # manual opening of the requisition and the observed authenticated shell.
            marker = '[data-alma-session="authenticated"]' if self.fixture_mode else '#selInfraUnidades, #lnkInfraSair'
            authenticated = await self.page.locator(', '.join(part.strip()+':visible' for part in marker.split(','))).count() > 0
            self.state = SessionState.AUTHENTICATED if authenticated else SessionState.REAUTH_REQUIRED
        import hashlib
        scope = ''
        if self.state == SessionState.AUTHENTICATED:
            units = self.page.locator('#selInfraUnidades:visible')
            if await units.count() == 1:
                scope = await units.input_value()
            elif not self.fixture_mode:
                # A logout link proves login, but not which unit should own a resumed queue.
                return {"state": self.state, "origin": self.origin, "scope_id": None}
        scope_id = hashlib.sha256(f'{self.origin}|{scope}'.encode()).hexdigest() if self.state == SessionState.AUTHENTICATED else None
        return {"state": self.state, "origin": self.origin, "scope_id": scope_id}

    async def require_session(self):
        if self.dialog_error:raise AlmaError(self.dialog_error,"unexpected_dialog")
        await self.check_session()
        if self.state != SessionState.AUTHENTICATED:
            raise AlmaError(ErrorCode.REAUTH_REQUIRED, "session")

    async def close(self):
        try:
            if self.context:
                await self.context.close()
        finally:
            try:
                if self.driver:
                    await self.driver.stop()
            finally:
                if self._profile_lease:
                    self._profile_lease.release()
                    self._profile_lease = None
                self.context = self.driver = self.page = None
                self.dialog_error = None
                self.state = SessionState.DISCONNECTED
