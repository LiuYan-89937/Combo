from __future__ import annotations

import asyncio
import atexit
import base64
import ipaddress
import json
import logging
import os
import socket
import threading
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from agent_factory.tooling.execution_context import register_runtime_tool_cancellation

BROWSER_RUNTIME_RESOURCE = "browser_runtime"
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BrowserRuntimeConfig:
    headless: bool = True
    allow_private_hosts: bool = False
    default_timeout_ms: int = 30_000
    navigation_timeout_ms: int = 45_000
    max_contexts: int = 24
    max_pages_per_context: int = 12
    idle_context_seconds: int = 1_800
    viewport_width: int = 1440
    viewport_height: int = 900
    max_snapshot_links: int = 200
    host_validation_ttl_seconds: int = 300
    executable_path: str | None = None

    @classmethod
    def from_environment(cls) -> BrowserRuntimeConfig:
        return cls(
            headless=_env_bool("AGENTFACTORY_BROWSER_HEADLESS", True),
            allow_private_hosts=_env_bool("AGENTFACTORY_BROWSER_ALLOW_PRIVATE_HOSTS", False),
            default_timeout_ms=_env_int("AGENTFACTORY_BROWSER_TIMEOUT_MS", 30_000, minimum=1_000),
            navigation_timeout_ms=_env_int(
                "AGENTFACTORY_BROWSER_NAVIGATION_TIMEOUT_MS",
                45_000,
                minimum=1_000,
            ),
            max_contexts=_env_int("AGENTFACTORY_BROWSER_MAX_CONTEXTS", 24, minimum=1),
            max_pages_per_context=_env_int("AGENTFACTORY_BROWSER_MAX_PAGES", 12, minimum=1),
            idle_context_seconds=_env_int(
                "AGENTFACTORY_BROWSER_IDLE_CONTEXT_SECONDS",
                1_800,
                minimum=60,
            ),
            viewport_width=_env_int("AGENTFACTORY_BROWSER_VIEWPORT_WIDTH", 1440, minimum=320),
            viewport_height=_env_int("AGENTFACTORY_BROWSER_VIEWPORT_HEIGHT", 900, minimum=240),
            max_snapshot_links=_env_int(
                "AGENTFACTORY_BROWSER_MAX_SNAPSHOT_LINKS",
                200,
                minimum=1,
            ),
            host_validation_ttl_seconds=_env_int(
                "AGENTFACTORY_BROWSER_HOST_VALIDATION_TTL_SECONDS",
                300,
                minimum=1,
            ),
            executable_path=_optional_env("AGENTFACTORY_BROWSER_EXECUTABLE_PATH"),
        )


@dataclass(slots=True)
class BrowserSession:
    context: Any
    pages: dict[str, Any] = field(default_factory=dict)
    active_page_id: str | None = None
    last_used_at: float = field(default_factory=time.monotonic)


