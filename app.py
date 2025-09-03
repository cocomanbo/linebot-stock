import os
import sqlite3
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, PushMessageRequest
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import yfinance as yf
import requests
from datetime import datetime, timedelta, time as dt_time
import logging
import traceback
import threading
import time
import re

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StockService:
    """股票服務類別，整合台股和美股的數據獲取"""
    
    @staticmethod
    def get_stock_info(symbol):
        """獲取股票資訊，自動判斷台股或美股"""
        try:
            # 判斷是否為台股（純數字）
            if re.match(r'^\d+$', symbol):
                return StockService._get_twse_stock_info(symbol)
            else:
                return StockService._get_yfinance_stock_info(symbol)
        except Exception as e:
            logger.error(f"獲取股票資訊失敗 {symbol}: {str(e)}")
            return None
    
    @staticmethod
    def _get_twse_stock_info(symbol):
        """從台灣證交所獲取台股資訊"""
        try:
            # 台股交易時間檢查
            now = datetime.now()
            if now.weekday() >= 5:  # 週末
                return StockService._get_twse_offline_data(symbol)
            
            # 交易時間：9:00-13:30
            current_time = now.time()
            if current_time < datetime.strptime('09:00', '%H:%M').time() or \
               current_time > datetime.strptime('13:30', '%H:%M').time():
                return StockService._get_twse_offline_data(symbol)
            
            # 嘗試獲取即時數據
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_AVG?date={now.strftime('%Y%m%d')}&stockNo={symbol}&response=json"
            response = requests.get(url, timeout=10)
            
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
                        'symbol': f"{symbol}.TW",
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
            logger.error(f"台股數據獲取失敗 {symbol}: {str(e)}")
            return StockService._get_twse_offline_data(symbol)
    
    @staticmethod
    def _get_twse_offline_data(symbol):
        """台股離線/備用數據"""
        try:
            # 使用 yfinance 作為台股備用數據源
            ticker = yf.Ticker(f"{symbol}.TW")
            info = ticker.info
            current_price = info.get('currentPrice', 0)
            
            if current_price:
                # 獲取歷史數據計算漲跌
                hist = ticker.history(period="2d")
                if len(hist) >= 2:
                    prev_price = hist.iloc[-2]['Close']
                    change = current_price - prev_price
                    change_percent = (change / prev_price) * 100
                else:
                    change = 0
                    change_percent = 0
                
                return {
                    'symbol': f"{symbol}.TW",
                    'name': info.get('longName', f"台股{symbol}"),
                    'price': current_price,
                    'change': change,
                    'change_percent': change_percent,
                    'source': 'smart_fallback',
                    'market_state': 'CLOSED'
                }
        except:
            pass
        
        # 最終備用：模擬數據
        return {
            'symbol': f"{symbol}.TW",
            'name': f"台股{symbol}",
            'price': 100.0,
            'change': 0.0,
            'change_percent': 0.0,
            'source': 'fallback',
            'market_state': 'CLOSED'
        }
    
    @staticmethod
    def _get_yfinance_stock_info(symbol):
        """從 yfinance 獲取美股資訊"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            current_price = info.get('currentPrice', 0)
            if not current_price:
                # 嘗試獲取最新收盤價
                hist = ticker.history(period="1d")
                if len(hist) > 0:
                    current_price = hist.iloc[-1]['Close']
                else:
                    return None
            
            # 獲取歷史數據計算漲跌
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                prev_price = hist.iloc[-2]['Close']
                change = current_price - prev_price
                change_percent = (change / prev_price) * 100
            else:
                change = 0
                change_percent = 0
            
            # 判斷市場狀態
            market_state = 'CLOSED'
            if 'regularMarketState' in info:
                state_map = {
                    'REGULAR': 'REGULAR',
                    'CLOSED': 'CLOSED',
                    'PRE': 'PRE',
                    'POST': 'POST'
                }
                market_state = state_map.get(info['regularMarketState'], 'CLOSED')
            
            return {
                'symbol': symbol,
                'name': info.get('longName', symbol),
                'price': current_price,
                'change': change,
                'change_percent': change_percent,
                'source': 'yfinance',
                'market_state': market_state
            }
            
        except Exception as e:
            logger.error(f"yfinance 數據獲取失敗 {symbol}: {str(e)}")
            return None


class TradingTimeChecker:
    """交易時間檢查器"""
    
    @staticmethod
    def is_taiwan_trading_time():
        """檢查是否為台股交易時間"""
        now = datetime.now()
        
        # 週末不交易
        if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return False
        
        # 交易時間：09:00-13:30
        current_time = now.time()
        market_open = dt_time(9, 0)
        market_close = dt_time(13, 30)
        
        return market_open <= current_time <= market_close
    
    @staticmethod
    def is_us_trading_time():
        """檢查是否為美股交易時間（簡化版）"""
        now = datetime.now()
        
        # 週末不交易
        if now.weekday() >= 5:
            return False
        
        # 美股時間複雜，這裡簡化處理
        # 實際應該考慮美國時區和夏令時間
        current_time = now.time()
        # 台灣時間 21:30-04:00 (次日)
        return current_time >= dt_time(21, 30) or current_time <= dt_time(4, 0)


class StockAlertManager:
    """股票價格提醒管理器"""
    
    def __init__(self, db_path='stock_bot.db'):
        self.db_path = db_path
        self.cooldown_hours = 1  # 冷卻時間
        self.init_alert_tables()
    
    def init_alert_tables(self):
        """初始化提醒相關資料表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 提醒設定表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    target_price INTEGER NOT NULL,
                    alert_type TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    triggered_at TIMESTAMP NULL
                )
            ''')
            
            # 提醒記錄表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    target_price INTEGER NOT NULL,
                    current_price REAL NOT NULL,
                    alert_type TEXT NOT NULL,
                    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("提醒系統資料表初始化完成")
            
        except Exception as e:
            logger.error(f"提醒系統初始化失敗: {str(e)}")
    
    def add_price_alert(self, user_id: str, symbol: str, target_price: int, alert_type: str) -> dict:
        """新增價格提醒"""
        try:
            # 標準化股票代號
            symbol = self._normalize_symbol(symbol)
            
            # 驗證股票存在
            stock_data = StockService.get_stock_info(symbol)
            if not stock_data:
                return {'success': False, 'message': f'找不到股票: {symbol}'}
            
            # 檢查是否有相同設定的冷卻期
            if self._is_in_cooldown(user_id, symbol, target_price, alert_type):
                return {'success': False, 'message': f'{symbol} 相同條件在冷卻期內，請稍後再設定'}
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 新增提醒設定
            cursor.execute('''
                INSERT INTO price_alerts (user_id, symbol, target_price, alert_type)
                VALUES (?, ?, ?, ?)
            ''', (user_id, symbol, target_price, alert_type))
            
            conn.commit()
            conn.close()
            
            action_text = "買進" if alert_type == "buy" else "賣出"
            
            logger.info(f"用戶 {user_id} 設定價格提醒: {symbol} {target_price} {action_text}")
            
            return {
                'success': True,
                'message': f'已設定提醒: {stock_data["name"]} ({symbol})\n價格: ${target_price}\n動作: {action_text}\n僅在交易時間內觸發'
            }
            
        except Exception as e:
            logger.error(f"新增價格提醒失敗: {str(e)}")
            return {'success': False, 'message': '設定提醒失敗，請稍後再試'}
    
    def get_user_alerts(self, user_id: str) -> list:
        """取得用戶的價格提醒清單"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT symbol, target_price, alert_type, created_at, is_active
                FROM price_alerts 
                WHERE user_id = ? AND is_active = 1
                ORDER BY created_at DESC
            ''', (user_id,))
            
            alerts = []
            for row in cursor.fetchall():
                symbol, target_price, alert_type, created_at, is_active = row
                
                # 獲取股票資訊
                stock_data = StockService.get_stock_info(symbol)
                stock_name = stock_data['name'] if stock_data else symbol
                
                alerts.append({
                    'symbol': symbol,
                    'name': stock_name,
                    'target_price': target_price,
                    'alert_type': alert_type,
                    'created_at': created_at,
                    'is_active': is_active
                })
            
            conn.close()
            return alerts
            
        except Exception as e:
            logger.error(f"取得提醒清單失敗: {str(e)}")
            return []
    
    def remove_all_alerts(self, user_id: str) -> dict:
        """移除用戶所有提醒"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 計算移除數量
            cursor.execute('SELECT COUNT(*) FROM price_alerts WHERE user_id = ? AND is_active = 1', (user_id,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                conn.close()
                return {'success': False, 'message': '沒有設定任何提醒'}
            
            # 將所有提醒設為非活躍
            cursor.execute('''
                UPDATE price_alerts 
                SET is_active = 0, triggered_at = CURRENT_TIMESTAMP 
                WHERE user_id = ? AND is_active = 1
            ''', (user_id,))
            
            conn.commit()
            conn.close()
            
            logger.info(f"用戶 {user_id} 取消了 {count} 個提醒")
            
            return {
                'success': True,
                'message': f'已取消 {count} 個價格提醒'
            }
            
        except Exception as e:
            logger.error(f"取消所有提醒失敗: {str(e)}")
            return {'success': False, 'message': '取消提醒失敗，請稍後再試'}
    
    def check_price_alerts(self):
        """檢查所有價格提醒（背景執行）"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 取得所有活躍的提醒
            cursor.execute('''
                SELECT id, user_id, symbol, target_price, alert_type
                FROM price_alerts 
                WHERE is_active = 1
            ''')
            
            alerts = cursor.fetchall()
            triggered_alerts = []
            
            for alert_id, user_id, symbol, target_price, alert_type in alerts:
                # 檢查交易時間
                if symbol.endswith('.TW'):
                    if not TradingTimeChecker.is_taiwan_trading_time():
                        continue
                else:
                    if not TradingTimeChecker.is_us_trading_time():
                        continue
                
                # 獲取即時股價（不使用快取）
                stock_data = self._get_fresh_stock_data(symbol)
                if not stock_data:
                    continue
                
                current_price = stock_data['price']
                triggered = False
                
                # 判斷是否觸發
                if alert_type == 'buy' and current_price <= target_price:
                    triggered = True
                elif alert_type == 'sell' and current_price >= target_price:
                    triggered = True
                
                if triggered:
                    # 記錄觸發
                    self._trigger_alert(alert_id, user_id, symbol, target_price, current_price, alert_type)
                    triggered_alerts.append({
                        'user_id': user_id,
                        'symbol': symbol,
                        'target_price': target_price,
                        'current_price': current_price,
                        'alert_type': alert_type,
                        'stock_data': stock_data
                    })
            
            conn.close()
            
            # 發送提醒通知
            for alert in triggered_alerts:
                self._send_alert_notification(alert)
                
            if triggered_alerts:
                logger.info(f"觸發了 {len(triggered_alerts)} 個價格提醒")
                
        except Exception as e:
            logger.error(f"檢查價格提醒時發生錯誤: {str(e)}")
    
    def _normalize_symbol(self, symbol: str) -> str:
        """標準化股票代號"""
        symbol = symbol.upper().strip()
        
        # 台股處理
        if symbol.isdigit() and len(symbol) == 4:
            symbol = f"{symbol}.TW"
        
        return symbol
    
    def _is_in_cooldown(self, user_id: str, symbol: str, target_price: int, alert_type: str) -> bool:
        """檢查是否在冷卻期內"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cooldown_time = datetime.now() - timedelta(hours=self.cooldown_hours)
            
            cursor.execute('''
                SELECT COUNT(*) FROM alert_history
                WHERE user_id = ? AND symbol = ? AND target_price = ? AND alert_type = ?
                AND triggered_at > ?
            ''', (user_id, symbol, target_price, alert_type, cooldown_time))
            
            count = cursor.fetchone()[0]
            conn.close()
            
            return count > 0
            
        except Exception as e:
            logger.error(f"檢查冷卻期失敗: {str(e)}")
            return False
    
    def _get_fresh_stock_data(self, symbol: str):
        """獲取新鮮的股票數據（不使用快取）"""
        try:
            # 直接調用 StockService，不使用 cache
            return StockService.get_stock_info(symbol)
        except Exception as e:
            logger.error(f"獲取新鮮股票數據失敗 {symbol}: {str(e)}")
            return None
    
    def _trigger_alert(self, alert_id: int, user_id: str, symbol: str, target_price: int, current_price: float, alert_type: str):
        """觸發提醒"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 將提醒設為非活躍（單次提醒）
            cursor.execute('''
                UPDATE price_alerts 
                SET is_active = 0, triggered_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (alert_id,))
            
            # 記錄到提醒歷史
            cursor.execute('''
                INSERT INTO alert_history (user_id, symbol, target_price, current_price, alert_type)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, symbol, target_price, current_price, alert_type))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"觸發提醒記錄失敗: {str(e)}")
    
    def _send_alert_notification(self, alert: dict):
        """發送提醒通知給用戶"""
        try:
            if not channel_access_token or not configuration:
                logger.error("LINE Bot 未初始化，無法發送提醒")
                return
            
            user_id = alert['user_id']
            stock_data = alert['stock_data']
            target_price = alert['target_price']
            current_price = alert['current_price']
            alert_type = alert['alert_type']
            
            action_text = "買進時機" if alert_type == "buy" else "賣出時機"
            
            message = f"""
價格提醒觸發！

{stock_data['name']} ({stock_data['symbol']})
目標價格: ${target_price}
當前價格: ${current_price}
建議動作: {action_text}

觸發時間: {datetime.now().strftime('%H:%M:%S')}
此提醒已自動停用
            """.strip()
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.push_message_with_http_info(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(text=message)]
                    )
                )
            
            logger.info(f"價格提醒通知已發送給用戶 {user_id}")
            
        except Exception as e:
            logger.error(f"發送提醒通知失敗: {str(e)}")


