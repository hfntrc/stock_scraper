"""
Scrape WantGoo shareholders meeting souvenir data.

The WantGoo page is rendered by JavaScript. On GitHub Actions, waiting for
"networkidle" can time out because analytics/ad requests may keep the network
busy. This scraper waits for DOM content, then waits for the rendered table
selectors with graceful fallbacks.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_OK = True
except ImportError:
    PlaywrightTimeoutError = Exception
    sync_playwright = None
    PLAYWRIGHT_OK = False


PAGE_URL = "https://www.wantgoo.com/stock/calendar/shareholders-meeting-souvenirs?year={year}"
OUTPUT_DIR = Path("data")


def _text(node: Any) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _cmodel(row: Any, name: str) -> str:
    cell = row.find("td", attrs={"c-model": name})
    return _text(cell)


def _save_debug_html(html: str, year: int) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"wantgoo_debug_{year}.html"
    path.write_text(html, encoding="utf-8")
    print(f"Saved debug HTML: {path}")
    return path


def _get_rendered_html(year: int) -> str:
    if not PLAYWRIGHT_OK or sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )

    url = PAGE_URL.format(year=year)
    print(f"Opening WantGoo page: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        page = browser.new_page(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page.set_extra_http_headers(
            {
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.wantgoo.com/",
            }
        )

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except PlaywrightTimeoutError:
            print("Page navigation timed out after DOM wait; continuing with current content.")

        selectors = [
            "td[c-model='souvenirs']",
            "a.stock-company",
            "table tbody tr",
        ]
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=20_000)
                print(f"Rendered selector found: {selector}")
                break
            except PlaywrightTimeoutError:
                print(f"Selector not ready yet: {selector}")

        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except PlaywrightTimeoutError:
            print("Network did not become idle; this is expected on WantGoo sometimes.")

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_500)
        html = page.content()
        browser.close()

    return html


def _parse_rows(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    souvenir_cells = soup.find_all("td", attrs={"c-model": "souvenirs"})
    for cell in souvenir_cells:
        row = cell.find_parent("tr")
        if row:
            rows.append(row)

    if not rows:
        rows = [
            row
            for row in soup.select("table tbody tr")
            if row.select_one("a.stock-company") or row.find("td", attrs={"c-model": "souvenirs"})
        ]

    results: list[dict[str, str]] = []
    seen_codes: set[str] = set()

    for row in rows:
        link = row.find("a", class_="stock-company")
        code_node = link.find("span", class_="stock-code") if link else None
        name_node = link.find("span", class_="stock-name") if link else None

        stock_code = _text(code_node)
        company = _text(name_node)
        souvenir = _cmodel(row, "souvenirs")

        if not stock_code:
            cells = row.find_all("td")
            if cells:
                stock_code = _text(cells[0]).split()[0]
            if len(cells) > 1 and not company:
                company = _text(cells[1])
            if len(cells) > 7 and not souvenir:
                souvenir = _text(cells[7])

        if not stock_code or stock_code in seen_codes:
            continue
        seen_codes.add(stock_code)

        city = ""
        address = ""
        city_span = row.find("span", attrs={"data-toggle": "tooltip"})
        if city_span:
            city = _text(city_span)
            address = city_span.get("data-original-title", "").strip()

        detail_url = ""
        detail_link = row.find("a", class_="detail-btn")
        if detail_link:
            href = detail_link.get("href", "")
            detail_url = f"https://www.wantgoo.com{href}" if href.startswith("/") else href

        results.append(
            {
                "stock_code": stock_code,
                "company": company,
                "souvenir": souvenir,
                "latest_buy_date": _cmodel(row, "latestBuyDateFormat"),
                "meeting_date": _cmodel(row, "dateFormat"),
                "meeting_type": _cmodel(row, "type"),
                "city": city,
                "address": address,
                "odd_shares": _cmodel(row, "oddSharesNotice"),
                "re_election": _cmodel(row, "isReElection"),
                "agent": _cmodel(row, "agentFormat"),
                "agent_phone": _cmodel(row, "agentPhone"),
                "detail_url": detail_url,
            }
        )

    return results


def fetch_souvenirs(year: int = 2026) -> list[dict[str, str]]:
    if not PLAYWRIGHT_OK:
        print("Playwright is missing; returning no data.")
        return []

    try:
        html = _get_rendered_html(year)
    except Exception as exc:
        print(f"Failed to render WantGoo page: {exc}")
        return []

    data = _parse_rows(html)
    print(f"Parsed WantGoo rows: {len(data)}")

    if not data:
        _save_debug_html(html, year)

    return data


def save_to_json(data: list[dict[str, str]], year: int = 2026) -> str:
    OUTPUT_DIR.mkdir(exist_ok=True)
    filepath = OUTPUT_DIR / f"souvenirs_{year}.json"
    payload = {
        "source": "WantGoo",
        "url": PAGE_URL.format(year=year),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "year": year,
        "total": len(data),
        "data": data,
    }

    filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved JSON: {filepath}")
    return str(filepath)


def main() -> int:
    year = int(os.getenv("SCRAPE_YEAR", "2026"))
    data = fetch_souvenirs(year)
    save_to_json(data, year)

    if data:
        print("\nPreview:")
        print(f"{'Code':<8} {'Company':<14} {'Last buy':<10} {'Meeting':<10} Souvenir")
        print("-" * 80)
        for item in data[:5]:
            print(
                f"{item['stock_code']:<8} "
                f"{item['company'][:12]:<14} "
                f"{item['latest_buy_date']:<10} "
                f"{item['meeting_date']:<10} "
                f"{item['souvenir'][:30]}"
            )
    else:
        print("No WantGoo rows parsed. The workflow still completed; check debug HTML if needed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
