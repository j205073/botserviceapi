# 階段 2：自然語言 Skill 架構

> 狀態：🔲 待開發
> 建立日期：2026-04-08

## 目標

將 Bot 從指令式操作（`@it`、`@add`）進化為自然語言驅動，使用者不需記指令，直接說需求即可自動路由到對應功能。

## 架構設計

採用 **SKILL.md + Handler** 的 plugin 模式，參考 Claude Code 的 skill 機制：

```
features/skills/
├── registry.py          # 自動掃描、註冊所有 skill
├── base.py              # BaseSkill 抽象類別
├── leave/
│   ├── SKILL.md         # skill 定義（直接作為 GPT prompt）
│   └── handler.py       # LeaveSkill(BaseSkill)
├── overtime/
│   ├── SKILL.md
│   └── handler.py
├── knowledge/
│   ├── SKILL.md
│   └── handler.py
└── it_support/
    ├── SKILL.md
    └── handler.py       # 包裝現有 IT 提單邏輯
```

## 核心元件

### 1. SKILL.md（Skill 定義檔）

每個 skill 用 Markdown 描述，frontmatter 放元資料，內文直接拼入 GPT prompt：

```markdown
---
name: leave
display_name: 請假申請
category: form
---

# 請假申請

## 觸發時機
當使用者表達想要請假、休息、不上班、調休等意圖時觸發。

## 範例
- 我明天想請特休
- 下週一到週三請病假
- 後天身體不舒服想休息

## 需要擷取的欄位
- leave_type: 假別（特休/病假/事假/喪假/婚假/公假）
- start_date: 開始日期
- end_date: 結束日期
- reason: 請假原因

## 處理流程
1. 從使用者訊息擷取上述欄位
2. 顯示 Adaptive Card 讓使用者確認/補填
3. 呼叫 Portal EIP API 建立請假單
4. 回傳申請結果
```

### 2. BaseSkill 抽象類別

```python
class BaseSkill(ABC):
    def __init__(self, meta: dict, markdown_content: str):
        self.name = meta["name"]
        self.display_name = meta["display_name"]
        self.category = meta.get("category", self.name)
        self.markdown_content = markdown_content

    @abstractmethod
    async def handle(self, turn_context, user_info, intent_result) -> None:
        """執行 skill 主流程"""

    def build_extract_prompt(self, user_message: str) -> str:
        """根據 SKILL.md 中的欄位定義，動態產生擷取 prompt"""
```

### 3. SkillRegistry 自動發現

```python
class SkillRegistry:
    def discover(self, skills_dir: str):
        """掃描 features/skills/ 下所有 SKILL.md，自動註冊"""

    def build_intent_prompt(self) -> str:
        """把所有 SKILL.md 內容直接拼進 GPT intent prompt"""

    def get_skill(self, category: str) -> BaseSkill | None:
        """根據 category 取得對應 skill"""
```

### 4. 路由自動分派（取代 if/elif）

```python
async def _handle_intent_based_response(self, turn_context, user_info):
    intent_result = await self.intent_service.analyze_intent(user_info.message_text)

    skill = self.skill_registry.get_skill(intent_result.category)
    if skill:
        await skill.handle(turn_context, user_info, intent_result)
    else:
        await self._handle_direct_openai_response(turn_context, user_info)
```

## 完整流程

```
使用者：「我明天想請特休一天」
    │
    ▼
SkillRegistry.build_intent_prompt()
    → 動態組合所有 SKILL.md 給 GPT 做意圖判斷
    │
    ▼
IntentService.analyze_intent()
    → GPT 回傳 {category: "leave", action: "apply"}
    │
    ▼
SkillRegistry.get_skill("leave") → LeaveSkill
    │
    ▼
LeaveSkill.handle()
    ├─ GPT 擷取欄位 → {leave_type: "特休", start_date: "2026-04-09", days: 1}
    ├─ 產生 Adaptive Card（預填欄位）
    ├─ 使用者確認送出
    └─ 呼叫 Portal EIP API
```

## 實作順序

1. 建立 `BaseSkill` + `SkillRegistry` 骨架
2. 把現有 `todo`、`meeting` 包裝成 skill（驗證架構可行）
3. 改造 `IntentService` 使用動態 prompt
4. 改造 `message_handler` 路由為自動分派
5. 包裝現有 `it_support`（IT 提單）為 skill — `@it` 指令 + 自然語言雙入口
6. 新增 `leave`（請假）skill — 串接 Portal EIP API
7. 新增 `overtime`（加班）skill — 串接 Portal EIP API
8. 新增 `knowledge`（知識庫）skill — 包裝現有 KB 查詢

## 設計重點

- **SKILL.md 即 prompt**：不需要中間轉換，寫什麼 GPT 就看什麼
- **新增功能 = 新增資料夾**：放 SKILL.md + handler.py，零設定
- **意圖判斷靠 GPT 語意理解**：不是關鍵字比對，使用者用任何方式表達都能識別
- **漸進式遷移**：現有 `@指令` 保持不變，自然語言是額外入口

## IT 提單 Skill 化

現有 `features/it_support/` 包裝為 skill，不重寫邏輯：

```
features/skills/it_support/
├── SKILL.md         # IT 問題觸發條件與範例
└── handler.py       # 薄包裝，呼叫現有 service.py
```

SKILL.md 範例：

```markdown
---
name: it_support
display_name: IT 支援提單
category: it
---

# IT 支援提單

## 觸發時機
當使用者描述電腦、網路、印表機、系統帳號、軟體安裝等 IT 相關問題時觸發。

## 範例
- 我的電腦開不了機
- VPN 連不上
- 印表機一直卡紙
- 幫我開一個 ERP 帳號
- 信箱收不到信

## 處理流程
1. 從訊息擷取問題描述
2. **KB 自助建議**：先查知識庫，若有匹配結果，回覆使用者「您可以先試試：...」
3. 使用者仍需提單 → 顯示 IT 提單 Adaptive Card（預填描述）
4. AI 分類 + 知識庫查詢結果寫入 Asana notes 供 IT 人員參考
5. 建立 Asana 任務 + Email 通知
```

效果：`@it` 指令和自然語言是**兩個入口、同一個出口**，零重複邏輯。

## KB 自助建議（IT 提單前置）

> 狀態：🔲 待開發（2026-04-09 規劃）

### 現狀
KB 查詢結果只寫入 Asana notes 給 IT 人員看，使用者看不到。

### 改進
提單送出前，先將 KB 結果回覆給使用者，讓使用者有機會自行解決：

```
使用者：「VPN 連不上」
    │
    ▼
KB 查詢 → 有匹配結果
    │
    ▼
Bot 回覆：
  「📚 根據知識庫，您可以先試試：
    1. 確認 VPN 用戶端版本是否為最新
    2. 重啟網路介面卡
    3. ...
    
   如果仍無法解決，請點擊下方按鈕提交 IT 工單。」
  [提交 IT 工單] ← Adaptive Card 按鈕
    │
    ├─ 使用者自行解決 → 結束，不產生工單
    └─ 使用者點擊提單 → 走現有 IT 提單流程
```

### 效益
- 減少 IT 人員處理已知問題的工單量
- 使用者能更快得到解答，不用等 IT 回覆
- KB 結果同時寫入 Asana notes，IT 人員接單時仍可參考

## 相依項目

- Portal EIP API（請假/加班單）需確認 endpoint 與認證方式
- 現有 `ENABLE_AI_INTENT_ANALYSIS` 開關繼續沿用
