#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vamp_agent.py — Enhanced Playwright agent with Outlook Office365 authentication fixes
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
from collections import OrderedDict
import inspect
import io
import json
import logging
import os
import platform
import re
import tempfile
import time
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from textwrap import dedent

try:
    from playwright.async_api import async_playwright, Error as PWError, TimeoutError as PWTimeout
except ImportError as exc:  # pragma: no cover - optional runtime dependency
    async_playwright = None  # type: ignore[assignment]

    class PWError(RuntimeError):
        pass

    class PWTimeout(PWError):
        pass

    _PLAYWRIGHT_IMPORT_ERROR = exc
else:
    _PLAYWRIGHT_IMPORT_ERROR = None

from email.utils import parsedate_to_datetime

OCR_AVAILABLE = False
_OCR_ERROR: Optional[str] = None
_OCR_STATUS_LOGGED = False

try:
    from PIL import Image  # type: ignore
    import pytesseract  # type: ignore

    try:
        pytesseract.get_tesseract_version()
        OCR_AVAILABLE = True
    except Exception as exc:  # pragma: no cover - environment dependent
        OCR_AVAILABLE = False
        _OCR_ERROR = str(exc)
except Exception as exc:  # pragma: no cover - optional dependency
    Image = None  # type: ignore
    pytesseract = None  # type: ignore
    OCR_AVAILABLE = False
    _OCR_ERROR = str(exc)

from . import BRAIN_DATA_DIR, STATE_DIR
from .agent_app.app_state import agent_state
from .attachments import AttachmentReader, extract_text_from_attachment
from .date_utils import MonthBounds, compute_month_bounds, parse_outlook_date
from .onedrive_selectors import ONEDRIVE_SELECTORS
from .outlook_selectors import (
    ATTACHMENT_CANDIDATES,
    ATTACHMENT_NAME_SELECTORS,
    BODY_SELECTORS,
    OUTLOOK_ROW_SELECTORS,
    OUTLOOK_SELECTORS,
)
from .vamp_store import _uid
from .nwu_brain.scoring import NWUScorer

# --------------------------------------------------------------------------------------
# Constants / Globals
# --------------------------------------------------------------------------------------

MANIFEST_PATH = BRAIN_DATA_DIR / "brain_manifest.json"

_SYSTEM = platform.system().lower()


def _default_browser_args() -> List[str]:
    """Return Chromium launch arguments tailored to the current platform."""

    base_args = [
        "--disable-web-security",
        "--disable-features=VizDisplayCompositor",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-plugins",
        "--disable-translate",
        "--mute-audio",
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ]

    linux_only = {"--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox"}

    if _SYSTEM == "linux":
        base_args.extend(sorted(linux_only))
    else:
        base_args = [arg for arg in base_args if arg not in linux_only]

    if _SYSTEM == "darwin":
        base_args.append("--use-mock-keychain")

    return base_args


# Enhanced browser configuration for Outlook Office365
BROWSER_CONFIG = {
    "headless": os.getenv("VAMP_HEADLESS", "0").strip().lower() not in {"0", "false", "no"},
    "slow_mo": 0,
    "args": _default_browser_args(),
}

OUTLOOK_MAX_ROWS = int(os.getenv("VAMP_OUTLOOK_MAX_ROWS", "500"))
OUTLOOK_RETRY_WAIT_MS = int(os.getenv("VAMP_OUTLOOK_RETRY_WAIT_MS", "1500"))

# Mapping of env variable fallbacks for services
SERVICE_ENV_VARS = {
    "outlook": ("VAMP_OUTLOOK_USERNAME", "VAMP_OUTLOOK_PASSWORD"),
    "onedrive": ("VAMP_ONEDRIVE_USERNAME", "VAMP_ONEDRIVE_PASSWORD"),
    "drive": ("VAMP_GOOGLE_USERNAME", "VAMP_GOOGLE_PASSWORD"),
}

# User agent that looks like a real browser
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"

# Keep a single shared browser across scans
_PLAYWRIGHT = None
_BROWSER = None
_CTX = None
_PAGES: Dict[str, Any] = {}
_SERVICE_CONTEXTS: "OrderedDict[str, Any]" = OrderedDict()
_CONTEXT_LOCK = asyncio.Lock()
_BROWSER_LOCK = asyncio.Lock()
_MAX_CONTEXTS = 10

PLATFORM_LABELS = {
    "outlook": "Outlook",
    "onedrive": "OneDrive",
    "drive": "Google Drive",
    "efundi": "eFundi",
}

ATTACHMENT_READER = AttachmentReader()

# Service-specific storage state paths and URLs
STATE_DIR.mkdir(parents=True, exist_ok=True)

LEGACY_STATE_PATHS = {
    "outlook": STATE_DIR / "outlook_state.json",
    "onedrive": STATE_DIR / "onedrive_state.json",
    "drive": STATE_DIR / "drive_state.json",
}

SERVICE_STATE_DIRS = {
    "outlook": STATE_DIR / "outlook",
    "onedrive": STATE_DIR / "onedrive",
    "drive": STATE_DIR / "drive",
}

SERVICE_URLS = {
    "outlook": "https://outlook.office.com/mail/",
    "onedrive": "https://onedrive.live.com/",
    "drive": "https://drive.google.com/drive/my-drive",
    # Add for Nextcloud: "nextcloud": "https://your.nextcloud.instance/apps/files/"
}

SERVICE_LOGIN_READY = {
    "outlook": OUTLOOK_SELECTORS.inbox_list,
    "onedrive": ONEDRIVE_SELECTORS.grid,
    "drive": [
        "[aria-label=\"My Drive\"]",
        "[data-target=\"docos-DriveMain\"]",
    ],
}

MANUAL_LOGIN_TIMEOUT = int(os.getenv("VAMP_MANUAL_LOGIN_TIMEOUT", "300"))  # seconds

ALLOW_INTERACTIVE_LOGIN = os.getenv("VAMP_ALLOW_INTERACTIVE_LOGIN", "1").strip().lower() not in {"0", "false", "no"}

# NWU Brain scorer
try:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Brain manifest not found: {MANIFEST_PATH}")
    SCORER = NWUScorer(str(MANIFEST_PATH))
except Exception as e:
    print(f"Warning: NWUScorer not available - {e}")
    class MockScorer:
        def compute(self, item):
            return {
                "kpa": ["KPA1"],
                "tier": ["Compliance"],
                "score": 3.0,
                "band": "Developing",
                "rationale": "Mock scoring - backend not available",
                "policy_hits": [],
                "must_pass_risks": []
            }
        def to_csv_row(self, item):
            return item
    SCORER = MockScorer()

