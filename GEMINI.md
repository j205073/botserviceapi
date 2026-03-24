# TR GPT — 台灣林內 Teams Bot 專案全覽

> 本文件供 AI 助手（如 Gemini）快速理解本專案的架構、技術棧、資料流與開發慣例。

---

## 1. 專案定位

**TR GPT** 是台灣林內（Rinnai Taiwan）資訊課開發的 **Microsoft Teams Bot**，部署於 Azure App Service，整合商用 LLM 模型，提供企業內部 AI 助理服務。

### 核心功能
| 功能 | 說明 |
|------|------|
| AI 智能對話 | 透過 OpenAI / Azure OpenAI 提供自然語言互動 |
| 待辦管理 | 個人任務清單，含智能重複偵測與自動清理 |
| 會議室預約 | 整合 Microsoft Graph API，查詢/預約/取消會議室 |
| IT 支援提單 | Adaptive Card 表單 → AI 分類 → Asana 任務 → Email/Teams 通知 |
| 知識庫查詢 | KB-Vector-Service 向量搜尋歷史工單建議 |
| 審計日誌 | 完整對話記錄壓縮上傳 AWS S3 |
| 廣播推播 | 主動推播訊息至指定使用者 |

### Bot 指令
```
@help       — 功能選單
@ls         — 列出待辦
@add <內容> — 新增待辦
@done 1,2   — 完成待辦
@book-room  — 會議室預約
@check-booking — 查詢預約
@cancel-booking — 取消預約
@info       — 個人資訊與系統狀態
@you        — Bot 自我介紹
@status     — 系統狀態（同 @info）
@new-chat   — 清除工作記憶（保留審計日誌）
@model      — 切換 AI 模型（非 Azure 模式）
@it         — IT 支援提單
@itt        — IT 代理提單（代他人提交）
```

---

## 2. 技術棧

| 層面 | 技術 |
|------|------|
| 語言 | Python 3.11 |
| Web 框架 | **Quart**（Flask 的 async 版本）|
| ASGI Server | **Hypercorn** |
| Bot Framework | `botbuilder-core` / `botbuilder-schema` 4.16.2 |
| LLM | OpenAI SDK（支援 Azure OpenAI 與 OpenAI 雙模式）|
| 雲端部署 | Azure App Service（Linux）|
| CI/CD | GitHub Actions → Azure Web App Deploy |
| 審計儲存 | AWS S3（gzip 壓縮 JSON）|
| 任務管理 | Asana API（httpx） |
| 日曆/用戶 | Microsoft Graph API（aiohttp）|
| 知識庫 | KB-Vector-Service（Azure AD Client Credentials 認證）|
| Email | SMTP（STARTTLS）|
| 依賴注入 | 自建 DI Container（Singleton / Transient / Scoped 生命週期）|

### 主要套件（requirements.txt）
```
botbuilder-core==4.16.2    # Teams Bot Framework
Quart==0.19.4              # Async Web Framework
hypercorn==0.15.0          # ASGI Server
openai>=1.0.0              # LLM Client
httpx==0.25.2              # Async HTTP (Asana)
aiohttp==3.10.5            # Async HTTP (Graph API, KB)
boto3>=1.26.0              # AWS S3
python-dotenv==1.0.0       # 環境變數
python-docx, openpyxl, PyPDF2, Pillow, pandas  # 檔案處理
```

---

## 3. 專案結構

