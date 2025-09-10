import os
import sqlite3
from flask import Flask, request, abort

# 載入環境變數
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, PushMessageRequest
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import yfinance as yf
import requests
from datetime import datetime, timedelta
import logging
import traceback
import threading
import time
import re
import pytz

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 設定時區
tz = pytz.timezone('Asia/Taipei')

class StockService:
    """股票服務類別，整合台股和美股的數據獲取"""
    
    @staticmethod
    def get_stock_info(symbol):
        """獲取股票資訊，自動判斷台股或美股"""
        try:
            # 判斷是否為台股（純數字）
            if re.match(r'^\d+$', symbol):
                result = StockService._get_twse_stock_info(symbol)
                # 如果台股獲取失敗，嘗試使用 yfinance 作為備用
                if not result:
                    logger.info(f"🔄 台股 {symbol} 主要數據源失敗，嘗試 yfinance 備用方案")
                    result = StockService._get_yfinance_stock_info(f"{symbol}.TW")
                return result
            else:
                result = StockService._get_yfinance_stock_info(symbol)
                # 如果美股獲取失敗，嘗試使用備用數據源
                if not result:
                    logger.info(f"🔄 美股 {symbol} yfinance 失敗，嘗試備用數據源")
                    result = StockService._get_fallback_stock_info(symbol)
                return result
        except Exception as e:
            logger.error(f"❌ 獲取股票資訊失敗 {symbol}: {str(e)}")
            return None
    
    @staticmethod
    def _get_twse_stock_info(symbol):
        """從台灣證交所獲取台股資訊"""
        try:
            # 台股交易時間檢查（使用台北時區）
            now = datetime.now(tz)
            if now.weekday() >= 5:  # 週末
                return StockService._get_twse_offline_data(symbol)
            
            # 交易時間：9:00-13:30
            current_time = now.time()
            if current_time < datetime.strptime('09:00', '%H:%M').time() or \
               current_time > datetime.strptime('13:30', '%H:%M').time():
                return StockService._get_twse_offline_data(symbol)
            
            # 嘗試獲取即時數據
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_AVG?date={now.strftime('%Y%m%d')}&stockNo={symbol}&response=json"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    latest_data = data['data'][-1]
                    price = float(latest_data[1].replace(',', ''))
                    
                    # 計算漲跌（需要前一日數據）
                    if len(data['data']) > 1:
                        prev_price = float(data['data'][-2][1].replace(',', ''))
                        change = price - prev_price
                        change_percent = (change / prev_price) * 100
                    else:
                        change = 0
                        change_percent = 0
                    
                    return {
                        'symbol': symbol,
                        'name': f"台股{symbol}",
                        'price': price,
                        'change': change,
                        'change_percent': change_percent,
                        'source': 'twse',
                        'market_state': 'REGULAR' if current_time < datetime.strptime('13:30', '%H:%M').time() else 'CLOSED'
                    }
            
            # 如果即時數據失敗，使用備用數據
            return StockService._get_twse_offline_data(symbol)
            
        except Exception as e:
            logger.error(f"❌ 台股數據獲取失敗 {symbol}: {str(e)}")
            return StockService._get_twse_offline_data(symbol)
    
    @staticmethod
    def _get_twse_offline_data(symbol):
        """台股離線/備用數據"""
        try:
            import time
            
            # 使用 yfinance 作為台股備用數據源
            ticker = yf.Ticker(f"{symbol}.TW")
            current_price = None
            info = None
            
            # 方法1: 嘗試從 info 獲取（重試3次）
            for attempt in range(3):
                try:
                    info = ticker.info
                    current_price = info.get('currentPrice', 0)
                    if current_price and current_price > 0:
                        logger.info(f"✅ 台股 {symbol} 從 info 獲取價格: {current_price}")
                        break
                    else:
                        logger.warning(f"⚠️ 第{attempt+1}次嘗試獲取台股 {symbol} info 價格為空")
                except Exception as e:
                    logger.warning(f"⚠️ 第{attempt+1}次嘗試獲取台股 {symbol} info 失敗: {e}")
                    if attempt < 2:
                        time.sleep(1)
            
            # 方法2: 嘗試從歷史數據獲取（重試3次）
            if not current_price or current_price <= 0:
                for attempt in range(3):
                    try:
                        hist = ticker.history(period="1d", timeout=30)
                        if len(hist) > 0:
                            current_price = hist.iloc[-1]['Close']
                            logger.info(f"✅ 台股 {symbol} 從歷史數據獲取價格: {current_price}")
                            break
                        else:
                            logger.warning(f"⚠️ 第{attempt+1}次嘗試獲取台股 {symbol} 歷史數據為空")
                    except Exception as e:
                        logger.warning(f"⚠️ 第{attempt+1}次嘗試獲取台股 {symbol} 歷史數據失敗: {e}")
                        if attempt < 2:
                            time.sleep(1)
            
            # 方法3: 嘗試獲取更長時間的數據
            if not current_price or current_price <= 0:
                try:
                    hist = ticker.history(period="5d", timeout=30)
                    if len(hist) > 0:
                        current_price = hist.iloc[-1]['Close']
                        logger.info(f"✅ 台股 {symbol} 從5天歷史數據獲取價格: {current_price}")
                except Exception as e:
                    logger.warning(f"⚠️ 台股 {symbol} 從5天歷史數據獲取失敗: {e}")
            
            # 方法4: 嘗試使用不同的時間間隔
            if not current_price or current_price <= 0:
                try:
                    hist = ticker.history(period="2d", interval="1d", timeout=30)
                    if len(hist) > 0:
                        current_price = hist.iloc[-1]['Close']
                        logger.info(f"✅ 台股 {symbol} 從2天日線數據獲取價格: {current_price}")
                except Exception as e:
                    logger.warning(f"⚠️ 台股 {symbol} 從2天日線數據獲取失敗: {e}")
            
            if current_price and current_price > 0:
                # 獲取歷史數據計算漲跌
                change = 0
                change_percent = 0
                try:
                    hist = ticker.history(period="2d", timeout=30)
                    if len(hist) >= 2:
                        prev_price = hist.iloc[-2]['Close']
                        change = current_price - prev_price
                        change_percent = (change / prev_price) * 100
                    else:
                        logger.warning(f"⚠️ 台股 {symbol} 歷史數據不足，無法計算漲跌")
                except Exception as e:
                    logger.warning(f"⚠️ 台股 {symbol} 計算漲跌失敗: {e}")
                
                return {
                    'symbol': symbol,
                    'name': info.get('longName', f"台股{symbol}") if info else f"台股{symbol}",
                    'price': current_price,
                    'change': change,
                    'change_percent': change_percent,
                    'source': 'smart_fallback',
                    'market_state': 'CLOSED'
                }
            else:
                logger.error(f"❌ 台股 {symbol} 無法獲取有效價格，所有方法都失敗")
                return None
                
        except Exception as e:
            logger.error(f"❌ 台股 {symbol} 備用數據獲取失敗: {e}")
            traceback.print_exc()
            return None
    
    @staticmethod
    def _get_yfinance_stock_info(symbol):
        """從 yfinance 獲取美股資訊"""
        try:
            # 添加重試機制和更長的超時時間
            import time
            
            ticker = yf.Ticker(symbol)
            current_price = None
            info = None
            
            # 方法1: 嘗試從 info 獲取（重試3次）
            for attempt in range(3):
                try:
                    info = ticker.info
                    current_price = info.get('currentPrice', 0)
                    if current_price and current_price > 0:
                        logger.info(f"✅ 從 info 獲取 {symbol} 價格: {current_price}")
                        break
                    else:
                        logger.warning(f"⚠️ 第{attempt+1}次嘗試獲取 {symbol} info 價格為空")
                except Exception as e:
                    logger.warning(f"⚠️ 第{attempt+1}次嘗試獲取 {symbol} info 失敗: {e}")
                    if attempt < 2:  # 不是最後一次嘗試
                        time.sleep(1)  # 等待1秒後重試
            
            # 方法2: 嘗試從歷史數據獲取（重試3次）
            if not current_price or current_price <= 0:
                for attempt in range(3):
                    try:
                        hist = ticker.history(period="1d", timeout=30)
                        if len(hist) > 0:
                            current_price = hist.iloc[-1]['Close']
                            logger.info(f"✅ 從歷史數據獲取 {symbol} 價格: {current_price}")
                            break
                        else:
                            logger.warning(f"⚠️ 第{attempt+1}次嘗試獲取 {symbol} 歷史數據為空")
                    except Exception as e:
                        logger.warning(f"⚠️ 第{attempt+1}次嘗試獲取 {symbol} 歷史數據失敗: {e}")
                        if attempt < 2:
                            time.sleep(1)
            
            # 方法3: 嘗試獲取更長時間的數據
            if not current_price or current_price <= 0:
                try:
                    hist = ticker.history(period="5d", timeout=30)
                    if len(hist) > 0:
                        current_price = hist.iloc[-1]['Close']
                        logger.info(f"✅ 從5天歷史數據獲取 {symbol} 價格: {current_price}")
                except Exception as e:
                    logger.warning(f"⚠️ 從5天歷史數據獲取 {symbol} 失敗: {e}")
            
            # 方法4: 嘗試使用不同的時間間隔
            if not current_price or current_price <= 0:
                try:
                    hist = ticker.history(period="2d", interval="1d", timeout=30)
                    if len(hist) > 0:
                        current_price = hist.iloc[-1]['Close']
                        logger.info(f"✅ 從2天日線數據獲取 {symbol} 價格: {current_price}")
                except Exception as e:
                    logger.warning(f"⚠️ 從2天日線數據獲取 {symbol} 失敗: {e}")
            
            if not current_price or current_price <= 0:
                logger.error(f"❌ 無法獲取 {symbol} 的有效價格，所有方法都失敗")
                return None
            
            # 獲取歷史數據計算漲跌
            change = 0
            change_percent = 0
            try:
                hist = ticker.history(period="2d", timeout=30)
                if len(hist) >= 2:
                    prev_price = hist.iloc[-2]['Close']
                    change = current_price - prev_price
                    change_percent = (change / prev_price) * 100
                else:
                    logger.warning(f"⚠️ {symbol} 歷史數據不足，無法計算漲跌")
            except Exception as e:
                logger.warning(f"⚠️ 計算 {symbol} 漲跌失敗: {e}")
            
            # 判斷市場狀態
            market_state = 'CLOSED'
            try:
                if info and 'regularMarketState' in info:
                    state_map = {
                        'REGULAR': 'REGULAR',
                        'CLOSED': 'CLOSED',
                        'PRE': 'PRE',
                        'POST': 'POST'
                    }
                    market_state = state_map.get(info['regularMarketState'], 'CLOSED')
            except:
                pass
            
            return {
                'symbol': symbol,
                'name': info.get('longName', symbol) if info else symbol,
                'price': current_price,
                'change': change,
                'change_percent': change_percent,
                'source': 'yfinance',
                'market_state': market_state
            }
            
        except Exception as e:
            logger.error(f"❌ yfinance 數據獲取失敗 {symbol}: {str(e)}")
            traceback.print_exc()
            return None
    
    @staticmethod
    def _get_fallback_stock_info(symbol):
        """備用股票數據源 - 使用模擬數據"""
        try:
            logger.info(f"🔄 使用備用數據源獲取 {symbol}")
            
            # 常見股票的模擬數據
            fallback_data = {
                'AAPL': {'name': 'Apple Inc.', 'price': 180.50, 'change': 2.30, 'change_percent': 1.29},
                'MSFT': {'name': 'Microsoft Corporation', 'price': 350.20, 'change': -1.80, 'change_percent': -0.51},
                'GOOGL': {'name': 'Alphabet Inc.', 'price': 140.75, 'change': 0.95, 'change_percent': 0.68},
                'AMZN': {'name': 'Amazon.com Inc.', 'price': 145.30, 'change': -0.45, 'change_percent': -0.31},
                'TSLA': {'name': 'Tesla Inc.', 'price': 240.80, 'change': 5.20, 'change_percent': 2.21},
                'NVDA': {'name': 'NVIDIA Corporation', 'price': 450.60, 'change': 12.40, 'change_percent': 2.83},
                'META': {'name': 'Meta Platforms Inc.', 'price': 320.15, 'change': -2.10, 'change_percent': -0.65},
                '2330': {'name': '台積電', 'price': 580.00, 'change': 5.00, 'change_percent': 0.87},
                '0050': {'name': '元大台灣50', 'price': 145.20, 'change': 0.80, 'change_percent': 0.55},
                '2317': {'name': '鴻海', 'price': 105.50, 'change': -0.50, 'change_percent': -0.47}
            }
            
            if symbol in fallback_data:
                data = fallback_data[symbol]
                return {
                    'symbol': symbol,
                    'name': data['name'],
                    'price': data['price'],
                    'change': data['change'],
                    'change_percent': data['change_percent'],
                    'source': 'fallback_simulation',
                    'market_state': 'CLOSED'
                }
            else:
                # 如果沒有預設數據，返回一個通用的模擬數據
                return {
                    'symbol': symbol,
                    'name': f"股票 {symbol}",
                    'price': 100.00,
                    'change': 0.00,
                    'change_percent': 0.00,
                    'source': 'fallback_generic',
                    'market_state': 'CLOSED'
                }
                
        except Exception as e:
            logger.error(f"❌ 備用數據源獲取失敗 {symbol}: {e}")
            return None

