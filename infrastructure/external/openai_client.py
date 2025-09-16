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

                # 對 gpt-5 / o1 類推理模型優先使用 Responses API（僅 OpenAI，Azure 仍走 Chat Completions）
                use_reasoning_responses = (
                    not self.config.openai.use_azure
                    and (model.startswith("gpt-5") or model.startswith("o1"))
                )

                if use_reasoning_responses:
                    # 將 messages 簡單串接為文字輸入；Responses API 以 input 為主
                    input_segments = []
                    for m in messages or []:
                        role = m.get("role", "user")
                        content = m.get("content", "")
                        input_segments.append(f"{role}: {content}")
                    input_text = "\n".join(input_segments) if input_segments else ""

                    # 構建 Responses API 參數
                    responses_params = {"model": model, "input": input_text}

                    # gpt-5 / o1 使用 max_output_tokens
                    if "max_completion_tokens" in kwargs:
                        responses_params["max_output_tokens"] = kwargs[
                            "max_completion_tokens"
                        ]
                    elif "max_tokens" in kwargs:
                        responses_params["max_output_tokens"] = kwargs["max_tokens"]
                    else:
                        responses_params["max_output_tokens"] = min(
                            self.config.openai.max_tokens, 4000
                        )

                    # reasoning 努力等級（與既有行為對齊）
                    effort = None
                    if model == "gpt-5":
                        effort = "medium"
                    elif model == "gpt-5-mini":
                        effort = "low"
                    elif model == "gpt-5-nano":
                        effort = "minimal"
                    if effort:
                        responses_params["reasoning"] = {"effort": effort}

                    import json
                    print(json.dumps({"endpoint": "responses.create", **responses_params}, ensure_ascii=False))

                    # 呼叫 Responses API（同步 SDK 以執行緒池包裝）
                    response = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self.client.responses.create(**responses_params)
                    )

                    # 優先使用 output_text（SDK 聚合的便捷欄位）
                    output_text = getattr(response, "output_text", None)
                    if isinstance(output_text, str) and output_text.strip():
                        return output_text.strip()

                    # 回退解析：嘗試從結構化內容中提取文字
                    try:
                        outputs = getattr(response, "output", None) or []
                        text_candidate = None
                        for out in outputs:
                            contents = getattr(out, "content", None) or []
                            for part in contents:
                                ptype = getattr(part, "type", None)
                                ptext = getattr(part, "text", None)
                                if ptext is None and isinstance(part, dict):
                                    ptype = ptype or part.get("type")
                                    ptext = part.get("text")
                                if ptext and str(ptext).strip():
                                    # 優先 output_text 類型
                                    if ptype in ("output_text", "text"):
                                        return str(ptext).strip()
                                    if text_candidate is None:
                                        text_candidate = str(ptext).strip()
                        if text_candidate:
                            return text_candidate
                    except Exception:
                        pass

                    # 若仍無內容，提供一致的回退訊息
                    return "抱歉，我目前沒有可回應的內容。（模型未提供文本內容）"

                # 構建請求參數
                # request_params = {
                #     "model": model,
                #     "messages": messages,
                #     "timeout": kwargs.get("timeout", self.config.openai.timeout),
                # }
                request_params = {
                    "model": model,
                    "messages": messages,
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

                    # chat.completions 仍然使用 max_tokens
                    if "max_tokens" in kwargs:
                        request_params["max_tokens"] = kwargs["max_tokens"]
                    elif "max_completion_tokens" in kwargs:
                        request_params["max_tokens"] = kwargs["max_completion_tokens"]
                    # 不添加 temperature 參數（推理模型通常忽略）
                else:
                    # 其他模型使用 max_tokens 和 temperature
                    if "max_tokens" in kwargs:
                        request_params["max_tokens"] = kwargs["max_tokens"]
                    if "temperature" in kwargs:
                        request_params["temperature"] = kwargs["temperature"]
                import json
                print(json.dumps(request_params, ensure_ascii=False))

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
                    # 新版 SDK 可能回傳 content parts 陣列（含 reasoning/output_text 等型別）
                    elif isinstance(content_field, list):
                        preferred_text = None
                        fallback_text = None
                        for part in content_field:
                            p_text = None
                            p_type = None
                            # 兼容物件或 dict 兩種型態
                            try:
                                p_text = getattr(part, "text", None)
                                p_type = getattr(part, "type", None)
                            except Exception:
                                p_text = None
                                p_type = None
                            if isinstance(part, dict):
                                p_text = p_text or part.get("text")
                                p_type = p_type or part.get("type")
                            if p_text and str(p_text).strip():
                                if p_type in ("output_text", "text") and preferred_text is None:
                                    preferred_text = str(p_text).strip()
                                elif fallback_text is None:
                                    fallback_text = str(p_text).strip()
                        message_content = preferred_text or fallback_text

                    # 可能存在拒絕/安全輸出
                    if not message_content:
                        refusal = getattr(msg, "refusal", None)
                        if isinstance(refusal, str) and refusal.strip():
                            message_content = refusal.strip()

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
