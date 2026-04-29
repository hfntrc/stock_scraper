"""
Scrape WantGoo shareholders meeting souvenir data.

WantGoo now loads the table from JSON APIs. Scraping the rendered table is
fragile on GitHub Actions, so this script reads the same API data directly and
keeps a Playwright-free workflow.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


YEAR = 2026
BASE_URL = "https://www.wantgoo.com"
PAGE_URL = f"{BASE_URL}/stock/calendar/shareholders-meeting-souvenirs?year={{year}}"
DATA_URL = f"{BASE_URL}/stock/calendar/all-shareholders-meeting-souvenirs-data?year={{year}}"
INVESTRUE_URL = f"{BASE_URL}/investrue/all-alive"
HOLIDAY_URL = f"{BASE_URL}/global/all-holiday-data"
OUTPUT_DIR = Path("data")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": PAGE_URL.format(year=YEAR),
}

CITY_NAMES = [
    "\u53f0\u5317",
    "\u81fa\u5317",
    "\u65b0\u5317",
    "\u57fa\u9686",
    "\u65b0\u7af9",
    "\u6843\u5712",
    "\u5b9c\u862d",
    "\u53f0\u4e2d",
    "\u81fa\u4e2d",
    "\u5f70\u5316",
    "\u5357\u6295",
    "\u82d7\u6817",
    "\u96f2\u6797",
    "\u53f0\u5357",
    "\u81fa\u5357",
    "\u9ad8\u96c4",
    "\u5c4f\u6771",
    "\u6f8e\u6e56",
    "\u5609\u7fa9",
    "\u53f0\u6771",
    "\u81fa\u6771",
    "\u82b1\u84ee",
]

AGENT_MAPPING = {
    "\u4e2d\u570b\u4fe1\u8a17": "\u4e2d\u4fe1",
    "\u4e2d\u4fe1\u9280": "\u4e2d\u4fe1",
    "\u5143\u5927": "\u5143\u5927",
    "\u5143\u5bcc": "\u5143\u5bcc",
    "\u53f0\u65b0": "\u53f0\u65b0",
    "\u6c38\u8c50\u91d1": "\u6c38\u8c50\u91d1",
    "\u5146\u8c50": "\u5146\u8c50",
    "\u4e9e\u6771": "\u4e9e\u6771",
    "\u570b\u7968": "\u570b\u7968",
    "\u5eb7\u548c": "\u5eb7\u548c",
    "\u7b2c\u4e00\u91d1": "\u7b2c\u4e00\u91d1",
    "\u7d71\u4e00": "\u7d71\u4e00",
    "\u51f1\u57fa": "\u51f1\u57fa",
    "\u51f1\u7881": "\u51f1\u57fa",
    "\u5bcc\u90a6": "\u5bcc\u90a6",
    "\u83ef\u5357": "\u83ef\u5357",
    "\u7fa4\u76ca": "\u7fa4\u76ca",
    "\u5b8f\u9060": "\u5b8f\u9060",
    "\u798f\u90a6": "\u798f\u90a6",
    "\u65b0\u5149": "\u65b0\u5149",
}


def _get_json(url: str) -> Any:
    response = requests.get(url, headers=HEADERS, timeout=40)
    response.raise_for_status()
    return response.json()


def _date_from_ms(value: int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _format_mmdd(value: int | None) -> str:
    date = _date_from_ms(value)
    return date.strftime("%m/%d") if date else ""


def _is_holiday(date: datetime, holiday_dates: set[str]) -> bool:
    return date.weekday() >= 5 or date.strftime("%Y-%m-%d") in holiday_dates


def _previous_business_day(date: datetime, holiday_dates: set[str]) -> datetime:
    while _is_holiday(date, holiday_dates):
        date -= timedelta(days=1)
    return date


def _latest_buy_date(meeting_ms: int | None, holiday_dates: set[str]) -> datetime | None:
    meeting_date = _date_from_ms(meeting_ms)
    if not meeting_date:
        return None

    latest = _previous_business_day(meeting_date - timedelta(days=60), holiday_dates)
    latest = _previous_business_day(latest - timedelta(days=1), holiday_dates)
    latest = _previous_business_day(latest - timedelta(days=1), holiday_dates)
    return latest


def _format_date(date: datetime | None) -> str:
    return date.strftime("%m/%d") if date else ""


def _extract_city(location: str) -> str:
    for name in CITY_NAMES:
        if name in location:
            return name.replace("\u81fa", "\u53f0")
    return location[:2] if location else ""


def _format_agent(agent: str) -> str:
    for keyword, short_name in AGENT_MAPPING.items():
        if keyword in agent:
            return short_name
    return "\u81ea\u8fa6" if agent else ""


def _load_company_map() -> dict[str, dict[str, Any]]:
    try:
        rows = _get_json(INVESTRUE_URL)
    except Exception as exc:
        print(f"Company lookup failed; continuing without company names: {exc}")
        return {}

    return {
        str(item.get("id")): item
        for item in rows
        if item.get("country") == "TW" and item.get("type") in {"Stock", "ETF", "DR"}
    }


def _load_twse_holidays() -> set[str]:
    try:
        rows = _get_json(HOLIDAY_URL)
    except Exception as exc:
        print(f"Holiday lookup failed; weekends will still be handled: {exc}")
        return set()

    holidays = set()
    for item in rows:
        if item.get("countryCode") != "TWSE":
            continue
        raw_date = str(item.get("date", ""))[:10]
        if raw_date:
            holidays.add(raw_date)
    return holidays


def fetch_souvenirs(year: int = YEAR, include_all: bool = False) -> list[dict[str, str]]:
    print(f"Opening WantGoo API: {DATA_URL.format(year=year)}")
    rows = _get_json(DATA_URL.format(year=year))
    company_map = _load_company_map()
    holiday_dates = _load_twse_holidays()

    results: list[dict[str, str]] = []
    for row in rows:
        status = row.get("status") or ""
        souvenir = row.get("souvenirs") or status or "\u672a\u6c7a\u5b9a"
        if not include_all and status != "\u6709\u767c\u653e":
            continue

        stock_code = str(row.get("stockNo") or "").strip()
        company = company_map.get(stock_code, {})
        latest_buy = _latest_buy_date(row.get("date"), holiday_dates)
        meeting_date = _date_from_ms(row.get("date"))
        detail_date = meeting_date.strftime("%Y-%m-%d") if meeting_date else ""

        results.append(
            {
                "stock_code": stock_code,
                "company": company.get("name", ""),
                "souvenir": souvenir,
                "latest_buy_date": _format_date(latest_buy),
                "meeting_date": _format_mmdd(row.get("date")),
                "meeting_type": row.get("type") or "",
                "city": _extract_city(row.get("location") or ""),
                "address": row.get("location") or "",
                "odd_shares": "\u662f" if row.get("oddSharesNotice") else "\u5426",
                "re_election": row.get("isReElection") or "",
                "agent": _format_agent(row.get("agent") or ""),
                "agent_phone": row.get("agentPhone") or "",
                "detail_url": (
                    f"{BASE_URL}/stock/calendar/shareholders-meeting-souvenirs/"
                    f"{stock_code}/detail?date={detail_date}"
                    if stock_code and detail_date
                    else ""
                ),
            }
        )

    results.sort(key=lambda item: (item["latest_buy_date"], item["stock_code"]))
    print(f"Parsed WantGoo API rows: {len(results)}")
    return results


def save_to_json(data: list[dict[str, str]], year: int = YEAR) -> str:
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
    year = int(os.getenv("SCRAPE_YEAR", str(YEAR)))
    include_all = os.getenv("WANTGOO_INCLUDE_ALL", "").lower() in {"1", "true", "yes"}
    data = fetch_souvenirs(year, include_all=include_all)
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
        print("No WantGoo rows parsed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