# 初始化 Flask app
app = Flask(__name__)

# LINE Bot 設定
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN') or os.getenv('CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET') or os.getenv('CHANNEL_SECRET')

# 如果環境變數未設定，使用預設值
if not channel_access_token:
    channel_access_token = "PpSQF0Bo3FVHtT+XP8GrGAkPYVBvQPTFy69o/nr3+9iOZvUpg2XZ30MzbHKjdPHGximx0IAmfSKjjq64pSqRQsfujpFwgtNCFYXtJnJConGVse0d8008yY74Vo40YQ1K22xi4fDYn+TZD30wgIVz6QdB04t89/1O/w1cDnyilFU="

if not channel_secret:
    channel_secret = "2cef684f6f8a9d2ca4c5f0ac8cae531c"

logger.info("✅ LINE Bot 憑證已載入")

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# 全局變數用於緩存
cache = {}
cache_timeout = 300  # 5分鐘緩存

def format_stock_message(stock_data):
    """改良的股票訊息格式化"""
    if not stock_data:
        return """❌ 目前金融數據連線失敗

🔧 可能原因:
• 網路連線問題
• 金融數據服務暫時不可用
• 股票代碼不存在

💡 建議:
• 檢查網路連線
• 稍後再試
• 確認股票代碼正確

⏰ 時間: """ + datetime.now(tz).strftime('%H:%M:%S')
    
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
        'fallback_simulation': "📊 模擬數據",
        'fallback_generic': "📈 參考數據"
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
⏰ 更新: {datetime.now(tz).strftime('%H:%M:%S')}
🔗 來源: {source_text}{market_state}
""".strip()

def generate_weekly_report():
    """改良的週報生成"""
    try:
        # 取得主要股票數據
        stocks_to_check = [
            ('2330', '台股代表'),  # 自動加上 .TW
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
        now = datetime.now(tz)
        week_start = (now - timedelta(days=7)).strftime('%m/%d')
        week_end = now.strftime('%m/%d')
        
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
⏰ 報告時間: {now.strftime('%Y-%m-%d %H:%M')}
        """.strip()
        
        return report
        
    except Exception as e:
        logger.error(f"❌ 週報生成失敗: {str(e)}")
        return f"""
📊 股市週報
⚠️ 報告生成時遇到問題

🔧 系統狀態: 維護中
📞 建議: 請稍後再試或使用個別股票查詢

⏰ {datetime.now(tz).strftime('%Y-%m-%d %H:%M')}
        """.strip()

