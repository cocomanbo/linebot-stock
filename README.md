# LINE Bot 股票監控系統

## 功能特色

- 📊 **股票查詢**: 支援台股和美股查詢
- 🔔 **價格追蹤**: 設定價格提醒，自動通知
- 📈 **週報推送**: 每週一早上8點自動發送週報
- 📱 **LINE 整合**: 透過 LINE 訊息操作

## 支援指令

- `你好` - 基本問候
- `功能` - 查看所有功能
- `台股 2330` - 查詢台股股價
- `美股 AAPL` - 查詢美股股價
- `追蹤 2330 600 買進` - 設定價格提醒
- `我的追蹤` - 查看追蹤清單
- `週報` - 查看週報

## 部署到 Render

### 1. 上傳到 GitHub
將以下檔案上傳到 GitHub 儲存庫：
- `app.py`
- `requirements.txt`
- `Procfile`
- `runtime.txt`
- `README.md`

### 2. 在 Render 建立服務
1. 前往 https://render.com/
2. 選擇 "New Web Service"
3. 連接您的 GitHub 儲存庫
4. 設定環境變數：
   - `LINE_CHANNEL_ACCESS_TOKEN`: 您的 LINE Bot Access Token
   - `LINE_CHANNEL_SECRET`: 您的 LINE Bot Secret

### 3. 設定 LINE Bot
1. 前往 https://developers.line.biz/
2. 選擇您的 Bot
3. 設定 Webhook URL: `https://your-app-name.onrender.com/callback`
4. 啟用 Webhook

## 本地開發

```bash
# 安裝依賴
pip install -r requirements.txt

# 設定環境變數
export LINE_CHANNEL_ACCESS_TOKEN="your_token"
export LINE_CHANNEL_SECRET="your_secret"

# 啟動程式
python app.py
```

## 技術架構

- **Flask**: Web 框架
- **LINE Bot SDK**: LINE 訊息處理
- **yfinance**: 股票數據獲取
- **SQLite**: 資料庫儲存
- **Render**: 雲端部署平台


