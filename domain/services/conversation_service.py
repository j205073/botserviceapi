"""
對話管理業務邏輯服務
重構自原始 app.py 中的對話相關功能
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from uuid import uuid4

from domain.models.conversation import (
    Conversation,
    ConversationMessage,
    ConversationState,
)
from domain.models.audit import MessageRole
from domain.repositories.conversation_repository import ConversationRepository
from domain.services.audit_service import AuditService
from infrastructure.external.openai_client import OpenAIClient
from config.settings import AppConfig
from shared.exceptions import BusinessLogicError, NotFoundError, OpenAIServiceError
from shared.utils.helpers import get_taiwan_time


class ConversationService:
    """對話管理業務邏輯服務"""

    def __init__(
        self,
        config: AppConfig,
        conversation_repository: ConversationRepository,
        audit_service: AuditService,
        openai_client: OpenAIClient,
    ):
        self.config = config
        self.conversation_repository = conversation_repository
        self.audit_service = audit_service
        self.openai_client = openai_client
        self.logger = logging.getLogger(__name__)

    async def start_conversation(
        self, conversation_id: str, user_mail: str
    ) -> Conversation:
        """開始新對話"""
        return await self.conversation_repository.create(conversation_id, user_mail)

    async def get_or_create_conversation(
        self, conversation_id: str, user_mail: str
    ) -> Conversation:
        """獲取或創建用戶對話"""
        conversation = await self.conversation_repository.get_by_id(conversation_id)
        if not conversation:
            conversation = await self.start_conversation(conversation_id, user_mail)
        return conversation

    async def add_user_message(
        self,
        conversation_id: str,
        user_mail: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationMessage:
        """添加用戶消息"""
        conversation = await self.conversation_repository.get_by_id(conversation_id)
        if not conversation:
            # 自動創建對話，保持與原始行為一致
            conversation = await self.conversation_repository.create(
                conversation_id, user_mail
            )

        if conversation.user_mail != user_mail:
            raise BusinessLogicError("無權限操作此對話")

        # 創建用戶消息
        message = ConversationMessage(
            role=MessageRole.USER,
            content=content,
            timestamp=get_taiwan_time(),
            metadata=metadata or {},
        )

        # 添加到對話歷史
        updated_conversation = await self.conversation_repository.add_message(
            conversation_id, message
        )

        # 記錄到稽核日誌
        await self.audit_service.log_user_message(
            conversation_id=conversation_id,
            user_mail=user_mail,
            content=content,
            metadata=metadata,
        )

        return message

    async def add_assistant_message(
        self,
        conversation_id: str,
        user_mail: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationMessage:
        """添加助手回應"""
        conversation = await self.conversation_repository.get_by_id(conversation_id)
        if not conversation:
            # 自動創建對話，保持與原始行為一致
            conversation = await self.conversation_repository.create(
                conversation_id, user_mail
            )

        # 創建助手消息
        message = ConversationMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            timestamp=get_taiwan_time(),
            metadata=metadata or {},
        )

        # 添加到對話歷史
        updated_conversation = await self.conversation_repository.add_message(
            conversation_id, message
        )

        # 記錄到稽核日誌
        await self.audit_service.log_assistant_message(
            conversation_id=conversation_id,
            user_mail=user_mail,
            content=content,
            metadata=metadata,
        )

        return message

    async def get_conversation_history(
        self,
        conversation_id: str,
        user_mail: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[ConversationMessage]:
        """獲取對話歷史"""
        conversation = await self.conversation_repository.get_by_id(conversation_id)
        if not conversation:
            raise NotFoundError(f"對話 {conversation_id} 不存在")

        # 驗證用戶權限
        if user_mail and conversation.user_mail != user_mail:
            raise BusinessLogicError("無權限查看此對話")

        messages = conversation.messages
        if limit:
            messages = messages[-limit:]  # 獲取最新的 N 條消息

        return messages

    async def get_conversation_context(
        self, conversation_id: str, user_mail: str, max_messages: int = 10
    ) -> List[Dict[str, str]]:
        """獲取對話上下文（OpenAI 格式）"""
        messages = await self.get_conversation_history(
            conversation_id, user_mail, max_messages
        )

        # 轉換為 OpenAI 格式
        context = []
        for message in messages:
            context.append(
                {
                    "role": message.role.value,  # 使用 enum 的 value
                    "content": message.content,
                }
            )

        return context

    async def end_conversation(
        self, conversation_id: str, user_mail: str, reason: Optional[str] = None
    ) -> Conversation:
        """結束對話"""
        conversation = await self.conversation_repository.get_by_id(conversation_id)
        if not conversation:
            raise NotFoundError(f"對話 {conversation_id} 不存在")

        if conversation.user_mail != user_mail:
            raise BusinessLogicError("無權限操作此對話")

        # 更新對話狀態
        updated_conversation = await self.conversation_repository.update_state(
            conversation_id, ConversationState.COMPLETED
        )

        # 記錄系統動作
        await self.audit_service.log_system_action(
            conversation_id=conversation_id,
            user_mail=user_mail,
            action_description=f"對話結束: {reason or '用戶主動結束'}",
            metadata={"reason": reason},
        )

        return updated_conversation

    async def get_user_conversations(
        self, user_mail: str, include_completed: bool = False, limit: int = 50
    ) -> List[Conversation]:
        """獲取用戶的對話列表"""
        return await self.conversation_repository.get_by_user(
            user_mail, include_completed, limit
        )

    async def search_conversations(
        self,
        user_mail: str,
        keyword: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> List[Conversation]:
        """搜索對話"""
        conversations = await self.conversation_repository.get_by_user(user_mail, True)

        # 應用過濾條件
        filtered = conversations

        if keyword:
            keyword_lower = keyword.lower()
            filtered = []
            for conv in conversations:
                # 搜索消息內容
                for message in conv.messages:
                    if keyword_lower in message.content.lower():
                        filtered.append(conv)
                        break

        if date_from:
            filtered = [c for c in filtered if c.created_at >= date_from]

        if date_to:
            filtered = [c for c in filtered if c.created_at <= date_to]

        return filtered

    async def get_conversation_stats(self, user_mail: str) -> Dict[str, Any]:
        """獲取對話統計"""
        conversations = await self.get_user_conversations(user_mail, True)

        total_messages = sum(len(c.messages) for c in conversations)
        active_count = len(
            [c for c in conversations if c.state == ConversationState.ACTIVE]
        )
        completed_count = len(
            [c for c in conversations if c.state == ConversationState.COMPLETED]
        )

        # 最近活動
        week_ago = get_taiwan_time() - timedelta(days=7)
        recent_conversations = [
            c for c in conversations if c.last_activity_at >= week_ago
        ]

        return {
            "total_conversations": len(conversations),
            "active_conversations": active_count,
            "completed_conversations": completed_count,
            "total_messages": total_messages,
            "recent_week_conversations": len(recent_conversations),
            "average_messages_per_conversation": round(
                total_messages / max(len(conversations), 1), 2
            ),
        }

    async def clean_old_conversations(
        self, user_mail: str, retention_days: Optional[int] = None
    ) -> Dict[str, int]:
        """清理舊對話"""
        days = retention_days or self.config.database.retention_days
        cutoff_date = get_taiwan_time() - timedelta(days=days)

        cleaned_count = await self.conversation_repository.clean_old_conversations(
            user_mail, cutoff_date
        )

        return {
            "cleaned_count": cleaned_count,
            "cutoff_date": cutoff_date.isoformat(),
            "retention_days": days,
        }

    async def get_ai_response(
        self, conversation_id: str, user_mail: str, message: str, **kwargs
    ) -> str:
        """獲取 AI 回應"""
        try:
            model_name = kwargs.get("model", self.config.openai.model)
            request_id = kwargs.get("request_id")
            if not request_id:
                request_id = str(uuid4())
                kwargs["request_id"] = request_id
            prompt_preview = (message or "").strip()
            if len(prompt_preview) > 120:
                prompt_preview = f"{prompt_preview[:117]}..."
            self.logger.info(
                "AI response requested user_mail=%s conversation_id=%s model=%s request_id=%s",
                user_mail,
                conversation_id,
                model_name,
                request_id,
            )
            if prompt_preview:
                self.logger.debug(
                    "AI request prompt preview request_id=%s conversation_id=%s text=\"%s\"",
                    request_id,
                    conversation_id,
                    prompt_preview,
                )
            # 確保對話存在（自動創建機制，模擬原始行為）
            conversation = await self.conversation_repository.get_by_id(conversation_id)
            if not conversation:
                self.logger.info(
                    "Conversation missing, creating new conversation user_mail=%s conversation_id=%s request_id=%s",
                    user_mail,
                    conversation_id,
                    request_id,
                )
                conversation = await self.conversation_repository.create(
                    conversation_id, user_mail
                )

            # 添加用戶消息到對話歷史
            await self.add_user_message(conversation_id, user_mail, message)

            # 獲取對話上下文
            context = await self.get_conversation_context(conversation_id, user_mail)
            # 如果是新對話，添加系統提示
            if len(context) <= 1:  # 只有用戶消息或空對話
                system_prompt = self._get_system_prompt(user_mail)
                context = [{"role": "system", "content": system_prompt}] + context
            max_tokens = 4000
            # 記錄上下文資訊（避免記錄完整內容）
            self.logger.debug(
                "Prepared OpenAI context user_mail=%s conversation_id=%s messages=%d request_id=%s",
                user_mail,
                conversation_id,
                len(context),
                request_id,
            )
            # 調用 OpenAI API
            response = await self.openai_client.chat_completion(
                messages=context,
                model=model_name,
                max_tokens=kwargs.get("max_tokens", max_tokens),
                temperature=kwargs.get("temperature", 1.0),
            )

            # 添加AI回應到對話歷史
            await self.add_assistant_message(conversation_id, user_mail, response)
            response_preview = (response or "").strip()
            if len(response_preview) > 120:
                response_preview = f"{response_preview[:117]}..."
            self.logger.info(
                "AI response stored user_mail=%s conversation_id=%s len=%d request_id=%s preview=\"%s\"",
                user_mail,
                conversation_id,
                len(response or ""),
                request_id,
                response_preview or "<empty>",
            )

            return response

        except Exception as e:
            self.logger.exception(
                "獲取 AI 回應失敗 user_mail=%s conversation_id=%s request_id=%s",
                user_mail,
                conversation_id,
                kwargs.get("request_id"),
            )
            raise OpenAIServiceError(f"AI 回應生成失敗: {str(e)}")

    def _get_system_prompt(self, user_mail: str) -> str:
        """獲取系統提示"""
        # 簡化的系統提示，可以根據用戶語言偏好調整
        return "你是一個智能助理，負責協助用戶處理各種問題和任務。請用繁體中文回應。"

    async def get_conversation_summary(self, user_mail: str) -> Dict[str, Any]:
        """獲取用戶對話摘要"""
        try:
            conversations = await self.conversation_repository.get_by_user(user_mail)
            active_count = len(
                [c for c in conversations if c.state == ConversationState.ACTIVE]
            )
            total_messages = sum(len(c.messages) for c in conversations)

            return {
                "total_conversations": len(conversations),
                "active_conversations": active_count,
                "total_messages": total_messages,
            }
        except Exception as e:
            self.logger.exception(
                "Error getting conversation summary user_mail=%s", user_mail
            )
            return {
                "total_conversations": 0,
                "active_conversations": 0,
                "total_messages": 0,
            }

    async def cleanup_old_conversations(self) -> Dict[str, Any]:
        """清理舊對話"""
        try:
            # 這裡可以實現清理邏輯，暫時返回簡單結果
            return {"cleaned_count": 0, "message": "Memory cleanup not implemented yet"}
        except Exception as e:
            return {"error": str(e)}
