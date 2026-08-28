from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import nodriver as uc

OUT = Path("diagnostics/dxbinteract-auth-probe.json")
REPORT_COPY = Path("reports/dxbinteract-auth-probe.json")
PROBE_URLS = [
    "https://dxbinteract.com/dubai-property-prices",
    "https://dxbinteract.com/dubai-rental-index/elite-residences-2",
    "https://dxbinteract.com/projects/api-barsha-residential-tower",
]


def _clean(value: str | None, limit: int = 240) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _structure(html: str, url: str) -> dict[str, object]:
    headings = [
        _clean(re.sub(r"<[^>]+>", " ", x))
        for x in re.findall(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", html, flags=re.I | re.S)
    ]
    headings = [x for x in headings if x][:80]
    table_headers = [
        _clean(re.sub(r"<[^>]+>", " ", x))
        for x in re.findall(r"<th\b[^>]*>(.*?)</th>", html, flags=re.I | re.S)
    ]
    table_headers = [x for x in table_headers if x][:100]
    inputs = []
    for tag in re.findall(r"<input\b[^>]*>", html, flags=re.I):
        attrs = {}
        for key in ("type", "name", "id", "placeholder", "autocomplete"):
            match = re.search(rf"\b{key}=[\"']([^\"']*)[\"']", tag, flags=re.I)
            attrs[key] = _clean(match.group(1)) if match else None
        inputs.append(attrs)
    plain = _clean(re.sub(r"<[^>]+>", " ", html), limit=12000) or ""
    lower = plain.lower()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return {
        "url": _safe_url(url),
        "title": _clean(title_match.group(1) if title_match else None),
        "headings": headings,
        "inputs": inputs[:80],
        "table_headers": table_headers,
        "keywords_seen": [
            key
            for key in (
                "transaction",
                "transactions",
                "rental",
                "rentals",
                "sold",
                "rented",
                "unit series",
                "property history",
                "project sales history",
                "project rent history",
                "service charge",
                "login",
                "log in",
                "account",
            )
            if key in lower
        ],
        "cloudflare_challenge": "performing security verification" in lower
        or "cf-turnstile-response" in html,
    }


async def _find_first(tab, selectors: list[str]):
    for selector in selectors:
        try:
            element = await tab.select(selector, timeout=2)
            if element:
                return element
        except Exception:
            continue
    return None


async def _authenticate(tab, username: str, password: str) -> dict[str, object]:
    result: dict[str, object] = {
        "login_entry_found": False,
        "username_field_found": False,
        "password_field_found": False,
        "submitted": False,
        "success_signal": False,
    }
    try:
        login = await tab.find("log in", best_match=True, timeout=3)
        if not login:
            login = await tab.find("login", best_match=True, timeout=3)
        if login:
            result["login_entry_found"] = True
            await login.click()
            await tab.sleep(1.5)
    except Exception:
        pass

    username_field = await _find_first(
        tab,
        [
            "input[type=email]",
            "input[name*=email]",
            "input[name*=user]",
            "input[autocomplete=username]",
        ],
    )
    password_field = await _find_first(
        tab,
        ["input[type=password]", "input[autocomplete=current-password]"],
    )
    result["username_field_found"] = bool(username_field)
    result["password_field_found"] = bool(password_field)

    if username_field and password_field:
        await username_field.clear_input()
        await username_field.send_keys(username)
        await password_field.clear_input()
        await password_field.send_keys(password)
        submit = await _find_first(tab, ["button[type=submit]", "input[type=submit]"])
        if not submit:
            try:
                submit = await tab.find("log in", best_match=True, timeout=2)
            except Exception:
                submit = None
        if submit:
            await submit.click()
            result["submitted"] = True
            await tab.sleep(3)

    html = await tab.get_content()
    lower = html.lower()
    result["success_signal"] = bool(
        result["submitted"]
        and not any(x in lower for x in ("invalid password", "incorrect password", "login failed"))
        and any(x in lower for x in ("logout", "log out", "my account", "profile"))
    )
    result["post_login_url"] = _safe_url(tab.url)
    result["post_login_cloudflare"] = (
        "cf-turnstile-response" in html or "performing security verification" in lower
    )
    return result


def _write_probe(payload: dict[str, object]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_COPY.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2)
    OUT.write_text(rendered, encoding="utf-8")
    REPORT_COPY.write_text(rendered, encoding="utf-8")


async def main() -> None:
    username = os.getenv("DXBINTERACT_USERNAME")
    password = os.getenv("DXBINTERACT_PASSWORD")
    if not username or not password:
        _write_probe({"credentials_present": False, "status": "credentials-missing"})
        print("DXB auth probe skipped: credentials unavailable")
        return

    chrome_bin = os.getenv("CHROME_BIN") or None
    try:
        browser = await uc.start(
            headless=False,
            browser_executable_path=chrome_bin,
            browser_args=[
                "--window-size=1920,1080",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
            lang="en-US",
            expert=False,
            no_sandbox=True,
        )
    except Exception as exc:
        _write_probe(
            {
                "credentials_present": True,
                "engine": "nodriver",
                "status": "browser-start-failed",
                "error_type": type(exc).__name__,
            }
        )
        print(f"DXB auth probe browser start failed: {type(exc).__name__}")
        return

    try:
        tab = await browser.get(PROBE_URLS[0])
        await tab.sleep(2)
        before_html = await tab.get_content()
        before = _structure(before_html, tab.url)
        auth = await _authenticate(tab, username, password)

        pages: list[dict[str, object]] = []
        for url in PROBE_URLS:
            try:
                tab = await browser.get(url)
                await tab.sleep(2)
                pages.append(_structure(await tab.get_content(), tab.url))
            except Exception as exc:
                pages.append({"url": _safe_url(url), "error": type(exc).__name__})

        payload = {
            "credentials_present": True,
            "engine": "nodriver",
            "status": "completed",
            "before_login": before,
            "auth": auth,
            "pages": pages,
        }
        _write_probe(payload)
        print(
            "DXB nodriver auth probe: "
            f"submitted={auth['submitted']} success_signal={auth['success_signal']} "
            f"before_cloudflare={before['cloudflare_challenge']} pages={len(pages)}"
        )
    finally:
        browser.stop()
        await asyncio.sleep(0.2)


if __name__ == "__main__":
    asyncio.run(main())
