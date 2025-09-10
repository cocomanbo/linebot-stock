#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LINE Bot 股票監控系統啟動腳本
"""

import os
import sys
import logging
from datetime import datetime
import pytz

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_environment():
    """檢查環境設定"""
    logger.info("🔍 檢查環境設定...")
    
    # 檢查必要的環境變數
    required_vars = ['LINE_CHANNEL_ACCESS_TOKEN', 'LINE_CHANNEL_SECRET']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.warning(f"⚠️ 缺少環境變數: {missing_vars}")
        logger.info("💡 將使用預設值")
    else:
        logger.info("✅ 環境變數設定正常")
    
    return len(missing_vars) == 0

def test_dependencies():
    """測試依賴套件"""
    logger.info("🔍 測試依賴套件...")
    
    try:
        import yfinance as yf
        logger.info(f"✅ yfinance 版本: {yf.__version__}")
    except ImportError as e:
        logger.error(f"❌ yfinance 導入失敗: {e}")
        return False
    
    try:
        import requests
        logger.info(f"✅ requests 版本: {requests.__version__}")
    except ImportError as e:
        logger.error(f"❌ requests 導入失敗: {e}")
        return False
    
    try:
        from linebot.v3 import WebhookHandler
        logger.info("✅ line-bot-sdk 導入成功")
    except ImportError as e:
        logger.error(f"❌ line-bot-sdk 導入失敗: {e}")
        return False
    
    return True

def test_stock_service():
    """測試股票服務"""
    logger.info("🔍 測試股票服務...")
    
    try:
        # 導入股票服務
        from app import StockService
        
        # 測試台股
        logger.info("📊 測試台股 2330...")
        tw_result = StockService.get_stock_info('2330')
        if tw_result:
            logger.info(f"✅ 台股 2330: ${tw_result['price']} ({tw_result['source']})")
        else:
            logger.warning("⚠️ 台股 2330 獲取失敗")
        
        # 測試美股
        logger.info("📊 測試美股 AAPL...")
        us_result = StockService.get_stock_info('AAPL')
        if us_result:
            logger.info(f"✅ 美股 AAPL: ${us_result['price']} ({us_result['source']})")
        else:
            logger.warning("⚠️ 美股 AAPL 獲取失敗")
        
        return tw_result is not None or us_result is not None
        
    except Exception as e:
        logger.error(f"❌ 股票服務測試失敗: {e}")
        return False

def main():
    """主函數"""
    logger.info("🚀 啟動 LINE Bot 股票監控系統...")
    logger.info(f"⏰ 啟動時間: {datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # 檢查環境
    env_ok = check_environment()
    
    # 測試依賴
    deps_ok = test_dependencies()
    
    # 測試股票服務
    service_ok = test_stock_service()
    
    logger.info("=" * 60)
    logger.info("📊 系統檢查結果:")
    logger.info(f"   環境設定: {'✅ 正常' if env_ok else '⚠️ 使用預設值'}")
    logger.info(f"   依賴套件: {'✅ 正常' if deps_ok else '❌ 異常'}")
    logger.info(f"   股票服務: {'✅ 正常' if service_ok else '❌ 異常'}")
    
    if not deps_ok:
        logger.error("❌ 依賴套件有問題，請執行: pip install -r requirements.txt")
        return False
    
    if not service_ok:
        logger.warning("⚠️ 股票服務有問題，但系統仍可啟動")
    
    logger.info("=" * 60)
    logger.info("🎯 啟動主應用程式...")
    
    try:
        # 啟動主應用程式
        from app import app
        port = int(os.environ.get('PORT', 5000))
        app.run(host="0.0.0.0", port=port, debug=False)
    except Exception as e:
        logger.error(f"❌ 應用程式啟動失敗: {e}")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)
