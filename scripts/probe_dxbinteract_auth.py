from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Locator, Page, async_playwright

OUT = Path("diagnostics/dxbinteract-auth-probe.json")
PROBE_URLS = [
    "https://dxbinteract.com/area-analysis/al-karama",
    "https://dxbinteract.com/dubai-property-prices",
    "https://dxbinteract.com/interactive-price-change",
]


def _clean(value: str | None, limit: int = 180) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


async def _all_text(locator: Locator, limit: int = 80) -> list[str]:
    values: list[str] = []
    for item in await locator.all():
        try:
            text = _clean(await item.inner_text())
        except Exception:
            continue
        if text and text not in values:
            values.append(text)
        if len(values) >= limit:
            break
    return values


async def _page_structure(page: Page) -> dict[str, object]:
    inputs: list[dict[str, str | None]] = []
    for locator in await page.locator("input").all():
        inputs.append(
            {
                "type": await locator.get_attribute("type"),
                "name": await locator.get_attribute("name"),
                "id": await locator.get_attribute("id"),
                "placeholder": _clean(await locator.get_attribute("placeholder")),
                "autocomplete": await locator.get_attribute("autocomplete"),
            }
        )

    tables: list[list[str]] = []
    for table in await page.locator("table").all():
        headers = await _all_text(table.locator("th"), limit=30)
        if headers:
            tables.append(headers)

    buttons = await _all_text(page.locator("button"), limit=60)
    links = await _all_text(page.locator("a"), limit=80)
    headings: list[str] = []
    for selector in ("h1", "h2", "h3"):
        headings.extend(await _all_text(page.locator(selector), limit=40))
    headings = list(dict.fromkeys(headings))[:80]

    body_text = _clean(await page.locator("body").inner_text(), limit=6000) or ""
    keywords = [
        keyword
        for keyword in (
            "transaction",
            "transactions",
            "rental",
            "rentals",
            "sold",
            "rented",
            "unit series",
            "property history",
            "service charge",
            "median",
            "price per sqft",
        )
        if keyword in body_text.lower()
    ]

    return {
        "url": _safe_url(page.url),
        "title": _clean(await page.title()),
        "headings": headings,
        "inputs": inputs,
        "table_headers": tables,
        "buttons": buttons,
        "links": links,
        "keywords_seen": keywords,
    }


async def _click_login_entry(page: Page) -> bool:
    selectors = [
        "text=/log ?in/i",
        "text=/sign ?in/i",
        "a[href*='login']",
        "a[href*='signin']",
        "button:has-text('Login')",
        "button:has-text('Sign in')",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() and await locator.is_visible():
                await locator.click(timeout=5000)
                await page.wait_for_timeout(1200)
                return True
        except Exception:
            continue
    return False


async def _fill_first(page: Page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() and await locator.is_visible():
                await locator.fill(value)
                return True
        except Exception:
            continue
    return False


async def _submit_login(page: Page) -> bool:
    selectors = [
        "button[type='submit']",
        "button:has-text('Login')",
        "button:has-text('Log in')",
        "button:has-text('Sign in')",
        "input[type='submit']",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() and await locator.is_visible():
                await locator.click(timeout=5000)
                await page.wait_for_timeout(2500)
                return True
        except Exception:
            continue
    return False


async def _authenticate(page: Page, username: str, password: str) -> dict[str, object]:
    result: dict[str, object] = {
        "login_entry_clicked": False,
        "username_field_found": False,
        "password_field_found": False,
        "submitted": False,
        "success_signal": False,
    }

    result["login_entry_clicked"] = await _click_login_entry(page)
    result["username_field_found"] = await _fill_first(
        page,
        [
            "input[type='email']",
            "input[name*='email' i]",
            "input[name*='user' i]",
            "input[autocomplete='username']",
        ],
        username,
    )
    result["password_field_found"] = await _fill_first(
        page,
        ["input[type='password']", "input[autocomplete='current-password']"],
        password,
    )
    if result["username_field_found"] and result["password_field_found"]:
        result["submitted"] = await _submit_login(page)

    text = (await page.locator("body").inner_text()).lower()
    result["success_signal"] = bool(
        result["submitted"]
        and not any(marker in text for marker in ("invalid password", "incorrect password", "login failed"))
        and any(marker in text for marker in ("logout", "log out", "profile", "account", "dashboard"))
    )
    result["post_login_url"] = _safe_url(page.url)
    return result


async def main() -> None:
    username = os.getenv("DXBINTERACT_USERNAME")
    password = os.getenv("DXBINTERACT_PASSWORD")
    if not username or not password:
        raise SystemExit("DXBINTERACT_USERNAME/PASSWORD secrets are not available")

    chrome_bin = os.getenv("CHROME_BIN") or None
    OUT.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=chrome_bin,
        )
        context = await browser.new_context(
            locale="en-US",
            timezone_id="America/New_York",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        await page.goto(PROBE_URLS[0], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1500)
        before = await _page_structure(page)
        auth = await _authenticate(page, username, password)

        pages: list[dict[str, object]] = []
        for url in PROBE_URLS:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1500)
                pages.append(await _page_structure(page))
            except Exception as exc:
                pages.append({"url": _safe_url(url), "error": type(exc).__name__})

        payload = {
            "credentials_present": True,
            "before_login": before,
            "auth": auth,
            "pages": pages,
        }
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            "DXB auth probe: "
            f"submitted={auth['submitted']} success_signal={auth['success_signal']} "
            f"pages={len(pages)}"
        )
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
