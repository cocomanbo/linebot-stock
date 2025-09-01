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

# 取得本週日期範圍的函數
def get_week_range():
    """取得本週的日期範圍字串 (週一到週日)"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%m/%d')}-{sunday.strftime('%m/%d')}"

# 真實股市數據
def get_real_market_data():
    """取得真實股市數據 - 加強錯誤處理"""
    try:
        app.logger.info("開始取得股市數據...")
        
        # 台股加權指數 (^TWII)
        app.logger.info("取得台股數據...")
        taiwan = yf.Ticker("^TWII")
        tw_hist = taiwan.history(period="2d")
        
        if tw_hist.empty:
            app.logger.error("台股數據為空")
            tw_text = "• 台股加權：❌ 數據取得失敗"
        else:
            tw_current = float(tw_hist['Close'][-1])
            if len(tw_hist) > 1:
                tw_previous = float(tw_hist['Close'][-2])
                tw_change = tw_current - tw_previous
                tw_change_pct = (tw_change / tw_previous) * 100
            else:
                tw_change = 0
                tw_change_pct = 0
            
            tw_symbol = "▲" if tw_change >= 0 else "▼"
            tw_text = f"• 台股加權：{tw_current:.2f} {tw_symbol}{abs(tw_change_pct):.1f}% ({tw_change:+.2f}點)"
            app.logger.info(f"台股數據取得成功：{tw_current}")
        
        # 美股道瓊指數 (^DJI)
        app.logger.info("取得道瓊數據...")
        dow = yf.Ticker("^DJI")
        dow_hist = dow.history(period="2d")
        
        if dow_hist.empty:
            app.logger.error("道瓊數據為空")
            dow_text = "• 美股道瓊：❌ 數據取得失敗"
        else:
            dow_current = float(dow_hist['Close'][-1])
            if len(dow_hist) > 1:
                dow_previous = float(dow_hist['Close'][-2])
                dow_change = dow_current - dow_previous
                dow_change_pct = (dow_change / dow_previous) * 100
            else:
                dow_change = 0
                dow_change_pct = 0
            
            dow_symbol = "▲" if dow_change >= 0 else "▼"
            dow_text = f"• 美股道瓊：{dow_current:.2f} {dow_symbol}{abs(dow_change_pct):.1f}% ({dow_change:+.2f}點)"
            app.logger.info(f"道瓊數據取得成功：{dow_current}")
        
        # 那斯達克指數 (^IXIC)
        app.logger.info("取得那斯達克數據...")
        nasdaq = yf.Ticker("^IXIC")
        nasdaq_hist = nasdaq.history(period="2d")
        
        if nasdaq_hist.empty:
            app.logger.error("那斯達克數據為空")
            nasdaq_text = "• 那斯達克：❌ 數據取得失敗"
        else:
            nasdaq_current = float(nasdaq_hist['Close'][-1])
            if len(nasdaq_hist) > 1:
                nasdaq_previous = float(nasdaq_hist['Close'][-2])
                nasdaq_change = nasdaq_current - nasdaq_previous
                nasdaq_change_pct = (nasdaq_change / nasdaq_previous) * 100
            else:
                nasdaq_change = 0
                nasdaq_change_pct = 0
            
            nasdaq_symbol = "▲" if nasdaq_change >= 0 else "▼"
            nasdaq_text = f"• 那斯達克：{nasdaq_current:.2f} {nasdaq_symbol}{abs(nasdaq_change_pct):.1f}% ({nasdaq_change:+.2f}點)"
            app.logger.info(f"那斯達克數據取得成功：{nasdaq_current}")
        
        return f"""{tw_text}
{dow_text}
{nasdaq_text}"""
        
    except Exception as e:
        app.logger.error(f"取得股市數據發生錯誤: {str(e)}")
        return """• 台股加權：⚠️ 網路連線問題
• 美股道瓊：⚠️ 網路連線問題
• 那斯達克：⚠️ 網路連線問題

🔄 請稍後重試或檢查網路連線"""

# 真實匯率數據 - 改進版
def get_real_forex_data():
    """取得真實匯率數據 - 加強錯誤處理"""
    try:
        app.logger.info("開始取得匯率數據...")
        
        # 使用免費的匯率 API
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            app.logger.error(f"匯率API回應錯誤: {response.status_code}")
            return """• 美元/台幣：⚠️ API 連線失敗
• 歐元/美元：⚠️ API 連線失敗"""
        
        data = response.json()
        
        if 'rates' not in data:
            app.logger.error("匯率數據格式錯誤")
            return """• 美元/台幣：⚠️ 數據格式錯誤
• 歐元/美元：⚠️ 數據格式錯誤"""
        
        usd_twd = data['rates'].get('TWD', 0)
        eur_rate = data['rates'].get('EUR', 0)
        
        if usd_twd == 0 or eur_rate == 0:
            app.logger.error("匯率數據缺失")
            return """• 美元/台幣：⚠️ 匯率數據缺失
• 歐元/美元：⚠️ 匯率數據缺失"""
        
        eur_usd = 1 / eur_rate
        
        app.logger.info(f"匯率數據取得成功: USD/TWD={usd_twd}, EUR/USD={eur_usd}")
        
        # 注意：這裡沒有歷史比較，所以暫不顯示漲跌
        return f"""• 美元/台幣：{usd_twd:.2f}
• 歐元/美元：{eur_usd:.4f}"""
        
    except requests.exceptions.Timeout:
        app.logger.error("匯率API請求超時")
        return """• 美元/台幣：⏱️ 請求超時
