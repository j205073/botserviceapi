# CLAUDE.md

此檔案提供 Claude Code (claude.ai/code) 在此專案中的開發指引。

## 專案概覽

TR GPT 是台灣林內資訊課開發的 Microsoft Teams Bot，整合商用 LLM 模型，為企業提供 AI 助理服務，涵蓋待辦管理、會議室預約、IT 支援提單、知識庫查詢等功能。

## 建置、測試與開發指令

### 環境設定
- 建立虛擬環境：`python -m venv venv`
- 啟用（Linux/Mac）：`source venv/bin/activate`
- 啟用（Windows）：`venv\Scripts\activate`
- 安裝依賴：`pip install -r requirements.txt`

### 啟動應用
- 本地開發（ASGI）：`hypercorn app:app --bind 0.0.0.0:8000`
- 健康檢查：`curl http://localhost:8000/ping`
- 環境設定測試：`python test_config.py`
- Azure 部署啟動：`bash startup.sh`

### 測試
- 基本功能測試：`app_test.py`（輕量測試）
- 測試端點：`/ping` 和 `/api/test` 手動驗證
- Teams Bot 流程與 S3 上傳透過應用程式 log 驗證

## 架構與核心元件

### 專案結構

```
AzureChatBot/
├── app.py                          # 主程式入口（Quart + Bot Framework）
├── config/
│   └── settings.py                 # AppConfig 設定管理
├── core/
│   └── container.py                # DI 容器
├── infrastructure/
│   ├── bot/
│   │   └── bot_adapter.py          # CustomBotAdapter
│   └── external/
│       ├── graph_api_client.py     # Microsoft Graph API
│       ├── openai_client.py        # OpenAI / Azure OpenAI
│       ├── s3_client.py            # AWS S3 審計日誌
│       └── token_manager.py        # OAuth Token 管理
├── application/
│   └── handlers/
│       └── bot_command_handler.py  # 指令分派（@help, @it, @itt 等）
├── presentation/
│   ├── bot/
│   │   └── message_handler.py      # Teams 訊息處理 + Adaptive Card 互動
│   └── web/
│       └── api_routes.py           # HTTP API 路由
├── features/
│   └── it_support/
│       ├── service.py              # IT 提單主流程
│       ├── asana_client.py         # Asana API 客戶端
│       ├── cards.py                # Adaptive Card 建構
│       ├── email_notifier.py       # SMTP Email 通知
│       ├── kb_client.py            # KB-Vector-Service 知識庫客戶端
│       ├── knowledge_base.py       # IT 知識庫（SharePoint 存檔）
│       ├── intent_classifier.py    # 關鍵字分類器
│       └── taxonomy.json           # IT 問題分類定義（12 類）
├── shared/
│   └── utils/
│       └── helpers.py              # get_user_email() 等工具函式
└── scripts/
    └── sharepoint_kb_api.py        # SharePoint KB 獨立測試 API
```

### 主要功能
- **雙重記憶系統**：工作記憶（近期對話上下文）+ 審計日誌（完整記錄）
- **Teams 整合**：Bot Framework adapter 處理 Teams 訊息
- **待辦管理**：個人任務清單與自動清理
- **會議室預約**：Microsoft Graph 整合
- **IT 支援提單**：Adaptive Card 表單 → AI 分類 → Asana 任務建立 → Email/Teams 通知
- **AI 意圖分析**：`ENABLE_AI_INTENT_ANALYSIS` 啟用時自動辨識意圖
- **模型切換**：動態切換 AI 模型（非 Azure-only 模式）
- **知識庫整合**：KB-Vector-Service API 查詢歷史工單建議

### IT 支援提單資料流
```
使用者 @it / @itt
  → Adaptive Card 表單
  → AI 分類（OpenAI, IT_ANALYSIS_MODEL）
  → KB-Vector-Service 知識庫查詢（role=it）
  → Asana 任務建立（含分類、KB 參考、AI 分析）
  → Email 提單確認通知（提出人 + 代提單 CC）
  → Webhook 監聽任務完成 → Teams 推播 + Email 完成通知
```

## 環境變數設定

### 必要變數
- Bot Framework：`BOT_APP_ID`, `BOT_APP_PASSWORD`
- Azure AD：`TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`
- OpenAI：`USE_AZURE_OPENAI`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`
- AWS S3：`AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `S3_BUCKET_NAME`, `S3_REGION`
- 功能開關：`ENABLE_AI_INTENT_ANALYSIS`, `ENABLE_IT_AI_ANALYSIS`

### IT 支援相關
- Asana：`ASANA_ACCESS_TOKEN`, `ASANA_WORKSPACE_GID`, `ASANA_PROJECT_GID`, `ASANA_ASSIGNEE_GID`
- Asana 優先序標籤：`ASANA_TAG_P1` ~ `ASANA_TAG_P4`, `ASANA_PRIORITY_TAG_GID`
- 報到開通指派：`ASANA_ONBOARDING_ASSIGNEE_EMAIL`
- SMTP：`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`
- Email 測試模式：`EMAIL_TEST_MODE`（true=僅白名單）
- 知識庫 API：`KB_API_URL`（預設 `https://kb-vector-service.azurewebsites.net`）

### 設定管理
- 本地開發使用 `.env` 檔案（透過 python-dotenv 載入）
- 機敏資訊存放於 GitHub/Azure secrets
- 不可將 secrets 提交至版本庫

## 程式碼慣例

