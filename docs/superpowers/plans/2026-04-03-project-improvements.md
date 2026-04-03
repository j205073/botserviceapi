# TR GPT 專案改善計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依序完成專案體質改善（清理、測試基礎建設、DI 重構、logging 統一）及新功能（圖片解析），讓後續開發更穩定高效。

**Architecture:** 先做不影響功能的清理與基礎建設，再重構 IT Support 模組融入 DI，接著統一 logging，最後加入圖片解析新功能。每個 Task 獨立可交付、可驗證。

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio, Quart, Bot Framework, Azure OpenAI (GPT-4o vision)

---

## 改動總覽與順序

| 順序 | Task | 類型 | 風險 | 理由 |
|------|------|------|------|------|
| 1 | 清理死碼與重複檔案 | 清理 | 低 | 最低風險，減少雜訊，後續改動不會碰到舊檔案 |
| 2 | 清理 requirements.txt | 清理 | 低 | 移除未用套件、補齊缺漏、加入 pytest |
| 3 | 建立測試基礎建設 | 基建 | 低 | 不改產品程式碼，只建立 pytest 框架與 conftest |
| 4 | 為純邏輯元件寫測試 | 測試 | 無 | ITIntentClassifier、intent 解析、reporter 解析等零依賴測試 |
| 5 | IT Support 模組融入 DI | 重構 | 中 | 讓 ITSupportService 可注入依賴，為 mock 測試鋪路 |
| 6 | 為 IT Support 核心流程寫測試 | 測試 | 低 | 有了 DI 就能 mock，驗證 submit_issue 等主流程 |
| 7 | 統一 logging（print → logging） | 重構 | 低 | 全域搜尋替換，不改邏輯 |
| 8 | OpenAI Client 支援多模態 | 功能 | 中 | 擴充 chat_completion 支援 image content |
| 9 | Teams 圖片解析功能 | 功能 | 中 | 使用者貼圖 → GPT-4o 解析 → 回覆內容描述 |

---

## Task 1: 清理死碼與重複檔案

**Files:**
- Delete: `app copy.py`
- Delete: `app_bak.py`
- Delete: `token_manager.py` (root level, superseded by `infrastructure/external/token_manager.py`)
- Delete: `s3_manager.py` (root level, superseded by `infrastructure/external/s3_client.py`)
- Delete: `graph_api.py` (root level, superseded by `infrastructure/external/graph_api_client.py`)

- [ ] **Step 1: 確認這些檔案沒有被現行程式碼 import**

```bash
# 在專案根目錄搜尋，排除 app_bak.py 自身和 venv
grep -r "from app_bak\|import app_bak\|from app.copy\|from token_manager\|import token_manager\|from s3_manager\|import s3_manager\|from graph_api\|import graph_api" --include="*.py" . | grep -v venv | grep -v app_bak.py | grep -v "app copy.py"
```

Expected: 無結果（如果有，先不刪該檔案）

- [ ] **Step 2: 刪除確認無引用的檔案**

```bash
git rm "app copy.py"
git rm app_bak.py
git rm token_manager.py
git rm s3_manager.py
git rm graph_api.py
```

- [ ] **Step 3: 清理 app.py 中未使用的全域變數**

在 `app.py` 中移除以下未被任何現行程式碼讀取的全域變數（保留 `user_conversation_refs` 和 `user_display_names`，因為 `message_handler.py:162` 有 import）：
- `user_model_preferences` dict（如果 message_handler.py 有引用則保留）
- `MODEL_INFO` dict（如果 message_handler.py 有引用則保留）
- `get_user_pending_todos()` 函式
- `call_openai()` 函式

先 grep 確認引用情況再決定刪除範圍。

- [ ] **Step 4: 驗證應用程式仍能啟動**

```bash
python -c "from app import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove dead code and duplicate files (app_bak, app copy, legacy root modules)"
```

---

## Task 2: 清理 requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 移除未使用的 flask，加入缺漏的 msal，加入測試依賴**

```
# 移除這行：
flask==3.0.0

# 新增：
msal>=1.24.0
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: 統一版本釘選策略為 ~=（相容版本）**

將所有 `>=` 改為具體版本釘選（`==` 或 `~=`），避免不可控升級。例如：
```
# 改前
openai>=1.0.0
boto3>=1.26.0

