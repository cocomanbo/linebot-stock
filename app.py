# debug_api.py - API調用診斷工具
import yfinance as yf
import requests
import traceback
from datetime import datetime
import logging

# 設定日誌
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_yfinance():
    """測試 yfinance 套件"""
    print("=== 測試 yfinance ===")
    try:
        # 測試台積電
        ticker = yf.Ticker("2330.TW")
        info = ticker.info
        print(f"✅ 台積電資料: {info.get('longName', 'N/A')}")
        print(f"✅ 當前價格: {info.get('currentPrice', 'N/A')}")
        
        # 測試美股
        aapl = yf.Ticker("AAPL")
        aapl_info = aapl.info
        print(f"✅ Apple資料: {aapl_info.get('longName', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ yfinance錯誤: {str(e)}")
        traceback.print_exc()
        return False

def test_requests():
    """測試 requests 套件"""
    print("\n=== 測試 requests ===")
    try:
        # 測試簡單 HTTP 請求
        response = requests.get("https://httpbin.org/json", timeout=10)
        print(f"✅ HTTP狀態碼: {response.status_code}")
        print(f"✅ 回應內容: {response.json()}")
        
        # 測試台灣證交所 (如果可訪問)
        tse_url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
        params = {
            'response': 'json',
            'date': '20241101',
            'stockNo': '2330'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        tse_response = requests.get(tse_url, params=params, headers=headers, timeout=10)
        print(f"✅ 證交所API狀態: {tse_response.status_code}")
        
        return True
        
    except Exception as e:
        print(f"❌ requests錯誤: {str(e)}")
        traceback.print_exc()
        return False

def test_network_connectivity():
    """測試網路連線"""
    print("\n=== 測試網路連線 ===")
    test_urls = [
        "https://www.google.com",
        "https://finance.yahoo.com",
        "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
    ]
    
    for url in test_urls:
        try:
            response = requests.head(url, timeout=5)
            print(f"✅ {url}: {response.status_code}")
        except Exception as e:
            print(f"❌ {url}: {str(e)}")

def main():
    print(f"診斷時間: {datetime.now()}")
    print("=" * 50)
    
    # 執行所有測試
    yf_ok = test_yfinance()
    req_ok = test_requests()
    test_network_connectivity()
    
    print("\n" + "=" * 50)
    print("診斷結果總結:")
    print(f"yfinance: {'✅ 正常' if yf_ok else '❌ 異常'}")
    print(f"requests: {'✅ 正常' if req_ok else '❌ 異常'}")

if __name__ == "__main__":
    main()
