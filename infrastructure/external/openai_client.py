"""
OpenAI 客戶端封裝
"""

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional, AsyncGenerator
from uuid import uuid4
from openai import AzureOpenAI, OpenAI

from config.settings import AppConfig
from shared.exceptions import OpenAIServiceError
from shared.utils.helpers import AsyncRetry


class OpenAIClient:
    """OpenAI 客戶端封裝"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.client = self._create_client()
        self.logger = logging.getLogger(__name__)

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
        request_id = kwargs.pop("request_id", None) or str(uuid4())
        model = kwargs.get("model", self.config.openai.model)
        message_count = len(messages or [])
        start_time = time.perf_counter()
        self.logger.info(
            "OpenAI chat_completion start request_id=%s model=%s messages=%d azure=%s",
            request_id,
            model,
            message_count,
            self.config.openai.use_azure,
        )

        try:
            use_reasoning_responses = (
                not self.config.openai.use_azure
                and (model.startswith("gpt-5") or model.startswith("o1"))
            )

            result_text: Optional[str] = None

            if use_reasoning_responses:
                input_segments = []
                for m in messages or []:
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    input_segments.append(f"{role}: {content}")
                input_text = "\n".join(input_segments) if input_segments else ""

                responses_params = {"model": model, "input": input_text}

                if "max_completion_tokens" in kwargs:
                    responses_params["max_output_tokens"] = kwargs["max_completion_tokens"]
                elif "max_tokens" in kwargs:
                    responses_params["max_output_tokens"] = kwargs["max_tokens"]
                else:
                    responses_params["max_output_tokens"] = min(
                        self.config.openai.max_tokens, 4000
                    )

                effort = None
                if model == "gpt-5":
                    effort = "medium"
                elif model == "gpt-5-mini":
                    effort = "low"
                elif model == "gpt-5-nano":
                    effort = "minimal"
                if effort:
                    responses_params["reasoning"] = {"effort": effort}

                self.logger.debug(
                    "OpenAI responses params request_id=%s params=%s",
                    request_id,
                    {**responses_params, "endpoint": "responses.create"},
                )

                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.client.responses.create(**responses_params)
                )

                output_text = getattr(response, "output_text", None)
                if isinstance(output_text, str) and output_text.strip():
                    result_text = output_text.strip()
                else:
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
                                    if ptype in ("output_text", "text"):
                                        result_text = str(ptext).strip()
                                        break
                                    if text_candidate is None:
                                        text_candidate = str(ptext).strip()
                            if result_text:
                                break
                        if not result_text and text_candidate:
                            result_text = text_candidate
                    except Exception:
                        pass

                if not result_text:
                    result_text = "抱歉，我目前沒有可回應的內容。（模型未提供文本內容）"

            else:
                request_params: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                }

                if model.startswith("gpt-5"):
                    extra_params: Dict[str, Any] = {}
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
                    request_params.update(extra_params)

                    if "max_tokens" in kwargs:
                        request_params["max_tokens"] = kwargs["max_tokens"]
                    elif "max_completion_tokens" in kwargs:
                        request_params["max_tokens"] = kwargs["max_completion_tokens"]
                else:
                    if "max_tokens" in kwargs:
                        request_params["max_tokens"] = kwargs["max_tokens"]
                    if "temperature" in kwargs:
                        request_params["temperature"] = kwargs["temperature"]

                self.logger.debug(
                    "OpenAI chat params request_id=%s params=%s",
                    request_id,
                    request_params,
                )

                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.client.chat.completions.create(**request_params)
                )

                if not response or not response.choices:
                    raise OpenAIServiceError("API 回應為空或無效")

                choice = response.choices[0]
                msg = getattr(choice, "message", None)
                if msg is not None:
                    content_field = getattr(msg, "content", None)
                    if isinstance(content_field, str) and content_field.strip():
                        result_text = content_field.strip()
                    elif isinstance(content_field, list):
                        preferred_text = None
                        fallback_text = None
                        for part in content_field:
                            p_text = None
                            p_type = None
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
                        result_text = preferred_text or fallback_text

                    if not result_text:
                        refusal = getattr(msg, "refusal", None)
                        if isinstance(refusal, str) and refusal.strip():
                            result_text = refusal.strip()

                if not result_text:
                    model_name = request_params.get("model", self.config.openai.model)
                    debug_hint = "（模型未提供文本內容）"
                    result_text = f"抱歉，我目前沒有可回應的內容。{debug_hint}"

            duration_ms = (time.perf_counter() - start_time) * 1000
            preview = (result_text or "").strip().replace("\n", " ")
            if len(preview) > 120:
                preview = f"{preview[:117]}..."
            self.logger.info(
                "OpenAI chat_completion success request_id=%s model=%s latency_ms=%.1f text_len=%d preview=\"%s\"",
                request_id,
                model,
                duration_ms,
                len(result_text or ""),
                preview or "<empty>",
            )
            return result_text or ""

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self.logger.exception(
                "OpenAI chat_completion failed request_id=%s model=%s latency_ms=%.1f error=%s",
                request_id,
                model,
                duration_ms,
                str(e),
            )
            raise OpenAIServiceError(f"OpenAI API 調用失敗: {str(e)}") from e

    async def chat_completion_stream(
        self, messages: List[Dict[str, str]], **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式聊天完成"""
        try:
            request_id = kwargs.pop("request_id", None) or str(uuid4())
            model = kwargs.get("model", self.config.openai.model)
            self.logger.info(
                "OpenAI chat_completion_stream start request_id=%s model=%s messages=%d",
                request_id,
                model,
                len(messages or []),
            )

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

            self.logger.info(
                "OpenAI chat_completion_stream completed request_id=%s model=%s",
                request_id,
                model,
            )

        except Exception as e:
            error_msg = f"OpenAI 流式 API 調用失敗: {str(e)}"
            self.logger.exception(
                "OpenAI chat_completion_stream failed request_id=%s model=%s error=%s",
                locals().get("request_id"),
                locals().get("model"),
                str(e),
            )
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
            self.logger.exception(
                "OpenAI summarize_text failed error=%s", str(e)
            )
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