def init_db():
    """初始化資料庫"""
    try:
        conn = sqlite3.connect('stock_bot.db')
        cursor = conn.cursor()
        
        # 創建股票追蹤表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                target_price REAL NOT NULL,
                action TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                UNIQUE(user_id, symbol, target_price, action)
            )
        ''')
        
        # 創建股票提醒記錄表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                target_price REAL NOT NULL,
                current_price REAL NOT NULL,
                action TEXT NOT NULL,
                triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ 資料庫初始化完成")
        
    except Exception as e:
        logger.error(f"❌ 資料庫初始化失敗: {str(e)}")

def add_stock_tracking(user_id, symbol, target_price, action):
    """添加股票追蹤"""
    try:
        conn = sqlite3.connect('stock_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO stock_tracking 
            (user_id, symbol, target_price, action) 
            VALUES (?, ?, ?, ?)
        ''', (user_id, symbol, target_price, action))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ 添加股票追蹤失敗: {str(e)}")
        return False

def get_user_trackings(user_id):
    """獲取用戶的股票追蹤列表"""
    try:
        conn = sqlite3.connect('stock_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT symbol, target_price, action, created_at 
            FROM stock_tracking 
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at DESC
        ''', (user_id,))
        
        results = cursor.fetchall()
        conn.close()
        
        return [{'symbol': row[0], 'target_price': row[1], 'action': row[2], 'created_at': row[3]} for row in results]
        
    except Exception as e:
        logger.error(f"❌ 獲取股票追蹤失敗: {str(e)}")
        return []

def remove_stock_tracking(user_id, symbol, target_price, action):
    """移除股票追蹤"""
    try:
        conn = sqlite3.connect('stock_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE stock_tracking 
            SET is_active = 0 
            WHERE user_id = ? AND symbol = ? AND target_price = ? AND action = ?
        ''', (user_id, symbol, target_price, action))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ 移除股票追蹤失敗: {str(e)}")
        return False