# --------------------------------------------------------------------------------------
# Enhanced Browser Management with Authentication Fixes
# --------------------------------------------------------------------------------------

async def ensure_browser() -> None:
    """Launch persistent browser with Office365-compatible configuration."""
    global _PLAYWRIGHT, _BROWSER
    if _BROWSER is not None:
        return

    if _PLAYWRIGHT_IMPORT_ERROR is not None or async_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Install it with 'pip install playwright' "
            "and run 'playwright install chromium' before retrying."
        )

    async with _BROWSER_LOCK:
        if _BROWSER is not None:
            return

        logger.info("Initializing Playwright browser with Office365 compatibility...")
        try:
            _PLAYWRIGHT = await async_playwright().start()
            _BROWSER = await _PLAYWRIGHT.chromium.launch(**BROWSER_CONFIG)
        except Exception as exc:  # pragma: no cover - environment dependent
            _PLAYWRIGHT = None
            _BROWSER = None
            raise RuntimeError(
                "Failed to start Chromium via Playwright. Ensure 'playwright install chromium' "
                "has been executed and that the host allows sandboxed browsers to run."
            ) from exc


def _base_context_kwargs() -> Dict[str, Any]:
    return {
        'viewport': {'width': 1280, 'height': 800},
        'user_agent': USER_AGENT,
        'extra_http_headers': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    }


def _state_path_for(service: Optional[str], identity: Optional[str]) -> Optional[Path]:
    if not service:
        return None

    base = SERVICE_STATE_DIRS.get(service)
    if not base:
        return None

    base.mkdir(parents=True, exist_ok=True)

    safe_identity = _uid(identity) if identity else "default"
    state_path = base / f"{safe_identity}.json"

    # Migrate legacy single-state files if present
    legacy = LEGACY_STATE_PATHS.get(service)
    if legacy and legacy.exists() and not state_path.exists():
        try:
            import shutil

            shutil.copy2(legacy, state_path)
            logger.info("Migrated legacy %s storage state from %s", service, legacy)
        except Exception as exc:
            logger.warning("Failed to migrate legacy %s storage state: %s", service, exc)

    return state_path


async def _persist_context_state(service: Optional[str], identity: Optional[str], context: Any) -> None:
    """Persist the latest browser storage state for a given service."""

    state_path = _state_path_for(service, identity)
    if not state_path:
        return

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(state_path))
    except Exception as exc:
        logger.debug("Unable to persist %s storage state: %s", service or "generic", exc)


async def get_authenticated_context(service: str, identity: Optional[str] = None) -> Any:
    """Get or create an authenticated context using storage state."""
    await ensure_browser()

    identity_key = _uid(identity) if identity else "default"
    key = f"{service}:{identity_key}" if service else f"generic:{identity_key}"

    async with _CONTEXT_LOCK:
        existing = _SERVICE_CONTEXTS.get(key)
        if existing is not None:
            try:
                if not existing.is_closed():
                    logger.info(
                        "Reusing cached %s context with saved state for %s",
                        service or "generic",
                        identity or "default",
                    )
                    _SERVICE_CONTEXTS.move_to_end(key)
                    return existing
            except Exception:
                pass
            _SERVICE_CONTEXTS.pop(key, None)

        state_path = _state_path_for(service, identity)
        context_kwargs = _base_context_kwargs()

        await _ensure_storage_state(service, state_path, identity)

        if state_path and state_path.exists():
            context_kwargs['storage_state'] = str(state_path)
            logger.info("Using %s storage state from %s", service, state_path)

        if _BROWSER is None:
            raise RuntimeError("Playwright browser is not initialised. Call ensure_browser() first.")

        try:
            context = await _BROWSER.new_context(**context_kwargs)
        except Exception as exc:
            raise RuntimeError(
                "Unable to create a browser context. Ensure Playwright browsers are installed (playwright install chromium) "
                "and the launch configuration is supported on this host."
            ) from exc

        if state_path and not state_path.exists():
            if BROWSER_CONFIG.get("headless", True):
                await context.close()
                raise RuntimeError(
                    f"Storage state for {service} not found at {state_path}. "
                    "Headless mode requires a pre-authenticated storage_state file."
                )

            logger.info(
                "No storage state found for %s (%s). Waiting for manual sign-in to capture cookies...",
                service,
                identity or "default",
            )
            await _prompt_manual_login(context, service, state_path, identity)

            if not state_path.exists():
                await context.close()
                raise RuntimeError(
                    f"Manual login for {service} did not persist credentials to {state_path}."
                )

            # Reload the context with the freshly captured storage state
            await context.close()
            context_kwargs['storage_state'] = str(state_path)
            context = await _BROWSER.new_context(**context_kwargs)

        await apply_stealth(context)
        _SERVICE_CONTEXTS[key] = context
        _SERVICE_CONTEXTS.move_to_end(key)
        if len(_SERVICE_CONTEXTS) > _MAX_CONTEXTS:
            evicted_key, evicted_context = _SERVICE_CONTEXTS.popitem(last=False)
            try:
                await evicted_context.close()
            except Exception:
                logger.debug("Failed to close evicted context %s", evicted_key)
        return context

# --------------------------------------------------------------------------------------
# Stealth enhancements
# --------------------------------------------------------------------------------------

async def apply_stealth(context: Any) -> None:
    """Apply anti-detection measures."""
    await context.add_init_script("""
        delete window.navigator.webdriver;
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    """)


def _credentials_for(service: Optional[str], identity: Optional[str]) -> Optional[Tuple[str, str]]:
    if not service:
        return None

    identity_key = (identity or "").strip() or "default"
    manager = agent_state().auth_manager

    # Prefer secrets stored in the agent vault
    username = manager.username_for(service, identity_key) or (identity or "").strip()
    password = manager.password_for(service, identity_key)

    if not password and identity_key != "default":
        password = manager.password_for(service, "default")
    if not username:
        username = manager.username_for(service, "default") or (identity or "").strip()

    if username and password:
        return username, password

    # Fallback to environment variables for backwards compatibility
    env_keys = SERVICE_ENV_VARS.get(service, (None, None))
    if env_keys[0] and env_keys[1]:
        env_username = os.getenv(env_keys[0], "").strip()
        env_password = os.getenv(env_keys[1], "").strip()
        if not username and env_username:
            username = env_username
        if not password and env_password:
            password = env_password
        if username and password:
            return username, password

    logger.debug("No credentials available for automated %s login", service)
    return None