class CommandParser:
    """指令解析器"""
    
    @staticmethod
    def parse_command(message: str) -> dict:
        """解析用戶指令"""
        message = message.strip()
        
        # 追蹤指令：追蹤 股票代號 價格 買進/賣出
        track_pattern = r'^追蹤\s+(\w+)\s+(\d+)\s+(買進|賣出)$'
        match = re.match(track_pattern, message)
        if match:
            symbol, price, action = match.groups()
            action_type = "buy" if action == "買進" else "sell"
            return {
                'action': 'add_price_alert',
                'symbol': symbol,
                'target_price': int(price),
                'alert_type': action_type
            }
        
        # 其他指令
        command_map = {
            '我的提醒': {'action': 'list_alerts'},
            '提醒清單': {'action': 'list_alerts'},
            '取消全部': {'action': 'cancel_all_alerts'},
            '取消所有提醒': {'action': 'cancel_all_alerts'}
        }
        
        if message in command_map:
            return command_map[message]
        
        return {'action': 'unknown'}


def format_alert_list_message(alerts: list) -> str:
    """格式化提醒清單訊息"""
    if not alerts:
        return """
我的價格提醒

目前沒有設定任何提醒
輸入指令格式：追蹤 股票代號 價格 買進/賣出

範例：
• 追蹤 2330 800 買進
• 追蹤 AAPL 200 賣出

注意：僅支援整數價格，僅在交易時間觸發
        """.strip()
    
    alert_lines = []
    for alert in alerts:
        action_text = "買進" if alert['alert_type'] == 'buy' else "賣出"
        
        line = f"{alert['name']} ({alert['symbol']})"
        line += f"\n   ${alert['target_price']} {action_text}"
        alert_lines.append(line)
    
    return f"""
我的價格提醒 (共 {len(alerts)} 個)
{'='*25}

{chr(10).join(alert_lines)}

說明：
• 觸發後自動停用（單次提醒）
• 僅在交易時間內生效
• 相同設定有 1 小時冷卻期

更新: {datetime.now().strftime('%H:%M:%S')}
    """.strip()