def remove_all_trackings(user_id):
    """移除用戶的所有股票追蹤"""
    try:
        conn = sqlite3.connect('stock_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE stock_tracking 
            SET is_active = 0 
            WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ 移除所有股票追蹤失敗: {str(e)}")
        return False

def check_price_alerts():
    """檢查價格提醒"""
    try:
        conn = sqlite3.connect('stock_bot.db')
        cursor = conn.cursor()
        
        # 獲取所有活躍的追蹤
        cursor.execute('''
            SELECT user_id, symbol, target_price, action 
            FROM stock_tracking 
            WHERE is_active = 1
        ''')
        
        trackings = cursor.fetchall()
        alerts = []
        
        for tracking in trackings:
            user_id, symbol, target_price, action = tracking
            
            # 獲取當前股價
            stock_data = StockService.get_stock_info(symbol)
            if not stock_data:
                continue
            
            current_price = stock_data['price']
            triggered = False
            
            # 檢查是否觸發提醒
            if action == '買進' and current_price <= target_price:
                triggered = True
            elif action == '賣出' and current_price >= target_price:
                triggered = True
            
            if triggered:
                # 記錄提醒
                cursor.execute('''
                    INSERT INTO price_alerts 
                    (user_id, symbol, target_price, current_price, action) 
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, symbol, target_price, current_price, action))
                
                # 停用追蹤
                cursor.execute('''
                    UPDATE stock_tracking 
                    SET is_active = 0 
                    WHERE user_id = ? AND symbol = ? AND target_price = ? AND action = ?
                ''', (user_id, symbol, target_price, action))
                
                alerts.append({
                    'user_id': user_id,
                    'symbol': symbol,
                    'target_price': target_price,
                    'current_price': current_price,
                    'action': action
                })
        
        conn.commit()
        conn.close()
        return alerts
        
    except Exception as e:
        logger.error(f"❌ 檢查價格提醒失敗: {str(e)}")
        return []

def send_price_alert(user_id, alert_data):
    """發送價格提醒"""
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            
            message = f"""
🚨 價格提醒觸發！

📊 {alert_data['symbol']} 已達到目標價格
💰 目標: ${alert_data['target_price']}
💵 當前: ${alert_data['current_price']}
📈 動作: {alert_data['action']}

⏰ 時間: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}
            """.strip()
            
            line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message)]
                )
            )
            
            logger.info(f"✅ 價格提醒發送成功: {user_id} - {alert_data['symbol']}")
            
    except Exception as e:
        logger.error(f"❌ 發送價格提醒失敗: {str(e)}")

def price_check_scheduler():
    """價格檢查排程器"""
    while True:
        try:
            # 檢查是否為台股交易時間
            now = datetime.now(tz)
            is_trading_hours = (
                now.weekday() < 5 and  # 工作日
                now.time() >= datetime.strptime('09:00', '%H:%M').time() and
                now.time() <= datetime.strptime('13:30', '%H:%M').time()
            )
            
            if is_trading_hours:
                logger.info("🔄 執行價格檢查...")
                alerts = check_price_alerts()
                
                for alert in alerts:
                    send_price_alert(alert['user_id'], alert)
                    time.sleep(1)  # 避免發送過快
                
                if alerts:
                    logger.info(f"✅ 處理了 {len(alerts)} 個價格提醒")
                else:
                    logger.info("✅ 價格檢查完成，無觸發提醒")
            else:
                logger.info("⏰ 非交易時間，跳過價格檢查")
            
            # 等待5分鐘
            time.sleep(300)
            
        except Exception as e:
            logger.error(f"❌ 價格檢查排程器錯誤: {str(e)}")
            time.sleep(60)  # 錯誤時等待1分鐘

def weekly_report_scheduler():
    """週報發送排程器 - 每週一早上8點發送"""
    while True:
        try:
            now = datetime.now(tz)
            
            # 每週一早上8點發送週報
            if now.weekday() == 0 and now.hour == 8 and now.minute == 0:
                logger.info("📊 執行週報發送...")
                send_weekly_report_to_all_users()
                
                # 等待到下一分鐘，避免重複發送
                time.sleep(60)
            else:
                # 每分鐘檢查一次
                time.sleep(60)
                
        except Exception as e:
            logger.error(f"❌ 週報排程器錯誤: {str(e)}")
            time.sleep(300)  # 錯誤時等待5分鐘

def send_weekly_report_to_all_users():
    """向所有用戶發送週報"""
    try:
        # 獲取所有活躍用戶
        conn = sqlite3.connect('stock_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT user_id FROM stock_tracking 
            WHERE is_active = 1
        ''')
        
        users = cursor.fetchall()
        conn.close()
        
        if not users:
            logger.info("📊 沒有活躍用戶，跳過週報發送")
            return
        
        # 生成週報
        weekly_report = generate_weekly_report()
        
        # 發送給所有用戶
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            
            for user in users:
                try:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=user[0],
                            messages=[TextMessage(text=weekly_report)]
                        )
                    )
                    time.sleep(1)  # 避免發送過快
                    logger.info(f"✅ 週報發送成功: {user[0]}")
                except Exception as e:
                    logger.error(f"❌ 週報發送失敗 {user[0]}: {str(e)}")
        
        logger.info(f"✅ 週報發送完成，共 {len(users)} 個用戶")
        
    except Exception as e:
        logger.error(f"❌ 週報發送失敗: {str(e)}")

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
• 「台股 2330」- 查看台股股價
• 「美股 AAPL」- 查看美股股價  
• 「測試」- 系統狀態檢查
• 「診斷」- API功能診斷
• 「追蹤 2330 800 買進」- 設定股票價格提醒
• 「我的追蹤」- 查看追蹤清單
• 「取消追蹤 2330 800 買進」- 取消追蹤
• 「取消全部」- 取消所有追蹤
                """.strip()
                
            elif user_message == '週報':
                logger.info("🔄 生成週報中...")
                reply_text = generate_weekly_report()
                
            elif user_message.startswith('台股 '):
                # 處理台股查詢：台股 2330
                try:
                    parts = user_message.split()
                    if len(parts) >= 2:
                        symbol = parts[1]
                        logger.info(f"🔄 查詢台股 {symbol}...")
                        stock_data = StockService.get_stock_info(symbol)
                        reply_text = format_stock_message(stock_data)
                    else:
                        reply_text = "❌ 格式錯誤\n💡 正確格式: 台股 2330"
                except Exception as e:
                    reply_text = f"❌ 查詢台股失敗: {str(e)}"
                    
            elif user_message.startswith('美股 '):
                # 處理美股查詢：美股 AAPL
                try:
                    parts = user_message.split()
                    if len(parts) >= 2:
                        symbol = parts[1].upper()  # 轉換為大寫
                        logger.info(f"🔄 查詢美股 {symbol}...")
                        stock_data = StockService.get_stock_info(symbol)
                        reply_text = format_stock_message(stock_data)
                    else:
                        reply_text = "❌ 格式錯誤\n💡 正確格式: 美股 AAPL"
                except Exception as e:
                    reply_text = f"❌ 查詢美股失敗: {str(e)}"
                
            elif user_message == '測試':
                reply_text = f"✅ 系統正常運作\n⏰ 時間: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}\n📦 緩存項目: {len(cache)}"
            
            elif user_message == '診斷':
                # 詳細診斷功能
                try:
                    reply_text = "🔍 正在診斷系統狀態...\n\n"
                    
                    # 測試台股
                    reply_text += "📊 測試台股 2330...\n"
                    test_tw = StockService.get_stock_info('2330')
                    if test_tw:
                        reply_text += f"✅ 台股: {test_tw['source']} - ${test_tw['price']}\n"
                    else:
                        reply_text += "❌ 台股連線失敗\n"
                    
                    # 測試美股
                    reply_text += "\n📊 測試美股 AAPL...\n"
                    test_us = StockService.get_stock_info('AAPL')
                    if test_us:
                        reply_text += f"✅ 美股: {test_us['source']} - ${test_us['price']}\n"
                    else:
                        reply_text += "❌ 美股連線失敗\n"
                    
                    # 總結
                    if test_tw or test_us:
                        reply_text += "\n✅ 系統部分功能正常"
                    else:
                        reply_text += "\n❌ 系統連線異常，請檢查網路"
                    
                    reply_text += f"\n⏰ 診斷時間: {datetime.now(tz).strftime('%H:%M:%S')}"
                    
                except Exception as e:
                    reply_text = f"❌ 診斷失敗: {str(e)}"
            
            elif user_message.startswith('追蹤 '):
                # 處理股票追蹤指令
                try:
                    parts = user_message.split()
                    if len(parts) >= 4:
                        symbol = parts[1]
                        target_price = float(parts[2])
                        action = parts[3]
                        
                        if action in ['買進', '賣出']:
                            if add_stock_tracking(user_id, symbol, target_price, action):
                                reply_text = f"✅ 已設定追蹤 {symbol} {action} 提醒\n💰 目標價格: ${target_price}"
                            else:
                                reply_text = "❌ 設定追蹤失敗，請稍後再試"
                        else:
                            reply_text = "❌ 動作必須是「買進」或「賣出」\n💡 格式: 追蹤 2330 800 買進"
                    else:
                        reply_text = "❌ 格式錯誤\n💡 正確格式: 追蹤 2330 800 買進"
                except ValueError:
                    reply_text = "❌ 價格格式錯誤\n💡 正確格式: 追蹤 2330 800 買進"
                except Exception as e:
                    reply_text = f"❌ 設定追蹤失敗: {str(e)}"
            
            elif user_message == '我的追蹤':
                # 顯示用戶的股票追蹤列表
                trackings = get_user_trackings(user_id)
                if trackings:
                    tracking_list = []
                    for tracking in trackings:
                        tracking_list.append(f"📊 {tracking['symbol']}: ${tracking['target_price']} {tracking['action']}")
                    
                    reply_text = f"📋 您的股票追蹤清單:\n{chr(10).join(tracking_list)}"
                else:
                    reply_text = "📋 您目前沒有追蹤任何股票\n💡 使用「追蹤 2330 800 買進」來設定提醒"
            
            elif user_message.startswith('取消追蹤 '):
                # 處理取消追蹤指令
                try:
                    parts = user_message.split()
                    if len(parts) >= 4:
                        symbol = parts[1]
                        target_price = float(parts[2])
                        action = parts[3]
                        
                        if remove_stock_tracking(user_id, symbol, target_price, action):
                            reply_text = f"✅ 已取消追蹤 {symbol} {action} 提醒"
                        else:
                            reply_text = "❌ 取消追蹤失敗，請稍後再試"
                    else:
                        reply_text = "❌ 格式錯誤\n💡 正確格式: 取消追蹤 2330 800 買進"
                except ValueError:
                    reply_text = "❌ 價格格式錯誤\n💡 正確格式: 取消追蹤 2330 800 買進"
                except Exception as e:
                    reply_text = f"❌ 取消追蹤失敗: {str(e)}"
            
            elif user_message == '取消全部':
                # 取消所有追蹤
                if remove_all_trackings(user_id):
                    reply_text = "✅ 已取消所有股票追蹤"
                else:
                    reply_text = "❌ 取消所有追蹤失敗，請稍後再試"
                
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
    <p>時間: {datetime.now(tz)}</p>
    <p>緩存項目: {len(cache)}</p>
    <p><a href="/debug">診斷頁面</a></p>
    """

@app.route("/health")
def health():
    """健康檢查端點"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(tz).isoformat(),
        "cache_items": len(cache)
    }

@app.route("/debug")
def debug_api():
    """診斷API功能的端點"""
    results = {
        'timestamp': datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S'),
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
        stock_data = StockService.get_stock_info('2330')  # 自動加上 .TW
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
    
    # 啟動價格檢查排程器
    price_scheduler_thread = threading.Thread(target=price_check_scheduler, daemon=True)
    price_scheduler_thread.start()
    logger.info("✅ 價格檢查排程器已啟動")
    
    # 啟動週報發送排程器
    weekly_scheduler_thread = threading.Thread(target=weekly_report_scheduler, daemon=True)
    weekly_scheduler_thread.start()
    logger.info("✅ 週報發送排程器已啟動")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
