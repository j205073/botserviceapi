"""
OpenAI 客戶端封裝
"""

import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator
from openai import AzureOpenAI, OpenAI

from config.settings import AppConfig
from shared.exceptions import OpenAIServiceError
from shared.utils.helpers import AsyncRetry, PerformanceTimer


class OpenAIClient:
    """OpenAI 客戶端封裝"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.client = self._create_client()

    def _create_client(self):
        """創建 OpenAI 客戶端"""
        if self.config.openai.use_azure:
            return AzureOpenAI(
                api_key=self.config.openai.api_key,
                api_version=self.config.openai.api_version,
                azure_endpoint=self.config.openai.endpoint,
            )
        else:
            return OpenAI(api_key=self.config.openai.api_key)

    @AsyncRetry(max_attempts=3, delay=1.0, backoff=2.0)
    async def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """聊天完成"""
        try:
            with PerformanceTimer("OpenAI API 調用"):
                # 設置默認參數
                model = kwargs.get("model", self.config.openai.model)

                # 構建請求參數
                request_params = {
                    "model": model,
                    "messages": messages,
                    "timeout": kwargs.get("timeout", self.config.openai.timeout),
                }

                # 根據模型類型添加適當的參數
                if model.startswith("gpt-5"):
                    extra_params = {}
                    if model == "gpt-5":
                        extra_params = {
                            "reasoning_effort": "medium",
                            "verbosity": "medium",
                        }
                    elif model == "gpt-5-mini":
                        extra_params = {
                            "reasoning_effort": "low",
                            "verbosity": "medium",
                        }
                    elif model == "gpt-5-nano":
                        extra_params = {
                            "reasoning_effort": "minimal",
                            "verbosity": "low",
                        }

                    # 將 extra_params 合併到 request_params
                    request_params.update(extra_params)

                    # gpt-5 和 o1 系列模型使用 max_completion_tokens 且不支援 temperature
                    if "max_tokens" in kwargs:
                        request_params["max_completion_tokens"] = kwargs["max_tokens"]
                    elif "max_completion_tokens" in kwargs:
                        request_params["max_completion_tokens"] = kwargs[
                            "max_completion_tokens"
                        ]
                    # 不添加 temperature 參數
                else:
                    # 其他模型使用 max_tokens 和 temperature
                    if "max_tokens" in kwargs:
                        request_params["max_tokens"] = kwargs["max_tokens"]
                    if "temperature" in kwargs:
                        request_params["temperature"] = kwargs["temperature"]

                # 使用 asyncio 將同步調用轉為異步
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.client.chat.completions.create(**request_params)
                )

                if not response or not response.choices:
                    raise OpenAIServiceError("API 回應為空或無效")

                choice = response.choices[0]
                msg = getattr(choice, "message", None)
                message_content = None
                if msg is not None:
                    content_field = getattr(msg, "content", None)
                    # 常見情況：字串內容
                    if isinstance(content_field, str) and content_field.strip():
                        message_content = content_field.strip()
                    # 新版 SDK 可能回傳 content parts 陣列
                    elif isinstance(content_field, list):
                        for part in content_field:
                            text_val = None
                            # 兼容物件或 dict 兩種型態
                            try:
                                text_val = getattr(part, "text", None)
                            except Exception:
                                text_val = None
                            if text_val is None and isinstance(part, dict):
                                text_val = part.get("text")
                            if text_val and str(text_val).strip():
                                message_content = str(text_val).strip()
                                break

                if not message_content:
                    # 盡量避免直接拋錯：回傳可讀的fallback以提供較好體驗
                    model_name = request_params.get("model", self.config.openai.model)
                    debug_hint = "（模型未提供文本內容）"
                    return f"抱歉，我目前沒有可回應的內容。{debug_hint}"

                return message_content

        except Exception as e:
            error_msg = f"OpenAI API 調用失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise OpenAIServiceError(error_msg) from e

    async def chat_completion_stream(
        self, messages: List[Dict[str, str]], **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式聊天完成"""
        try:
            model = kwargs.get("model", self.config.openai.model)

            request_params = {
                "model": model,
                "messages": messages,
                "stream": True,
                "timeout": kwargs.get("timeout", self.config.openai.timeout),
            }

            # 根據模型類型添加適當的參數
            if model.startswith("gpt-5") or model.startswith("o1"):
                if "max_tokens" in kwargs:
                    request_params["max_completion_tokens"] = kwargs["max_tokens"]
            else:
                if "max_tokens" in kwargs:
                    request_params["max_tokens"] = kwargs["max_tokens"]
                if "temperature" in kwargs:
                    request_params["temperature"] = kwargs["temperature"]

            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.client.chat.completions.create(**request_params)
            )

            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            error_msg = f"OpenAI 流式 API 調用失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise OpenAIServiceError(error_msg) from e

    async def summarize_text(self, text: str, max_length: int = 200, **kwargs) -> str:
        """文本摘要"""
        try:
            summary_prompt = f"""請將以下文本摘要為不超過 {max_length} 字的內容，保留關鍵信息：

{text}

請提供簡潔的摘要："""

            messages = [{"role": "user", "content": summary_prompt}]

            model = kwargs.get("model", self.config.openai.summary_model)

            return await self.chat_completion(
                messages=messages,
                model=model,
                max_tokens=max_length + 50,
                temperature=0.3,
            )

        except Exception as e:
            error_msg = f"文本摘要失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise OpenAIServiceError(error_msg) from e

    async def test_connection(self) -> Dict[str, Any]:
        """測試連接"""
        try:
            test_messages = [
                {
                    "role": "user",
                    "content": "Hello, this is a connection test. Please respond with 'OK'.",
                }
            ]

            response = await self.chat_completion(
                messages=test_messages, max_tokens=10, temperature=0.1
            )

            return {
                "success": True,
                "response": response,
                "client_type": (
                    "Azure OpenAI" if self.config.openai.use_azure else "OpenAI"
                ),
                "model": self.config.openai.model,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "client_type": (
                    "Azure OpenAI" if self.config.openai.use_azure else "OpenAI"
                ),
            }

    def get_model_info(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """獲取模型資訊"""
        model = model_name or self.config.openai.model

        # 從原始 app.py 的 MODEL_INFO 映射
        model_info_map = {
            "gpt-4o": {
                "speed": "快速",
                "time": "5-10秒",
                "use_case": "日常對話",
                "timeout": 20,
            },
            "gpt-4o-mini": {
                "speed": "最快",
                "time": "3-5秒",
                "use_case": "簡單問題",
                "timeout": 15,
            },
            "gpt-5-mini": {
                "speed": "中等",
                "time": "15-30秒",
                "use_case": "推理任務",
                "timeout": 45,
            },
            "gpt-5-nano": {
                "speed": "最快",
                "time": "2-4秒",
                "use_case": "輕量查詢",
                "timeout": 10,
            },
            "gpt-5": {
                "speed": "較慢",
                "time": "60-120秒",
                "use_case": "複雜推理",
                "timeout": 120,
            },
            "gpt-5-chat-latest": {
                "speed": "快速",
                "time": "5-15秒",
                "use_case": "非推理版本",
                "timeout": 25,
            },
        }

        return model_info_map.get(
            model,
            {
                "speed": "未知",
                "time": "未知",
                "use_case": "通用",
                "timeout": 30,
            },
        )
