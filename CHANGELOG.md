# CHANGELOG

TR GPT Bot 變更紀錄（2026-03-01 ~）

---

## 2026-04-13

### 新功能

- **Azure Document Intelligence 整合** — 掃描型 PDF（圖片型）自動透過 OCR 擷取文字，不再回傳空白。大型 PDF 自動截取前 20 頁處理
- **PDF 格式類型回報** — 上傳 PDF 時第一行顯示「PDF格式: 文字」或「PDF格式: 圖片（已透過 OCR 辨識）」
- **擴充多模態檔案支援** — 新增 PPTX（python-pptx）、XLS（xlrd）、BMP 圖片支援
- **支援格式提示** — 四處顯示支援格式清單：附件分析回覆、@help 功能選單、歡迎訊息、Email footer
- **階段 2 規劃文件** — `docs/phase2_natural_language_skills.md`：自然語言 SKILL.md + Handler plugin 架構設計

### 改進

- **Email 評論 icon** — 無作者名的補充資訊 icon 從 `?` 改為 `ℹ`
- **舊格式檔案提示** — 上傳 .doc/.xls/.ppt 時提示使用者另存為新版格式
- **@t 權限 debug log** — 加入 user_mail 與 it_staff_emails 對照 log

### 修復

- **PDF 解析失敗** — Teams 傳檔時 content_type 為 `application/vnd.microsoft.teams.file.download.info`，未正確推斷 MIME type 導致 PDF 無法解析。加入 fileType/副檔名 → MIME 映射表修正
- **Azure 環境變數補齊** — `IT_STAFF_EMAILS`、`DOC_INTELLIGENCE_ENDPOINT`、`DOC_INTELLIGENCE_KEY` 透過 az cli 推上 Azure App Service

---

## 2026-04-04

### 改進

- **附件上傳互動確認** — 提單後 10 分鐘內傳檔案，彈出確認卡片讓使用者選擇「附加到 IT 工單」或「AI 解析內容」，不再強制附加
- **IT 工單附件時間限制** — `get_recent_task_gid` 加入 `max_age_minutes=10`，超過 10 分鐘的工單不再攔截附件
- **IT 工單卡片提示** — 提示文字改為「提單後 10 分鐘內可直接貼上或拖曳圖片／檔案」

### 修復

- **圖片附件下載認證** — Teams 圖片 URL 需要 Bot Framework auth token，之前用 aiohttp 裸下載會 401 失敗。改用 httpx + `ITSupportService._get_botframework_token()`（與 IT 附件上傳同一套認證方法）
- **`image/*` 通配符處理** — Teams 傳圖的 content_type 為 `image/*`，加入 magic byte sniffing 自動判斷實際格式（PNG/JPEG/GIF/WebP）
- **跳過 text/html 附件** — Teams 傳圖時附帶的 HTML 預覽不再被當成檔案處理
- **Azure 健康檢查設定** — 設定 `/ping` 為 health check path
- **Azure 環境變數補齊** — 透過 az cli 補上 `ASANA_WORKSPACE_GID`、`ASANA_PROJECT_GID`、`ASANA_ASSIGNEE_GID`、`ASANA_ASSIGNEE_SECTION_GID`、`ALERT_EMAIL`
- **Application Logging 開啟** — 透過 az cli 開啟 filesystem + docker container logging

### 文字修正

- `@my-it` → `@itls`
- `溝通評論` → `處理方式`
- 移除 `GEMINI.md`

---

## 2026-04-03

### 新功能

- **`@itls` 查詢個人 IT 工單** — 使用者輸入 `@itls` 可查看自己的支援單，顯示所有未完成項目 + 最近 3 筆已完成項目（Adaptive Card 呈現）
- **深度健康檢查 `/api/health`** — 9 項元件檢查，供 n8n 外部監控：
  - Bot Framework 認證、Bot Adapter、SMTP、OpenAI API、Asana API、Graph API、環境設定、Asana Webhook 存活、Teams 推播能力
- **Asana Webhook 自動重建** — health check 偵測到 webhook 不存在時，自動呼叫 setup 重新建立
- **n8n Health Check 工作流程** — 每 5 分鐘監控，異常時寄發告警 Email（含各項目狀態明細）
- **Email 完成通知附件圖片** — Asana 任務的附件圖片透過 `cid:` 內嵌到 Email（零暫存），Teams 推播用原始 URL 顯示
- **Email 通知加入需求內容** — 提單確認 Email 包含使用者原始問題描述；完成通知 Email 包含原始提交內容 + Asana 評論（排除知識庫區塊）
- **對話附件 AI 解析** — 使用者在一般對話中傳圖片或檔案，Bot 自動解析內容回覆：
  - 圖片：GPT-4o Vision 描述/分析（支援多張同時送）
  - 文件：擷取文字後 AI 摘要（支援 PDF、Word、Excel、純文字）
  - 有 IT 工單時優先附加到 Asana，無工單時走 AI 解析