# 改後（使用當前安裝的版本）
openai~=1.68.0
boto3~=1.35.0
```

執行 `pip freeze` 取得當前版本號。

- [ ] **Step 3: 移除 commented-out 的 asyncio**

刪除 `# asyncio==3.4.3` 這行。

- [ ] **Step 4: 驗證安裝**

```bash
pip install -r requirements.txt
```

Expected: 無錯誤

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "chore: clean up requirements.txt - remove unused flask, pin versions, add test deps"
```

---

## Task 3: 建立測試基礎建設

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/features/__init__.py`
- Create: `tests/features/it_support/__init__.py`
- Create: `tests/domain/__init__.py`
- Create: `tests/domain/services/__init__.py`
- Create: `pytest.ini`

- [ ] **Step 1: 建立 pytest.ini**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

- [ ] **Step 2: 建立 conftest.py 與目錄結構**

```python
# tests/conftest.py
"""Shared test fixtures for TR GPT."""

import sys
import os
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
```

```python
# tests/__init__.py, tests/features/__init__.py,
# tests/features/it_support/__init__.py,
# tests/domain/__init__.py, tests/domain/services/__init__.py
# 全部是空檔案
```

- [ ] **Step 3: 建立一個 smoke test 確認框架能跑**

```python
# tests/test_smoke.py
def test_import_app():
    """Verify the app module can be imported without errors."""
    import app
    assert hasattr(app, "app")
```

- [ ] **Step 4: 執行測試**

```bash
pytest tests/test_smoke.py -v
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/ pytest.ini
git commit -m "chore: set up pytest infrastructure with smoke test"
```

---

## Task 4: 為純邏輯元件寫測試（不需 DI 改動）

**Files:**
- Create: `tests/features/it_support/test_intent_classifier.py`
- Create: `tests/domain/services/test_intent_service_parsing.py`
- Create: `tests/features/it_support/test_service_parsing.py`

### 4A: ITIntentClassifier 測試

- [ ] **Step 1: 寫分類器測試**

```python
# tests/features/it_support/test_intent_classifier.py
import pytest
from features.it_support.intent_classifier import ITIntentClassifier


@pytest.fixture
def classifier():
    return ITIntentClassifier()


class TestITIntentClassifier:
    def test_empty_input_returns_other(self, classifier):
        code, label = classifier.classify("")
        assert code == "other"

    def test_none_input_returns_other(self, classifier):
        code, label = classifier.classify(None)
        assert code == "other"

    def test_printer_keywords(self, classifier):
        code, _ = classifier.classify("印表機卡紙無法列印")
        assert code == "printer"

    def test_network_keywords(self, classifier):
        code, _ = classifier.classify("VPN 連不上公司網路")
        assert code in ("network", "vpn_remote")

    def test_account_keywords(self, classifier):
        code, _ = classifier.classify("帳號被鎖定無法登入")
        assert code == "account_access"

    def test_hardware_keywords(self, classifier):
        code, _ = classifier.classify("筆電螢幕破裂")
        assert code == "hardware"

    def test_onboarding_keywords(self, classifier):
        code, _ = classifier.classify("新人報到需要開通帳號")
        assert code == "onboarding"

    def test_unrelated_text_returns_other(self, classifier):
        code, _ = classifier.classify("今天天氣不錯想去散步")
        assert code == "other"

    def test_label_is_nonempty_string(self, classifier):
        _, label = classifier.classify("印表機")
        assert isinstance(label, str)
        assert len(label) > 0

    def test_all_taxonomy_codes_have_labels(self, classifier):
        for cat in classifier.categories:
            code = cat["code"]
            label = classifier._label_for(code)
            assert label and label != code or code == "other"
```

- [ ] **Step 2: 執行測試**

```bash
pytest tests/features/it_support/test_intent_classifier.py -v
```

Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/features/it_support/test_intent_classifier.py
git commit -m "test: add ITIntentClassifier unit tests covering all 12 categories"
```

### 4B: IntentService 回應解析測試

- [ ] **Step 4: 寫 intent 解析測試（不需呼叫 OpenAI）**

```python
# tests/domain/services/test_intent_service_parsing.py
import pytest
from unittest.mock import MagicMock
from domain.services.intent_service import IntentService, IntentResult


