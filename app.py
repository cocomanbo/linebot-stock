import os
import sqlite3
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import yfinance as yf
import requests
from datetime import datetime, timedelta
import logging
import traceback
import threading
import time

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化 Flask app
app = Flask(__name__)

# LINE Bot 設定
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN') or os.getenv('CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET') or os.getenv('CHANNEL_SECRET')

if not channel_access_token or not channel_secret:
    logger.error("❌ LINE Bot 環境變數未設定")
    raise ValueError("CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET must be set")

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# 全局變數用於緩存
cache = {}
cache_timeout = 300  # 5分鐘緩存

def format_stock_message(stock_data):
    """改良的股票訊息格式化"""
    if not stock_data:
        return "❌ 無法獲取股票數據，請稍後再試"
    
    # 選擇表情符號
    if stock_data['change'] > 0:
        change_emoji = "📈"
        change_color = "🟢"
    elif stock_data['change'] < 0:
        change_emoji = "📉" 
        change_color = "🔴"
    else:
        change_emoji = "➡️"
        change_color = "⚪"
    
    # 格式化漲跌
    change_sign = "+" if stock_data['change'] >= 0 else ""
    
    # 數據來源標記
    source_indicators = {
        'yfinance': "🌐 即時數據",
        'twse': "🇹🇼 證交所",
        'smart_fallback': "🤖 智能估算",
        'fallback': "⚠️ 參考數據"
    }
    
    source_text = source_indicators.get(stock_data['source'], "📊 數據")
    
    # 市場狀態
    market_state = ""
    if 'market_state' in stock_data:
        state_map = {
            'REGULAR': "🟢 盤中",
            'CLOSED': "🔴 收盤", 
            'PRE': "🟡 盤前",
            'POST': "🟠 盤後"
        }
        if stock_data['market_state'] in state_map:
            market_state = f"\n📊 狀態: {state_map[stock_data['market_state']]}"
    
    return f"""
{change_emoji} {stock_data['name']} ({stock_data['symbol']})
💰 價格: ${stock_data['price']}
{change_color} 漲跌: {change_sign}{stock_data['change']} ({change_sign}{stock_data['change_percent']:.2f}%)
⏰ 更新: {datetime.now().strftime('%H:%M:%S')}
🔗 來源: {source_text}{market_state}
""".strip()

def generate_weekly_report():
    """改良的週報生成"""
    try:
        # 取得主要股票數據
        stocks_to_check = [
            ('2330.TW', '台股代表'),
            ('AAPL', '美股科技'),
            ('TSLA', '電動車'),
            ('NVDA', 'AI晶片')  # 新增熱門股票
        ]
        
        stock_reports = []
        success_count = 0
        
        for symbol, category in stocks_to_check:
            stock_data = StockService.get_stock_info(symbol)
            if stock_data:
                # 簡化版股票資訊用於週報
                change_emoji = "📈" if stock_data['change'] >= 0 else "📉"
                change_sign = "+" if stock_data['change'] >= 0 else ""
                
                report_line = f"{change_emoji} {stock_data['name']}: ${stock_data['price']} ({change_sign}{stock_data['change_percent']:.2f}%)"
                stock_reports.append(report_line)
                
                if stock_data['source'] in ['yfinance', 'twse']:
                    success_count += 1
        
        # 數據品質指示
        data_quality = "🟢 即時數據" if success_count >= 2 else "🟡 混合數據" if success_count >= 1 else "🔴 參考數據"
        
        # 組合週報
        week_start = (datetime.now() - timedelta(days=7)).strftime('%m/%d')
        week_end = datetime.now().strftime('%m/%d')
        
        report = f"""
📊 股市週報 ({week_start} - {week_end})
{'='*30}

📈 重點股票表現:
{chr(10).join(stock_reports)}

📰 本週關注重點:
• 🏦 聯準會決議與利率走向
• 💻 科技股財報季表現
• 🌍 地緣政治風險評估
• ⚡ AI與電動車產業動向

💡 投資策略建議:
• 📊 持續關注利率變化影響
• 🔍 留意個股財報與獲利表現
• 🛡️ 適度分散投資風險
• 📈 關注長期成長趨勢

📊 數據品質: {data_quality}
⏰ 報告時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """.strip()
        
        return report
        
    except Exception as e:
        logger.error(f"❌ 週報生成失敗: {str(e)}")
        return f"""
📊 股市週報
⚠️ 報告生成時遇到問題

🔧 系統狀態: 維護中
📞 建議: 請稍後再試或使用個別股票查詢

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """.strip()