# 背景監控執行緒
class BackgroundMonitor:
    """背景監控執行緒"""
    
    def __init__(self):
        self.alert_manager = StockAlertManager()
        self.running = False
        self.thread = None
    
    def start_monitoring(self):
        """開始背景監控"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("背景價格監控已啟動")
    
    def stop_monitoring(self):
        """停止背景監控"""
        self.running = False
        if self.thread:
            self.thread.join()
        logger.info("背景價格監控已停止")
    
    def _monitor_loop(self):
        """監控循環"""
        while self.running:
            try:
                # 每分鐘檢查一次價格提醒
                self.alert_manager.check_price_alerts()
                time.sleep(60)  # 等待1分鐘
                
            except Exception as e:
                logger.error(f"背景監控循環錯誤: {str(e)}")
                time.sleep(60)  # 發生錯誤也等待1分鐘


# 初始化 Flask app
app = Flask(__name__)

# LINE Bot 設定
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN') or os.getenv('CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET') or os.getenv('CHANNEL_SECRET')

if not channel_access_token or not channel_secret:
    logger.error("LINE Bot 環境變數未設定")
    raise ValueError("CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET must be set")

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# 全局變數用於緩存
cache = {}
cache_timeout = 300  # 5分鐘緩存

# 全局背景監控器
background_monitor = BackgroundMonitor()

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
        logger.info("資料庫初始化完成")
        
    except Exception as e:
        logger.error(f"資料庫初始化失敗: {str(e)}")

def format_stock_message(stock_data):
    """改良的股票訊息格式化"""
    if not stock_data:
        return "數據連線中斷，請稍後再試"
    
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
            ('2330', '台股代表'),
            ('AAPL', '美股科技'),
            ('TSLA', '電動車'),
            ('NVDA', 'AI晶片')
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
        logger.error(f"週報生成失敗: {str(e)}")
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
    
    logger.info(f"用戶 {user_id} 發送: {user_message}")
    
    try:
        # 初始化管理器
        alert_manager = StockAlertManager()
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            
            # 解析指令
            command = CommandParser.parse_command(user_message)
            
            if command['action'] == 'add_price_alert':
                # 新增價格提醒
                result = alert_manager.add_price_alert(
                    user_id, 
                    command['symbol'], 
                    command['target_price'], 
                    command['alert_type']
                )
                reply_text = result['message']
                
            elif command['action'] == 'list_alerts':
                # 顯示提醒清單
                alerts = alert_manager.get_user_alerts(user_id)
                reply_text = format_alert_list_message(alerts)
                
            elif command['action'] == 'cancel_all_alerts':
                # 取消所有提醒
                result = alert_manager.remove_all_alerts(user_id)
                reply_text = result['message']
                
            # 原有指令
            elif user_message in ['你好', 'hello', 'hi']:
                reply_text = "你好！我是股票監控機器人\n輸入「功能」查看可用指令"
                
            elif user_message == '功能':
                alert_count = len(alert_manager.get_user_alerts(user_id))
                reply_text = f"""