### 風格指引
- Python PEP 8：4 空格縮排，約 120 字元行寬
- 命名：`snake_case`（模組/函式/變數），`CamelCase`（類別）
- 新程式碼使用 `logging` 模組，避免 print
- 適當使用 type hints

### 檔案組織
- 依功能模組分層（features / infrastructure / application / presentation）
- 偏好小型、單一職責的檔案
- 新元件遵循現有模式

## 部署與 CI/CD

- Azure App Service 部署，透過 `.github/workflows/`
- 容器啟動：`startup.sh`
- 提交 PR 前確認 `requirements.txt` 已更新
- 部署前先驗證本地功能

## Bot 指令清單

| 指令 | 功能 |
|------|------|
| `@help` | 顯示功能選單 |
| `@ls` | 列出待辦事項 |
| `@add <內容>` | 新增待辦事項 |
| `@book-room` | 會議室預約 |
| `@info` | 個人資訊 |
| `@you` | Bot 自我介紹 |
| `@status` | 系統狀態 |
| `@new-chat` | 清除工作記憶（保留審計日誌）|
| `@model` | 切換 AI 模型 |
| `@it` | IT 支援提單 |
| `@itt` | IT 代理提單（代他人提交）|

## 安全與審計

- S3 完整審計日誌，供安全與除錯使用
- 本地快取於 S3 上傳成功後清除
- 工作記憶 vs 永久審計日誌區分
- Microsoft Graph OAuth Token 管理

## 外部服務整合

### KB-Vector-Service（知識庫 API）
- 文件：`INTEGRATION_GUIDE.md`
- 端點：`POST /api/v1/ask?question={問題}&role={user|it}`
- 認證：Azure AD Client Credentials Flow（scope: `api://de281045-d27f-4549-972a-0b331178668a/.default`）
- 使用現有 `TENANT_ID` / `CLIENT_ID` / `CLIENT_SECRET` 取得 token
- 重啟後需先呼叫 `POST /api/v1/sync` 同步知識庫

---

## 開發進度追蹤

### 已完成功能

#### 1. Email 完成通知加入溝通評論（2026-03-20）
- **需求**：IT 單完成的 Email 通知要包含與 Teams 推播相同的溝通評論內容
- **狀態**：✅ 已完成
- **異動檔案**：
  - `features/it_support/email_notifier.py` — `_build_completion_email()` 和 `send_completion_notification()` 新增 `comments` 參數，HTML 版加入「💬 溝通評論」卡片
  - `features/it_support/service.py` — 呼叫 `send_completion_notification()` 時傳入 `comments_str`

#### 2. KB-Vector-Service 知識庫整合（2026-03-21）
- **需求**：提單時自動查詢知識庫，將歷史工單建議寫入 Asana 供 IT 人員參考
- **狀態**：✅ 程式碼已完成，待驗證認證與實際查詢結果
- **異動檔案**：
  - `features/it_support/kb_client.py` — 新建，KB-Vector-Service 客戶端（Azure AD Client Credentials 認證、token 快取、`ask_safe()` 不影響主流程）
  - `features/it_support/service.py` — `submit_issue()` 在 AI 分類後呼叫 `kb_client.ask_safe(description, role="it")`，結果寫入 Asana notes【知識庫參考】區塊
  - `.env` — 新增 `KB_API_URL`
- **待確認事項**：
  - [ ] `CLIENT_ID` 是否已加入 KB-Vector-Service 的 `Auth__AllowedClientIds`
  - [ ] KB API 是否已執行 `POST /api/v1/sync` 同步知識庫
  - [ ] 實際提單測試，確認 Asana notes 中出現知識庫參考區塊

### 待開發功能

#### 3. 使用者查詢自己的 IT 工單（@my-it）
- **需求**：使用者在 Teams 輸入 `@my-it`，查詢自己提交或被代為提交的 IT 單及處理狀態
- **狀態**：🔲 待開發
- **設計方案**：
  - `asana_client.py` — 新增 `search_tasks_by_text()` 方法（Asana Search API）
  - `service.py` — 新增 `query_my_tickets()` 方法
  - `cards.py` — 新增 `build_my_tickets_card()` Adaptive Card（顯示單號、摘要、狀態、優先序）
  - `bot_command_handler.py` — 註冊 `@my-it` 指令
- **查詢邏輯**：搜尋 Asana project 中 notes 包含使用者 email 的任務，涵蓋自提與代提兩種情境

#### 4. IT 分類 taxonomy 自動優化（2026-04-18 暫緩）
- **需求**：`taxonomy.json` 寫死、不彈性，實務上常出現誤判（例：「ERP 領退料出錯」被歸到 `software`），希望隨 KB 累積自動找出分類缺口並建議調整
- **狀態**：🔁 構想已完成設計討論，暫緩實作（使用者評估先在外部程式處理）
- **核心構想**：
  - 新增 API `POST /api/it-taxonomy/analyze?days=90`（Bearer token 認證）
  - Azure OpenAI `text-embedding-3-small` 將最近 N 天 Asana 工單 + KB 內容向量化（用完即丟，不建新向量 DB）
  - HDBSCAN clustering 找群集 → 統計比對現有類別分布 → 找出「結構缺口」候選
  - LLM 僅對候選群集命名一次 → 產出新類別建議 + keywords 補充 + 每類 5 張代表範例
  - n8n 定時呼叫 API → email 使用者含可直接複製貼上的新版 `taxonomy.json`
- **Schema 擴充**：taxonomy.json 每類新增 `examples` 欄位（few-shot 範例）
- **詳細設計**：見 memory `project_it_taxonomy_auto_optimization.md`
