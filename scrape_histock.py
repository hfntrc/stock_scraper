"""
scrape_histock.py
功能：抓取 HiStock (嗨投資) 股東會紀念品資料
特點：處理 HTML 表格解析，確保能抓到公司名稱、紀念品名稱與關鍵日期。
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

# 目標網址 (2026 年)
BASE_URL = "https://histock.tw/stock/gift.aspx"
TARGET_URL = f"{BASE_URL}?year=2026"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://histock.tw/",
}

def fetch_histock_souvenirs() -> list[dict]:
    """爬取 HiStock 網頁表格並解析資料"""
    print(f"📡 正在請求 HiStock 網頁: {TARGET_URL}")
    
    try:
        resp = requests.get(TARGET_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        # HiStock 有時會使用 utf-8，確保編碼正確
        resp.encoding = 'utf-8'
    except Exception as e:
        print(f"❌ 請求失敗: {e}")
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # HiStock 的資料主要存在於 table.t-m 或是具有特定 class 的表格中
    # 我們抓取所有的資料列 (tr)
    rows = soup.select('table.t-m tr')
    
    if not rows:
        # 嘗試另一種常見的 selector
        rows = soup.select('tr[id^="ctl00_"] ') or soup.find_all('tr')

    results = []
    
    # 遍歷每一列，跳過標題列
    for row in rows:
        cols = row.find_all('td')
        # 典型的 HiStock 紀念品表格約有 10-11 個欄位
        if len(cols) < 8:
            continue
            
        try:
            # 欄位索引通常如下：
            # 0: 代號, 1: 名稱, 2: 股價, 3: 最後買進日, 4: 股東會日期, 
            # 5: 性質, 6: 地點, 7: 紀念品, 8: 零股寄單, 9: 股代
            stock_code   = cols[0].get_text(strip=True)
            
            # 過濾掉非數字的代號列（例如標題或廣告列）
            if not stock_code.isdigit():
                continue
                
            company      = cols[1].get_text(strip=True)
            # 移除名稱中可能夾雜的股價變動符號
            company      = company.split('+')[0].split('-')[0].strip()
            
            last_buy     = cols[3].get_text(strip=True)
            meeting_date = cols[4].get_text(strip=True)
            souvenir     = cols[7].get_text(strip=True)
            location     = cols[6].get_text(strip=True)
            odd_shares   = cols[8].get_text(strip=True)
            agent        = cols[9].get_text(strip=True)
            agent_phone  = cols[10].get_text(strip=True) if len(cols) > 10 else ""

            results.append({
                "stock_code":      stock_code,
                "company":         company,
                "meeting_date":    f"2026/{meeting_date}" if '/' in meeting_date else meeting_date,
                "latest_buy_date": f"2026/{last_buy}" if '/' in last_buy else last_buy,
                "souvenir":        souvenir.replace("參考圖", "").strip(),
                "location":        location,
                "odd_shares":      odd_shares,
                "agent":           agent,
                "agent_phone":     agent_phone.strip(),
                "source_url":      TARGET_URL
            })
        except Exception:
            continue

    print(f"✅ 解析完成，共獲得 {len(results)} 筆有效資料")
    return results

def save_data(data: list[dict]):
    """儲存資料為 JSON 檔案"""
    if not data:
        print("⚠️ 沒有資料可儲存")
        return
        
    os.makedirs("data", exist_ok=True)
    filepath = "data/souvenirs_histock_2026.json"
    
    output = {
        "source": "HiStock 嗨投資",
        "url": TARGET_URL,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(data),
        "data": data
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 資料已儲存至 {filepath}")

if __name__ == "__main__":
    souvenir_list = fetch_histock_souvenirs()
    
    if souvenir_list:
        print("\n📋 HiStock 資料預覽 (前 5 筆)：")
        print(f"{'代碼':<5} | {'公司':<8} | {'最後買進':<10} | {'紀念品'}")
        print("-" * 60)
        for item in souvenir_list[:5]:
            print(f"{item['stock_code']:<5} | {item['company']:<8} | {item['latest_buy_date']:<10} | {item['souvenir']}")
        
        save_data(souvenir_list)
    else:
        print("\n❌ 未能抓取到資料，請確認網路連線或網頁結構是否變動。")