```
AzureChatBot/
│
├── app.py                              # 應用程式入口：TRGPTApp 類別
│                                        # - 初始化 DI 容器
│                                        # - 建立 Quart app + 註冊路由
│                                        # - 啟動背景任務（每日維護、每小時提醒）
│                                        # - /api/messages 路由處理 Bot Framework 訊息
│
├── config/
│   └── settings.py                     # @dataclass 配置管理
│                                        # AppConfig 聚合：BotConfig, OpenAIConfig,
│                                        # DatabaseConfig, S3Config, GraphAPIConfig, TaskConfig
│
├── core/
│   ├── container.py                    # 自建 DI 容器
│   │                                    # Container: register_singleton/transient/scoped/factory/instance
│   │                                    # 支援建構子注入、循環依賴偵測、自動註冊
│   └── dependencies.py                 # DI 組裝：6 個 ServiceProvider 依序註冊所有服務
│
├── infrastructure/                     # 外部服務適配層
│   ├── bot/
│   │   └── bot_adapter.py              # CustomBotAdapter：Bot Framework 適配器
│   │                                    # 處理 conversationUpdate + message Activity
│   │                                    # 多語系歡迎訊息（zh/ja）
│   └── external/
│       ├── graph_api_client.py         # GraphAPIClient：Microsoft Graph API 封裝
│       │                                # 用戶查詢、會議室預約、日曆操作、SharePoint 上傳/下載
│       │                                # aiohttp session + TokenManager 認證
│       ├── openai_client.py            # OpenAIClient：OpenAI / Azure OpenAI 封裝
│       │                                # chat_completion() 含重試 (AsyncRetry)
│       │                                # 支援 Reasoning Responses (gpt-5/o1 系列)
│       ├── s3_client.py                # S3Client：審計日誌 gzip 壓縮上傳/下載
│       │                                # 路徑格式：audit-logs/YYYY/MM/DD/user_YYYYMMDD_HHMMSS.json.gz
│       └── token_manager.py            # OAuth Token 管理（Azure AD）
│
├── domain/                             # 領域層（業務邏輯）
│   ├── models/                         # 領域模型（User, Todo, Conversation 等）
│   ├── repositories/                   # Repository 介面
│   └── services/
│       ├── conversation_service.py     # 對話管理：上下文維護、AI 回應、記憶清除
│       ├── todo_service.py             # 待辦管理：CRUD、智能重複偵測、統計
│       ├── meeting_service.py          # 會議管理：預約、查詢、取消
│       ├── intent_service.py           # 意圖分析服務
│       └── audit_service.py            # 審計日誌服務
│
├── application/                        # 應用層
│   ├── handlers/
│   │   └── bot_command_handler.py      # 指令分派器：@command → handler 映射
│   │                                    # 13 個指令處理方法
│   ├── dtos/
│   │   └── bot_dtos.py                 # BotInteractionDTO, CommandExecutionDTO
│   └── services/
│       └── application_service.py      # 應用服務：統一入口處理使用者訊息、系統維護
│
├── presentation/                       # 展示層
│   ├── bot/
│   │   └── message_handler.py          # TeamsMessageHandler：Teams 訊息處理器
│   │                                    # 文字訊息 + Adaptive Card 互動
│   ├── cards/
│   │   └── card_builders.py            # Adaptive Card 建構器
│   │                                    # HelpCard, TodoCard, MeetingCard, ModelSelectionCard, UploadCard
│   └── web/
│       └── api_routes.py              # HTTP API 路由（Quart Blueprint）
│                                        # /ping, /api/test, /api/messages
│                                        # Asana webhook, 審計日誌 API, 廣播推播
│
├── features/                           # 獨立功能模組
│   └── it_support/
│       ├── service.py                  # ITSupportService：提單主流程編排
│       ├── asana_client.py             # AsanaClient：任務建立、查詢、webhook、附件
│       ├── cards.py                    # IT 提單 Adaptive Card
│       ├── intent_classifier.py        # 關鍵字意圖分類器（12 類）
│       ├── taxonomy.json               # IT 問題分類定義
│       ├── kb_client.py                # KBVectorClient：知識庫向量搜尋
│       │                                # Azure AD Client Credentials 認證、token 快取
│       │                                # ask_safe() 不影響主流程
│       ├── knowledge_base.py           # SharePoint 知識庫存檔
│       └── email_notifier.py           # EmailNotifier：SMTP 通知
│                                        # 提單確認 + 完成通知（含溝通評論）
│
├── shared/
│   ├── utils/
│   │   └── helpers.py                  # 工具函式集合
│   │                                    # get_taiwan_time(), determine_language()
│   │                                    # get_user_email()（多策略取得 Teams 用戶 email）
│   │                                    # AsyncRetry 裝飾器、PerformanceTimer
│   └── exceptions.py                   # 自定義例外
│
├── scripts/
│   └── sharepoint_kb_api.py            # SharePoint KB 獨立測試 API
│
├── .github/workflows/
│   └── master_rinnai-py-api.yml        # CI/CD：push master → build → deploy Azure
│
├── startup.sh                          # Azure App Service 啟動腳本
│                                        # pip install → hypercorn --bind 0.0.0.0:8000
│
├── requirements.txt                    # Python 依賴
├── .env                                # 本地環境變數（不入版控）
└── CLAUDE.md                           # Claude Code 開發指引
```

---

## 4. 架構設計

### 4.1 分層架構

