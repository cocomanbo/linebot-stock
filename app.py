# app.py
import os
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
# 這兩個值會從環境變數讀取（稍後設定）
configuration = Configuration(
    access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
)
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 健康檢查端點（確認服務正常運行）
@app.route("/")
def hello():
    return "LINE Bot 正在運行中！"

# LINE Webhook 端點
@app.route("/callback", methods=['POST'])
def callback():
    """
    這個函數處理來自 LINE 的所有訊息
    LINE 伺服器會將用戶訊息推送到這個端點
    """
    # 取得 LINE 的簽章（用來驗證請求是真的來自 LINE）
    signature = request.headers['X-Line-Signature']
    
    # 取得請求內容
    body = request.get_data(as_text=True)
    app.logger.info("收到請求: " + body)

    try:
        # 讓 handler 處理這個請求
        handler.handle(body, signature)
    except InvalidSignatureError:
        # 如果簽章不對，代表請求可能不是來自 LINE
        app.logger.info("簽章驗證失敗")
        abort(400)

    return 'OK'

# 處理文字訊息的函數
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """
    當用戶發送文字訊息時，這個函數會被呼叫
    event 包含了訊息內容、發送者資訊等
    """
    # 取得用戶發送的訊息
    user_message = event.message.text
    
    # 簡單的回應邏輯
    if user_message == "你好":
        reply_text = "你好！我是你的股票助手 📈"
    elif user_message == "測試":
        reply_text = "測試成功！Bot 正常運作中 ✅"
    elif user_message == "功能":
        reply_text = """目前可用功能：
📝 輸入「你好」- 打招呼
🧪 輸入「測試」- 測試連線
📋 輸入「功能」- 查看此說明
        
更多功能開發中... 🚀"""
    else:
        reply_text = f"你說了：{user_message}\n\n輸入「功能」查看可用指令"

    # 建立回應訊息
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,  # LINE 提供的回應 token
                messages=[TextMessage(text=reply_text)]
            )
        )

# 啟動應用
if __name__ == "__main__":
    # 從環境變數取得 PORT，如果沒有就用 5000
    port = int(os.environ.get('PORT', 5000))
    
    # 啟動 Flask 應用
    # host="0.0.0.0" 讓外部可以連接（雲端部署需要）
    app.run(host="0.0.0.0", port=port, debug=False)