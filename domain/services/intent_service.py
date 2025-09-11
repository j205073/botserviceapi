"""
意圖分析服務
重構自原始 app.py 的 analyze_user_intent 函數
"""

from typing import Dict, Any, Optional
import json
import re
from dataclasses import dataclass

from config.settings import AppConfig
from infrastructure.external.openai_client import OpenAIClient
from shared.exceptions import OpenAIServiceError
from shared.utils.helpers import clean_json_response, extract_json_from_text


@dataclass
class IntentResult:
    """意圖分析結果"""

    is_existing_feature: bool
    category: str
    action: str
    content: str
    confidence: float
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return {
            "is_existing_feature": self.is_existing_feature,
            "category": self.category,
            "action": self.action,
            "content": self.content,
            "confidence": self.confidence,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentResult":
        """從字典創建實例"""
        return cls(
            is_existing_feature=data.get("is_existing_feature", False),
            category=data.get("category", ""),
            action=data.get("action", ""),
            content=data.get("content", ""),
            confidence=float(data.get("confidence", 0.0)),
            reason=data.get("reason"),
        )


class IntentService:
    """意圖分析服務"""

    def __init__(self, config: AppConfig, openai_client: OpenAIClient):
        self.config = config
        self.openai_client = openai_client

    async def analyze_intent(self, user_message: str) -> IntentResult:
        """
        分析用戶意圖
        重構自原始 app.py 的 analyze_user_intent 函數
        """
        if not user_message or not user_message.strip():
            return IntentResult(
                is_existing_feature=False,
                category="",
                action="",
                content="",
                confidence=0.0,
                reason="空白輸入",
            )

        try:
            # 構建意圖分析 prompt
            system_prompt = self._build_intent_prompt()

            # 選擇適當的模型
            model_name = self._get_intent_model()

            print(f"🤖 [意圖分析] 使用模型: {model_name}")
            print(f"📝 [意圖分析] 用戶輸入: {user_message}")

            # 構建訊息
            messages = self._build_messages(system_prompt, user_message, model_name)

            # 調用 OpenAI API
            response_text = await self.openai_client.chat_completion(
                messages=messages,
                model=model_name,
                max_tokens=300,
                temperature=0.1 if not model_name.startswith("o1") else None,
            )

            print(f"🎯 [意圖分析] AI回應: {response_text}")
            print(f"📏 [意圖分析] 回應長度: {len(response_text)} 字符")

            # 解析回應
            result = self._parse_intent_response(response_text)

            print(f"✅ [意圖分析] 解析成功:")
            print(f"   類別: {result.category}")
            print(f"   動作: {result.action}")
            print(f"   現有功能: {result.is_existing_feature}")
            print(f"   信心度: {result.confidence}")

            return result

        except Exception as e:
            print(f"❌ [意圖分析] 失敗: {str(e)}")
            return IntentResult(
                is_existing_feature=False,
                category="",
                action="",
                content="",
                confidence=0.0,
                reason=f"分析失敗: {str(e)}",
            )

    def _build_intent_prompt(self) -> str:
        """構建意圖分析 prompt"""
        # 根據模式決定是否支援模型切換
        model_features = ""
        if not self.config.openai.use_azure:
            model_features = """
🧠 模型選擇 (Model Selection):
  - category: "model"
  - action: "select" (切換/選擇模型)
  - 觸發詞: 切換模型、換模型、使用 gpt-4o、選擇模型等
"""

        return f"""你是專業的意圖分析助手。分析用戶輸入並判斷是否符合以下現有功能，必須嚴格按照 JSON 格式回傳結果。

=== 現有功能分類 ===

📝 待辦事項管理 (TODO Management):
  - category: "todo"
  - actions:
    - query: 查詢/查看待辦事項、任務清單
    - add: 新增/添加待辦事項
    - smart_add: 智能新增待辦（含重複檢查）
    - complete: 完成/標記完成待辦事項

🏢 會議管理 (Meeting Management):
  - category: "meeting" 
  - actions:
    - book: 預約/預定會議室
    - query: 查詢會議、查看行程
    - cancel: 取消會議/預約

ℹ️ 資訊查詢 (Information Query):
  - category: "info"
  - actions:
    - user_info: 用戶個人資訊查詢（我是誰、我的部門、我的職稱、我的email等）
    - bot_info: 機器人介紹（你是誰、你的功能、自我介紹等）
    - help: 使用幫助、系統說明
    - status: 系統狀態查詢

{model_features}

=== 重要識別規則 ===
• "我是誰" → info.user_info (用戶查詢自己的身份)
• "你是誰" → info.bot_info (詢問機器人身份)  
• "我的部門/單位/職稱/email" → info.user_info
• "你會什麼/你的功能" → info.bot_info

=== 輸出格式 (必須是有效JSON) ===
{{
  "is_existing_feature": true/false,
  "category": "功能分類",
  "action": "具體動作", 
  "content": "相關內容",
  "confidence": 0.0到1.0之間的數值,
  "reason": "判斷依據"
}}

=== 判斷標準 ===
- 如果用戶輸入明確對應上述功能 → is_existing_feature: true, confidence: 0.8-0.95
- 如果可能相關但不確定 → is_existing_feature: true, confidence: 0.6-0.79  
- 如果完全無關（如天氣、數學題、寫報告等） → is_existing_feature: false, confidence: 0.0-0.5

請直接返回JSON，不要添加任何其他文字或格式符號。"""

    def _get_intent_model(self) -> str:
        """獲取意圖分析模型"""
        if self.config.openai.use_azure:
            return "gpt-4o-mini"  # Azure 模式使用穩定模型
        else:
            # OpenAI 模式：優先使用穩定的模型，避免 gpt-5 系列的相容性問題
            original_model = self.config.openai.intent_model
            # if original_model.startswith("gpt-5") or original_model.startswith("o1"):
            #     print(f"⚠️ [意圖分析] {original_model} 可能不穩定，改用 gpt-4o-mini")
            #     return "gpt-4o-mini"
            return original_model

    def _build_messages(
        self, system_prompt: str, user_message: str, model_name: str
    ) -> list:
        """構建訊息列表"""
        if model_name.startswith("o1"):
            # o1 模型不支援 system role，需要合併到 user message
            combined_prompt = f"{system_prompt}\n\n用戶輸入: {user_message}"
            return [{"role": "user", "content": combined_prompt}]
        else:
            # 標準模型支援 system role
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

    def _parse_intent_response(self, response_text: str) -> IntentResult:
        """解析意圖分析回應"""
        if not response_text or not response_text.strip():
            return IntentResult(
                is_existing_feature=False,
                category="",
                action="",
                content="",
                confidence=0.0,
                reason="AI 回應為空",
            )

        # 清理 JSON
        cleaned_text = clean_json_response(response_text)

        # 嘗試解析 JSON
        parsed_data = extract_json_from_text(cleaned_text)

        if not parsed_data:
            return IntentResult(
                is_existing_feature=False,
                category="",
                action="",
                content="",
                confidence=0.0,
                reason="無法解析 JSON 回應",
            )

        # 正規化結果
        result = IntentResult.from_dict(parsed_data)
        return self._normalize_intent_result(result)

    def _normalize_intent_result(self, result: IntentResult) -> IntentResult:
        """正規化意圖結果"""
        allowed_categories = {"todo", "meeting", "info", "model"}

        # Azure 模式不支援模型切換
        if self.config.openai.use_azure:
            allowed_categories.discard("model")

        # 檢查類別是否合法
        if result.category.lower() not in allowed_categories:
            result.is_existing_feature = False
            result.category = ""
            result.confidence = 0.0
            result.reason = f"不支援的類別: {result.category}"
        else:
            result.category = result.category.lower()

        # 確保信心度在合理範圍內
        result.confidence = max(0.0, min(1.0, result.confidence))

        # 如果沒有明確的 is_existing_feature，根據類別判斷
        if result.category and result.category in allowed_categories:
            result.is_existing_feature = True

        return result
