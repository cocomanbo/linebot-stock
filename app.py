class CommandParser:
    """指令解析器 - 支援價格提醒功能"""
    
    @staticmethod
    def parse_command(message: str) -> dict:
        """解析用戶指令"""
        message = message.strip()
        
        # 追蹤指令：追蹤 2330 800 買進/賣出
        if message.startswith('追蹤 '):
            parts = message[3:].strip().split()  # 移除"追蹤 "後分割
            
            if len(parts) == 1:
                # 僅追蹤，不設價格提醒：追蹤 2330
                return {
                    'action': 'add_tracking',
                    'symbol': parts[0]
                }
            elif len(parts) == 3:
                # 設定價格提醒：追蹤 2330 800 買進
                symbol, price_str, action = parts
                try:
                    target_price = float(price_str)
                    if action in ['買進', '賣出']:
                        return {
                            'action': 'add_price_alert',
                            'symbol': symbol,
                            'target_price': target_price,
                            'alert_action': action
                        }
                except ValueError:
                    pass
        
        # 取消全部指令
        if message in ['取消全部', '取消所有', '清除全部']:
            return {'action': 'remove_all_alerts'}
        
        # 我的提醒 / 提醒清單
        if message in ['我的提醒', '提醒清單', '我的股票']:
            return {'action': 'list_alerts'}
        
        return {'action': 'unknown'}


def format_alerts_list_message(alerts: list) -> str:
    """格式化提醒清單訊息"""
    if not alerts:
        return """
📊 我的價格提醒

目前沒有設定任何提醒
輸入指令開始設定提醒

指令格式：
追蹤 [股票代號] [價格] [買進/賣出]

範例：
• 追蹤 2330 800 買進
• 追蹤 AAPL 140 賣出
• 取消全部
        """.strip()
    
    # 分類統計
    buy_alerts = [a for a in alerts if a['action'] == '買進']
    sell_alerts = [a for a in alerts if a['action'] == '賣出']
    
    # 建立提醒清單
    alert_lines = []
    for alert in alerts[:15]:  # 最多顯示15個
        current_price = alert['current_price']
        target_price = alert['target_price']
        action = alert['action']
        
        # 計算距離目標價格的差距
        diff = target_price - current_price
        diff_percent = (diff / current_price * 100) if current_price > 0 else 0
        
        # 選擇圖示和狀態
        if action == '買進':
            icon = "🟢" if current_price > target_price else "🔴"
            status = f"還需跌 ${abs(diff):.0f}" if diff < 0 else f"已達標 +${diff:.0f}"
        else:  # 賣出
            icon = "🔴" if current_price < target_price else "🟢"
            status = f"還需漲 ${abs(diff):.0f}" if diff > 0 else f"已達標 +${abs(diff):.0f}"
        
        line = f"{icon} {alert['name']} ({alert['symbol']})"
        line += f"\n   目標: ${target_price} {action} | 現價: ${current_price}"
        line += f"\n   狀態: {status}"
        
        alert_lines.append(line)
    
    total_text = f"共 {len(alerts)} 個提醒" + (f"（顯示前15個）" if len(alerts) > 15 else "")
    
    return f"""
📊 我的價格提醒 ({total_text})
{'='*30}

{chr(10).join(alert_lines)}

📈 統計: 買進 {len(buy_alerts)} 個 | 賣出 {len(sell_alerts)} 個
⏰ 更新: {datetime.now().strftime('%H:%M:%S')}

💡 指令: 取消全部 | 追蹤 [代號] [價格] [動作]
    """.strip()


# 需要在 StockService 中新增 use_cache 參數
def enhanced_get_stock_info(symbol, use_cache=True):
    """增強版股票查詢，支援快取控制"""
    if use_cache:
        # 檢查快取（2-5分鐘）
        cache_key = f"stock_{symbol}"
        current_time = time.time()
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if current_time - timestamp < 300:  # 5分鐘快取
                return data
    
    # 取得新數據
    try:
        result = StockService.get_stock_info(symbol)
        
        if result and use_cache:
            cache[f"stock_{symbol}"] = (result, time.time())
        
        return result
        
    except Exception as e:
        logger.error(f"股票查詢失敗: {str(e)}")
        return None
