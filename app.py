# app.py - 無外部依賴版本
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

def test_imports():
    """測試套件導入狀況"""
    results = []
    
    try:
        import yfinance
        results.append(f"✅ yfinance {yfinance.__version__}")
    except ImportError:
        results.append("❌ yfinance 未安裝")
    except Exception as e:
        results.append(f"❌ yfinance 錯誤: {str(e)}")
    
    try:
        import requests
        results.append(f"✅ requests {requests.__version__}")
    except ImportError:
        results.append("❌ requests 未安裝")
    except Exception as e:
        results.append(f"❌ requests 錯誤: {str(e)}")
    
    return "\n".join(results)

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
            reply_text = "你好！我是你的股票助手 (版本3.0 - 診斷模式) 📈"
        elif user_message == "測試":
            reply_text = "測試成功！Bot 正常運作中 ✅"
        elif user_message in ["連線測試", "測試連線"]:
            reply_text = f"""🔧 套件檢查結果

{test_imports()}

🕐 {datetime.now().strftime('%H:%M:%S')}
💾 Python: {os.sys.version.split()[0]}"""
        elif user_message in ["週報", "周報"]:
            reply_text = f"""📈 診斷模式週報 ({get_week_range()})

⚠️ 目前為診斷模式
正在檢查數據套件安裝狀況

請先執行「連線測試」確認套件狀態

🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
        elif user_message == "功能":
            reply_text = """🔧 診斷模式功能：
📝「你好」- 確認版本
🧪「測試」- 基本功能
🔍「連線測試」- 檢查套件
📈「週報」- 診斷資訊"""
        else:
            reply_text = f"收到訊息：{user_message}\n輸入「功能」查看指令"
            
    except Exception as e:
        reply_text = f"❌ 處理錯誤: {str(e)}"
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