```
┌─────────────────────────────────────────────┐
│              Presentation Layer              │
│  ┌──────────────┐  ┌─────────────────────┐  │
│  │ Bot Adapter   │  │ API Routes (Quart)  │  │
│  │ Message Handler│  │ /ping /api/messages │  │
│  │ Adaptive Cards│  │ Asana Webhook       │  │
│  └──────┬───────┘  └──────────┬──────────┘  │
├─────────┴──────────────────────┴─────────────┤
│              Application Layer               │
│  ┌────────────────────────────────────────┐  │
│  │ BotCommandHandler (指令分派)            │  │
│  │ ApplicationService (統一入口)           │  │
│  │ DTOs: BotInteractionDTO, CommandDTO    │  │
│  └──────────────────┬─────────────────────┘  │
├─────────────────────┴────────────────────────┤
│               Domain Layer                   │
│  ┌────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Todo   │ │Conversa- │ │ Meeting       │  │
│  │Service │ │tion Svc  │ │ Service       │  │
│  └────────┘ └──────────┘ └───────────────┘  │
│  ┌────────┐ ┌──────────┐                     │
│  │ Intent │ │ Audit    │  Models/Repos       │
│  │Service │ │ Service  │                     │
│  └────────┘ └──────────┘                     │
├──────────────────────────────────────────────┤
│           Infrastructure Layer               │
│  ┌──────────┐ ┌────────┐ ┌────────────────┐ │
│  │ OpenAI   │ │Graph   │ │ S3 Client      │ │
│  │ Client   │ │API     │ │ (Audit Logs)   │ │
│  └──────────┘ └────────┘ └────────────────┘ │
│  ┌──────────┐ ┌────────────────────────────┐ │
│  │ Token    │ │ IT Support Feature         │ │
│  │ Manager  │ │ Asana / KB / Email / Cards │ │
│  └──────────┘ └────────────────────────────┘ │
├──────────────────────────────────────────────┤
│          Dependency Injection (Container)     │
│  core/container.py + core/dependencies.py    │
└──────────────────────────────────────────────┘
```

### 4.2 DI 容器

自建的依賴注入容器，支援：
- **Singleton**：全域單一實例（OpenAIClient, GraphAPIClient, S3Client 等）
- **Transient**：每次注入建立新實例
- **Scoped**：請求範圍內共用實例
- **Factory**：工廠方法註冊
- 建構子自動注入（透過 type hints 解析）
- 循環依賴偵測

### 4.3 記憶體系統

| 類型 | 用途 | 持久化 |
|------|------|--------|
| 工作記憶 | 近期對話上下文（context window） | ❌ 記憶體，重啟即清 |
| 審計日誌 | 完整對話記錄 | ✅ AWS S3（gzip JSON） |
| 待辦事項 | 個人任務清單 | ❌ 記憶體 |

---

## 5. 關鍵資料流

### 5.1 一般對話流程

```
Teams 使用者輸入
  → Bot Framework POST /api/messages
  → CustomBotAdapter.process_activity()
  → TeamsMessageHandler.handle_message()
  → 判斷：@command 或自然語言
    ├─ @command → BotCommandHandler.handle_command()
    └─ 自然語言 → ConversationService.get_ai_response()
                    → OpenAIClient.chat_completion()
                    → 回應 Teams + 寫入審計日誌
```

### 5.2 IT 提單流程

```
使用者 @it / @itt
  → BotCommandHandler._handle_it_command()
  → ITSupportService.build_issue_card()
  → 使用者填寫 Adaptive Card 表單
  → TeamsMessageHandler 處理 card submit
  → ITSupportService.submit_issue()
    ├─ ITIntentClassifier：關鍵字 + AI 分類（12 類 taxonomy）
    ├─ KBVectorClient.ask_safe()：知識庫查詢歷史工單
    ├─ AsanaClient.create_task()：建立 Asana 任務（含分類、KB 參考）
    ├─ EmailNotifier.send_submission_notification()：提單確認 Email
    └─ Asana Webhook 監聽完成
        → Teams 推播完成通知
        → EmailNotifier.send_completion_notification()（含溝通評論）
```

### 5.3 會議室預約流程

```
使用者 @book-room
  → Adaptive Card 表單（日期、時段、會議室）
  → MeetingService → GraphAPIClient
    ├─ list_meeting_rooms()：取得可用會議室
    ├─ get_room_availability()：查空檔
    └─ book_meeting()：Graph API 建立事件
  → 回傳預約結果 Adaptive Card
```

---

## 6. 外部服務整合

### 6.1 Microsoft Graph API
- **用途**：使用者資訊、會議室預約、日曆管理、SharePoint 操作
- **認證**：Azure AD OAuth（Client Credentials + Delegated）
- **Token 管理**：`TokenManager` 自動刷新
- **封裝**：`GraphAPIClient`（aiohttp + 重試）

### 6.2 OpenAI / Azure OpenAI
- **雙模式切換**：`USE_AZURE_OPENAI` 環境變數
- **支援模型**：gpt-4o, gpt-4o-mini, gpt-5, gpt-5-mini, gpt-5-nano
- **特殊處理**：gpt-5/o1 系列使用 Reasoning Responses API
- **重試**：AsyncRetry 裝飾器（max 3 次，指數退避）

