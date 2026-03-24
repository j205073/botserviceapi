# 出勤功能設計方案 — 加班 / 忘刷 / 請假

> 日期：2026-03-24
> 狀態：規劃中，待確認簽核系統串接方式

---

## 1. 需求概述

讓使用者可以直接在 Teams Bot 中申請：
- **加班** — 簡單表單
- **忘刷卡補登** — 簡單表單
- **請假** — 複雜表單（多假別、餘額驗證、條件式欄位）

所有申請需結合現有簽核系統。

---

## 2. 方案比較

| 方案 | 加班/忘刷 | 請假（驗證多） | 開發成本 | 使用者體驗 |
|------|-----------|---------------|----------|-----------|
| **A. Adaptive Card** | 適合 | 勉強（無動態驗證） | 低 | 中 |
| **B. AI 對話式** | 適合 | 適合但風險高 | 中 | 高（但不可控） |
| **C. 內嵌網頁（Task Module）** | 殺雞用牛刀 | 最適合 | 高 | 最好 |
| **D. 混合式（推薦）** | Card | 網頁 | 中高 | 最佳 |

---

## 3. 推薦方案：D. 混合式架構

### 3.1 簡單流程 → Adaptive Card（加班、忘刷）

跟現在 `@it` 提單一樣的模式，一張卡片搞定：

```
使用者 @overtime / @forgot-punch
  → Adaptive Card（日期、時段、原因）
  → 後端驗證 → 送簽核系統 API
  → 回覆確認卡片
```

欄位少、驗證簡單，Adaptive Card 就夠了。

### 3.2 複雜流程 → Teams Task Module（內嵌網頁）

請假的痛點在於：
- 假別不同 → 欄位不同（病假要附證明、特休要看餘額、婚假要日期區間）
- 即時驗證（餘額夠不夠、日期衝突、代理人是否可用）
- 條件式欄位顯示（Adaptive Card 做不到動態聯動）

**Teams Task Module** 可以在 Teams 裡彈出一個網頁視窗：

```
使用者 @leave
  → Bot 回傳一張卡片，上面有「申請請假」按鈕
  → 按鈕觸發 Task Module（打開內嵌網頁）
  → 網頁：完整表單 + 即時驗證 + 呼叫簽核 API
  → 送出後關閉視窗，Bot 收到回傳結果
  → Bot 推播確認訊息到 Teams
```

### 3.3 AI 扮演的角色（輔助，不是主體）

AI 不適合當「表單引擎」（容易幻覺、不可控），但很適合當 **前導助手**：

```
使用者：「我明天想請假」
  → AI 判斷意圖：請假
  → AI 追問：「請問是什麼假別？特休/病假/事假？」
  → 使用者：「特休，請一天」
  → AI：「你目前特休餘額 8 天，確認要申請 3/25 特休一天嗎？」
  → 使用者：「對」
  → AI 預填表單 → 開啟 Task Module（已填好的表單供確認）
  → 使用者確認送出
```

AI 負責「收集資訊」，網頁表單負責「驗證和送出」，各司其職。

---

## 4. 技術架構

### 4.1 整體流程

```
Teams 使用者
  │
  ├─ @overtime / @forgot-punch
  │    → Adaptive Card 表單
  │    → AttendanceService.submit_overtime()
  │    → 簽核系統 API
  │
  ├─ @leave
  │    → AI 對話收集資訊（假別、日期、天數）
  │    → 查詢餘額（簽核系統 API）
  │    → 產生 Task Module 按鈕（含預填參數）
  │    → 內嵌網頁：表單確認 + 即時驗證
  │    → 送出 → 簽核系統 API
  │    → Bot 推播結果
  │
  └─ 自然語言觸發（選配，搭配 intent analysis）
       「我明天要請特休」→ 自動辨識為 @leave 流程
```

### 4.2 新增檔案結構

```
features/
└── attendance/
    ├── service.py              # AttendanceService：加班/忘刷/請假主流程
    ├── approval_client.py      # 簽核系統 API 客戶端
    ├── cards.py                # Adaptive Card（加班、忘刷、請假入口）
    ├── leave_validator.py      # 請假驗證邏輯（餘額、衝突、規則）
    └── web/                    # Task Module 內嵌網頁
        ├── leave_form.html     # 請假表單頁面
        ├── leave_form.js       # 前端驗證 + Teams SDK 整合
        └── api.py              # 表單後端 API（Quart routes）
```

### 4.3 新增 Bot 指令

| 指令 | 功能 |
|------|------|
| `@overtime` | 加班申請（Adaptive Card） |
| `@forgot-punch` | 忘刷卡補登（Adaptive Card） |
| `@leave` | 請假申請（AI 對話 + Task Module） |
| `@my-leave` | 查詢個人假勤餘額與申請紀錄 |

---

## 5. 待確認事項

在動手實作之前需要釐清：

| # | 問題 | 影響範圍 |
|---|------|----------|
| 1 | **簽核系統有 API 嗎？** 還是只有網頁介面？ | 決定 `approval_client.py` 串接方式（API / RPA / DB 直連） |
| 2 | **假別規則從哪來？** 簽核系統回傳，還是要自己寫驗證邏輯？ | 決定 `leave_validator.py` 複雜度 |
| 3 | **餘額查詢** — 簽核系統能即時查嗎？ | 決定 AI 對話中能否即時告知餘額 |
| 4 | **審批流程** — 送出後走簽核系統 workflow，還是要自己實作？ | 決定是否需要審批通知推播 |
| 5 | **簽核系統的認證方式** — API Key / OAuth / LDAP？ | 決定認證整合方式 |
| 6 | **代理人機制** — 請假時是否需要指定職務代理人？ | 影響表單欄位設計 |

---

## 6. 開發階段建議

### Phase 1：加班 + 忘刷（Adaptive Card）
- 串接簽核系統 API
- 建立 `AttendanceService` + `approval_client.py`
- 新增 `@overtime`、`@forgot-punch` 指令
- 預估：確認 API 規格後 2-3 天

### Phase 2：請假（Task Module 內嵌網頁）
- 建立請假表單網頁（HTML/JS）
- 整合 Teams JavaScript SDK（Task Module 開啟/關閉/回傳）
- 實作 `leave_validator.py` 驗證邏輯
- 預估：1-2 週

### Phase 3：AI 對話式輔助（選配）
- 新增請假意圖辨識
- AI 引導收集資訊 → 預填表單
- 自然語言觸發（「我想請假」自動進入流程）
- 預估：3-5 天

---

*本文件最後更新：2026-03-24*