可用功能：

📊 股價查詢：
• 「週報」- 本週股市報告
• 「台股」- 台積電股價
• 「美股」- Apple股價

🚨 價格提醒：
• 「追蹤 [代號] [價格] [買進/賣出]」
• 「我的提醒」- 查看提醒清單
• 「取消全部」- 取消所有提醒

🔧 系統功能：
• 「測試」- 系統狀態
• 「診斷」- API診斷

目前提醒: {alert_count} 個

範例：追蹤 2330 800 買進
                """.strip()
                
            elif user_message == '週報':
                logger.info("生成週報中...")
                reply_text = generate_weekly_report()
                
            elif user_message == '台股':
                logger.info("查詢台積電...")
                stock_data = StockService.get_stock_info('2330')
                reply_text = format_stock_message(stock_data) if stock_data else "台積電數據連線中斷，請稍後再試"
                
            elif user_message == '美股':
                logger.info("查詢Apple...")
                stock_data = StockService.get_stock_info('AAPL')
                reply_text = format_stock_message(stock_data) if stock_data else "Apple數據連線中斷，請稍後再試"
                
            elif user_message == '測試':
                alert_count = len(alert_manager.get_user_alerts(user_id))
                is_taiwan_trading = TradingTimeChecker.is_taiwan_trading_time()
                is_us_trading = TradingTimeChecker.is_us_trading_time()
                
                reply_text = f"""