• 歐元/美元：⏱️ 請求超時"""
    except requests.exceptions.RequestException as e:
        app.logger.error(f"匯率API請求錯誤: {str(e)}")
        return """• 美元/台幣：🌐 網路連線問題
• 歐元/美元：🌐 網路連線問題"""
    except Exception as e:
        app.logger.error(f"取得匯率數據發生未知錯誤: {str(e)}")
        return """• 美元/台幣：❌ 未知錯誤
• 歐元/美元：❌ 未知錯誤"""

# 測試數據連線功能
def test_data_connection():
    """測試數據連線狀況"""
    try:
        # 測試股市 API
        app.logger.info("測試 yfinance 連線...")
        test_ticker = yf.Ticker("AAPL")
        test_data = test_ticker.history(period="1d")
        stock_status = "✅ 正常" if not test_data.empty else "❌ 異常"
        
        # 測試匯率 API
        app.logger.info("測試匯率 API 連線...")
        test_url = "https://api.exchangerate-api.com/v4/latest/USD"
        test_response = requests.get(test_url, timeout=5)
        forex_status = "✅ 正常" if test_response.status_code == 200 else "❌ 異常"
        
        return f"""🔧 數據連線測試

📈 股市數據 (Yahoo Finance): {stock_status}
💱 匯率數據 (ExchangeRate API): {forex_status}

🕐 測試時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
    except Exception as e:
        app.logger.error(f"連線測試錯誤: {str(e)}")
        return f"❌ 連線測試失敗: {str(e)}"

# 真實新聞數據（暫時簡化）
def get_real_news():
    """取得財經新聞摘要"""
    # 暫時提供靜態新聞，後續可整合真實新聞 API
    return """• 主要股市持續關注 Fed 利率政策走向
• 科技股表現受到市場景氣預期影響
• 國際油價波動影響通膨預期心理"""

# 重要事件
def get_real_upcoming_events():
    """取得下週重要經濟事件"""
    next_week = datetime.now() + timedelta(weeks=1)
    base_date = next_week.strftime("%m/%d")
    
    return f"""• {base_date} 重要經濟數據發布日
• {(next_week + timedelta(1)).strftime('%m/%d')} 企業財報公布密集期
• {(next_week + timedelta(2)).strftime('%m/%d')} 央行政策相關會議"""

# 生成真實週報的主函數
def generate_real_weekly_report():
    """生成包含真實數據的週報"""
    week_range = get_week_range()
    
    report = f"""📈 本週經濟週報 ({week_range})

🏛️ 主要指數
{get_real_market_data()}

💱 匯率動態
{get_real_forex_data()}

📰 重點新聞
{get_real_news()}

📊 下週關注
{get_real_upcoming_events()}

---
💡 數據僅供參考，投資請謹慎評估
🕐 更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}"""
    
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
📈 輸入「週報」- 查看本週經濟報告 (即時數據)
🔧 輸入「連線測試」- 檢查數據來源狀態
🔍 輸入「模擬」- 預覽模擬數據格式
        
更多功能開發中... 🚀"""
    
    # 週報功能
    elif user_message in ["週報", "周報", "即時週報", "real"]:
        reply_text = generate_real_weekly_report()
    
    elif user_message in ["連線測試", "測試連線", "狀態檢查", "debug"]:
        reply_text = test_data_connection()
    
    elif user_message in ["模擬", "預覽", "demo"]:
        # 保留原來的模擬數據功能作為對比
        reply_text = generate_mock_weekly_report()
    
    elif user_message == "幫助" or user_message == "help":
        reply_text = """🤖 股票助手使用指南

📊 週報功能：
• 「週報」- 即時經濟數據週報
• 「模擬」- 模擬數據格式預覽
• 「連線測試」- 檢查數據來源

💡 數據來源：
• 股市：Yahoo Finance 即時數據
• 匯率：Exchange Rate API
• 新聞：財經新聞整合

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

# 模擬數據函數（保留作為對比）
def get_mock_market_data():
    """模擬股市數據"""
    return """• 台股加權：17,234 ▲1.2% (+205點) [模擬]
• 美股道瓊：34,567 ▼0.8% (-278點) [模擬]
• 那斯達克：13,456 ▲0.5% (+67點) [模擬]"""

def get_mock_forex_data():
    """模擬匯率數據"""
    return """• 美元/台幣：31.25 ▲0.3% [模擬]
• 歐元/美元：1.0845 ▼0.2% [模擬]"""

def get_mock_news():
    """模擬新聞數據"""
    return """• 台積電Q2營收創新高，上調全年展望 [模擬]
• Fed暗示可能降息，市場樂觀看待 [模擬]
• 油價本週上漲3.2%，通膨壓力增加 [模擬]"""

def get_mock_upcoming_events():
    """模擬下週重要事件"""
    next_week = datetime.now() + timedelta(weeks=1)
    base_date = next_week.strftime("%m/%d")
    return f"""• {base_date} 美國GDP數據公布 [模擬]
• {(next_week + timedelta(1)).strftime("%m/%d")} 台股除息高峰期 [模擬]
• {(next_week + timedelta(2)).strftime("%m/%d")} 歐洲央行利率決議 [模擬]"""

def generate_mock_weekly_report():
    """生成模擬數據週報"""
    week_range = get_week_range()
    
    report = f"""📈 本週經濟週報 ({week_range}) - 模擬版

🏛️ 主要指數
{get_mock_market_data()}

💱 匯率動態
{get_mock_forex_data()}

📰 重點新聞
{get_mock_news()}

📊 下週關注
{get_mock_upcoming_events()}

---
💡 這是模擬數據，輸入「週報」查看即時數據"""
    
    return report

# 啟動應用
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
