# app.py - 極簡修復版
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

# 建立 Flask 應用
app = Flask(__name__)

# LINE Bot 設定
configuration = Configuration(
    access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
)
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 取得本週日期範圍
def get_week_range():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%m/%d')}-{sunday.strftime('%m/%d')}"

# 簡化版即時數據
def get_simple_real_data():
    """簡化版真實數據 - 只測試基本功能"""
    try:
        import yfinance as yf
        
        # 只抓台股，減少複雜度
        ticker = yf.Ticker("^TWII")
        hist = ticker.history(period="1d")
        
        if hist.empty:
            return "❌ 無法取得股市數據"
        
        current_price = float(hist['Close'][-1])
        return f"✅ 台股加權：{current_price:.2f} (測試成功)"
        
    except ImportError:
        return "❌ yfinance 套件未安裝"
    except Exception as e:
        return f"❌ 錯誤：{str(e)}"

# 生成簡化週報
def generate_simple_report():
    week_range = get_week_range()
    
    return f"""📈 簡化週報 ({week_range})

🏛️ 數據測試
{get_simple_real_data()}

💡 這是簡化測試版本
輸入「診斷」查看詳細錯誤資訊

---
🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"""

# 健康檢查端點
@app.route("/")
def hello():
    return "LINE Bot 正在運行中！"

# Webhook 端點
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

# 處理訊息
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_message = event.message.text.strip()
    
    if user_message == "你好":
        reply_text = "你好！我是你的股票助手 📈 (版本2.0)"
    elif user_message == "測試":
        reply_text = "測試成功！Bot 正常運作中 ✅"
    elif user_message in ["週報", "简化", "簡化"]:
        reply_text = generate_simple_report()
    elif user_message in ["診斷", "debug", "錯誤"]:
        reply_text = f"""🔧 診斷資訊

📦 Python 版本：{os.sys.version}
📁 當前目錄：{os.getcwd()}
🕐 伺服器時間：{datetime.now()}

輸入「測試套件」檢查 yfinance 安裝"""
    elif user_message in ["測試套件", "套件"]:
        try:
            import yfinance
            reply_text = f"✅ yfinance 套件已安裝\n版本：{yfinance.__version__}"
        except ImportError:
            reply_text = "❌ yfinance 套件未安裝"
        except Exception as e:
            reply_text = f"⚠️ 套件檢查錯誤：{str(e)}"
    else:
        reply_text = f"你說了：{user_message}\n\n可用指令：你好、週報、診斷、測試套件"

    # 回應訊息
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