async def _dismiss_kmsi_prompt(page: Any) -> None:
    """Dismiss the 'Stay signed in?' prompt if it appears."""

    try:
        await page.wait_for_selector('input[id="idBtn_Back"]', timeout=5000)
        await page.click('input[id="idBtn_Back"]')
        return
    except PWTimeout:
        pass

    try:
        await page.wait_for_selector('button#idBtn_Back, button[data-report-value="No"]', timeout=3000)
        await page.click('button#idBtn_Back, button[data-report-value="No"]')
    except PWTimeout:
        pass


async def _try_nwu_adfs_login(page: Any, username: str, password: str) -> bool:
    """Attempt to authenticate against the NWU ADFS portal if detected."""

    selectors = [
        '#userNameInput',
        'input[name="UserName"]',
    ]
    password_selectors = [
        '#passwordInput',
        'input[name="Password"]',
    ]

    user_selector = None
    for candidate in selectors:
        try:
            await page.wait_for_selector(candidate, timeout=2000)
            user_selector = candidate
            break
        except PWTimeout:
            continue

    if not user_selector:
        return False

    logger.info("Detected NWU ADFS login flow; attempting automated authentication.")

    password_selector = None
    for candidate in password_selectors:
        try:
            await page.wait_for_selector(candidate, timeout=2000)
            password_selector = candidate
            break
        except PWTimeout:
            continue

    if not password_selector:
        logger.warning("NWU ADFS login detected but password field not found; falling back to manual flow.")
        return False

    await page.fill(user_selector, username)
    await page.fill(password_selector, password)

    submit_selectors = [
        '#submitButton',
        'input[type="submit"]#submitButton',
        'button[type="submit"]#submitButton',
        'input[type="submit"]',
        'button[type="submit"]',
    ]

    clicked = False
    for candidate in submit_selectors:
        try:
            element = await page.query_selector(candidate)
            if element:
                await element.click()
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        await page.press(password_selector, "Enter")

    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass

    return True


async def _wait_for_outlook_ready(page: Any) -> None:
    """Wait until the Outlook mailbox UI is available."""

    await _dismiss_kmsi_prompt(page)
    await page.wait_for_selector('[role="navigation"], [aria-label="Mail"]', timeout=60000)


async def _automated_login(service: Optional[str], identity: Optional[str], state_path: Optional[Path]) -> bool:
    """Attempt a fully headless login when credentials are configured."""

    if not service or not state_path:
        return False

    if _BROWSER is None:
        return False

    creds = _credentials_for(service, identity)
    if not creds:
        return False

    username, password = creds
    url = SERVICE_URLS.get(service)
    if not url:
        return False

    login_context = await _BROWSER.new_context(**_base_context_kwargs())
    page = None
    try:
        await apply_stealth(login_context)
        page = await login_context.new_page()
        await page.goto(url, wait_until="load", timeout=60000)

        if service == "outlook":
            # Some tenants immediately redirect to a custom ADFS login (e.g. NWU).
            adfs_used = await _try_nwu_adfs_login(page, username, password)

            if not adfs_used:
                await page.wait_for_selector('input[name="loginfmt"]', timeout=30000)
                await page.fill('input[name="loginfmt"]', username)
                await page.click('input[type="submit"]#idSIButton9')

                try:
                    await page.wait_for_selector('input[name="passwd"]', timeout=20000)
                except PWTimeout:
                    adfs_used = await _try_nwu_adfs_login(page, username, password)
                else:
                    await page.fill('input[name="passwd"]', password)
                    await page.click('input[type="submit"]#idSIButton9')

            if adfs_used:
                # Some ADFS flows still bounce back to Microsoft for the final password prompt.
                try:
                    await page.wait_for_selector('input[name="passwd"]', timeout=5000)
                except PWTimeout:
                    pass
                else:
                    await page.fill('input[name="passwd"]', password)
                    await page.click('input[type="submit"]#idSIButton9')

            await _wait_for_outlook_ready(page)
        elif service == "onedrive":
            await page.wait_for_selector('input[name="loginfmt"]', timeout=30000)
            await page.fill('input[name="loginfmt"]', username)
            await page.click('input[type="submit"]#idSIButton9')

            await page.wait_for_selector('input[name="passwd"]', timeout=30000)
            await page.fill('input[name="passwd"]', password)
            await page.click('input[type="submit"]#idSIButton9')

            try:
                await page.wait_for_selector('input[id="idBtn_Back"]', timeout=5000)
                await page.click('input[id="idBtn_Back"]')
            except PWTimeout:
                pass

            await page.wait_for_selector('[role="main"], [data-automationid="TopBar"]', timeout=60000)
        elif service == "drive":
            await page.wait_for_selector('input[type="email"]', timeout=30000)
            await page.fill('input[type="email"]', username)
            await page.click('#identifierNext')

            await page.wait_for_selector('input[type="password"]', timeout=30000)
            await page.fill('input[type="password"]', password)
            await page.click('#passwordNext')

            await page.wait_for_selector('[role="main"], [data-id="my-drive"]', timeout=60000)
        else:
            logger.debug("Automated login not implemented for %s", service)
            return False

        state_path.parent.mkdir(parents=True, exist_ok=True)
        await login_context.storage_state(path=str(state_path))
        logger.info("Captured %s storage state automatically (headless).", service)
        return True
    except Exception as exc:
        logger.error("Automated login for %s failed: %s", service, exc)
        return False
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        try:
            await login_context.close()
        except Exception:
            pass


async def _prompt_manual_login(context: Any, service: str, state_path: Path, identity: Optional[str]) -> None:
    """Open a visible Chromium page and capture storage state after manual login."""

    url = SERVICE_URLS.get(service)
    if not url:
        raise RuntimeError(f"No login URL configured for {service}")

    page = await context.new_page()
    try:
        await page.goto(url, wait_until="load", timeout=60000)
    except Exception as exc:
        raise RuntimeError(f"Failed to load {url} for {service}: {exc}") from exc

    logger.info(
        "Storage state for %s (%s) not found. A visible Chromium window has been opened for manual login."
        " The agent will automatically capture credentials once the workspace is detected.",
        service,
        identity or "default",
    )

    selectors = SERVICE_LOGIN_READY.get(service, ["[role='main']", "body.authenticated"])
    deadline = time.time() + MANUAL_LOGIN_TIMEOUT
    last_ping = 0.0

    while time.time() < deadline:
        for selector in selectors:
            try:
                await page.wait_for_selector(selector, timeout=2000)
            except PWTimeout:
                continue
            else:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=str(state_path))
                logger.info("Detected %s workspace; saved storage state to %s", service, state_path)
                try:
                    await page.close()
                except Exception:
                    pass
                return

        if time.time() - last_ping > 30:
            logger.info("Waiting for %s login to complete...", service)
            last_ping = time.time()

        await page.wait_for_timeout(1000)

    try:
        await page.close()
    except Exception:
        pass

    raise RuntimeError(
        f"Manual login for {service} did not complete within {MANUAL_LOGIN_TIMEOUT} seconds. "
        "Ensure the credentials are valid or supply them via the Auth Manager API for automated login."
    )


async def _ensure_storage_state(service: Optional[str], state_path: Optional[Path], identity: Optional[str]) -> None:
    """Ensure a storage_state file exists; trigger interactive capture if necessary."""

    if not service or not state_path:
        return

    if state_path.exists():
        return

    try:
        automated = await _automated_login(service, identity, state_path)
    except Exception as exc:
        logger.error("Automated login attempt for %s crashed: %s", service, exc)
        automated = False

    if automated and state_path.exists():
        return

    if not ALLOW_INTERACTIVE_LOGIN:
        raise RuntimeError(
            f"Storage state for {service} not found at {state_path}. "
            "Provide a pre-authenticated storage_state file or set VAMP_ALLOW_INTERACTIVE_LOGIN=1 to capture it interactively."
        )

    # Ensure Playwright is running so we can spawn a temporary visible browser.
    await ensure_browser()

    try:
        login_browser = await _PLAYWRIGHT.chromium.launch(
            headless=False,
            args=BROWSER_CONFIG.get("args", []),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Storage state for {service} not found at {state_path} and a visible Chromium session could not be started ({exc}). "
            "Install the required Playwright browser dependencies for your platform or generate the storage_state file manually "
            "with Playwright before retrying."
        ) from exc

    login_context = await login_browser.new_context(**_base_context_kwargs())

    try:
        await apply_stealth(login_context)
        await _prompt_manual_login(login_context, service, state_path, identity)
    finally:
        try:
            await login_context.close()
        except Exception:
            pass
        try:
            await login_browser.close()
        except Exception:
            pass

    if not state_path.exists():
        raise RuntimeError(
            f"Interactive login for {service} did not persist any credentials. "
            "Repeat the login flow and ensure you confirm completion in the terminal."
        )


async def refresh_storage_state(service: str, identity: Optional[str] = None) -> Path:
    """Force a fresh capture of the browser storage state for a service."""

    await ensure_browser()
    state_path = _state_path_for(service, identity)
    if not state_path:
        raise ValueError(f"Unknown service: {service}")

    try:
        if state_path.exists():
            state_path.unlink()
    except OSError:
        logger.warning("Unable to clear existing storage state at %s", state_path)

    await _ensure_storage_state(service, state_path, identity)
    return state_path


def refresh_storage_state_sync(service: str, identity: Optional[str] = None) -> Path:
    """Synchronous convenience wrapper around :func:`refresh_storage_state`."""

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(refresh_storage_state(service, identity))
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()

# --------------------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------------------

async def _maybe_await(result: Any) -> None:
    """Await the result if it is awaitable."""
    if inspect.isawaitable(result):
        await result


async def _score_and_batch(
    items: List[Dict[str, Any]],
    sink: Callable[[List[Dict[str, Any]]], Any],
    on_progress: Optional[Callable[[float, str], Any]] = None,
    batch_size: int = 25,
) -> None:
    """Score items using the NWU brain and flush in batches via sink."""

    if not items:
        return

    total = len(items)
    pending: List[Dict[str, Any]] = []

    for idx, item in enumerate(items, start=1):
        title = item.get("title") or item.get("path") or ""
        platform = item.get("platform") or item.get("source") or ""
        timestamp = item.get("timestamp") or item.get("date") or item.get("modified") or ""

        item.setdefault("title", title)
        item.setdefault("source", platform or item.get("source") or "")
        item.setdefault("platform", platform)
        item.setdefault("path", item.get("path") or title)
        item.setdefault("relpath", item.get("relpath") or item.get("path") or title)
        if timestamp:
            item.setdefault("date", timestamp)
            item.setdefault("modified", timestamp)

        try:
            scored = SCORER.compute(item)
            item.update(scored)
            item["_scored"] = True
        except Exception as exc:
            logger.warning(f"Scoring failed for item {title or '[unnamed]'}: {exc}")
            item.setdefault("_scored", False)
            item.setdefault("score", 0.0)
            item.setdefault("band", "Unscored")
            item.setdefault("rationale", "Scoring not available")

        _normalize_evidence(item)

        pending.append(item)

        if len(pending) >= batch_size:
            try:
                await _maybe_await(sink(list(pending)))
            finally:
                pending.clear()

        if on_progress:
            progress = 40 + (50 * (idx / total))
            capped = min(90, progress)
            await on_progress(capped, f"Scoring items ({idx}/{total})")

    if pending:
        await _maybe_await(sink(list(pending)))

    if on_progress:
        await on_progress(90, "Scoring complete")


def _normalize_evidence(item: Dict[str, Any]) -> None:
    """Align evidence items with the canonical schema."""

    source = (item.get("source") or "").lower() or "unknown"
    platform = item.get("platform") or PLATFORM_LABELS.get(source, source.title())

    item["source"] = source
    item["platform"] = platform
    item["title"] = item.get("title") or item.get("path") or "Untitled item"

    snippet = _clean_text(
        item.get("snippet")
        or item.get("body")
        or item.get("preview")
        or item.get("full_text")
        or ""
    )
    if snippet:
        item["snippet"] = snippet[:400]

    timestamp = item.get("date") or item.get("timestamp") or item.get("modified") or ""
    if timestamp:
        item["date"] = timestamp

    raw_ts = item.get("raw_timestamp") or item.get("timestamp_relative") or timestamp
    if raw_ts:
        item["raw_timestamp"] = raw_ts

    item["timestamp_confidence"] = float(item.get("timestamp_confidence") or 0.0)
    item["timestamp_estimated"] = bool(item.get("timestamp_estimated"))
    item.setdefault("kpa", item.get("kpa") or [])
    item.setdefault("score", float(item.get("score") or 0.0))
    item.setdefault("band", item.get("band") or "Unscored")
    item.setdefault("rationale", item.get("rationale") or "Scoring not available")

    if not item.get("id"):
        fallback_ts = item.get("date") or ""
        item["id"] = item.get("hash") or _hash_from(
            item.get("source", ""), item.get("path") or item.get("title") or "", fallback_ts
        )


def _build_attachment_items(parent: Dict[str, Any]) -> List[Dict[str, Any]]:
    attachments = parent.get("attachments") or []
    results: List[Dict[str, Any]] = []

    for attachment in attachments:
        att_name = attachment.get("name") or "Attachment"
        att_path = f"{parent.get('path', 'message')}::{att_name}"
        att_timestamp = parent.get("timestamp") or parent.get("date") or _now_iso()

        snippet = _clean_text(
            attachment.get("text") or attachment.get("read_error") or "Attachment could not be read"
        )

        att_item = {
            "source": parent.get("source", "outlook"),
            "platform": parent.get("platform") or PLATFORM_LABELS.get(parent.get("source", ""), "Outlook"),
            "title": f"{parent.get('title', 'Email')} – {att_name}",
            "path": att_path,
            "full_text": attachment.get("text") or "",
            "snippet": snippet,
            "timestamp": att_timestamp,
            "raw_timestamp": parent.get("raw_timestamp") or parent.get("timestamp_relative"),
            "timestamp_confidence": parent.get("timestamp_confidence", 0.0),
            "timestamp_estimated": bool(parent.get("timestamp_estimated")),
            "parent_hash": parent.get("hash"),
        }

        att_item["hash"] = _hash_from(att_item["source"], att_path, att_timestamp)
        if attachment.get("read_error"):
            att_item.setdefault("notes", attachment.get("read_error"))

        results.append(att_item)

    return results


def _expand_attachment_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    expanded: List[Dict[str, Any]] = []
    for item in items:
        expanded.append(item)
        expanded.extend(_build_attachment_items(item))
    return expanded

def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


async def _soft_scroll(page: Any, times: int = 5, delay: int = 500) -> None:
    """Smooth scroll to trigger lazy loading using multiple strategies."""
    for _ in range(times):
        try:
            await page.mouse.wheel(0, 600)
        except Exception:
            try:
                await page.evaluate("window.scrollBy(0, window.innerHeight / 2)")
            except Exception:
                pass
        try:
            await page.keyboard.press("PageDown")
        except Exception:
            pass
        await page.wait_for_timeout(delay)


async def _query_with_fallbacks(node: Any, selectors: List[str], attribute: Optional[str] = None) -> str:
    for sel in selectors:
        try:
            handle = await node.query_selector(sel)
        except Exception:
            handle = None
        if not handle:
            continue
        try:
            if attribute:
                value = await handle.get_attribute(attribute)
            else:
                value = await handle.inner_text()
        except Exception:
            value = ""
        text = _clean_text(value)
        if text:
            return text
    return ""

def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def _parse_ts(ts_str: str) -> Optional[dt.datetime]:
    value = (ts_str or "").strip()
    if not value:
        return None

    for parser in (
        lambda s: dt.datetime.fromisoformat(s),
        lambda s: dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ"),
        lambda s: dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
        lambda s: dt.datetime.strptime(s, "%m/%d/%Y %H:%M %p"),
    ):
        try:
            return parser(value)
        except Exception:
            continue

    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        parsed = None
    if parsed:
        return parsed

    lowered = value.lower()
    now = dt.datetime.now(dt.timezone.utc)
    base_date: Optional[dt.date] = None

    if "yesterday" in lowered:
        base_date = (now - dt.timedelta(days=1)).date()
    elif "today" in lowered:
        base_date = now.date()
    elif lowered.startswith("last "):
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        parts = lowered.split()
        if len(parts) >= 2:
            token = parts[1]
            target = weekdays.get(token)
            if target is None:
                for name, idx in weekdays.items():
                    if name.startswith(token):
                        target = idx
                        break
            if target is not None:
                delta = (now.weekday() - target) % 7 or 7
                base_date = (now - dt.timedelta(days=delta)).date()

    if base_date is None:
        return None

    time_match = re.search(r"(\d{1,2}:\d{2}\s*(?:am|pm)?)", value, flags=re.IGNORECASE)
    time_value = dt.time(hour=0, minute=0, tzinfo=now.tzinfo)
    if time_match:
        token = time_match.group(1).strip()
        for fmt in ("%I:%M %p", "%H:%M"):
            try:
                parsed_time = dt.datetime.strptime(token.upper(), fmt).time()
                time_value = parsed_time.replace(tzinfo=now.tzinfo)
                break
            except Exception:
                continue

    return dt.datetime.combine(base_date, time_value, tzinfo=now.tzinfo)

def _in_month(ts: Optional[dt.datetime], month_bounds: Optional[object]) -> bool:
    if not ts or not month_bounds:
        return True

    if isinstance(month_bounds, MonthBounds):
        return month_bounds.start <= ts < month_bounds.end

    try:
        start, end = month_bounds  # type: ignore[misc]
    except Exception:
        return True

    if isinstance(start, dt.datetime):
        return start <= ts < end  # type: ignore[operator]

    return start <= ts.date() < end  # type: ignore[operator]

def _hash_from(source: str, path: str, timestamp: str = "") -> str:
    """Deterministic hash for dedup."""
    h = hashlib.sha1()
    h.update(source.encode("utf-8"))
    h.update(b"|")
    h.update(path.encode("utf-8"))
    h.update(b"|")
    h.update(timestamp.encode("utf-8"))
    return h.hexdigest()

async def _ocr_element_text(element: Any) -> str:
    """Attempt OCR-based text extraction from an element screenshot."""
    if not OCR_AVAILABLE or element is None:
        return ""

    try:
        data = await element.screenshot(type="png")
    except Exception as exc:
        logger.debug("Element screenshot failed for OCR: %s", exc)
        return ""

    try:
        with Image.open(io.BytesIO(data)) as img:  # type: ignore[arg-type]
            text = pytesseract.image_to_string(img, config="--psm 6")  # type: ignore[union-attr]
    except Exception as exc:
        logger.debug("OCR text extraction failed: %s", exc)
        return ""

    return _clean_text(text)


async def _extract_element_text(node: Any, selector: str, timeout: int = 5000, allow_ocr: bool = True) -> str:
    """Extract text from first matching element with optional OCR fallback."""
    element = None
    try:
        await node.wait_for_selector(selector, timeout=timeout)
        element = await node.query_selector(selector)
    except Exception:
        element = None

    if not element:
        return ""

    try:
        text = await element.inner_text()
    except Exception:
        text = ""

    cleaned = _clean_text(text)
    if cleaned:
        return cleaned

    if allow_ocr:
        return await _ocr_element_text(element)

    return ""

# --------------------------------------------------------------------------------------
# Scrapers
# --------------------------------------------------------------------------------------

async def _scroll_element(element: Any, *, step: int = 600, max_attempts: int = 8) -> None:
    """Attempt to scroll a Playwright element node from top to bottom."""

    if not element:
        return

    try:
        await element.evaluate(
            "(node) => { node.scrollTop = 0; node.dataset.__vampScrollHeight = node.scrollHeight; }"
        )
    except Exception:
        return

    for _ in range(max_attempts):
        try:
            await element.evaluate(
                "(node, delta) => { node.scrollBy({ top: delta, behavior: 'smooth' }); }",
                step,
            )
            await asyncio.sleep(0.3)
        except Exception:
            break


async def _gather_outlook_attachments(page: Any, download_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Collect metadata (and optionally content) for Outlook attachments."""

    attachments: List[Dict[str, Any]] = []
    seen_nodes: set[str] = set()

    for selector in ATTACHMENT_CANDIDATES:
        try:
            nodes = await page.query_selector_all(selector)
        except Exception:
            nodes = []

        for node in nodes:
            try:
                handle_id = await node.get_attribute("data-attachment-id")
            except Exception:
                handle_id = None

            if handle_id and handle_id in seen_nodes:
                continue
            if handle_id:
                seen_nodes.add(handle_id)

            name = await _query_with_fallbacks(node, ATTACHMENT_NAME_SELECTORS)
            if not name:
                try:
                    aria = await node.get_attribute("aria-label")
                except Exception:
                    aria = ""
                name = _clean_text(aria)

            try:
                href = await node.get_attribute("href")
            except Exception:
                href = None

            info: Dict[str, Any] = {
                "name": name or "Attachment",
                "href": href or "",
            }

            try:
                extraction = await extract_text_from_attachment(
                    page,
                    node,
                    download_dir,
                    reader=ATTACHMENT_READER,
                )
                info.update(extraction)
            except Exception as exc:
                logger.debug("Attachment extraction failed for %s: %s", name or "attachment", exc)
                info.setdefault("read_error", f"Attachment could not be read: {exc}")

            if not info.get("text") and not info.get("read_error"):
                info.setdefault("read_error", "Attachment could not be read")

            attachments.append(info)

    return attachments


async def scrape_outlook(
    page: Any,
    month_bounds: Optional[object] = None,
    *,
    deep_read: bool = True,
    on_progress: Optional[Callable[[int, str], Any]] = None,
) -> List[Dict[str, Any]]:
    """Outlook scraper with optional deep read and month filtering."""
    items: List[Dict[str, Any]] = []
    seen_hashes: set[str] = set()
    download_dir: Optional[Path] = None
    now_ref = dt.datetime.now(dt.timezone.utc)

    if deep_read:
        try:
            download_dir = Path(tempfile.mkdtemp(prefix="vamp_outlook_attach_"))
        except Exception:
            download_dir = None

    try:
        await page.wait_for_load_state("networkidle")
        for inbox_selector in OUTLOOK_SELECTORS.inbox_list:
            try:
                await page.wait_for_selector(inbox_selector, timeout=12000)
                break
            except Exception:
                continue
        await page.wait_for_selector('[role="listitem"], [role="option"]', timeout=20000)
    except Exception:
        logger.warning(
            "Outlook message list not detected in expected time; continuing with adaptive scrape"
        )
        if on_progress:
            try:
                await on_progress(25, "Waiting for Outlook mailbox to stabilize...")
            except Exception:
                pass

    await _soft_scroll(page, times=20, delay=300)

    rows: List[Any] = []
    selector_hits: List[Tuple[str, int]] = []

    for attempt in range(3):
        rows.clear()
        selector_hits.clear()
        for sel in OUTLOOK_ROW_SELECTORS:
            try:
                nodes = await page.query_selector_all(sel)
            except Exception:
                nodes = []
            if not nodes:
                continue
            selector_hits.append((sel, len(nodes)))
            rows.extend(nodes)

        if rows:
            break

        if attempt < 2:
            logger.debug(
                "Outlook selectors matched zero rows (attempt %d); retrying after soft scroll",
                attempt + 1,
            )
            await _soft_scroll(page, times=15 + (attempt * 5), delay=350)
            await page.wait_for_timeout(OUTLOOK_RETRY_WAIT_MS)

    if not rows:
        try:
            rows = await page.query_selector_all('div[role="listitem"]')
        except Exception:
            rows = []

    if not rows:
        logger.warning("No Outlook rows located after selector retries; returning empty result set")
        return items

    if selector_hits:
        for sel, count in selector_hits:
            logger.debug("Outlook selector %s matched %d nodes", sel, count)
    else:
        logger.debug("Outlook fallback selector matched %d nodes", len(rows))

    total_rows = len(rows) or 1

    for idx, row in enumerate(rows):
        if len(items) >= OUTLOOK_MAX_ROWS:
            break

        try:
            await row.scroll_into_view_if_needed()
        except Exception:
            try:
                await row.evaluate("node => node.scrollIntoView({block: 'center', inline: 'nearest'})")
            except Exception:
                pass

        meta: Dict[str, Any] = {}
        subject = await _query_with_fallbacks(row, OUTLOOK_SELECTORS.message_subject)
        sender = await _query_with_fallbacks(row, OUTLOOK_SELECTORS.message_sender)
        preview = await _query_with_fallbacks(row, OUTLOOK_SELECTORS.message_preview)
        ts_text = await _query_with_fallbacks(row, OUTLOOK_SELECTORS.message_date)
        aria_label = ""
        convo_id = ""
        node_text = ""

        try:
            meta = await row.evaluate(
                """
                (node) => {
                    const attr = (name) => node.getAttribute(name) || "";
                    return {
                        aria: attr('aria-label'),
                        convoId: attr('data-convid') || attr('data-conversation-id') || attr('data-conversationid') || attr('data-unique-id'),
                        nodeText: node.innerText || "",
                        timestampAttr: attr('data-converteddatetime') || attr('data-timestamp')
                    };
                }
                """
            )
        except Exception as exc:
            logger.debug("Outlook row metadata evaluation failed: %s", exc)

        aria_label = _clean_text(meta.get("aria")) if meta else ""
        convo_id = _clean_text(meta.get("convoId")) if meta else ""
        node_text = _clean_text(meta.get("nodeText")) if meta else ""
        if not ts_text and meta:
            ts_text = _clean_text(meta.get("timestampAttr"))
        if not node_text:
            try:
                direct_text = await row.inner_text()
            except Exception:
                direct_text = ""
            node_text = _clean_text(direct_text)
        if not node_text:
            node_text = await _ocr_element_text(row)

        if node_text:
            parts = [p.strip() for p in node_text.split("\n") if p.strip()]
        else:
            parts = []

        if not sender and parts:
            sender = parts[0]
        if not subject and len(parts) > 1:
            subject = parts[1]
        if not ts_text and parts:
            for candidate in reversed(parts):
                if any(char.isdigit() for char in candidate):
                    ts_text = candidate
                    break

        if not subject:
            subject = "(no subject)"
        if not sender:
            sender = "(unknown sender)"

        ts = parse_outlook_date(ts_text, now_ref) if ts_text else None
        if ts is None and ts_text:
            ts = _parse_ts(ts_text)
        if month_bounds and ts is None and ts_text:
            logger.warning("Skipping Outlook email with unparseable timestamp '%s'", ts_text)
            continue

        if on_progress:
            try:
                pct_window = 8.5
                pct = 30.0 + (pct_window * ((idx + 1) / total_rows))
                clipped = max(30.0, min(39.0, pct))
                subject_label = subject[:64] if subject else "(no subject)"
                await on_progress(clipped, f"Reading email {idx + 1}/{total_rows}: {subject_label}")
            except Exception:
                pass

        if ts and not _in_month(ts, month_bounds):
            continue
        if ts is None and ts_text:
            logger.debug("Unable to parse Outlook timestamp '%s'; including email", ts_text)

        try:
            await row.hover()
        except Exception:
            pass

        opened = False
        try:
            await row.click(timeout=4000)
            opened = True
        except Exception:
            try:
                await row.focus()
                await page.keyboard.press("Enter")
                opened = True
            except Exception:
                logger.debug("Unable to activate Outlook row for %s", subject)

        body_text = ""
        if opened:
            try:
                selectors_js = json.dumps(BODY_SELECTORS)
                await page.wait_for_function(
                    dedent(
                        f"""
                        () => {{
                            const selectors = {selectors_js};
                            for (const sel of selectors) {{
                                const doc = document.querySelector(sel);
                                if (doc && doc.innerText && doc.innerText.trim().length > 0) {{
                                    return true;
                                }}
                            }}
                            return false;
                        }}
                        """
                    ),
                    timeout=6000,
                )
            except Exception:
                await page.wait_for_timeout(500)

            for selector in BODY_SELECTORS:
                body_text = await _extract_element_text(
                    page, selector, timeout=5000, allow_ocr=True
                )
                if body_text:
                    break

        if deep_read:
            try:
                container = None
                for selector in BODY_SELECTORS:
                    container = await page.query_selector(selector)
                    if container:
                        break
            except Exception:
                container = None
            await _scroll_element(container)

        body_text = _clean_text(body_text)

        timestamp_value = ts.isoformat() if ts else now_ref.isoformat()

        confidence = 0.95
        relative_label = None
        lowered_ts_text = ts_text.lower() if ts_text else ""
        if ts_text:
            if not any(ch.isdigit() for ch in ts_text):
                confidence = 0.55
                relative_label = ts_text
            elif any(token in lowered_ts_text for token in ["yesterday", "today", "ago", "hour", "minute", "last "]):
                confidence = 0.6
                relative_label = ts_text
        if ts is None:
            confidence = min(confidence, 0.45)

        path_id = convo_id or f"{sender} - {subject}"
        item = {
            "source": "outlook",
            "path": path_id,
            "title": subject,
            "sender": sender,
            "size": 0,
            "timestamp": timestamp_value,
        }

        if ts_text:
            item["raw_timestamp"] = ts_text
        if aria_label:
            item["aria_label"] = aria_label
        if preview:
            item["preview"] = preview
        if relative_label:
            item["timestamp_relative"] = relative_label
        item["timestamp_confidence"] = round(confidence, 3)
        if body_text:
            item["body"] = body_text
        if ts is None:
            item["timestamp_estimated"] = True

        attachments: List[Dict[str, Any]] = []
        if deep_read:
            try:
                attachments = await _gather_outlook_attachments(page, download_dir=download_dir)
            except Exception as exc:
                logger.debug("Attachment collection failed for %s: %s", subject, exc)
                attachments = []

        if attachments:
            item["attachments"] = attachments
            item["attachments_present"] = True
            item["attachment_names"] = [att.get("name") for att in attachments if att.get("name")]
            if any(att.get("text") for att in attachments):
                item["attachments_text_extracted"] = True
            if any(att.get("read_error") for att in attachments):
                note = "Attachment present but could not be read; possible evidence not fully captured."
                item.setdefault("notes", note)
        elif deep_read:
            item["attachments_present"] = False

        if deep_read and on_progress:
            try:
                await on_progress(35, f"Captured deep content for {subject[:64]}")
            except Exception:
                pass

        item_hash = _hash_from(item["source"], item["path"], item.get("timestamp", ""))
        if item_hash in seen_hashes:
            continue
        seen_hashes.add(item_hash)
        item["hash"] = item_hash

        items.append(item)

    if download_dir and download_dir.exists():
        try:
            shutil.rmtree(download_dir, ignore_errors=True)
        except Exception:
            pass

    return items

async def scrape_onedrive(page: Any, month_bounds: Optional[object] = None) -> List[Dict[str, Any]]:
    """OneDrive scraper with deep read and month filtering."""
    items: List[Dict[str, Any]] = []

    for grid_selector in ONEDRIVE_SELECTORS.grid:
        try:
            await page.wait_for_selector(grid_selector, timeout=12000)
            break
        except Exception:
            continue

    await _soft_scroll(page, times=15)

    rows: List[Any] = []
    for row_selector in ONEDRIVE_SELECTORS.row:
        try:
            rows = await page.query_selector_all(row_selector)
        except Exception:
            rows = []
        if rows:
            break

    for row in rows:
        try:
            name = await _query_with_fallbacks(row, ONEDRIVE_SELECTORS.name)
            modified = await _query_with_fallbacks(row, ONEDRIVE_SELECTORS.modified)
            ts = parse_outlook_date(modified, dt.datetime.now(dt.timezone.utc)) if modified else None
            if ts is None and modified:
                ts = _parse_ts(modified)
            if month_bounds and ts is None and modified:
                logger.debug("Skipping OneDrive row with unparseable modified label '%s'", modified)
                continue
            if not _in_month(ts, month_bounds):
                continue
            item = {
                "source": "onedrive",
                "path": name or "(unknown file)",
                "size": 0,
                "timestamp": ts.isoformat() if ts else _now_iso(),
            }
            item["hash"] = _hash_from(item["source"], item["path"], item.get("timestamp", ""))
            items.append(item)
            if len(items) >= 300:
                break
        except Exception:
            continue
    return items

async def scrape_drive(page: Any, month_bounds: Optional[object] = None) -> List[Dict[str, Any]]:
    """Google Drive scraper with deep read and month filtering."""
    items = []
    await _soft_scroll(page, times=15)

    rows = await page.query_selector_all('[role="row"]')
    for row in rows:
        try:
            name = await _extract_element_text(row, '[data-column="name"]')
            modified = await _extract_element_text(row, '[data-column="lastModified"]')
            ts = _parse_ts(modified)
            if not _in_month(ts, month_bounds):
                continue
            item = {
                "source": "drive",
                "path": name,
                "size": 0,
                "timestamp": ts.isoformat() if ts else _now_iso()
            }
            item["hash"] = _hash_from(item["source"], item["path"], item.get("timestamp", ""))
            items.append(item)
            if len(items) >= 300:
                break
        except Exception:
            continue
    return items

async def scrape_efundi(page: Any, month_bounds: Optional[object] = None) -> List[Dict[str, Any]]:
    """eFundi scraper with month filtering."""
    items = []
    await _soft_scroll(page, times=10)

    # Cover common containers: table/list rows, portlet bodies, instructions, resource lists
    sels = [
        '[role="row"]',
        '.listHier',
        '.portletBody',
        '.instruction',
        '.listHier > li',
        'table.listHier tr'
    ]
    for sel in sels:
        nodes = await page.query_selector_all(sel)
        for el in nodes:
            try:
                raw_text = await el.inner_text()
            except Exception:
                raw_text = ""
            txt = _clean_text(raw_text)
            if (not txt or len(txt) < 5) and OCR_AVAILABLE:
                txt = await _ocr_element_text(el)
            if not txt or len(txt) < 5:
                continue
            first = (txt.split("\n")[0] or "")[0:160].strip()
            if not first:
                continue
            ts_text = await _extract_element_text(el, 'time, .date', timeout=2000)
            if not ts_text:
                ts_text = await _extract_element_text(page, 'time, .date', timeout=3000, allow_ocr=False)
            ts = _parse_ts(ts_text)
            if not _in_month(ts, month_bounds):
                continue
            item = {
                "source": "eFundi",
                "path": first,
                "size": 0,
                "timestamp": ts.isoformat() if ts else _now_iso()
            }
            item["hash"] = _hash_from(item["source"], item["path"], item.get("timestamp", ""))
            items.append(item)
            if len(items) >= 300:
                break
        if len(items) >= 300:
            break
    return items

# --------------------------------------------------------------------------------------
# Router and Main Scan Function
# --------------------------------------------------------------------------------------

async def run_scan_active(
    url: str,
    on_progress: Optional[Callable] = None,
    month_bounds: Optional[object] = None,
    identity: Optional[str] = None,
    *,
    deep_read: bool = True,
) -> List[Dict[str, Any]]:
    try:
        await ensure_browser()
    except Exception as exc:
        logger.error("Browser startup failed: %s", exc)
        if on_progress:
            await on_progress(0, f"Browser startup failed: {exc}")
        return []
    
    parsed_url = urlparse(url)
    host = parsed_url.hostname.lower() if parsed_url.hostname else ""
    
    if "outlook" in host or "office365" in host or "office" in host or "live" in host:
        service = "outlook"
    elif "sharepoint" in host or "onedrive" in host or "1drv" in host:
        service = "onedrive"
    elif "drive.google" in host:
        service = "drive"
    elif "efundi.nwu.ac.za" in host:
        service = "efundi"  # No auth needed, assume
    else:
        service = None
        logger.warning(f"Unsupported host: {host}")
        return []
    
    if on_progress:
        await on_progress(10, f"Authenticating to {service}...")
    
    try:
        if service in ["outlook", "onedrive", "drive"]:
            context = await get_authenticated_context(service, identity)
        else:
            context = await get_authenticated_context(service or "generic", identity)
    except Exception as e:
        logger.error(f"Context error: {e}")
        if on_progress:
            await on_progress(0, f"Authentication failed: {e}")
        return []

    page = await context.new_page()
    
    if on_progress:
        await on_progress(20, f"Navigating to {url}...")
    
    try:
        await page.goto(url, timeout=60000)
    except PWError as e:
        logger.error(f"Navigation failed: {e}")
        await context.close()
        return []
    
    if on_progress:
        await on_progress(30, "Loading content...")

    items = []
    if service == "outlook":
        items = await scrape_outlook(page, month_bounds, deep_read=deep_read, on_progress=on_progress)
    elif service == "onedrive":
        items = await scrape_onedrive(page, month_bounds)
    elif service == "drive":
        items = await scrape_drive(page, month_bounds)
    elif service == "efundi":
        items = await scrape_efundi(page, month_bounds)

    items = _expand_attachment_items(items)

    await page.close()

    try:
        await _persist_context_state(service, identity, context)
    except Exception as exc:
        logger.debug("Failed to persist browser state for %s: %s", service, exc)

    logger.info("Scraped %d %s items from %s", len(items), service or "unknown", url)

    if on_progress:
        await on_progress(40, "Processing items...")

    # Dedup and filter
    seen = set()
    deduped = []
    for it in items:
        h = it.get("hash")
        if h not in seen:
            seen.add(h)
            deduped.append(it)
    
    await _score_and_batch(deduped, lambda batch: None, on_progress)  # Score if needed

    return deduped

# --------------------------------------------------------------------------------------
# Type Definitions and Logger Setup
# --------------------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("vamp_agent")


def _log_ocr_status_once() -> None:
    global _OCR_STATUS_LOGGED
    if _OCR_STATUS_LOGGED:
        return
    _OCR_STATUS_LOGGED = True

    if OCR_AVAILABLE:
        logger.info("OCR fallback enabled for scraper text extraction")
    else:
        if _OCR_ERROR:
            logger.info("OCR fallback disabled: %s", _OCR_ERROR)
        else:
            logger.info("OCR fallback disabled: dependencies not installed")


_log_ocr_status_once()

# --------------------------------------------------------------------------------------
# SCAN_ACTIVE Wrapper for WebSocket integration
# --------------------------------------------------------------------------------------

async def run_scan_active_ws(email=None, year=None, month=None, url=None, deep_read=True, progress_callback=None):
    import datetime as dt
    from urllib.parse import urlparse

    if not url:
        if progress_callback:
            await progress_callback(0, "Missing URL.")
        return []

    # Month bounds for filtering
    try:
        if year and month:
            y, m = int(year), int(month)
            month_bounds = compute_month_bounds(y, m, tzinfo=dt.timezone.utc)
        else:
            month_bounds = None
    except Exception:
        month_bounds = None

    if isinstance(deep_read, str):
        deep_read_flag = deep_read.strip().lower() in {"1", "true", "yes", "on"}
    else:
        deep_read_flag = bool(deep_read)

    return await run_scan_active(
        url=url,
        month_bounds=month_bounds,
        on_progress=progress_callback,
        identity=email,
        deep_read=deep_read_flag,
    )