系統狀態：
⏰ 時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📦 緩存: {len(cache)} 項
🚨 提醒: {alert_count} 個

交易時間：
🇹🇼 台股: {'🟢 開盤' if is_taiwan_trading else '🔴 休市'}
🇺🇸 美股: {'🟢 開盤' if is_us_trading else '🔴 休市'}

🔄 背景監控: {'運行中' if background_monitor.running else '未啟動'}
                """.strip()
            
            elif user_message == '診斷':
                # API診斷
                try:
                    test_stock = StockService.get_stock_info('2330')
                    if test_stock and test_stock['source'] in ['yfinance', 'twse']:
                        reply_text = "API功能正常\n數據連線成功"
                    elif test_stock:
                        reply_text = f"API部分正常\n使用{test_stock['source']}數據"
                    else:
                        reply_text = "API功能異常\n數據連線中斷"
                except Exception as e:
                    reply_text = f"診斷失敗: {str(e)}"
                
            else:
                reply_text = "不認識的指令\n輸入「功能」查看所有指令"
            
            # 發送回覆
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
            logger.info("訊息發送成功")
            
    except Exception as e:
        logger.error(f"處理訊息失敗: {str(e)}")
        traceback.print_exc()

@app.route("/")
def home():
    return f"""
    <h1>LINE Bot 股票監控系統</h1>
    <p>狀態: ✅ 運行中</p>
    <p>時間: {datetime.now()}</p>
    <p>緩存項目: {len(cache)}</p>
    <p>背景監控: {'✅ 運行中' if background_monitor.running else '❌ 未啟動'}</p>
    <p><a href="/debug">診斷頁面</a></p>
    """

@app.route("/health")
def health():
    """健康檢查端點"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_items": len(cache),
        "background_monitor": background_monitor.running
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
        stock_data = StockService.get_stock_info('2330')
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
    
    # 啟動背景價格監控
    background_monitor.start_monitoring()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
