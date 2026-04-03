# CHANGELOG

TR GPT Bot 變更紀錄（2026-03-01 ~ 2026-04-03）

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

### 改進

- **Email 模板全面重新設計** — 深海軍藍 header、table-based layout（Outlook 相容）、卡片式區塊、狀態標籤、評論頭像列表
- **Asana 工單查詢改用 Project Tasks API** — 避免 Search API 的付費方案限制（402 Payment Required）
- **移除使用者通知中的 Asana 連結** — Teams 推播和 Email 完成通知不再顯示「查看任務詳情」（使用者無 Asana 帳號）
- **SMTP 日誌改用 logger** — 移除 print emoji，解決 Windows cp950 編碼錯誤

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

## 未提交（本地修改中）

以下功能已開發完成，尚未 commit：

- **健康檢查擴充至 9 項** — 新增 OpenAI API、Graph API、環境設定、Asana Webhook、Teams 推播檢查
- **Asana Webhook 自動重建** — health check 發現 webhook 不存在時自動重建
- **附件圖片內嵌 Email** — Asana 任務附件圖片透過 cid: 內嵌到完成通知 Email
- **n8n 工作流程更新** — 修正 URL、優化 Email 模板、動態列出各項檢查結果
