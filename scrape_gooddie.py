"""
Scrape shareholders meeting souvenir data from gooddie.tw.

The page is server-rendered HTML. Field names are stored as Chinese labels, so
this file keeps those labels as unicode escapes to avoid Windows encoding
problems when the file is copied or uploaded.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.gooddie.tw"
MEETING_URL = f"{BASE_URL}/stock/meeting/{{year}}"
OUTPUT_DIR = "data"

LABEL_LATEST_BUY = "\u6700\u5f8c\u8cb7\u9032\u65e5"
LABEL_PROXY_DEADLINE = "\u59d4\u8a17\u4ee3\u9818\u622a\u6b62"
LABEL_EVOTE = "\u96fb\u6295"
LABEL_AGENT = "\u80a1\u52d9\u4ee3\u7406"
LABEL_MARKET = "\u5e02\u5834\u985e\u5225"
TEXT_EVOTE_YES = "\u8981\u96fb\u6295"
TEXT_SOUVENIR_SUFFIX = "\u80a1\u6771\u6703\u7d00\u5ff5\u54c1"
TEXT_HISTORY = "\u6b77\u5e74\u767c\u653e"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": BASE_URL,
}


def _clean_text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _normalize_date(value: str, year: int) -> str:
    if not value:
        return ""

    match = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", value)
    if match:
        return f"{int(match.group(1)):04d}/{int(match.group(2)):02d}/{int(match.group(3)):02d}"

    match = re.search(r"(\d{1,2})/(\d{1,2})", value)
    if match:
        return f"{year}/{int(match.group(1)):02d}/{int(match.group(2)):02d}"

    return value.strip()


def _field_value(container, label: str) -> str:
    if not container:
        return ""

    for title_div in container.find_all("div", class_="title"):
        if label not in _clean_text(title_div):
            continue

        row = title_div.find_parent("div", class_="form-row")
        if not row:
            continue

        value_div = row.find("div", class_="col")
        if value_div:
            return _clean_text(value_div)

    return ""


def _field_node(container, label: str):
    if not container:
        return None

    for title_div in container.find_all("div", class_="title"):
        if label not in _clean_text(title_div):
            continue

        row = title_div.find_parent("div", class_="form-row")
        if not row:
            continue

        value_div = row.find("div", class_="col")
        if value_div:
            return value_div

    return None


def _parse_evote(container, year: int) -> tuple[bool, str, str]:
    node = _field_node(container, LABEL_EVOTE)
    text = _clean_text(node)

    if not text or TEXT_EVOTE_YES not in text:
        return False, "", ""

    match = re.search(r"(\d{1,2}/\d{1,2})\s*[~\uff5e-]\s*(\d{1,2}/\d{1,2})", text)
    if not match:
        return True, "", ""

    return True, _normalize_date(match.group(1), year), _normalize_date(match.group(2), year)


def _fetch_page(url: str) -> BeautifulSoup | None:
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        print(f"  Request failed: {exc}")
        return None


def fetch_souvenirs(year: int = 2026) -> list[dict]:
    results: list[dict] = []
    page = 1

    print(f"Fetching gooddie.tw shareholders meeting data for {year}...")

    while True:
        url = MEETING_URL.format(year=year) if page == 1 else f"{MEETING_URL.format(year=year)}?page={page}"
        print(f"  Page {page}: {url}")

        soup = _fetch_page(url)
        if not soup:
            break

        page_results = []
        for card in soup.select("div.card"):
            item = _parse_single_card(card, year)
            if item:
                page_results.append(item)

        print(f"  Parsed cards: {len(page_results)}")
        if not page_results:
            break

        results.extend(page_results)

        next_link = soup.select_one("li.PagedList-skipToNext a[rel='next']")
        if not next_link or not next_link.get("href"):
            break

        page += 1
        time.sleep(0.5)

    print(f"Done. Total rows: {len(results)}")
    return results


def _parse_title(card) -> tuple[str, str, str, str] | None:
    link = card.select_one("a.text-truncate.d-block[data-toggle='collapse']")
    if not link:
        return None

    title = _clean_text(link)
    match = re.match(r"^(\d{4,6})\s+(.+?)\s+(\d{1,2}/\d{1,2})\s+(\S+)$", title)
    if not match:
        return None

    return match.group(1), match.group(2), match.group(3), match.group(4)


def _parse_single_card(card, year: int) -> dict | None:
    title_parts = _parse_title(card)
    if not title_parts:
        return None

    stock_code, company, meeting_date, meeting_type = title_parts
    card_header = card.find("div", class_="card-header")
    card_body = card.find("div", class_="card-body")

    souvenir = _parse_souvenir(card, stock_code, company, year)

    latest_buy = _normalize_date(_field_value(card_header, LABEL_LATEST_BUY), year)
    proxy_deadline = _normalize_date(_field_value(card_header, LABEL_PROXY_DEADLINE), year)
    is_evote, evote_start, evote_end = _parse_evote(card_header, year)
    if not is_evote:
        is_evote, evote_start, evote_end = _parse_evote(card_body, year)

    agent_node = _field_node(card_body, LABEL_AGENT)
    agent_phone = ""
    if agent_node:
        phone_link = agent_node.find("a", href=re.compile(r"^tel:"))
        agent_phone = _clean_text(phone_link)
    agent = _field_value(card_body, LABEL_AGENT)
    if agent_phone:
        agent = agent.replace(agent_phone, "").strip()

    return {
        "stock_code": stock_code,
        "company": company,
        "souvenir": souvenir,
        "latest_buy_date": latest_buy,
        "proxy_deadline": proxy_deadline,
        "meeting_date": _normalize_date(meeting_date, year),
        "meeting_type": meeting_type,
        "is_evote": is_evote,
        "evote_start": evote_start,
        "evote_end": evote_end,
        "agent": agent,
        "agent_phone": agent_phone,
        "market": _field_value(card_body, LABEL_MARKET),
    }


def _parse_souvenir(card, stock_code: str, company: str, year: int) -> str:
    for node in card.select("div.text-truncate[title]"):
        candidate = (node.get("title") or _clean_text(node)).strip()
        if candidate and not _is_placeholder_souvenir(candidate, stock_code, company, year):
            return candidate

    gift_div = card.find("div", class_=lambda c: c and "gift-picture" in c.split())
    if not gift_div:
        return ""

    candidate = (gift_div.get("title") or "").strip()
    if _is_placeholder_souvenir(candidate, stock_code, company, year):
        return ""

    return candidate


def _is_placeholder_souvenir(value: str, stock_code: str, company: str, year: int) -> bool:
    text = re.sub(r"\s+", "", value or "")
    if not text:
        return True

    if TEXT_HISTORY in text:
        return True

    has_stock_identity = stock_code in text or (company and company in text)
    has_meeting_words = str(year) in text or TEXT_SOUVENIR_SUFFIX in text
    return has_stock_identity and has_meeting_words


def save_to_json(data: list[dict], year: int = 2026) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"souvenirs_{year}.json")
    output = {
        "source": "\u80a1\u4ee3\u7db2 gooddie.tw",
        "url": MEETING_URL.format(year=year),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "year": year,
        "total": len(data),
        "data": data,
    }

    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(f"Saved JSON: {filepath}")
    return filepath


def main() -> int:
    year = int(os.getenv("SCRAPE_YEAR", "2026"))
    data = fetch_souvenirs(year)
    save_to_json(data, year)

    if data:
        print("\nPreview:")
        print(f"{'Code':<6} {'Company':<10} {'Buy date':<10} {'Meeting':<10} {'EVote':<21} Souvenir")
        print("-" * 90)
        for item in data[:5]:
            evote = f"{item['evote_start']}~{item['evote_end']}" if item["is_evote"] else "No"
            print(
                f"{item['stock_code']:<6} "
                f"{item['company'][:8]:<10} "
                f"{item['latest_buy_date']:<10} "
                f"{item['meeting_date']:<10} "
                f"{evote:<21} "
                f"{item['souvenir'][:30]}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