- **嚴重錯誤 Email 通知** — 啟動失敗、Bot 未捕獲例外、背景任務崩潰時自動寄信通知管理員（10 分鐘冷卻防爆量）
- **IT 提單完成提示** — `@it` / `@itt` 提單成功後顯示「輸入 @itls 查看工單進度」

### 改進

- **Email 模板全面重新設計** — 深海軍藍 header、table-based layout（Outlook 相容）、卡片式區塊、狀態標籤、評論頭像列表
- **Asana 工單查詢改用 Project Tasks API** — 避免 Search API 的付費方案限制（402 Payment Required）
- **移除使用者通知中的 Asana 連結** — Teams 推播和 Email 完成通知不再顯示「查看任務詳情」（使用者無 Asana 帳號）
- **SMTP 日誌改用 logger** — 移除 print emoji，解決 Windows cp950 編碼錯誤
- **IT Support 模組融入 DI 架構** — `ITSupportService` 改為 constructor injection，支援 mock 測試
- **IT Support 設定集中管理** — 新增 `ITSupportConfig`，Asana GID 等設定從 `os.getenv` 搬到 `AppConfig`
- **全域 logging 統一** — 16 個核心檔案的 `print()` 統一替換為 `logging` 模組（info/warning/error/debug）
- **OpenAI Client 支援多模態** — `chat_completion` type hint 擴充支援 vision 格式（image_url）
- **歡迎選單預設值** — 功能下拉選單預設選第一個選項，不再顯示空白
- **Azure 健康檢查** — 設定 `/ping` 為 health check path，服務異常時自動重啟

### 清理

- **移除死碼** — 刪除 `app_bak.py`、`app copy.py`、root 層 legacy modules（`token_manager.py`、`s3_manager.py`、`graph_api.py`）、未使用的 `check_webhooks.py`、`refresh_webhook.py`
- **移除 `app.py` 死函式** — `get_user_pending_todos()`、`call_openai()` 無引用已移除
- **移除未使用虛擬環境** — 刪除 `myenv`（Linux 環境用，Windows 不需要）
- **移除未使用套件** — `pandas` 從 requirements.txt 移除（專案無 import）
- **移除 GEMINI.md** — 不再需要

### 測試

- **建立 pytest 測試框架** — `pytest.ini`、`tests/` 目錄結構、conftest.py
- **30 個單元測試** — 涵蓋 IT 分類器（12 類）、意圖解析/正規化、Asana notes 解析
- **測試依賴分離** — pytest 移至 `requirements-dev.txt`，不裝到 production
- **Git pre-push hook** — push 前自動跑測試，失敗阻止 push

### 修復

- **Flask 版本釘回 3.0.0** — Quart 0.19.4 依賴 Flask，未釘版導致 Azure 裝 Flask 3.1+ 啟動崩潰
- **Asana GID 預設值恢復** — DI 重構時誤改為空字串，導致 Asana API 400 錯誤
- **helpers.py Graph API 遷移** — `get_user_email()` 改用 DI 容器的 `GraphAPIClient` 取代已刪除的 legacy module

---

## 2026-03-28

### 新功能

- **多知識庫查詢與對話上下文注入** — 支援多個 KB-Vector-Service 知識庫同時查詢，查詢結果注入對話上下文供 AI 參考
- **部門清單 API** — `/api/graph/departments` 從 Graph API 撈出所有部門名稱

---

## 2026-03-27

### 維護

- **統一換行符號** — 新增 `.gitattributes` 規範 LF
- **Webhook 診斷日誌** — 任務完成事件加入詳細 debug logging，協助排查 webhook 不觸發問題

---

## 2026-03-24

### 文件

- **CLAUDE.md 更新** — 改為繁體中文，完善開發指引、架構說明、指令清單、開發進度追蹤

---

## 2026-03-20

### 新功能

- **KB-Vector-Service 知識庫整合** — 提單時自動查詢歷史工單建議，寫入 Asana notes 供 IT 人員參考
- **KB 客戶端** — Azure AD Client Credentials 認證、token 快取、`ask_safe()` 不影響主流程

### 文件

- **INTEGRATION_GUIDE.md** — 新增 KB-Vector-Service API 串接指南

---

## 2026-03-19

### 新功能

- **廣播推播功能** — 支援對全體或指定使用者發送 Teams 推播訊息（Adaptive Card 表單）
- **SharePoint 知識庫** — IT 工單完成後自動存檔到 SharePoint，建立 IT 知識庫
- **自動 Commit 腳本** — `scripts/auto_commit.py`

### 修復

- **GraphAPIClient session 重初始化** — 確保 HTTP session 關閉後能自動重建，避免連線錯誤

---

## 2026-03-16

### 新功能

- **SharePoint 查詢功能** — 新增 SharePoint 知識庫查詢端點

---

## 2026-03-12

### 新功能

- **`@itt` 代理提單** — IT 人員可代他人提交支援單，完成後通知提出人，提單確認 Email CC 給代理人

---