@pytest.fixture
def intent_service():
    mock_config = MagicMock()
    mock_config.openai.use_azure = False
    mock_config.openai.intent_model = "gpt-4o-mini"
    mock_openai = MagicMock()
    return IntentService(config=mock_config, openai_client=mock_openai)


class TestIntentResponseParsing:
    def test_parse_valid_json(self, intent_service):
        raw = '{"is_existing_feature": true, "category": "todo", "action": "add", "content": "買牛奶", "confidence": 0.9, "reason": "明確待辦"}'
        result = intent_service._parse_intent_response(raw)
        assert result.is_existing_feature is True
        assert result.category == "todo"
        assert result.action == "add"
        assert result.confidence == 0.9

    def test_parse_json_with_markdown_wrapper(self, intent_service):
        raw = '```json\n{"is_existing_feature": true, "category": "meeting", "action": "book", "content": "", "confidence": 0.85}\n```'
        result = intent_service._parse_intent_response(raw)
        assert result.category == "meeting"

    def test_parse_empty_response(self, intent_service):
        result = intent_service._parse_intent_response("")
        assert result.is_existing_feature is False
        assert result.confidence == 0.0

    def test_parse_garbage_response(self, intent_service):
        result = intent_service._parse_intent_response("這完全不是JSON")
        assert result.is_existing_feature is False

    def test_normalize_invalid_category(self, intent_service):
        result = IntentResult(
            is_existing_feature=True,
            category="weather",
            action="query",
            content="",
            confidence=0.9,
        )
        normalized = intent_service._normalize_intent_result(result)
        assert normalized.is_existing_feature is False
        assert normalized.confidence == 0.0

    def test_normalize_azure_blocks_model_category(self, intent_service):
        intent_service.config.openai.use_azure = True
        result = IntentResult(
            is_existing_feature=True,
            category="model",
            action="select",
            content="gpt-4o",
            confidence=0.9,
        )
        normalized = intent_service._normalize_intent_result(result)
        assert normalized.is_existing_feature is False
```

- [ ] **Step 5: 執行測試**

```bash
pytest tests/domain/services/test_intent_service_parsing.py -v
```

Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add tests/domain/services/test_intent_service_parsing.py
git commit -m "test: add IntentService response parsing and normalization tests"
```

### 4C: reporter 解析測試

- [ ] **Step 7: 寫 _parse_reporter_from_notes 測試**

```python
# tests/features/it_support/test_service_parsing.py
import pytest
from features.it_support.service import ITSupportService


class TestParseReporterFromNotes:
    """Test _parse_reporter_from_notes without needing DI — we only call the pure parsing method."""

    def setup_method(self):
        # ITSupportService.__init__ reads env vars; we patch minimally
        import os
        os.environ.setdefault("ASANA_ACCESS_TOKEN", "fake")
        os.environ.setdefault("SMTP_HOST", "localhost")
        self.svc = ITSupportService()

    def test_parse_standard_notes(self):
        notes = """【IT 支援單 TRQ-20260403-001】
提出人: 王小明
Email: wang@rinnai.com.tw
部門: 資訊課"""
        result = self.svc._parse_reporter_from_notes(notes)
        assert result is not None
        assert result["email"] == "wang@rinnai.com.tw"

    def test_parse_notes_with_proxy_reporter(self):
        notes = """【IT 支援單 TRQ-20260403-002】
提出人: 李大華
Email: lee@rinnai.com.tw
代提人: 張小明 (chang@rinnai.com.tw)"""
        result = self.svc._parse_reporter_from_notes(notes)
        assert result is not None
        assert "email" in result

    def test_parse_empty_notes(self):
        result = self.svc._parse_reporter_from_notes("")
        assert result is None

    def test_parse_notes_without_email(self):
        notes = "這是一般描述，沒有 IT 支援單格式"
        result = self.svc._parse_reporter_from_notes(notes)
        assert result is None
```

- [ ] **Step 8: 執行測試**

