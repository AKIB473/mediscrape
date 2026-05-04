"""
Anti-bot / Cloudflare bypass utilities for mediscrape.

Priority order (fastest → most capable):
  1. curl_cffi   — TLS fingerprint impersonation (Chrome/Firefox/Safari)
                   Bypasses Cloudflare Bot Management, Akamai, DataDome
  2. cloudscraper — httpx-based CF-clearance solver (older CF versions)
  3. Playwright  — full headless Chrome, solves JS challenges
  4. httpx       — plain fallback with realistic headers

Usage:
    from utils.bypass import BypassSession, fetch_bypass

    # Context manager for bulk requests to one domain
    async with BypassSession("https://example.com") as session:
        html = await session.get("/some/path")

    # One-shot
    html = await fetch_bypass("https://example.com/page")
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Realistic browser headers (rotate to avoid pattern matching)         #
# ------------------------------------------------------------------ #

_CHROME_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_FIREFOX_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

_SAFARI_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

ALL_UAS = _CHROME_UAS + _FIREFOX_UAS + _SAFARI_UAS


def get_headers(ua: str | None = None, referer: str = "", extra: dict | None = None) -> dict:
    """Return a realistic browser header set."""
    ua = ua or random.choice(_CHROME_UAS)
    is_chrome = "Chrome" in ua
    is_ff = "Firefox" in ua

    h: dict[str, str] = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    if referer:
        h["Referer"] = referer

    if is_chrome:
        h.update({
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        })
    elif is_ff:
        h.update({
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "TE": "trailers",
        })

    if extra:
        h.update(extra)

    return h


# ------------------------------------------------------------------ #
# curl_cffi impersonation (Level 1 — TLS fingerprint)                 #
# ------------------------------------------------------------------ #

_CURL_IMPERSONATIONS = [
    "chrome124", "chrome123", "chrome120",
    "firefox124", "firefox120",
    "safari17_4_1", "safari16_5",
]

_curl_available = False
try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    _curl_available = True
except ImportError:
    pass


async def _fetch_curl(
    url: str,
    headers: dict | None = None,
    timeout: int = 30,
    impersonate: str | None = None,
) -> str | None:
    """Fetch with curl_cffi TLS impersonation — bypasses CF Bot Management."""
    if not _curl_available:
        return None
    impersonate = impersonate or random.choice(_CURL_IMPERSONATIONS[:4])  # prefer Chrome
    try:
        async with CurlAsyncSession(impersonate=impersonate) as session:
            r = await session.get(
                url,
                headers=headers or get_headers(),
                timeout=timeout,
                allow_redirects=True,
            )
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 429, 503):
                logger.debug(f"curl_cffi {impersonate}: {r.status_code} on {url}")
                return None
    except Exception as e:
        logger.debug(f"curl_cffi failed: {e}")
    return None


# ------------------------------------------------------------------ #
# cloudscraper (Level 2 — CF clearance cookie)                        #
# ------------------------------------------------------------------ #

_cloudscraper_available = False
try:
    import cloudscraper as _cs_mod
    _cloudscraper_available = True
except ImportError:
    pass


async def _fetch_cloudscraper(url: str, headers: dict | None = None) -> str | None:
    """Fetch with cloudscraper — handles CF challenge pages."""
    if not _cloudscraper_available:
        return None
    loop = asyncio.get_event_loop()
    try:
        scraper = _cs_mod.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        if headers:
            scraper.headers.update(headers)
        r = await loop.run_in_executor(None, lambda: scraper.get(url, timeout=30))
        if r.status_code == 200:
            return r.text
    except Exception as e:
        logger.debug(f"cloudscraper failed: {e}")
    return None


# ------------------------------------------------------------------ #
# Playwright (Level 3 — full browser)                                  #
# ------------------------------------------------------------------ #

async def _fetch_playwright(url: str, wait_ms: int = 3000) -> str | None:
    """Fetch with headless Playwright — full JS execution, solves any challenge."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=random.choice(_CHROME_UAS),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            # Hide automation signals
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}};
            """)
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(wait_ms)
            # Wait for CF challenge to clear if present
            for _ in range(10):
                title = await page.title()
                if "just a moment" in title.lower() or "checking" in title.lower():
                    await page.wait_for_timeout(2000)
                else:
                    break
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        logger.debug(f"playwright failed: {e}")
    return None


# ------------------------------------------------------------------ #
# httpx fallback (Level 4)                                             #
# ------------------------------------------------------------------ #

async def _fetch_httpx(url: str, headers: dict | None = None) -> str | None:
    try:
        import httpx
        async with httpx.AsyncClient(
            headers=headers or get_headers(),
            follow_redirects=True,
            timeout=20,
            http2=True,
        ) as c:
            r = await c.get(url)
            if r.status_code == 200:
                return r.text
    except Exception as e:
        logger.debug(f"httpx fallback failed: {e}")
    return None


# ------------------------------------------------------------------ #
# Main bypass fetch function                                           #
# ------------------------------------------------------------------ #

async def fetch_bypass(
    url: str,
    *,
    headers: dict | None = None,
    use_playwright_fallback: bool = True,
    rate_limit: float = 0.5,
    _last_request: dict | None = None,
) -> str | None:
    """
    Fetch a URL with progressive anti-bot bypass:
      1. curl_cffi (TLS impersonation)
      2. curl_cffi with different impersonation
      3. cloudscraper
      4. Playwright (if use_playwright_fallback=True)
      5. httpx fallback

    Returns HTML string or None if all methods fail.
    """
    if _last_request is not None:
        elapsed = time.time() - _last_request.get("t", 0)
        if elapsed < rate_limit:
            await asyncio.sleep(rate_limit - elapsed)
        _last_request["t"] = time.time()

    hdrs = headers or get_headers()

    # Level 1: curl_cffi chrome impersonation
    if _curl_available:
        html = await _fetch_curl(url, hdrs, impersonate="chrome124")
        if html and len(html) > 500:
            logger.debug(f"bypass: curl_cffi chrome124 OK for {url}")
            return html

        # Retry with Firefox impersonation
        html = await _fetch_curl(url, hdrs, impersonate="firefox124")
        if html and len(html) > 500:
            logger.debug(f"bypass: curl_cffi firefox124 OK for {url}")
            return html

    # Level 2: cloudscraper
    html = await _fetch_cloudscraper(url, hdrs)
    if html and len(html) > 500:
        logger.debug(f"bypass: cloudscraper OK for {url}")
        return html

    # Level 3: Playwright
    if use_playwright_fallback:
        logger.debug(f"bypass: trying Playwright for {url}")
        html = await _fetch_playwright(url)
        if html and len(html) > 500:
            logger.debug(f"bypass: Playwright OK for {url}")
            return html

    # Level 4: httpx
    html = await _fetch_httpx(url, hdrs)
    if html and len(html) > 500:
        logger.debug(f"bypass: httpx fallback OK for {url}")
        return html

    logger.warning(f"bypass: ALL methods failed for {url}")
    return None


# ------------------------------------------------------------------ #
# BypassSession — context manager for bulk requests                   #
# ------------------------------------------------------------------ #

class BypassSession:
    """
    Reusable session for multiple requests to the same domain.
    Maintains cookies and CF clearance across requests.

    Usage:
        async with BypassSession("https://drugs.com") as s:
            html = await s.get("/alprazolam.html")
    """

    def __init__(
        self,
        base_url: str = "",
        *,
        rate_limit: float = 1.0,
        impersonate: str | None = None,
        use_playwright: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.rate_limit = rate_limit
        self.impersonate = impersonate or random.choice(_CURL_IMPERSONATIONS[:4])
        self.use_playwright = use_playwright
        self._session: Any = None
        self._last_t = 0.0
        self._headers = get_headers()

    async def __aenter__(self):
        if _curl_available:
            from curl_cffi.requests import AsyncSession as CurlAsync
            self._session = CurlAsync(impersonate=self.impersonate)
            await self._session.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._session is not None:
            try:
                await self._session.__aexit__(*args)
            except Exception:
                pass

    async def _throttle(self):
        elapsed = time.time() - self._last_t
        if elapsed < self.rate_limit:
            await asyncio.sleep(self.rate_limit - elapsed)
        self._last_t = time.time()

    async def get(self, path_or_url: str, params: dict | None = None) -> str | None:
        """GET request using best available method."""
        await self._throttle()
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else f"{self.base_url}{path_or_url}"
        )

        # Use maintained curl session (keeps cookies/CF clearance)
        if self._session is not None:
            try:
                r = await self._session.get(
                    url,
                    headers=self._headers,
                    params=params,
                    timeout=30,
                    allow_redirects=True,
                )
                if r.status_code == 200 and len(r.text) > 200:
                    return r.text
                if r.status_code in (403, 503):
                    logger.debug(f"BypassSession: CF challenge on {url}, rotating impersonation")
                    # Rotate impersonation on CF challenge
                    new_imp = random.choice(_CURL_IMPERSONATIONS)
                    self._session._impersonate = new_imp
                    await asyncio.sleep(2)
                    r2 = await self._session.get(url, headers=self._headers, timeout=30, allow_redirects=True)
                    if r2.status_code == 200:
                        return r2.text
            except Exception as e:
                logger.debug(f"BypassSession curl error: {e}")

        # Fallback
        return await fetch_bypass(url, headers=self._headers, use_playwright_fallback=self.use_playwright)

    async def get_json(self, path_or_url: str, params: dict | None = None) -> dict | list | None:
        """GET and parse JSON response."""
        self._headers = get_headers(extra={"Accept": "application/json, text/plain, */*"})
        html = await self.get(path_or_url, params=params)
        if html:
            try:
                import orjson
                return orjson.loads(html)
            except Exception:
                pass
        return None