class BrowserRuntime:
    """One managed Chromium process with an isolated BrowserContext per Agent session."""

    def __init__(self, config: BrowserRuntimeConfig | None = None) -> None:
        self.config = config or BrowserRuntimeConfig.from_environment()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="agentfactory-browser-runtime",
            daemon=True,
        )
        self._thread.start()
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._sessions: dict[str, BrowserSession] = {}
        self._start_lock: asyncio.Lock | None = None
        self._safe_hosts: dict[tuple[str, int], float] = {}
        self._closed = False

    def open(
        self,
        *,
        session_key: str,
        url: str,
        page_id: str | None,
        wait_until: str,
    ) -> dict[str, Any]:
        return self._call(self._open(session_key, url, page_id, wait_until))

    def snapshot(
        self,
        *,
        session_key: str,
        page_id: str | None,
        max_chars: int,
        include_links: bool,
    ) -> dict[str, Any]:
        return self._call(self._snapshot(session_key, page_id, max_chars, include_links))

    def click(
        self, *, session_key: str, page_id: str | None, target: dict[str, Any]
    ) -> dict[str, Any]:
        return self._call(self._click(session_key, page_id, target))

    def type_text(
        self,
        *,
        session_key: str,
        page_id: str | None,
        target: dict[str, Any],
        text: str,
        clear: bool,
        submit: bool,
    ) -> dict[str, Any]:
        return self._call(self._type_text(session_key, page_id, target, text, clear, submit))

    def select(
        self,
        *,
        session_key: str,
        page_id: str | None,
        target: dict[str, Any],
        values: list[str],
    ) -> dict[str, Any]:
        return self._call(self._select(session_key, page_id, target, values))

    def press(
        self,
        *,
        session_key: str,
        page_id: str | None,
        key: str,
        target: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._call(self._press(session_key, page_id, key, target))

    def scroll(
        self,
        *,
        session_key: str,
        page_id: str | None,
        delta_x: int,
        delta_y: int,
        target: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._call(self._scroll(session_key, page_id, delta_x, delta_y, target))

    def wait(
        self,
        *,
        session_key: str,
        page_id: str | None,
        milliseconds: int,
        target: dict[str, Any] | None,
        state: str,
    ) -> dict[str, Any]:
        return self._call(self._wait(session_key, page_id, milliseconds, target, state))

    def extract(
        self,
        *,
        session_key: str,
        page_id: str | None,
        selector: str | None,
        format_name: str,
        max_chars: int,
    ) -> dict[str, Any]:
        return self._call(self._extract(session_key, page_id, selector, format_name, max_chars))

    def screenshot(
        self,
        *,
        session_key: str,
        page_id: str | None,
        full_page: bool,
        target: dict[str, Any] | None,
        output_path: Path,
    ) -> dict[str, Any]:
        return self._call(self._screenshot(session_key, page_id, full_page, target, output_path))

    def download(
        self,
        *,
        session_key: str,
        page_id: str | None,
        target: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any]:
        return self._call(self._download(session_key, page_id, target, output_path))

    def upload(
        self,
        *,
        session_key: str,
        page_id: str | None,
        target: dict[str, Any],
        paths: list[Path],
    ) -> dict[str, Any]:
        return self._call(self._upload(session_key, page_id, target, paths))

    def tabs(self, *, session_key: str) -> dict[str, Any]:
        return self._call(self._tabs(session_key))

    def close(
        self,
        *,
        session_key: str,
        page_id: str | None,
        close_context: bool,
    ) -> dict[str, Any]:
        return self._call(self._close(session_key, page_id, close_context))

    def shutdown(self) -> None:
        if self._closed:
            return
        try:
            self._call(self._shutdown(), timeout=15, allow_closed=True)
        except Exception as exc:
            LOGGER.debug("browser runtime shutdown did not complete cleanly: %s", exc)
        self._closed = True
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(
        self,
        operation: Coroutine[Any, Any, dict[str, Any] | None],
        *,
        timeout: int | None = None,
        allow_closed: bool = False,
    ):
        if self._closed and not allow_closed:
            operation.close()
            raise RuntimeError("browser runtime is closed")
        future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        unregister = register_runtime_tool_cancellation(future.cancel)
        try:
            return future.result(timeout=timeout)
        finally:
            unregister()

    async def _ensure_started(self) -> None:
        if self._browser is not None:
            return
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        async with self._start_lock:
            if self._browser is not None:
                return
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "Playwright is not installed. Install project dependencies and run "
                    "'python -m playwright install chromium'."
                ) from exc
            self._playwright = await async_playwright().start()
            launch_options: dict[str, Any] = {"headless": self.config.headless}
            if self.config.executable_path:
                launch_options["executable_path"] = self.config.executable_path
            try:
                self._browser = await self._playwright.chromium.launch(**launch_options)
            except Exception as exc:
                await self._playwright.stop()
                self._playwright = None
                raise RuntimeError(
                    "Chromium could not be started. Run 'python -m playwright install chromium' "
                    f"or configure AGENTFACTORY_BROWSER_EXECUTABLE_PATH. Detail: {exc}"
                ) from exc

    async def _session(self, session_key: str) -> BrowserSession:
        await self._ensure_started()
        await self._remove_idle_sessions()
        existing = self._sessions.get(session_key)
        if existing is not None:
            existing.last_used_at = time.monotonic()
            return existing
        if len(self._sessions) >= self.config.max_contexts:
            raise RuntimeError("browser context capacity is exhausted")
        context = await self._browser.new_context(
            accept_downloads=True,
            service_workers="block",
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
        )
        context.set_default_timeout(self.config.default_timeout_ms)
        context.set_default_navigation_timeout(self.config.navigation_timeout_ms)
        await context.route("**/*", self._route_request)
        await context.route_web_socket("**/*", self._route_web_socket)
        session = BrowserSession(context=context)
        self._sessions[session_key] = session
        return session

    async def _route_request(self, route: Any) -> None:
        url = str(route.request.url or "")
        if _non_network_url(url):
            await route.continue_()
            return
        try:
            await self._safe_url(url)
        except (OSError, ValueError):
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def _route_web_socket(self, web_socket: Any) -> None:
        try:
            await self._safe_web_socket_url(str(web_socket.url or ""))
        except (OSError, ValueError):
            await web_socket.close(code=1008, reason="Blocked by browser network policy")
            return
        web_socket.connect_to_server()

    async def _open(
        self, session_key: str, url: str, page_id: str | None, wait_until: str
    ) -> dict[str, Any]:
        safe_url = await self._safe_url(url)
        session = await self._session(session_key)
        if page_id:
            page = self._page(session, page_id)
            effective_page_id = page_id
        else:
            if len(session.pages) >= self.config.max_pages_per_context:
                raise RuntimeError("browser page capacity is exhausted for this session")
            page = await session.context.new_page()
            effective_page_id = uuid4().hex[:16]
            session.pages[effective_page_id] = page
        response = await page.goto(safe_url, wait_until=wait_until)
        session.active_page_id = effective_page_id
        session.last_used_at = time.monotonic()
        return {
            **await self._page_summary(page, effective_page_id),
            "status_code": response.status if response is not None else 0,
        }

    async def _snapshot(
        self,
        session_key: str,
        page_id: str | None,
        max_chars: int,
        include_links: bool,
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        text = await page.locator("body").inner_text()
        links: list[dict[str, str]] = []
        if include_links:
            links = await page.locator("a[href]").evaluate_all(
                "(els, limit) => els.slice(0, limit).map(el => "
                "({text: (el.innerText || '').trim(), href: el.href}))",
                self.config.max_snapshot_links,
            )
        truncated = len(text) > max_chars
        session.last_used_at = time.monotonic()
        return {
            **await self._page_summary(page, effective_page_id),
            "text": text[:max_chars],
            "links": links,
            "truncated": truncated,
        }

    async def _click(
        self, session_key: str, page_id: str | None, target: dict[str, Any]
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        await self._locator(page, target).click()
        session.last_used_at = time.monotonic()
        return await self._page_after_action(session, effective_page_id, page)

    async def _type_text(
        self,
        session_key: str,
        page_id: str | None,
        target: dict[str, Any],
        text: str,
        clear: bool,
        submit: bool,
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        locator = self._locator(page, target)
        if clear:
            await locator.fill(text)
        else:
            await locator.type(text)
        if submit:
            await locator.press("Enter")
        session.last_used_at = time.monotonic()
        return await self._page_after_action(session, effective_page_id, page)

    async def _select(
        self,
        session_key: str,
        page_id: str | None,
        target: dict[str, Any],
        values: list[str],
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        selected = await self._locator(page, target).select_option(values)
        session.last_used_at = time.monotonic()
        return {**await self._page_summary(page, effective_page_id), "selected": list(selected)}

    async def _press(
        self,
        session_key: str,
        page_id: str | None,
        key: str,
        target: dict[str, Any] | None,
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        if target:
            await self._locator(page, target).press(key)
        else:
            await page.keyboard.press(key)
        session.last_used_at = time.monotonic()
        return await self._page_after_action(session, effective_page_id, page)

    async def _scroll(
        self,
        session_key: str,
        page_id: str | None,
        delta_x: int,
        delta_y: int,
        target: dict[str, Any] | None,
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        if target:
            await self._locator(page, target).evaluate(
                "(el, delta) => el.scrollBy(delta.x, delta.y)",
                {"x": delta_x, "y": delta_y},
            )
        else:
            await page.mouse.wheel(delta_x, delta_y)
        session.last_used_at = time.monotonic()
        return await self._page_summary(page, effective_page_id)

    async def _wait(
        self,
        session_key: str,
        page_id: str | None,
        milliseconds: int,
        target: dict[str, Any] | None,
        state: str,
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        if target:
            await self._locator(page, target).wait_for(state=state, timeout=milliseconds)
        else:
            await page.wait_for_timeout(milliseconds)
        session.last_used_at = time.monotonic()
        return await self._page_summary(page, effective_page_id)

    async def _extract(
        self,
        session_key: str,
        page_id: str | None,
        selector: str | None,
        format_name: str,
        max_chars: int,
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        locator = page.locator(selector) if selector else page.locator("body")
        if format_name == "html":
            content = await locator.inner_html()
        elif format_name == "links":
            values = await locator.locator("a[href]").evaluate_all(
                "(els, limit) => els.slice(0, limit).map(el => "
                "({text: (el.innerText || '').trim(), href: el.href}))",
                self.config.max_snapshot_links,
            )
            content = json.dumps(values, ensure_ascii=False)
        else:
            content = await locator.inner_text()
        session.last_used_at = time.monotonic()
        return {
            **await self._page_summary(page, effective_page_id),
            "format": format_name,
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    async def _screenshot(
        self,
        session_key: str,
        page_id: str | None,
        full_page: bool,
        target: dict[str, Any] | None,
        output_path: Path,
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if target:
            data = await self._locator(page, target).screenshot(path=str(output_path), type="png")
        else:
            data = await page.screenshot(path=str(output_path), full_page=full_page, type="png")
        session.last_used_at = time.monotonic()
        return {
            **await self._page_summary(page, effective_page_id),
            "path": str(output_path),
            "mime_type": "image/png",
            "size_bytes": len(data),
            "image_base64": base64.b64encode(data).decode("ascii"),
        }

    async def _download(
        self,
        session_key: str,
        page_id: str | None,
        target: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        async with page.expect_download() as download_info:
            await self._locator(page, target).click()
        download = await download_info.value
        destination = output_path
        if destination.is_dir() or not destination.suffix:
            destination = destination / download.suggested_filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        await download.save_as(str(destination))
        session.last_used_at = time.monotonic()
        return {
            **await self._page_summary(page, effective_page_id),
            "path": str(destination),
            "suggested_filename": download.suggested_filename,
            "size_bytes": destination.stat().st_size,
        }

    async def _upload(
        self,
        session_key: str,
        page_id: str | None,
        target: dict[str, Any],
        paths: list[Path],
    ) -> dict[str, Any]:
        session, effective_page_id, page = await self._active_page(session_key, page_id)
        await self._locator(page, target).set_input_files([str(path) for path in paths])
        session.last_used_at = time.monotonic()
        return {
            **await self._page_summary(page, effective_page_id),
            "uploaded": [str(path) for path in paths],
        }

    async def _tabs(self, session_key: str) -> dict[str, Any]:
        session = await self._session(session_key)
        self._register_untracked_pages(session)
        tabs = []
        for page_id, page in list(session.pages.items()):
            if page.is_closed():
                session.pages.pop(page_id, None)
                continue
            tabs.append(await self._page_summary(page, page_id))
        return {"tabs": tabs, "active_page_id": session.active_page_id}

    async def _close(
        self,
        session_key: str,
        page_id: str | None,
        close_context: bool,
    ) -> dict[str, Any]:
        session = self._sessions.get(session_key)
        if session is None:
            return {"closed": False, "remaining_pages": 0}
        if close_context:
            await session.context.close()
            self._sessions.pop(session_key, None)
            return {"closed": True, "remaining_pages": 0}
        effective_page_id = page_id or session.active_page_id
        if not effective_page_id:
            raise ValueError("page_id is required because this browser context has no active page")
        page = self._page(session, effective_page_id)
        await page.close()
        session.pages.pop(effective_page_id, None)
        session.active_page_id = next(reversed(session.pages), None) if session.pages else None
        return {"closed": True, "remaining_pages": len(session.pages)}

    async def _active_page(
        self, session_key: str, page_id: str | None
    ) -> tuple[BrowserSession, str, Any]:
        session = await self._session(session_key)
        effective_page_id = page_id or session.active_page_id
        if not effective_page_id:
            raise ValueError("No browser page is open. Call browser_open first.")
        return session, effective_page_id, self._page(session, effective_page_id)

    def _page(self, session: BrowserSession, page_id: str) -> Any:
        page = session.pages.get(page_id)
        if page is None or page.is_closed():
            session.pages.pop(page_id, None)
            raise KeyError(f"unknown browser page: {page_id}")
        return page

    def _locator(self, page: Any, target: dict[str, Any]) -> Any:
        selector = _text(target.get("selector"))
        role = _text(target.get("role"))
        name = _text(target.get("name"))
        text = _text(target.get("text"))
        label = _text(target.get("label"))
        placeholder = _text(target.get("placeholder"))
        test_id = _text(target.get("test_id"))
        methods = [
            bool(selector),
            bool(role),
            bool(text),
            bool(label),
            bool(placeholder),
            bool(test_id),
        ]
        if sum(methods) != 1:
            raise ValueError(
                "target requires exactly one locator: selector, role, text, label, placeholder, or test_id"
            )
        exact = bool(target.get("exact", False))
        if selector:
            locator = page.locator(selector)
        elif role:
            locator = page.get_by_role(role, name=name or None, exact=exact)
        elif text:
            locator = page.get_by_text(text, exact=exact)
        elif label:
            locator = page.get_by_label(label, exact=exact)
        elif placeholder:
            locator = page.get_by_placeholder(placeholder, exact=exact)
        else:
            locator = page.get_by_test_id(test_id)
        nth = target.get("nth")
        if isinstance(nth, int) and not isinstance(nth, bool):
            locator = locator.nth(nth)
        return locator

    async def _page_summary(
        self, page: Any, page_id: str, *, response: Any | None = None
    ) -> dict[str, Any]:
        result = {
            "page_id": page_id,
            "url": page.url,
            "title": await page.title(),
        }
        if response is not None:
            result["status_code"] = response.status
        return result

    async def _page_after_action(
        self,
        session: BrowserSession,
        page_id: str,
        page: Any,
    ) -> dict[str, Any]:
        self._register_untracked_pages(session)
        active_page_id = session.active_page_id or page_id
        active_page = session.pages.get(active_page_id, page)
        return await self._page_summary(active_page, active_page_id)

    async def _remove_idle_sessions(self) -> None:
        threshold = time.monotonic() - self.config.idle_context_seconds
        stale = [key for key, session in self._sessions.items() if session.last_used_at < threshold]
        for key in stale:
            session = self._sessions.pop(key)
            await session.context.close()

    async def _shutdown(self) -> None:
        for session in list(self._sessions.values()):
            await session.context.close()
        self._sessions.clear()
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _safe_url(self, url: str) -> str:
        parsed = _validated_network_url(url)
        if self.config.allow_private_hosts:
            return parsed.geturl()
        hostname = str(parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        cache_key = (hostname, port)
        now = time.monotonic()
        if self._safe_hosts.get(cache_key, 0) > now:
            return parsed.geturl()
        await _assert_global_host(hostname, port)
        self._safe_hosts[cache_key] = now + self.config.host_validation_ttl_seconds
        return parsed.geturl()

    async def _safe_web_socket_url(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        scheme_mapping = {"ws": "http", "wss": "https"}
        if parsed.scheme not in scheme_mapping or not parsed.hostname:
            raise ValueError("browser WebSocket URL must be an absolute WS or WSS URL")
        validation_url = parsed._replace(scheme=scheme_mapping[parsed.scheme]).geturl()
        await self._safe_url(validation_url)
        return parsed.geturl()

    def _register_untracked_pages(self, session: BrowserSession) -> None:
        known_pages = set(session.pages.values())
        for page in session.context.pages:
            if page in known_pages or page.is_closed():
                continue
            page_id = uuid4().hex[:16]
            session.pages[page_id] = page
            session.active_page_id = page_id


_DEFAULT_BROWSER_RUNTIME: BrowserRuntime | None = None
_DEFAULT_BROWSER_RUNTIME_LOCK = threading.Lock()


def default_browser_runtime() -> BrowserRuntime:
    global _DEFAULT_BROWSER_RUNTIME
    if _DEFAULT_BROWSER_RUNTIME is not None:
        return _DEFAULT_BROWSER_RUNTIME
    with _DEFAULT_BROWSER_RUNTIME_LOCK:
        if _DEFAULT_BROWSER_RUNTIME is None:
            _DEFAULT_BROWSER_RUNTIME = BrowserRuntime()
            atexit.register(_DEFAULT_BROWSER_RUNTIME.shutdown)
    return _DEFAULT_BROWSER_RUNTIME


def _validated_network_url(url: str):
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("browser URL must be an absolute HTTP or HTTPS URL")
    return parsed


async def _assert_global_host(hostname: str, port: int) -> None:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("private or local browser hosts are not allowed")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        addresses = list({ipaddress.ip_address(record[4][0]) for record in records})
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError(f"private or non-global browser host is not allowed: {hostname}")


def _non_network_url(url: str) -> bool:
    return url.startswith(("about:", "data:", "blob:"))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_env(name: str) -> str | None:
    value = str(os.getenv(name) or "").strip()
    return value or None


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _env_int(name: str, default: int, *, minimum: int) -> int:
    value = str(os.getenv(name) or "").strip()
    if not value:
        return default
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed
