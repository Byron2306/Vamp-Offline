from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
import time


EFUNDI_URL = "https://efundi.nwu.ac.za/portal"


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _safe_fragment(value: str, length: int = 64) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
    return (text or "efundi-artifact")[:length]


def _module_codes_from_plans(search_plans: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    codes: list[str] = []
    for plan in search_plans:
        blob = " ".join(
            [
                str(plan.get("title") or ""),
                " ".join(str(k) for k in (plan.get("keywords") or [])),
            ]
        )
        for prefix, number in re.findall(r"\b([A-Z]{2,})\s*([0-9]{2,})\b", blob):
            code = f"{prefix}{number}".upper()
            if code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def _artifact(path: Path, title: str, body: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{title}\n{'=' * len(title)}\n\n{body}\n", encoding="utf-8")
    return str(path)


def _dismiss_efundi_popups(page: Any) -> None:
    """Dismiss common eFundi/Sakai landing-page alerts and announcement modals."""
    selectors = [
        "button:has-text('Dismiss Alert')",
        "a:has-text('Dismiss Alert')",
        "button:has-text('Don\\'t show this again')",
        "button:has-text(\"Don't show this again\")",
        "a:has-text('Don\\'t show this again')",
        "a:has-text(\"Don't show this again\")",
        "button:has-text('Remind me later')",
        "a:has-text('Remind me later')",
        "button[aria-label*='Close']",
        "a[aria-label*='Close']",
        "button:has-text('Close')",
        ".close",
        ".modal button:has-text('×')",
    ]
    for _ in range(4):
        dismissed = False
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() > 0 and locator.is_visible(timeout=500):
                    locator.click(timeout=1200)
                    page.wait_for_timeout(700)
                    dismissed = True
                    break
            except Exception:
                continue
        if not dismissed:
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            except Exception:
                pass
            break


def _open_module_site(page: Any, code: str) -> bool:
    """Open a specific eFundi module site from the visible portal navigation."""
    variants = [code, f"{code}-2026", code.replace(" ", ""), code.replace(" ", "-")]
    for variant in variants:
        for selector in [
            f"a:has-text('{variant}')",
            f"button:has-text('{variant}')",
            f"[title*='{variant}']",
            f"text={variant}",
        ]:
            try:
                locator = page.locator(selector).first
                if locator.count() > 0 and locator.is_visible(timeout=700):
                    locator.click(timeout=2500)
                    page.wait_for_timeout(2500)
                    _dismiss_efundi_popups(page)
                    return True
            except Exception:
                continue
    return False


def _open_tool_page(page: Any, tool_names: list[str]) -> tuple[bool, str]:
    """Open a module tool from the left nav / top nav by visible label."""
    for name in tool_names:
        for selector in [
            f"a:has-text('{name}')",
            f"button:has-text('{name}')",
            f"[title*='{name}']",
            f"[aria-label*='{name}']",
            f"text={name}",
        ]:
            try:
                locator = page.locator(selector).first
                if locator.count() > 0 and locator.is_visible(timeout=700):
                    locator.click(timeout=3000)
                    page.wait_for_timeout(2500)
                    _dismiss_efundi_popups(page)
                    return True, name
            except Exception:
                continue
    return False, ""


def _try_download_exports(page: Any, target_dir: Path, prefix: str) -> list[str]:
    """Best-effort export/download capture for gradebook/resources/tools."""
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    labels = [
        "Export",
        "Download",
        "Export Gradebook",
        "Export for Excel",
        "Export CSV",
        "CSV",
        "Excel",
        "Spreadsheet",
        "Download All",
    ]
    selectors = ["a[download]", "a[href*='download']", "button", "a"]
    seen: set[str] = set()
    for label in labels:
        for selector in selectors:
            try:
                locator = page.locator(f"{selector}:has-text('{label}')")
                count = min(locator.count(), 4)
            except Exception:
                count = 0
            for index in range(count):
                try:
                    item = locator.nth(index)
                    marker = f"{label}:{index}:{_normalize(item.inner_text(timeout=300))}"
                    if marker in seen:
                        continue
                    seen.add(marker)
                    with page.expect_download(timeout=5000) as download_info:
                        item.click(timeout=2000)
                    download = download_info.value
                    filename = download.suggested_filename or f"{prefix}_{_safe_fragment(label)}"
                    safe_name = f"{_safe_fragment(prefix, 32)}_{_safe_fragment(filename, 80)}"
                    target_path = target_dir / safe_name
                    download.save_as(str(target_path))
                    saved.append(str(target_path))
                    page.wait_for_timeout(800)
                except Exception:
                    continue
    return saved


def _link_rows(page: Any) -> list[dict[str, str]]:
    try:
        rows = page.locator("a").evaluate_all(
            """
            els => els.map(a => ({
                text: (a.innerText || a.textContent || '').trim(),
                href: a.href || '',
                title: a.title || '',
                aria: a.getAttribute('aria-label') || ''
            }))
            """
        )
    except Exception:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _tool_link_score(tool_key: str, row: dict[str, str]) -> int:
    text = _normalize(" ".join([row.get("text", ""), row.get("title", ""), row.get("aria", "")]))
    href = str(row.get("href") or "")
    blob = f"{text} {href}".lower()
    if not href or href.startswith("javascript:") or href.startswith("mailto:"):
        return 0
    if any(
        skip in blob
        for skip in (
            "logout",
            "portal/site",
            "calendar",
            "membership",
            "preferences",
            "help",
            "opens in a new window",
            "north-west-university",
            "nwu.ac.za",
        )
    ):
        return 0

    score = 0
    if tool_key == "resources":
        for marker in ("content", "resource", "attachment", "study guide", "slides", "reader", "rubric", "pdf", "docx", "pptx", "xlsx"):
            if marker in blob:
                score += 2
    elif tool_key == "announcements":
        for marker in ("announcement", "annc", "notice", "details", "view"):
            if marker in blob:
                score += 2
    elif tool_key == "assignments":
        for marker in ("assignment", "submission", "rubric", "instructions", "view"):
            if marker in blob:
                score += 2
    elif tool_key == "tests_quizzes":
        for marker in ("test", "quiz", "assessment", "exam", "view"):
            if marker in blob:
                score += 2

    if re.search(r"\.(pdf|docx?|pptx?|xlsx?|csv|txt)($|[?#])", href.lower()):
        score += 3
    if len(text) >= 4:
        score += 1
    return score


def _capture_relevant_subpages(page: Any, target_dir: Path, prefix: str, tool_key: str, limit: int = 5) -> tuple[list[str], list[str]]:
    """Open relevant tool inner links and capture their text/screenshots/downloads."""
    if tool_key not in {"resources", "announcements", "assignments", "tests_quizzes"}:
        return [], []

    rows = []
    seen: set[str] = set()
    for row in _link_rows(page):
        href = str(row.get("href") or "")
        if href in seen:
            continue
        seen.add(href)
        score = _tool_link_score(tool_key, row)
        if score:
            rows.append((score, row))
    rows.sort(key=lambda item: item[0], reverse=True)

    saved_paths: list[str] = []
    snippets: list[str] = []
    start_url = page.url
    for index, (_, row) in enumerate(rows[:limit], start=1):
        href = str(row.get("href") or "")
        label = _safe_fragment(_normalize(row.get("text") or row.get("title") or f"{tool_key}-{index}"), 48)
        if re.search(r"\.(pdf|docx?|pptx?|xlsx?|csv|txt)($|[?#])", href.lower()):
            try:
                with page.expect_download(timeout=5000) as download_info:
                    page.goto(href, wait_until="domcontentloaded", timeout=8000)
                download = download_info.value
                filename = download.suggested_filename or f"{prefix}_{label}"
                target_path = target_dir / f"{_safe_fragment(prefix, 32)}_{_safe_fragment(filename, 80)}"
                download.save_as(str(target_path))
                saved_paths.append(str(target_path))
            except Exception:
                pass
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=8000)
                page.wait_for_timeout(800)
            except Exception:
                pass
            continue

        try:
            page.goto(href, wait_until="domcontentloaded", timeout=10000)
            page.wait_for_timeout(1200)
            _dismiss_efundi_popups(page)
            body_text = _normalize(page.locator("body").inner_text(timeout=4000))
            if body_text:
                text_path = target_dir / f"{_safe_fragment(prefix, 32)}_subpage_{index}_{label}.txt"
                saved_paths.append(_artifact(text_path, f"eFundi {tool_key} subpage: {label}", f"URL: {page.url}\n\n{body_text[:10000]}"))
                snippets.append(f"{label}: {body_text[:1500]}")
            shot_path = target_dir / f"{_safe_fragment(prefix, 32)}_subpage_{index}_{label}.png"
            try:
                page.screenshot(path=str(shot_path), full_page=True)
                saved_paths.append(str(shot_path))
            except Exception:
                pass
        except Exception:
            pass
        finally:
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=10000)
                page.wait_for_timeout(1000)
                _dismiss_efundi_popups(page)
            except Exception:
                pass

    return saved_paths, snippets


def _probe_gradebook_views(page: Any, target_dir: Path, prefix: str) -> tuple[list[str], list[str]]:
    """Capture visible gradebook subtabs/views and any exports they expose."""
    labels = [
        "Course Grades",
        "Gradebook Items",
        "Student Review Mode",
        "All Grades",
        "Statistics",
        "Import / Export",
        "Import/Export",
        "Permissions",
    ]
    saved_paths: list[str] = []
    snippets: list[str] = []
    seen: set[str] = set()
    for label in labels:
        for selector in (f"a:has-text('{label}')", f"button:has-text('{label}')", f"text={label}"):
            try:
                locator = page.locator(selector).first
                if locator.count() <= 0 or not locator.is_visible(timeout=500):
                    continue
                marker = f"{label}:{selector}"
                if marker in seen:
                    continue
                seen.add(marker)
                locator.click(timeout=2500)
                page.wait_for_timeout(1800)
                _dismiss_efundi_popups(page)
                view_key = _safe_fragment(label, 40)
                body_text = _normalize(page.locator("body").inner_text(timeout=4000))
                if body_text:
                    text_path = target_dir / f"{_safe_fragment(prefix, 32)}_view_{view_key}.txt"
                    saved_paths.append(_artifact(text_path, f"eFundi Gradebook view: {label}", f"URL: {page.url}\n\n{body_text[:10000]}"))
                    snippets.append(f"{label}: {body_text[:1200]}")
                shot_path = target_dir / f"{_safe_fragment(prefix, 32)}_view_{view_key}.png"
                try:
                    page.screenshot(path=str(shot_path), full_page=True)
                    saved_paths.append(str(shot_path))
                except Exception:
                    pass
                saved_paths.extend(_try_download_exports(page, target_dir, f"{prefix}_{view_key}"))
                break
            except Exception:
                continue
    return saved_paths, snippets


def _capture_tool_artifact(
    page: Any,
    *,
    code: str,
    month_bucket: str,
    target_dir: Path,
    tool_key: str,
    tool_label: str,
    task_ids: list[str],
) -> dict[str, Any] | None:
    body_text = _normalize(page.locator("body").inner_text(timeout=5000))
    if not body_text:
        return None

    tool_dir = target_dir / tool_key
    tool_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = tool_dir / f"{_safe_fragment(code)}_{_safe_fragment(tool_key)}.png"
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        screenshot_path = Path("")

    export_paths = _try_download_exports(page, tool_dir, f"{code}_{tool_key}")
    explored_paths: list[str] = []
    explored_snippets: list[str] = []
    if tool_key == "gradebook":
        explored_paths, explored_snippets = _probe_gradebook_views(page, tool_dir, f"{code}_{tool_key}")
    else:
        explored_paths, explored_snippets = _capture_relevant_subpages(page, tool_dir, f"{code}_{tool_key}", tool_key)
    export_paths.extend(path for path in explored_paths if path not in export_paths)
    if explored_snippets:
        body_text = _normalize("\n\n".join([body_text, "Explored subpages/views:", *explored_snippets]))
    body_path = Path(
        _artifact(
            tool_dir / f"{_safe_fragment(code)}_{_safe_fragment(tool_key)}.txt",
            f"eFundi {tool_label} evidence: {code}",
            "\n".join(
                [
                    f"URL: {page.url}",
                    f"Tool: {tool_label}",
                    "",
                    body_text[:12000],
                    "",
                    "Downloaded/exported files:",
                    *export_paths,
                ]
            ),
        )
    )
    evidence_text = f"{code} eFundi {tool_label} {body_text[:3000]} {' '.join(Path(p).name for p in export_paths)}"
    digest = hashlib.sha1(evidence_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
    attachment_paths = ([str(screenshot_path)] if screenshot_path else []) + export_paths
    attachment_names = [Path(path).name for path in attachment_paths]
    return {
        "source": "efundi_playwright",
        "source_message_id": f"efundi_{code}_{tool_key}_{digest}",
        "source_url": page.url,
        "month_bucket": month_bucket,
        "subject": f"eFundi {tool_label} evidence: {code}",
        "sender": "eFundi LMS",
        "recipients": "",
        "received_at": f"{month_bucket}-01",
        "body_text": evidence_text,
        "attachment_names": attachment_names,
        "attachment_paths": attachment_paths,
        "body_artifact_path": str(body_path),
        "task_candidates": task_ids,
        "matched_tasks": [],
        "kpa_hint_code": "KPA1",
        "evidence_type_hint": f"efundi_{tool_key}",
        "search_reason": f"eFundi direct {tool_label} capture for {code}",
        "source_context": {
            "source_trust_tier": "A",
            "confidence_boost": 0.18,
            "reasons": [f"direct eFundi/LMS {tool_label} evidence"],
            "people_matches": [],
        },
        "meta": {
            "module_code": code,
            "efundi_tool": tool_key,
            "exports": export_paths,
        },
    }


def collect_efundi_candidates(
    *,
    month_bucket: str,
    search_plans: list[dict[str, Any]],
    storage_state: str | None = None,
    downloads_dir: str | None = None,
    max_items: int = 30,
    headless: bool = False,
    efundi_url: str = EFUNDI_URL,
) -> list[dict[str, Any]]:
    """Collect direct LMS/eFundi evidence for module-linked tasks.

    This first implementation is intentionally conservative: it logs into
    eFundi, finds visible module sites by module code, captures site-level
    screenshots/text, and returns evidence candidates. Tool-specific exports
    for announcements/resources/assignments/gradebook can be layered on top
    once the local eFundi DOM is observed.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "eFundi collection requires Playwright. Install it with: pip install playwright && playwright install chromium"
        ) from exc

    module_codes = _module_codes_from_plans(search_plans)
    if not module_codes:
        return []

    storage_path = Path(storage_state).expanduser() if storage_state else None
    if storage_path:
        storage_path.parent.mkdir(parents=True, exist_ok=True)

    download_root = Path(downloads_dir).expanduser() if downloads_dir else None
    if download_root:
        download_root.mkdir(parents=True, exist_ok=True)

    candidates: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        ctx_kwargs: dict[str, Any] = {"accept_downloads": True}
        if storage_path and storage_path.exists():
            ctx_kwargs["storage_state"] = str(storage_path)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        page.goto(efundi_url, wait_until="domcontentloaded")

        # Allow manual login if required. Do not treat generic portal/login
        # chrome as ready; wait until at least one target module code is visible.
        # In the visible browser, the user can log in and navigate to the sites
        # dashboard or a module site.
        ready = False
        deadline = time.monotonic() + (300 if not headless else 120)
        while time.monotonic() < deadline:
            body_text = ""
            try:
                body_text = _normalize(page.locator("body").inner_text(timeout=1500))
            except Exception:
                body_text = ""
            body_l = body_text.lower()
            if any(code.lower() in body_l for code in module_codes):
                ready = True
                break
            print(
                f"[VAMP-eFundi] Waiting for module codes on page: {', '.join(module_codes[:6])}",
                flush=True,
            )
            page.wait_for_timeout(2000)
        if not ready:
            raise RuntimeError(
                "eFundi module codes did not become visible. Complete login, open the Sites dashboard "
                "or a target module site, and retry."
            )
        _dismiss_efundi_popups(page)

        if storage_path:
            try:
                context.storage_state(path=str(storage_path))
            except Exception:
                pass

        page_text = _normalize(page.locator("body").inner_text(timeout=5000))
        for code in module_codes:
            if len(candidates) >= max_items:
                break
            code_l = code.lower()
            target_dir = (download_root or Path("backend/data/efundi/downloads")) / month_bucket / code
            target_dir.mkdir(parents=True, exist_ok=True)

            found = code_l in page_text.lower()
            opened_site = _open_module_site(page, code)
            if opened_site:
                found = True

            body_text = _normalize(page.locator("body").inner_text(timeout=5000))
            if not found and code_l not in body_text.lower():
                continue

            screenshot_path = target_dir / f"{_safe_fragment(code)}_site.png"
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:
                screenshot_path = Path("")

            body_path = Path(
                _artifact(
                    target_dir / f"{_safe_fragment(code)}_site_snapshot.txt",
                    f"eFundi site snapshot: {code}",
                    body_text[:8000],
                )
            )
            evidence_text = f"{code} eFundi LMS site snapshot {body_text[:2000]}"
            digest = hashlib.sha1(evidence_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
            matching_task_ids = [
                str(plan.get("task_id"))
                for plan in search_plans
                if str(plan.get("task_id") or "")
                and code in " ".join([str(plan.get("title") or ""), " ".join(str(k) for k in (plan.get("keywords") or []))]).upper()
            ]

            candidates.append(
                {
                    "source": "efundi_playwright",
                    "source_message_id": f"efundi_{code}_{digest}",
                    "source_url": page.url,
                    "month_bucket": month_bucket,
                    "subject": f"eFundi LMS site evidence: {code}",
                    "sender": "eFundi LMS",
                    "recipients": "",
                    "received_at": f"{month_bucket}-01",
                    "body_text": evidence_text,
                    "attachment_names": [screenshot_path.name] if screenshot_path else [],
                    "attachment_paths": [str(screenshot_path)] if screenshot_path else [],
                    "body_artifact_path": str(body_path),
                    "task_candidates": matching_task_ids,
                    "matched_tasks": [],
                    "kpa_hint_code": "KPA1",
                    "evidence_type_hint": "efundi_lms_snapshot",
                    "search_reason": f"eFundi direct LMS site snapshot for {code}",
                    "source_context": {
                        "source_trust_tier": "A",
                        "confidence_boost": 0.18,
                        "reasons": ["direct eFundi/LMS site evidence"],
                        "people_matches": [],
                    },
                    "meta": {"module_code": code},
                }
            )

            tool_specs = [
                ("gradebook", "Gradebook", ["Gradebook", "Gradebook NG", "Marks", "Markbook"]),
                ("resources", "Resources", ["Resources", "Study Guides", "Content", "Materials"]),
                ("announcements", "Announcements", ["Announcements", "Announcement"]),
                ("assignments", "Assignments", ["Assignments", "Assignment"]),
                ("tests_quizzes", "Tests & Quizzes", ["Tests & Quizzes", "Tests", "Quizzes", "Assessments"]),
            ]
            for tool_key, tool_label, labels in tool_specs:
                if len(candidates) >= max_items:
                    break
                # Re-open module page before each tool; Sakai can leave us inside
                # iframes or tool-specific views where left navigation differs.
                _open_module_site(page, code)
                opened, resolved_label = _open_tool_page(page, labels)
                if not opened:
                    continue
                artifact = _capture_tool_artifact(
                    page,
                    code=code,
                    month_bucket=month_bucket,
                    target_dir=target_dir,
                    tool_key=tool_key,
                    tool_label=resolved_label or tool_label,
                    task_ids=matching_task_ids,
                )
                if artifact:
                    candidates.append(artifact)

        context.close()
        browser.close()

    return candidates