### 6.3 Asana
- **用途**：IT 提單任務管理
- **功能**：建立任務、查詢、附件上傳、Webhook 監聽完成事件
- **封裝**：`AsanaClient`（httpx）
- **優先序標籤**：P1–P4 對應不同 Asana Tag GID

### 6.4 KB-Vector-Service
- **用途**：IT 知識庫向量搜尋，查詢歷史工單提供建議
- **端點**：`POST /api/v1/ask?question={問題}&role={user|it}`
- **認證**：Azure AD Client Credentials（scope: `api://de281045-.../.default`）
- **設計**：`ask_safe()` 靜默失敗，不影響主流程

### 6.5 AWS S3
- **用途**：審計日誌持久化儲存
- **格式**：gzip 壓縮 JSON
- **路徑**：`audit-logs/YYYY/MM/DD/user_mail_YYYYMMDD_HHMMSS.json.gz`
- **排程**：每日台灣時間 07:00 自動上傳，上傳成功後清本地快取

### 6.6 SMTP Email
- **用途**：IT 提單確認 / 完成通知
- **格式**：HTML + 純文字（multipart）
- **功能**：CC 支援（代提單情境）、溝通評論內嵌

---

## 7. 環境變數

### 必要
```env
# Bot Framework
BOT_APP_ID=
BOT_APP_PASSWORD=

# Azure AD（Graph API + KB 認證共用）
TENANT_ID=
CLIENT_ID=
CLIENT_SECRET=

# OpenAI
USE_AZURE_OPENAI=true|false
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_KEY=

# AWS S3
AWS_ACCESS_KEY=
AWS_SECRET_KEY=
S3_BUCKET_NAME=
S3_REGION=
```

### IT 支援
```env
# Asana
ASANA_ACCESS_TOKEN=
ASANA_WORKSPACE_GID=
ASANA_PROJECT_GID=
ASANA_ASSIGNEE_GID=
ASANA_ASSIGNEE_SECTION_GID=
ASANA_TAG_P1=  # ~ P4
ASANA_PRIORITY_TAG_GID=
ASANA_ONBOARDING_ASSIGNEE_EMAIL=

# SMTP
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASSWORD=
EMAIL_TEST_MODE=true|false

# 知識庫
KB_API_URL=https://kb-vector-service.azurewebsites.net

# 功能開關
ENABLE_AI_INTENT_ANALYSIS=true|false
ENABLE_IT_AI_ANALYSIS=true|false
IT_ANALYSIS_MODEL=gpt-5-nano
```

---

## 8. 部署架構

```
GitHub (master branch)
  │ push / workflow_dispatch
  ▼
GitHub Actions
  │ Build: Python 3.11, pip install, zip
  │ Deploy: Azure Login (OIDC) → Web App Deploy
  ▼
Azure App Service (rinnai-py-api)
  │ startup.sh: pip install → hypercorn --bind 0.0.0.0:8000
  ▼
Quart ASGI App
  ├── /ping                  → Health Check
  ├── /api/messages          → Bot Framework Webhook
  ├── /api/test              → 測試端點
  ├── /api/asana-webhook     → Asana 完成事件
  └── /api/broadcast         → 主動推播
```

---

## 9. 程式碼慣例

- **Python PEP 8**：4 空格縮排，約 120 字元行寬
- **命名**：`snake_case`（模組/函式/變數），`CamelCase`（類別）
- **日誌**：使用 `logging` 模組，不用 print（歷史程式碼中仍有 print）
- **非同步**：全面 async/await，使用 `asyncio`
- **Type Hints**：適當使用
- **重試**：`AsyncRetry` 裝飾器（max_attempts, delay, backoff）
- **錯誤處理**：外部服務呼叫都有 try/except，知識庫用 `ask_safe()` 靜默失敗
- **多語系**：`determine_language()` 依 email domain 判斷（.jp→ja, .vn→vi, 預設 zh）

---

## 10. 已知限制與風險

| 項目 | 說明 |
|------|------|
| 記憶體儲存 | 對話記憶、待辦事項存於記憶體，重啟即清 |
| 單實例 | 無 HA/水平擴展設計 |
| 全域變數 | `user_conversation_refs` 等仍為全域 dict（向後相容） |
| Token 過期 | Azure AD CLIENT_SECRET 有效期限需定期更換 |
| 無自動化測試 | 僅有 `app_test.py` 輕量測試，無 CI 自動執行 |

---

## 11. 快速啟動（本地開發）

```bash
# 1. 建立虛擬環境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定環境變數
cp .env.example .env  # 填入必要變數

# 4. 啟動
hypercorn app:app --bind 0.0.0.0:8000

# 5. 驗證
curl http://localhost:8000/ping
```

---

*本文件最後更新：2026-03-24*
