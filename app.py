# app.py
import os
import yfinance as yf
import requests
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, 
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# 建立 Flask 應用
app = Flask(__name__)

# LINE Bot 設定
configuration = Configuration(
    access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
)
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

def get_week_range():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%m/%d')}-{sunday.strftime('%m/%d')}"

def get_real_stock_price(symbol):
    """取得單一股票的即時價格"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")
        
        if hist.empty:
            return None, f"無法取得 {symbol} 數據"
        
        current = float(hist['Close'][-1])
        
        if len(hist) > 1:
            previous = float(hist['Close'][-2])
            change = current - previous
            change_pct = (change / previous) * 100
        else:
            change = 0
            change_pct = 0
        
        symbol_arrow = "▲" if change >= 0 else "▼"
        
        return current, f"{current:.2f} {symbol_arrow}{abs(change_pct):.1f}% ({change:+.2f}點)"
        
    except Exception as e:
        app.logger.error(f"取得 {symbol} 數據錯誤: {str(e)}")
        return None, f"❌ {symbol} 數據取得失敗"

def get_real_market_data():
    """取得真實股市數據"""
    try:
        app.logger.info("開始取得股市數據...")
        
        # 台股加權指數
        tw_price, tw_text = get_real_stock_price("^TWII")
        
        # 美股道瓊指數  
        dow_price, dow_text = get_real_stock_price("^DJI")
        
        # 那斯達克指數
        nasdaq_price, nasdaq_text = get_real_stock_price("^IXIC")
        
        result = f"""• 台股加權：{tw_text}
• 美股道瓊：{dow_text}
• 那斯達克：{nasdaq_text}"""
        
        app.logger.info(f"股市數據取得完成")
        return result
        
    except Exception as e:
        app.logger.error(f"取得股市數據總錯誤: {str(e)}")
        return """• 台股加權：⚠️ 系統錯誤
• 美股道瓊：⚠️ 系統錯誤
• 那斯達克：⚠️ 系統錯誤"""

def get_real_forex_data():
    """取得真實匯率數據"""
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return "• 匯率數據：⚠️ API 連線失敗"
        
        data = response.json()
        usd_twd = data['rates']['TWD']
        eur_usd = 1 / data['rates']['EUR']
        
        return f"""• 美元/台幣：{usd_twd:.2f}
• 歐元/美元：{eur_usd:.4f}"""
        
    except Exception as e:
        app.logger.error(f"匯率錯誤: {str(e)}")
        return "• 匯率數據：❌ 取得失敗"

def test_data_connection():
    """測試 API 連線"""
    try:
        # 測試 yfinance
        import yfinance
        test_ticker = yf.Ticker("AAPL")
        test_data = test_ticker.history(period="1d")
        yf_status = "✅" if not test_data.empty else "❌"
        
        # 測試匯率 API
        test_response = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
        forex_status = "✅" if test_response.status_code == 200 else "❌"
        
        return f"""🔧 連線測試結果

📈 股市 API: {yf_status}
💱 匯率 API: {forex_status}
📦 yfinance 版本: {yfinance.__version__}

🕐 {datetime.now().strftime('%H:%M:%S')}"""
        
    except Exception as e:
        return f"❌ 測試失敗: {str(e)}"

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
    
    if user_message == "你好":
        reply_text = "你好！我是你的股票助手 (版本2.0) 📈"
    elif user_message == "測試":
        reply_text = "測試成功！Bot 正常運作中 ✅"
    elif user_message == "功能":
        reply_text = """目前可用功能：
📝 輸入「你好」- 打招呼
🧪 輸入「測試」- 測試連線  
📋 輸入「功能」- 查看此說明
📈 輸入「週報」- 即時經濟數據
🔧 輸入「連線測試」- 檢查 API 狀態
        
更多功能開發中..."""
    elif user_message in ["週報", "周報"]:
        week_range = get_week_range()
        reply_text = f"""📈 本週經濟週報 ({week_range})

🏛️ 主要指數
{get_real_market_data()}

💱 匯率動態
{get_real_forex_data()}

---
🕐 更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}"""
        
    elif user_message in ["連線測試", "測試連線"]:
        reply_text = test_data_connection()
        
    else:
        reply_text = f"你說了：{user_message}\n\n輸入「功能」查看可用指令"

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
