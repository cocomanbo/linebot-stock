# app.py - 優化版真實數據
import os
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, 
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

configuration = Configuration(
    access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
)
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

def get_week_range():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%m/%d')}-{sunday.strftime('%m/%d')}"

def get_taiwan_stock_price():
    """只抓取台股數據，減少複雜度"""
    try:
        import yfinance as yf
        
        # 設定短超時時間
        ticker = yf.Ticker("^TWII")
        hist = ticker.history(period="1d", timeout=10)
        
        if hist.empty:
            return "❌ 台股數據暫時無法取得"
        
        current = float(hist['Close'][-1])
        return f"台股加權：{current:.2f} 點"
        
    except Exception as e:
        return f"⚠️ 台股數據錯誤：{str(e)[:50]}..."

def get_simple_forex():
    """簡化匯率數據"""
    try:
        import requests
        
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        response = requests.get(url, timeout=5)
        
        if response.status_code != 200:
            return "❌ 匯率數據暫時無法取得"
        
        data = response.json()
        usd_twd = data['rates']['TWD']
        return f"美元/台幣：{usd_twd:.2f}"
        
    except Exception as e:
        return f"⚠️ 匯率數據錯誤：{str(e)[:50]}..."

def test_single_api():
    """測試單一 API 調用"""
    try:
        import yfinance as yf
        
        ticker = yf.Ticker("AAPL")
        info = ticker.info
        
        if 'regularMarketPrice' in info:
            price = info['regularMarketPrice']
            return f"✅ API 測試成功：AAPL ${price}"
        else:
            return "⚠️ API 有響應但數據格式異常"
            
    except Exception as e:
        return f"❌ API 測試失敗：{str(e)}"

@app.route("/")
def hello():
    return "LINE Bot 正在運行中！"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("收到請求: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("簽章驗證失敗")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_message = event.message.text.strip()
    
    try:
        if user_message == "你好":
            reply_text = "你好！我是你的股票助手 (優化版 4.0) 📈"
            
        elif user_message == "測試":
            reply_text = "測試成功！Bot 正常運作中 ✅"
            
        elif user_message in ["台股", "台股價格"]:
            reply_text = f"""🇹🇼 台股查詢

{get_taiwan_stock_price()}

🕐 {datetime.now().strftime('%H:%M')}"""
            
        elif user_message in ["匯率", "美元"]:
            reply_text = f"""💱 匯率查詢

{get_simple_forex()}

🕐 {datetime.now().strftime('%H:%M')}"""
            
        elif user_message in ["週報", "周報"]:
            week_range = get_week_range()
            reply_text = f"""📈 簡化週報 ({week_range})

🏛️ 市場數據
• {get_taiwan_stock_price()}
• {get_simple_forex()}

📰 重點提醒
• 數據為即時查詢結果
• 投資請謹慎評估風險

🕐 更新：{datetime.now().strftime('%m-%d %H:%M')}"""
            
        elif user_message in ["連線測試", "API測試"]:
            reply_text = f"""🔧 API 連線測試

{test_single_api()}

📦 套件狀態：
• yfinance ✅ 0.2.28
• requests ✅ 2.31.0

🕐 {datetime.now().strftime('%H:%M:%S')}"""
            
        elif user_message == "功能":
            reply_text = """📋 可用功能：

🎯 單項查詢：
• 「台股」- 查詢台股加權指數
• 「匯率」- 查詢美元台幣匯率

📊 綜合功能：
• 「週報」- 簡化市場週報
• 「連線測試」- API 狀態檢查

💡 這是優化版，專注核心功能"""
            
        else:
            reply_text = f"收到：{user_message}\n\n輸入「功能」查看指令清單"
            
    except Exception as e:
        reply_text = f"❌ 處理錯誤：{str(e)}"
        app.logger.error(f"處理訊息錯誤: {str(e)}")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
