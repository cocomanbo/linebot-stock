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
channel_access_token = os.getenv('CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('CHANNEL_SECRET')

if not channel_access_token or not channel_secret:
    logger.error("❌ LINE Bot 環境變數未設定")
    raise ValueError("CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET must be set")

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# 全局變數用於緩存
cache = {}
cache_timeout = 300  # 5分鐘緩存

class StockService:
    """股票數據服務"""
    
    @staticmethod
    def get_stock_info(symbol, max_retries=2):
        """取得股票資訊，帶重試機制"""
        cache_key = f"stock_{symbol}"
        current_time = time.time()
        
        # 檢查緩存
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if current_time - timestamp < cache_timeout:
                logger.info(f"📦 使用緩存數據: {symbol}")
                return data
        
        # 嘗試獲取新數據
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 嘗試獲取 {symbol} 數據 (第{attempt+1}次)")
                
                # 使用不同的數據源
                if symbol.endswith('.TW'):
                    # 台股
                    result = StockService._get_tw_stock(symbol)
                else:
                    # 美股
                    result = StockService._get_us_stock(symbol)
                
                if result:
                    # 更新緩存
                    cache[cache_key] = (result, current_time)
                    logger.info(f"✅ 成功獲取 {symbol} 數據")
                    return result
                    
            except Exception as e:
                logger.error(f"❌ 第{attempt+1}次嘗試失敗: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)  # 等待1秒後重試
        
        logger.error(f"❌ 所有嘗試都失敗: {symbol}")
        return StockService._get_fallback_data(symbol)
    
    @staticmethod
    def _get_tw_stock(symbol):
        """獲取台股數據"""
        try:
            # 方法1: yfinance
            ticker = yf.Ticker(symbol)
            
            # 設定較短的超時時間
            info = ticker.info
            hist = ticker.history(period="2d")  # 取得最近2天數據
            
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
                change = current_price - prev_close
                change_percent = (change / prev_close * 100) if prev_close else 0
                
                return {
                    'symbol': symbol,
                    'name': info.get('longName', symbol),
                    'price': round(current_price, 2),
                    'change': round(change, 2),
                    'change_percent': round(change_percent, 2),
                    'source': 'yfinance'
                }
        except Exception as e:
            logger.warning(f"yfinance失敗: {str(e)}")
        
        return None
    
    @staticmethod
    def _get_us_stock(symbol):
        """獲取美股數據"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            current_price = info.get('currentPrice') or info.get('previousClose')
            prev_close = info.get('previousClose', current_price)
            
            if current_price:
                change = current_price - prev_close
                change_percent = (change / prev_close * 100) if prev_close else 0
                
                return {
                    'symbol': symbol,
                    'name': info.get('longName', symbol),
                    'price': round(current_price, 2),
                    'change': round(change, 2),
                    'change_percent': round(change_percent, 2),
                    'source': 'yfinance'
                }
        except Exception as e:
            logger.warning(f"美股數據獲取失敗: {str(e)}")
        
        return None
    
    @staticmethod
    def _get_fallback_data(symbol):
        """備用模擬數據"""
        logger.info(f"🔄 使用備用數據: {symbol}")
        
        # 根據股票代號提供不同的模擬數據
        fallback_data = {
            '2330.TW': {'name': '台積電', 'price': 575.0, 'change': 5.0, 'change_percent': 0.88},
            'AAPL': {'name': 'Apple Inc.', 'price': 150.25, 'change': -2.15, 'change_percent': -1.41},
            'TSLA': {'name': 'Tesla Inc.', 'price': 248.98, 'change': 12.45, 'change_percent': 5.26}
        }
        
        if symbol in fallback_data:
            data = fallback_data[symbol]
            return {
                'symbol': symbol,
                'name': data['name'],
                'price': data['price'],
                'change': data['change'],
                'change_percent': data['change_percent'],
                'source': 'fallback'
            }
        
        return None

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
    """格式化股票訊息"""
    if not stock_data:
        return "❌ 無法獲取股票數據"
    
    change_emoji = "📈" if stock_data['change'] >= 0 else "📉"
    change_sign = "+" if stock_data['change'] >= 0 else ""
    
    source_text = "⚠️ [模擬數據]" if stock_data['source'] == 'fallback' else ""
    
    return f"""
{change_emoji} {stock_data['name']} ({stock_data['symbol']})
💰 價格: ${stock_data['price']}
📊 漲跌: {change_sign}{stock_data['change']} ({change_sign}{stock_data['change_percent']:.2f}%)
⏰ 更新: {datetime.now().strftime('%H:%M:%S')}
{source_text}
""".strip()

def generate_weekly_report():
    """生成週報"""
    try:
        # 取得主要股票數據
        stocks_to_check = ['2330.TW', 'AAPL', 'TSLA']
        stock_reports = []
        
        for symbol in stocks_to_check:
            stock_data = StockService.get_stock_info(symbol)
            if stock_data:
                stock_reports.append(format_stock_message(stock_data))
        
        # 組合週報
        report_date = datetime.now().strftime('%Y-%m-%d')
        week_start = (datetime.now() - timedelta(days=7)).strftime('%m/%d')
        week_end = datetime.now().strftime('%m/%d')
        
        report = f"""
📊 週報 ({week_start} - {week_end})
{'='*25}

📈 重點股票表現:
{chr(10).join(stock_reports)}

📰 本週重點:
• 聯準會決議結果關注
• 科技股財報季持續
• 地緣政治風險評估

💡 投資建議:
• 持續關注利率走向
• 留意個股財報表現
• 適度分散風險

⏰ 報告時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """.strip()
        
        return report
        
    except Exception as e:
        logger.error(f"❌ 週報生成失敗: {str(e)}")
        return "❌ 週報生成失敗，請稍後再試"

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
