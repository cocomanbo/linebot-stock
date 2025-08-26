# app.py
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

# 取得本週日期範圍的函數
def get_week_range():
    """取得本週的日期範圍字串 (週一到週日)"""
    today = datetime.now()
    # 找到本週一 (weekday() 0=週一, 6=週日)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%m/%d')}-{sunday.strftime('%m/%d')}"

# 模擬數據函數
def get_mock_market_data():
    """模擬股市數據"""
    return """• 台股加權：17,234 ▲1.2% (+205點)
• 美股道瓊：34,567 ▼0.8% (-278點)  
• 那斯達克：13,456 ▲0.5% (+67點)"""

def get_mock_forex_data():
    """模擬匯率數據"""
    return """• 美元/台幣：31.25 ▲0.3%
• 歐元/美元：1.0845 ▼0.2%"""

def get_mock_news():
    """模擬新聞數據"""
    return """• 台積電Q2營收創新高，上調全年展望
• Fed暗示可能降息，市場樂觀看待
• 油價本週上漲3.2%，通膨壓力增加"""

def get_mock_upcoming_events():
    """模擬下週重要事件"""
    next_week = datetime.now() + timedelta(weeks=1)
    base_date = next_week.strftime("%m/%d")
    return f"""• {base_date} 美國GDP數據公布
• {(next_week + timedelta(1)).strftime("%m/%d")} 台股除息高峰期
• {(next_week + timedelta(2)).strftime("%m/%d")} 歐洲央行利率決議"""

# 生成週報的主函數
def generate_weekly_report():
    """生成完整的週報內容"""
    week_range = get_week_range()
    
    report = f"""📈 本週經濟週報 ({week_range})

🏛️ 主要指數
{get_mock_market_data()}

💱 匯率動態
{get_mock_forex_data()}

📰 重點新聞
{get_mock_news()}

📊 下週關注
{get_mock_upcoming_events()}

---
💡 本報告僅供參考，投資請謹慎評估"""
    
    return report

# 健康檢查端點
@app.route("/")
def hello():
    return "LINE Bot 正在運行中！"

# LINE Webhook 端點
@app.route("/callback", methods=['POST'])
def callback():
    """處理來自 LINE 的所有訊息"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("收到請求: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("簽章驗證失敗")
        abort(400)

    return 'OK'

# 處理文字訊息的函數
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """當用戶發送文字訊息時，這個函數會被呼叫"""
    user_message = event.message.text.strip()
    
    # 基本功能
    if user_message == "你好":
        reply_text = "你好！我是你的股票助手 📈"
    elif user_message == "測試":
        reply_text = "測試成功！Bot 正常運作中 ✅"
    elif user_message == "功能":
        reply_text = """目前可用功能：
📝 輸入「你好」- 打招呼
🧪 輸入「測試」- 測試連線
📋 輸入「功能」- 查看此說明
📈 輸入「週報」- 查看本週經濟報告
🔍 輸入「預覽」- 預覽週報格式
        
更多功能開發中... 🚀"""
    
    # 新增的週報功能
    elif user_message in ["週報", "周報", "週報預覽", "预览", "預覽"]:
        reply_text = generate_weekly_report()
    
    elif user_message == "幫助" or user_message == "help":
        reply_text = """🤖 股票助手使用指南

📊 週報功能：
• 「週報」- 查看完整經濟週報
• 「預覽」- 預覽報告格式

💡 提示：
目前為測試版本，使用模擬數據
正式版將整合即時經濟數據

📱 更多功能即將推出：
• 股價監控與提醒
• 財報發布通知  
• 個人化投資追蹤"""
    
    # 預設回應
    else:
        reply_text = f"你說了：{user_message}\n\n輸入「功能」查看可用指令"

    # 建立回應訊息
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

# 啟動應用
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