```bash
pytest tests/features/it_support/test_service_parsing.py -v
```

Expected: 全部 PASS

- [ ] **Step 9: Commit**

```bash
git add tests/features/it_support/test_service_parsing.py
git commit -m "test: add ITSupportService notes parsing tests"
```

---

## Task 5: IT Support 模組融入 DI

**Files:**
- Modify: `features/it_support/service.py` (constructor signature)
- Modify: `config/settings.py` (add ITSupportConfig dataclass)
- Modify: `core/dependencies.py` (update registration)

- [ ] **Step 1: 在 AppConfig 新增 IT Support 設定區塊**

在 `config/settings.py` 新增：

```python
@dataclass
class ITSupportConfig:
    """IT Support 相關設定"""
    enable_ai_analysis: bool
    analysis_model: str
    workspace_gid: str
    project_gid: str
    assignee_gid: str
    assignee_section_gid: str
    onboarding_assignee_email: str
    priority_tag_map: dict

    @classmethod
    def from_env(cls) -> "ITSupportConfig":
        return cls(
            enable_ai_analysis=os.getenv("ENABLE_IT_AI_ANALYSIS", "false").strip().lower() == "true",
            analysis_model=os.getenv("IT_ANALYSIS_MODEL", "gpt-5-nano").strip(),
            workspace_gid=os.getenv("ASANA_WORKSPACE_GID", ""),
            project_gid=os.getenv("ASANA_PROJECT_GID", ""),
            assignee_gid=os.getenv("ASANA_ASSIGNEE_GID", ""),
            assignee_section_gid=os.getenv("ASANA_ASSIGNEE_SECTION_GID", ""),
            onboarding_assignee_email=os.getenv("ASANA_ONBOARDING_ASSIGNEE_EMAIL", "").strip(),
            priority_tag_map={
                "P1": os.getenv("ASANA_TAG_P1", "").strip(),
                "P2": os.getenv("ASANA_TAG_P2", "").strip(),
                "P3": os.getenv("ASANA_TAG_P3", "").strip(),
                "P4": os.getenv("ASANA_TAG_P4", "").strip(),
            },
        )
```

在 `AppConfig` 的 `from_env()` 中加入：
```python
it_support=ITSupportConfig.from_env(),
```

- [ ] **Step 2: 重構 ITSupportService constructor 接受注入**

修改 `features/it_support/service.py`：

```python
class ITSupportService:
    def __init__(
        self,
        asana: AsanaClient = None,
        classifier: ITIntentClassifier = None,
        email_notifier: EmailNotifier = None,
        kb_client: KBVectorClient = None,
        config: "ITSupportConfig" = None,
    ):
        # 向後相容：未提供則自行建立（過渡期）
        self.asana = asana or AsanaClient()
        self.classifier = classifier or ITIntentClassifier()
        self.email_notifier = email_notifier or EmailNotifier()
        self.kb_client = kb_client or KBVectorClient()

        if config:
            self.enable_ai_analysis = config.enable_ai_analysis
            self.analysis_model = config.analysis_model
            self.workspace_gid = config.workspace_gid
            self.project_gid = config.project_gid
            self.assignee_gid = config.assignee_gid
            self.assignee_section_gid = config.assignee_section_gid
            self.onboarding_assignee_email = config.onboarding_assignee_email
            self.priority_tag_map = config.priority_tag_map
        else:
            # 保留原有 os.getenv fallback
            self.enable_ai_analysis = os.getenv("ENABLE_IT_AI_ANALYSIS", "false").strip().lower() == "true"
            # ... (保留現有的 os.getenv 邏輯作為 fallback)

        self._taxonomy = self.classifier.categories
        self._recent_task_by_user: dict[str, dict] = {}
        self._task_to_reporter: dict[str, dict] = {}
        self._bf_token_cache: dict[str, Any] = {}
        self._webhook_secret: Optional[str] = None
```

- [ ] **Step 3: 更新 DI 註冊**

在 `core/dependencies.py` 中更新 `ITSupportService` 的註冊方式，改用 factory：

```python
def _register_it_support(container):
    from features.it_support.service import ITSupportService
    from features.it_support.asana_client import AsanaClient
    from features.it_support.intent_classifier import ITIntentClassifier
    from features.it_support.email_notifier import EmailNotifier
    from features.it_support.kb_client import KBVectorClient

    config = container.get(AppConfig)

    container.register_factory(
        ITSupportService,
        lambda: ITSupportService(
            asana=AsanaClient(),
            classifier=ITIntentClassifier(),
            email_notifier=EmailNotifier(),
            kb_client=KBVectorClient(),
            config=config.it_support,
        ),
        lifetime="singleton",
    )
```

- [ ] **Step 4: 驗證應用程式仍能啟動**

```bash
python -c "from app import app; print('OK')"
```

- [ ] **Step 5: 執行所有現有測試**

```bash
pytest tests/ -v
```

Expected: 全部 PASS（Task 4 的測試不應被影響）

- [ ] **Step 6: Commit**

```bash
git add config/settings.py features/it_support/service.py core/dependencies.py
git commit -m "refactor: integrate ITSupportService into DI container with injectable dependencies"
```

---

## Task 6: 為 IT Support 核心流程寫 mock 測試

**Files:**
- Create: `tests/features/it_support/test_service_submit.py`
- Create: `tests/features/it_support/conftest.py`

- [ ] **Step 1: 建立共用 fixtures**

```python
# tests/features/it_support/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from features.it_support.service import ITSupportService
from features.it_support.asana_client import AsanaClient
from features.it_support.intent_classifier import ITIntentClassifier
from features.it_support.email_notifier import EmailNotifier
from features.it_support.kb_client import KBVectorClient


@pytest.fixture
def mock_asana():
    client = AsyncMock(spec=AsanaClient)
    client.create_task.return_value = {
        "gid": "12345",
        "name": "Test Task",
        "permalink_url": "https://app.asana.com/0/0/12345",
    }
    client.get_user_gid_by_email.return_value = "user_gid_123"
    return client


@pytest.fixture
def mock_email():
    notifier = AsyncMock(spec=EmailNotifier)
    notifier.send_submission_notification.return_value = True
    return notifier


@pytest.fixture
def mock_kb():
    client = AsyncMock(spec=KBVectorClient)
    client.ask_safe.return_value = {"answer": "建議重開機", "source": "KB-001"}
    return client


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.enable_ai_analysis = False
    config.analysis_model = "gpt-4o-mini"
    config.workspace_gid = "ws_123"
    config.project_gid = "proj_123"
    config.assignee_gid = "assignee_123"
    config.assignee_section_gid = "section_123"
    config.onboarding_assignee_email = ""
    config.priority_tag_map = {"P1": "", "P2": "", "P3": "", "P4": ""}
    return config


@pytest.fixture
def it_service(mock_asana, mock_email, mock_kb, mock_config):
    return ITSupportService(
        asana=mock_asana,
        classifier=ITIntentClassifier(),
        email_notifier=mock_email,
        kb_client=mock_kb,
        config=mock_config,
    )
```

- [ ] **Step 2: 寫 submit_issue 測試**

```python
# tests/features/it_support/test_service_submit.py
import pytest
from unittest.mock import AsyncMock


class TestSubmitIssue:
    @pytest.mark.asyncio
    async def test_submit_creates_asana_task(self, it_service, mock_asana):
        result = await it_service.submit_issue(
            form={"description": "電腦無法開機", "category": "hardware", "priority": "P2"},
            reporter_name="王小明",
            reporter_email="wang@rinnai.com.tw",
        )
        assert result["success"] is True
        mock_asana.create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_sends_email_notification(self, it_service, mock_email):
        result = await it_service.submit_issue(
            form={"description": "印表機故障", "category": "printer", "priority": "P3"},
            reporter_name="李小華",
            reporter_email="lee@rinnai.com.tw",
        )
        assert result["success"] is True
        mock_email.send_submission_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_queries_knowledge_base(self, it_service, mock_kb):
        result = await it_service.submit_issue(
            form={"description": "VPN 無法連線", "category": "vpn_remote", "priority": "P2"},
            reporter_name="張大明",
            reporter_email="chang@rinnai.com.tw",
        )
        assert result["success"] is True
        mock_kb.ask_safe.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_handles_asana_failure_gracefully(self, it_service, mock_asana):
        mock_asana.create_task.side_effect = Exception("Asana API error")
        result = await it_service.submit_issue(
            form={"description": "測試", "category": "other", "priority": "P4"},
            reporter_name="Test",
            reporter_email="test@rinnai.com.tw",
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_submit_with_proxy_reporter(self, it_service, mock_asana):
        result = await it_service.submit_issue(
            form={"description": "新人需要帳號", "category": "onboarding", "priority": "P3"},
            reporter_name="王小明",
            reporter_email="wang@rinnai.com.tw",
            requester_email="newguy@rinnai.com.tw",
        )
        assert result["success"] is True
```

