"""
scrape_wantgoo.py
玩股網股東會紀念品爬蟲

策略：
  玩股網用 Vue.js 動態渲染，requests 直接抓只會拿到空殼。
  → 用 Playwright 讓瀏覽器把 JS 跑完，
  → 再用 BeautifulSoup 解析已渲染的 HTML，
  → 和 HiStock 同樣的解析邏輯。

已確認的 HTML 欄位（c-model 屬性）：
  stock-code / stock-name  → 股票代號、公司名稱
  c-model="souvenirs"          → 紀念品
  c-model="latestBuyDateFormat"→ 最後買進日
  c-model="dateFormat"         → 開會日期
  c-model="type"               → 性質（常會/臨時）
  data-original-title          → 完整開會地址
  span text (city)             → 開會城市
  c-model="oddSharesNotice"    → 零股寄單
  c-model="isReElection"       → 董監改選
  c-model="agentFormat"        → 股代
  c-model="agentPhone"         → 股代電話
"""

import json
import os
from datetime import datetime

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False
    print("⚠️  請先安裝: pip install playwright && playwright install chromium")

PAGE_URL = "https://www.wantgoo.com/stock/calendar/shareholders-meeting-souvenirs?year={year}"


def _get_rendered_html(year: int) -> str:
    """用 Playwright 讓頁面完整渲染後，回傳 HTML 字串"""
    url = PAGE_URL.format(year=year)
    print(f"🌐 啟動瀏覽器，載入頁面（約需 10~20 秒）...")

    with sync_playwright() as p:
      # 定義瀏覽器類型 (修正 NameError 的關鍵)
        browser_type = p.chromium
        # 修改後 (增加對 Actions 環境的支援)
        browser = browser_type.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", # 防止記憶體不足導致崩潰
            ]
        )
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "zh-TW,zh;q=0.9"})

        page.goto(url, wait_until="networkidle", timeout=60000)

        # 等到表格第一列出現（代表 Vue.js 已渲染完成）
        try:
            page.wait_for_selector(
                "td[c-model='souvenirs']",
                timeout=30000
            )
            print("  ✅ 頁面渲染完成")
        except PWTimeout:
            print("  ⚠️  等待逾時，嘗試用目前已載入的內容解析")

        html = page.content()
        browser.close()

    return html


def fetch_souvenirs(year: int = 2026) -> list[dict]:
    """
    抓取玩股網股東會紀念品，回傳整理後的 list。
    """
    if not PLAYWRIGHT_OK:
        print("❌ 未安裝 playwright，無法執行")
        return []

    html = _get_rendered_html(year)
    soup = BeautifulSoup(html, "html.parser")

    # 找所有有紀念品的列（以 c-model="souvenirs" 的 td 為基準）
    souvenir_cells = soup.find_all("td", attrs={"c-model": "souvenirs"})
    print(f"  找到 {len(souvenir_cells)} 個紀念品欄位")

    if not souvenir_cells:
        print("❌ 沒有找到資料，可能頁面結構改變")
        return []

    results = []
    for td in souvenir_cells:
        tr = td.find_parent("tr")
        if not tr:
            continue

        # ── 股票代號 & 公司名稱 ──
        stock_code = ""
        company = ""
        link = tr.find("a", class_="stock-company")
        if link:
            code_span = link.find("span", class_="stock-code")
            name_span = link.find("span", class_="stock-name")
            stock_code = code_span.get_text(strip=True) if code_span else ""
            company    = name_span.get_text(strip=True) if name_span else ""

        # ── 紀念品 ──
        souvenir = td.get_text(strip=True)

        # ── 最後買進日 ──
        latest_buy = _cmodel(tr, "latestBuyDateFormat")

        # ── 開會日期 ──
        meeting_date = _cmodel(tr, "dateFormat")

        # ── 性質（常會/臨時） ──
        meeting_type = _cmodel(tr, "type")

        # ── 開會地點（城市 + 完整地址） ──
        city = ""
        address = ""
        city_span = tr.find("span", attrs={"data-toggle": "tooltip"})
        if city_span:
            city    = city_span.get_text(strip=True)
            address = city_span.get("data-original-title", "").strip()

        # ── 零股寄單 ──
        odd_shares = _cmodel(tr, "oddSharesNotice")

        # ── 董監改選 ──
        re_election = _cmodel(tr, "isReElection")

        # ── 股代 & 電話 ──
        agent       = _cmodel(tr, "agentFormat")
        agent_phone = _cmodel(tr, "agentPhone")

        # ── 詳細頁網址 ──
        detail_url = ""
        detail_a = tr.find("a", class_="detail-btn")
        if detail_a:
            href = detail_a.get("href", "")
            detail_url = f"https://www.wantgoo.com{href}" if href.startswith("/") else href

        results.append({
            "stock_code":      stock_code,
            "company":         company,
            "souvenir":        souvenir,
            "latest_buy_date": latest_buy,        # MM/DD
            "meeting_date":    meeting_date,       # MM/DD
            "meeting_type":    meeting_type,
            "city":            city,
            "address":         address,
            "odd_shares":      odd_shares,
            "re_election":     re_election,
            "agent":           agent,
            "agent_phone":     agent_phone,
            "detail_url":      detail_url,
        })

    print(f"✅ 共整理 {len(results)} 筆紀念品資料")
    return results


def _cmodel(tr, name: str) -> str:
    """從 <tr> 內找特定 c-model 屬性的 <td>，回傳文字"""
    td = tr.find("td", attrs={"c-model": name})
    return td.get_text(strip=True) if td else ""


def save_to_json(data: list[dict], year: int = 2026) -> str:
    os.makedirs("data", exist_ok=True)
    filepath = f"data/souvenirs_{year}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "source":     "玩股網",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "year":       year,
            "total":      len(data),
            "data":       data,
        }, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON 已儲存: {filepath}")
    return filepath


if __name__ == "__main__":
    year = 2026
    data = fetch_souvenirs(year)

    if data:
        print("\n📋 前 5 筆預覽：")
        print(f"{'代號':<6} {'公司':<8} {'最後買進':>8} {'開會日':>7}  {'紀念品'}")
        print("-" * 70)
        for item in data[:5]:
            print(
                f"{item['stock_code']:<6} "
                f"{item['company']:<8} "
                f"{item['latest_buy_date']:>8} "
                f"{item['meeting_date']:>7}  "
                f"{item['souvenir'][:30]}"
            )
        save_to_json(data, year)
    else:
        print("❌ 沒有抓到資料")
