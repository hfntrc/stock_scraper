# -*- coding: utf-8 -*-
"""
TDCC 電子投票資料爬蟲（含分頁）
"""

import json
import os
from datetime import datetime
from bs4 import BeautifulSoup

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://stockservices.tdcc.com.tw/evote/index.html?language=TW"


def get_all_data():
    results = []

    with sync_playwright() as p:
        print("🌐 啟動瀏覽器...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(URL, wait_until="networkidle", timeout=60000)

        page_num = 1

        while True:
            print(f"\n📄 抓第 {page_num} 頁...")

            # 等資料出現
            try:
                page.wait_for_selector("tr.btnPopup", timeout=10000)
            except PWTimeout:
                print("❌ 等不到資料")
                break

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            rows = soup.select("tr.btnPopup")
            print(f"  找到 {len(rows)} 筆")

            if not rows:
                print("❌ 沒資料，結束")
                break

            for tr in rows:
                tds = tr.find_all("td")

                if len(tds) < 3:
                    continue

                # 股票代號
                stock_code = tds[0].contents[0].strip()

                # 公司名稱
                name_tag = tr.select_one("a.td-link")
                company = name_tag.text.strip() if name_tag else ""

                # 會議日期
                meeting_date = tds[1].text.strip()

                # 投票日期
                vote_date = tds[2].text.strip()

                # 其他資訊（從 data-* 抓）
                agency = tr.get("data-agencycompany", "")
                phone = tr.get("data-phone", "")
                vote_range = tr.get("data-voteat", "")

                results.append({
                    "stock_code": stock_code,
                    "company": company,
                    "meeting_date": meeting_date,
                    "vote_date": vote_date,
                    "vote_range": vote_range,
                    "agency": agency,
                    "phone": phone
                })

            # 👉 找下一頁按鈕
            next_btn = page.locator(".btn-next")

            # 👉 如果不存在就結束
            if next_btn.count() == 0:
                print("🚫 沒有下一頁按鈕")
                break

            # 👉 判斷是否可點（有些頁會 disabled）
            try:
                if not next_btn.is_enabled():
                    print("🚫 已到最後一頁")
                    break
            except:
                pass

            # 👉 點擊下一頁
            print("➡️ 前往下一頁...")
            next_btn.click()

            # 👉 等待資料刷新（關鍵）
            page.wait_for_timeout(2000)

            page_num += 1

            # 安全限制（避免無限跑）
            if page_num > 300:
                print("⚠️ 超過300頁強制停止")
                break

        browser.close()

    print(f"\n✅ 共抓到 {len(results)} 筆資料")
    return results


def save_json(data):
    os.makedirs("data", exist_ok=True)
    path = f"data/evote_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"💾 已儲存: {path}")


if __name__ == "__main__":
    data = get_all_data()

    if data:
        print("\n📋 前5筆：")
        for item in data[:5]:
            print(item)

        save_json(data)
    else:
        print("❌ 沒抓到資料")