def init_db():
    """初始化資料庫"""
    try:
        conn = sqlite3.connect('stock_bot.db')
        cursor = conn.cursor()
        
        # 創建用戶追蹤表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                alert_price REAL,
                alert_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, symbol)
            )
        ''')
        
        # 創建提醒記錄表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                alert_price REAL NOT NULL,
                current_price REAL NOT NULL,
                alert_type TEXT NOT NULL,
                triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ 資料庫初始化完成")
        
    except Exception as e:
        logger.error(f"❌ 資料庫初始化失敗: {str(e)}")

def format_stock_message(stock_data):
    """改良的股票訊息格式化"""
    if not stock_data:
        return "❌ 無法獲取股票數據，請稍後再試"
    
    # 選擇表情符號
    if stock_data['change'] > 0:
        change_emoji = "📈"
        change_color = "🟢"
    elif stock_data['change'] < 0:
        change_emoji = "📉" 
        change_color = "🔴"
    else:
        change_emoji = "➡️"
        change_color = "⚪"
    
    # 格式化漲跌
    change_sign = "+" if stock_data['change'] >= 0 else ""
    
    # 數據來源標記
    source_indicators = {
        'yfinance': "🌐 即時數據",
        'twse': "🇹🇼 證交所",
        'smart_fallback': "🤖 智能估算",
        'fallback': "⚠️ 參考數據"
    }
    
    source_text = source_indicators.get(stock_data['source'], "📊 數據")
    
    # 市場狀態
    market_state = ""
    if 'market_state' in stock_data:
        state_map = {
            'REGULAR': "🟢 盤中",
            'CLOSED': "🔴 收盤", 
            'PRE': "🟡 盤前",
            'POST': "🟠 盤後"
        }
        if stock_data['market_state'] in state_map:
            market_state = f"\n📊 狀態: {state_map[stock_data['market_state']]}"
    
    return f"""
{change_emoji} {stock_data['name']} ({stock_data['symbol']})
💰 價格: ${stock_data['price']}
{change_color} 漲跌: {change_sign}{stock_data['change']} ({change_sign}{stock_data['change_percent']:.2f}%)
⏰ 更新: {datetime.now().strftime('%H:%M:%S')}
🔗 來源: {source_text}{market_state}
""".strip()
def generate_weekly_report():
    """改良的週報生成"""
    try:
        # 取得主要股票數據
        stocks_to_check = [
            ('2330.TW', '台股代表'),
            ('AAPL', '美股科技'),
            ('TSLA', '電動車'),
            ('NVDA', 'AI晶片')  # 新增熱門股票
        ]
        
        stock_reports = []
        success_count = 0
        
        for symbol, category in stocks_to_check:
            stock_data = StockService.get_stock_info(symbol)
            if stock_data:
                # 簡化版股票資訊用於週報
                change_emoji = "📈" if stock_data['change'] >= 0 else "📉"
                change_sign = "+" if stock_data['change'] >= 0 else ""
                
                report_line = f"{change_emoji} {stock_data['name']}: ${stock_data['price']} ({change_sign}{stock_data['change_percent']:.2f}%)"
                stock_reports.append(report_line)
                
                if stock_data['source'] in ['yfinance', 'twse']:
                    success_count += 1
        
        # 數據品質指示
        data_quality = "🟢 即時數據" if success_count >= 2 else "🟡 混合數據" if success_count >= 1 else "🔴 參考數據"
        
        # 組合週報
        week_start = (datetime.now() - timedelta(days=7)).strftime('%m/%d')
        week_end = datetime.now().strftime('%m/%d')
        
        report = f"""
📊 股市週報 ({week_start} - {week_end})
{'='*30}

📈 重點股票表現:
{chr(10).join(stock_reports)}

📰 本週關注重點:
- 🏦 聯準會決議與利率走向
- 💻 科技股財報季表現
- 🌍 地緣政治風險評估
- ⚡ AI與電動車產業動向

💡 投資策略建議:
- 📊 持續關注利率變化影響
- 🔍 留意個股財報與獲利表現
- 🛡️ 適度分散投資風險
- 📈 關注長期成長趨勢

📊 數據品質: {data_quality}
⏰ 報告時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """.strip()
        
        return report
        
    except Exception as e:
        logger.error(f"❌ 週報生成失敗: {str(e)}")
        return f"""
📊 股市週報
⚠️ 報告生成時遇到問題

🔧 系統狀態: 維護中
📞 建議: 請稍後再試或使用個別股票查詢

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """.strip()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    logger.info("📨 收到請求")
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("❌ 簽名驗證失敗")
        abort(400)
    except Exception as e:
        logger.error(f"❌ 處理請求時發生錯誤: {str(e)}")
        traceback.print_exc()
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    
    logger.info(f"👤 用戶 {user_id} 發送: {user_message}")
    
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            
            # 處理不同指令
            if user_message in ['你好', 'hello', 'hi']:
                reply_text = "👋 你好！我是股票監控機器人\n輸入「功能」查看可用指令"
                
            elif user_message == '功能':
                reply_text = """
📱 可用功能:
• 「週報」- 查看本週股市報告
• 「台股」- 查看台積電股價
• 「美股」- 查看Apple股價  
• 「測試」- 系統狀態檢查
• 「診斷」- API功能診斷
• 「追蹤 [股票代號]」- 追蹤股票 (開發中)
                """.strip()
                
            elif user_message == '週報':
                logger.info("🔄 生成週報中...")
                reply_text = generate_weekly_report()
                
            elif user_message == '台股':
                logger.info("🔄 查詢台積電...")
                stock_data = StockService.get_stock_info('2330.TW')
                reply_text = format_stock_message(stock_data)
                
            elif user_message == '美股':
                logger.info("🔄 查詢Apple...")
                stock_data = StockService.get_stock_info('AAPL')
                reply_text = format_stock_message(stock_data)
                
            elif user_message == '測試':
                reply_text = f"✅ 系統正常運作\n⏰ 時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📦 緩存項目: {len(cache)}"
            
            elif user_message == '診斷':
                # 簡化版診斷
                try:
                    test_stock = StockService.get_stock_info('2330.TW')
                    if test_stock and test_stock['source'] == 'yfinance':
                        reply_text = "✅ API功能正常\n🔗 即時數據連線成功"
                    elif test_stock and test_stock['source'] == 'fallback':
                        reply_text = "⚠️ API功能異常\n🔄 使用備用數據模式"
                    else:
                        reply_text = "❌ API功能故障\n請稍後再試"
                except Exception as e:
                    reply_text = f"❌ 診斷失敗: {str(e)}"
                
            else:
                reply_text = "🤔 不認識的指令\n輸入「功能」查看可用指令"
            
            # 發送回覆
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
            logger.info("✅ 訊息發送成功")
            
    except Exception as e:
        logger.error(f"❌ 處理訊息失敗: {str(e)}")
        traceback.print_exc()

@app.route("/")
def home():
    return f"""
    <h1>LINE Bot 股票監控系統</h1>
    <p>狀態: ✅ 運行中</p>
    <p>時間: {datetime.now()}</p>
    <p>緩存項目: {len(cache)}</p>
    <p><a href="/debug">診斷頁面</a></p>
    """

@app.route("/health")
def health():
    """健康檢查端點"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_items": len(cache)
    }

@app.route("/debug")
def debug_api():
    """診斷API功能的端點"""
    results = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'tests': {}
    }
    
    # 測試 yfinance
    try:
        ticker = yf.Ticker("2330.TW")
        info = ticker.info
        results['tests']['yfinance'] = {
            'status': 'success',
            'data': {
                'name': info.get('longName', 'N/A'),
                'price': info.get('currentPrice', 'N/A')
            }
        }
    except Exception as e:
        results['tests']['yfinance'] = {
            'status': 'error',
            'error': str(e)
        }
    
    # 測試 requests
    try:
        response = requests.get("https://httpbin.org/json", timeout=10)
        results['tests']['requests'] = {
            'status': 'success',
            'status_code': response.status_code
        }
    except Exception as e:
        results['tests']['requests'] = {
            'status': 'error',
            'error': str(e)
        }
    
    # 測試股票服務
    try:
        stock_data = StockService.get_stock_info('2330.TW')
        results['tests']['stock_service'] = {
            'status': 'success' if stock_data else 'no_data',
            'data': stock_data
        }
    except Exception as e:
        results['tests']['stock_service'] = {
            'status': 'error',
            'error': str(e)
        }
    
    return results

@app.route("/test-stock/<symbol>")
def test_stock(symbol):
    """測試特定股票"""
    try:
        stock_data = StockService.get_stock_info(symbol)
        return {
            'symbol': symbol,
            'success': stock_data is not None,
            'data': stock_data,
            'formatted': format_stock_message(stock_data)
        }
    except Exception as e:
        return {
            'symbol': symbol,
            'success': False,
            'error': str(e)
        }

if __name__ == "__main__":
    logger.info("🚀 啟動 LINE Bot 股票監控系統...")
    init_db()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