- [ ] **Step 3: 執行測試**

```bash
pytest tests/features/it_support/test_service_submit.py -v
```

Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add tests/features/it_support/
git commit -m "test: add ITSupportService submit_issue tests with mocked dependencies"
```

---

## Task 7: 統一 logging（print → logging）

**Files:**
- Modify: 所有使用 `print()` 的 `.py` 檔案（約 29 個檔案、327 處）

- [ ] **Step 1: 列出所有需要修改的檔案**

```bash
grep -rn "print(" --include="*.py" . | grep -v venv | grep -v app_bak | grep -v "app copy" | grep -v test_ | grep -v __pycache__ | cut -d: -f1 | sort -u
```

- [ ] **Step 2: 逐檔案替換（每個檔案加 logger 並替換 print）**

每個檔案頂部加入（如果還沒有）：
```python
import logging
logger = logging.getLogger(__name__)
```

替換規則：
| print 模式 | 替換為 |
|-----------|--------|
| `print(f"✅ ...")` | `logger.info(...)` |
| `print(f"❌ ...")` | `logger.error(...)` |
| `print(f"⚠️ ...")` | `logger.warning(...)` |
| `print(f"🔄 ...")` / `print(f"📤 ...")` | `logger.info(...)` |
| `print(f"🤖 ...")` / `print(f"📝 ...")` | `logger.debug(...)` |

移除 emoji 前綴（logging 不需要），保留有意義的訊息文字。

優先處理核心檔案：
1. `app.py`
2. `infrastructure/external/openai_client.py`
3. `infrastructure/external/graph_api_client.py`
4. `infrastructure/external/s3_client.py`
5. `infrastructure/external/token_manager.py`
6. `infrastructure/bot/bot_adapter.py`
7. `domain/services/*.py`
8. `application/services/application_service.py`
9. `presentation/bot/message_handler.py`（已有 logging，檢查是否有殘留 print）
10. `core/dependencies.py`

- [ ] **Step 3: 執行所有測試確認無破壞**

```bash
pytest tests/ -v
```

- [ ] **Step 4: 驗證應用程式仍能啟動**

```bash
python -c "from app import app; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: replace all print() calls with structured logging module"
```

---

## Task 8: OpenAI Client 支援多模態（Vision）

**Files:**
- Modify: `infrastructure/external/openai_client.py`

- [ ] **Step 1: 擴充 chat_completion 支援多模態 messages**

修改 `infrastructure/external/openai_client.py` 中 `chat_completion` 的 type hint：

```python
async def chat_completion(
    self,
    messages: List[Dict[str, Any]],  # 改 str -> Any，支援 content 為 list
    **kwargs,
) -> str:
```

這樣就能接受 vision 格式的 messages：
```python
[{
    "role": "user",
    "content": [
        {"type": "text", "text": "描述這張圖片"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
}]
```

不需要改方法內部邏輯，因為 OpenAI SDK 本身已支援這個格式，只是 type hint 限制了。

- [ ] **Step 2: 驗證現有對話功能不受影響**

```bash
pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
git add infrastructure/external/openai_client.py
git commit -m "feat: extend OpenAI client to support multimodal (vision) message format"
```

---

## Task 9: Teams 圖片解析功能

**Files:**
- Modify: `presentation/bot/message_handler.py` (新增 `_handle_image_analysis`)
- Modify: `application/dtos/bot_dtos.py` (可選：新增 attachment 欄位)

- [ ] **Step 1: 在 message_handler.py 新增圖片解析方法**

```python
async def _handle_image_analysis(
    self, turn_context: TurnContext, user_info: BotInteractionDTO, image_bytes: bytes, mime_type: str
) -> None:
    """使用 GPT-4o Vision 解析使用者貼上的圖片"""
    import base64

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64}"

    # 取得使用者附帶的文字（如果有）
    user_text = (user_info.message_text or "").strip()
    prompt = user_text if user_text else "請描述這張圖片的內容，如果是錯誤截圖請說明可能的問題和建議解法。"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]

    try:
        # 使用支援 vision 的模型
        from infrastructure.external.openai_client import OpenAIClient
        openai_client: OpenAIClient = self.conversation_service.openai_client
        response = await openai_client.chat_completion(
            messages=messages,
            model="gpt-4o",
            max_tokens=1000,
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=response)
        )
    except Exception:
        self.logger.exception("圖片解析失敗")
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text="❌ 圖片解析失敗，請稍後再試。")
        )
```

- [ ] **Step 2: 修改 handle_message 的附件處理流程**

在 `handle_message` 方法中，修改 lines 90-105 的邏輯：

```python
# 若含有附件
if turn_context.activity.attachments:
    # 先嘗試附加到 IT 工單（現有邏輯）
    handled = await self._try_attach_images(turn_context, user_info)
    if handled:
        return

    # 如果沒有最近的 IT 單，改走圖片解析
    image_data = await self._extract_first_image(turn_context)
    if image_data:
        await self._handle_image_analysis(
            turn_context, user_info,
            image_data["bytes"], image_data["mime_type"],
        )
        return
```

- [ ] **Step 3: 新增 _extract_first_image 輔助方法**

```python
async def _extract_first_image(self, turn_context: TurnContext) -> Optional[dict]:
    """從 attachments 中提取第一張圖片的 bytes 和 mime_type"""
    import base64
    import aiohttp

    for att in (turn_context.activity.attachments or []):
        ctype = (getattr(att, "content_type", None) or "").lower()
        if ctype.startswith("application/vnd.microsoft.card"):
            continue

        url = getattr(att, "content_url", None) or getattr(att, "contentUrl", None)

        # data URL (e.g., from Bot Emulator)
        if url and str(url).startswith("data:"):
            try:
                header, b64data = str(url).split(",", 1)
                mime = "image/png"
                if ":" in header and ";" in header:
                    mime = header.split(":", 1)[1].split(";", 1)[0] or mime
                if not mime.startswith("image/"):
                    continue
                return {"bytes": base64.b64decode(b64data), "mime_type": mime}
            except Exception:
                continue

        # Teams file download info
        if not url and ctype == "application/vnd.microsoft.teams.file.download.info":
            content = getattr(att, "content", None) or {}
            if isinstance(content, dict):
                url = content.get("downloadUrl")

        # HTTP URL — download and check if image
        if url and str(url).startswith("http"):
            if not ctype.startswith("image/"):
                continue
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            return {"bytes": data, "mime_type": ctype or "image/png"}
            except Exception:
                continue

    return None
```

- [ ] **Step 4: 修改 _try_attach_images 回傳邏輯**

目前 `_try_attach_images` 在沒有最近 IT 單時會回傳提示訊息並 `return True`（line 1064-1068）。需要改為 `return False`，讓流程繼續到圖片解析：

```python
if not gid:
    # 沒有最近的 IT 單，不攔截，讓後續流程處理圖片
    return False
```

- [ ] **Step 5: 驗證完整流程**

```bash
pytest tests/ -v
python -c "from app import app; print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add presentation/bot/message_handler.py
git commit -m "feat: add image analysis via GPT-4o Vision when user pastes images in chat"
```

---

## 不在此次範圍但建議後續處理

- **安全性**：`.env` 中的 credentials 輪換（需與 IT/DevOps 協調，非程式碼改動）
- **錯誤處理精細化**：將 `except Exception` 改為具體例外型別
- **DI Container 修正**：`tuple` service key 改為具名型別、`ServiceProvider` 加 `ABC` 繼承
- **背景任務重試機制**：daily maintenance / hourly reminder 的 exception recovery
