# 🤖 TR GPT — 台灣林內 IT 智能助理

> 基於 Microsoft Bot Framework + Quart 的 Teams Bot，整合 OpenAI、Microsoft Graph、Asana、AWS S3 等服務。

## 📋 目錄

- [環境需求](#環境需求)
- [快速開始](#快速開始)
- [環境變數設定](#環境變數設定)
- [本機開發](#本機開發)
- [Azure 部署](#azure-部署)
- [API 端點](#api-端點)
- [專案結構](#專案結構)
- [功能說明](#功能說明)

---

## 環境需求

| 項目 | 版本 |
|------|------|
| Python | 3.11+ |
| OS | Windows / Linux (Azure App Service) |
| Bot Channel | Microsoft Teams |

## 快速開始

### 1. 建立虛擬環境

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 2. 安裝依賴

```bash
pip install -r requirements.txt
```

### 3. 設定環境變數

複製 `.env.example`（或直接編輯 `.env`），填入必要的金鑰與設定（詳見[環境變數設定](#環境變數設定)）。

### 4. 啟動服務

```bash
# 本機開發（推薦）
hypercorn app:app --bind 0.0.0.0:8000 --reload

# 或使用 Python 直接啟動
python app.py
```

服務啟動後可訪問：
- 健康檢查：`http://localhost:8000/ping`
- API 測試：`http://localhost:8000/api/test`
- 路由列表：`http://localhost:8000/api/routes`

---

## 環境變數設定

在專案根目錄建立 `.env` 檔案，以下為必要設定：

### Bot Framework
```env
BOT_APP_ID=<your-bot-app-id>
BOT_APP_PASSWORD=<your-bot-app-password>
```

### OpenAI / Azure OpenAI
```env
# 選擇 API 提供商（true = Azure OpenAI, false = OpenAI）
USE_AZURE_OPENAI=false

# OpenAI
OPENAI_API_KEY=<your-openai-key>
OPENAI_ENDPOINT=https://api.openai.com/v1/
OPENAI_MODEL=gpt-4o-mini

# Azure OpenAI（如使用 Azure）
AZURE_OPENAI_KEY=<your-azure-key>
AZURE_OPENAI_ENDPOINT=<your-azure-endpoint>
```

### Microsoft Graph API
```env
TENANT_ID=<your-tenant-id>
CLIENT_ID=<your-client-id>
CLIENT_SECRET=<your-client-secret>
```

### Asana
```env
ASANA_ACCESS_TOKEN=<your-asana-token>
ASANA_PRIORITY_TAG_GID=<tag-gid>
```

### SMTP Email 通知
```env
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=<sender-email>
SMTP_PASSWORD=<sender-password>
```

### AWS S3（稽核日誌上傳）
```env
AWS_ACCESS_KEY=<your-access-key>
AWS_SECRET_KEY=<your-secret-key>
S3_BUCKET_NAME=<bucket-name>
S3_REGION=ap-northeast-1
```

### 其他
```env
DEBUG_MODE=true
DEBUG_ACCOUNT=<your-email>
ENABLE_AI_INTENT_ANALYSIS=true
MAX_CONTEXT_MESSAGES=5
CONVERSATION_RETENTION_DAYS=30
IT_ANALYSIS_MODEL=gpt-4o-mini
```

---

## 本機開發

### 使用 Bot Framework Emulator 測試

1. 下載 [Bot Framework Emulator](https://github.com/microsoft/BotFramework-Emulator/releases)
2. 啟動本機服務：`hypercorn app:app --bind 0.0.0.0:8000 --reload`
3. 在 Emulator 中連接到 `http://localhost:8000/api/messages`

### 使用 ngrok 搭配 Teams 測試

1. 啟動 ngrok：`ngrok http 8000`
2. 在 [Azure Bot Service](https://portal.azure.com/) 中將 Messaging endpoint 設為 ngrok URL + `/api/messages`
3. 在 Teams 中與 Bot 對話測試

### 測試 Email 發送

```bash
python test_email.py
```

---

## Azure 部署

### 部署方式：Azure App Service (Linux)

1. **建立 App Service**（Python 3.11, Linux）

2. **設定啟動命令**（Azure Portal → Configuration → General Settings → Startup Command）：
   ```
   startup.sh
   ```
   或直接設定：
   ```
   hypercorn app:app --bind 0.0.0.0:8000 --access-logfile - --error-logfile -
   ```

3. **設定環境變數**（Azure Portal → Configuration → Application Settings）  
   將 `.env` 中的各變數加入 Application Settings

4. **部署程式碼**
   ```bash
   git push origin master
   ```
   若已設定 GitHub Actions 或 Azure DevOps，推送後會自動部署。

### 部署後驗證

```bash
# 健康檢查
curl https://<your-app>.azurewebsites.net/ping

# API 測試
curl https://<your-app>.azurewebsites.net/api/test

# 查看路由
curl https://<your-app>.azurewebsites.net/api/routes
```

### Asana Webhook 設定（一次性）

部署後呼叫此 API 建立 Asana Webhook 訂閱：

```bash
curl -X POST https://<your-app>.azurewebsites.net/api/asana/webhook/setup \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://<your-app>.azurewebsites.net/api/asana/webhook"}'
```

---

## API 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET` | `/ping` | 健康檢查 |
| `GET/POST` | `/api/test` | API 測試 |
| `GET` | `/api/routes` | 列出所有路由 |
| `POST` | `/api/messages` | Bot Framework 訊息處理 |
| `GET` | `/api/audit/upload-all` | 上傳所有用戶稽核日誌 |
| `GET` | `/api/audit/summary` | 稽核摘要 |
| `GET` | `/api/audit/files` | 列出稽核文件 |
| `GET` | `/api/memory/clear?user_mail=xxx` | 清除用戶記憶體 |
| `POST` | `/api/asana/webhook` | Asana Webhook 回呼 |
| `POST` | `/api/asana/webhook/setup` | 建立 Asana Webhook 訂閱 |

---

## 專案結構

```
AzureChatBot/
├── app.py                      # 應用程式入口
├── config/settings.py          # 統一配置管理
├── core/
│   ├── container.py            # DI 容器
│   └── dependencies.py         # 依賴註冊
├── domain/
│   ├── models/                 # 領域模型 (User, Todo, Audit, Conversation)
│   ├── repositories/           # 倉儲介面
│   └── services/               # 領域服務 (Intent, Todo, Meeting, Audit)
├── infrastructure/
│   ├── bot/bot_adapter.py      # Bot Framework 適配器
│   └── external/               # 外部服務 (OpenAI, Graph API, S3, Token)
├── application/
│   ├── dtos/                   # 資料傳輸物件
│   ├── handlers/               # 命令處理器
│   └── services/               # 應用服務
├── presentation/
│   ├── bot/message_handler.py  # Teams 訊息處理
│   ├── cards/                  # Adaptive Card 建構器
│   └── web/api_routes.py       # Web API 路由
├── features/
│   └── it_support/             # IT 支援功能模組
│       ├── service.py          # IT 服務核心邏輯
│       ├── asana_client.py     # Asana API 客戶端
│       ├── email_notifier.py   # Email 通知模組
│       ├── intent_classifier.py # 意圖分類器
│       └── cards.py            # IT 表單卡片
├── shared/                     # 共用工具與例外處理
├── requirements.txt            # Python 依賴
├── startup.sh                  # Azure 部署啟動腳本
└── .env                        # 環境變數（不納入版控）
```

> 詳細架構說明請參閱 [STRUCTURE.md](STRUCTURE.md)

---

## 功能說明

### 🤖 Teams Bot 對話
- 自然語言對話（OpenAI / Azure OpenAI）
- AI 意圖分析與路由

### 📋 IT 支援工單
- 透過 `@it` 觸發 IT 提單表單
- 自動建立 Asana 任務（含 AI 分類與分析）
- 支援拖拽檔案附加至工單
- **提單完成後自動通知**：Teams 推播 + Email 通知

### ✅ 待辦事項管理
- 新增 / 完成 / 列出待辦事項
- 定時提醒（每小時檢查）

### 📅 會議室預訂
- 透過 Microsoft Graph API 查詢 / 預訂會議室

### 📊 稽核日誌
- 自動記錄對話與操作
- 上傳至 AWS S3 備份

---

## 📄 授權

此專案為台灣林內內部使用專案。
