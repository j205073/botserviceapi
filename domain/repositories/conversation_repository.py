"""
對話記錄 Repository
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime

from domain.models.conversation import Conversation, ConversationMessage, MessageRole
from shared.exceptions import RepositoryError, NotFoundError
from shared.utils.helpers import generate_id, get_taiwan_time


class ConversationRepository(ABC):
    """對話記錄 Repository 接口"""
    
    @abstractmethod
    async def create(self, conversation_id: str, user_mail: str) -> Conversation:
        """創建對話記錄"""
        pass
    
    @abstractmethod
    async def get_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """根據 ID 獲取對話記錄"""
        pass
    
    @abstractmethod
    async def get_by_user(
        self, 
        user_mail: str, 
        include_completed: bool = True,
        limit: Optional[int] = None
    ) -> List[Conversation]:
        """獲取用戶的所有對話記錄"""
        pass
    
    @abstractmethod
    async def get_active_by_user(self, user_mail: str) -> Optional[Conversation]:
        """獲取用戶的主動對話"""
        pass
    
    @abstractmethod
    async def update_state(self, conversation_id: str, state) -> Conversation:
        """更新對話狀態"""
        pass
    
    @abstractmethod
    async def add_message(
        self, 
        conversation_id: str, 
        message: ConversationMessage
    ) -> Optional[Conversation]:
        """向對話添加訊息"""
        pass
    
    @abstractmethod
    async def update(self, conversation: Conversation) -> Conversation:
        """更新對話記錄"""
        pass
    
    @abstractmethod
    async def delete(self, conversation_id: str) -> bool:
        """刪除對話記錄"""
        pass
    
    @abstractmethod
    async def clear_conversation_messages(self, conversation_id: str) -> bool:
        """清空對話訊息"""
        pass
    
    @abstractmethod
    async def compress_conversation(
        self, 
        conversation_id: str, 
        summary_message: ConversationMessage
    ) -> Optional[Conversation]:
        """壓縮對話記錄"""
        pass
    
    @abstractmethod
    async def get_active_conversations(self, user_mail: str) -> List[Conversation]:
        """獲取用戶的活躍對話"""
        pass
    
    @abstractmethod
    async def clean_old_conversations(self, before_date: datetime) -> int:
        """清理舊對話"""
        pass


class InMemoryConversationRepository(ConversationRepository):
    """記憶體中的對話記錄 Repository 實現"""
    
    def __init__(self):
        self._conversations: Dict[str, Conversation] = {}
        self._user_conversations: Dict[str, List[str]] = {}  # user_mail -> [conversation_ids]
    
    async def create(self, conversation_id: str, user_mail: str) -> Conversation:
        """創建對話記錄（如果已存在則返回現有的）"""
        # 如果對話已存在，直接返回（模擬原始行為）
        if conversation_id in self._conversations:
            existing_conversation = self._conversations[conversation_id]
            print(f"對話 {conversation_id} 已存在，返回現有對話")
            return existing_conversation
        
        conversation = Conversation(
            id=conversation_id,
            user_mail=user_mail,
            created_at=get_taiwan_time(),
            last_updated=get_taiwan_time()
        )
        
        self._conversations[conversation_id] = conversation
        
        # 更新用戶對話列表
        if user_mail not in self._user_conversations:
            self._user_conversations[user_mail] = []
        self._user_conversations[user_mail].append(conversation_id)
        
        print(f"成功創建新對話 {conversation_id} for {user_mail}")
        return conversation
    
    async def get_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """根據 ID 獲取對話記錄"""
        return self._conversations.get(conversation_id)
    
    async def get_by_user(
        self, 
        user_mail: str, 
        include_completed: bool = True,
        limit: Optional[int] = None
    ) -> List[Conversation]:
        """獲取用戶的所有對話記錄"""
        conversation_ids = self._user_conversations.get(user_mail, [])
        conversations = []
        
        for conv_id in conversation_ids:
            if conv_id in self._conversations:
                conversation = self._conversations[conv_id]
                if include_completed or conversation.is_active:
                    conversations.append(conversation)
        
        # 按最後更新時間排序
        conversations.sort(key=lambda x: x.last_updated, reverse=True)
        
        if limit:
            conversations = conversations[:limit]
        
        return conversations
    
    async def get_active_by_user(self, user_mail: str) -> Optional[Conversation]:
        """獲取用戶的主動對話"""
        conversations = await self.get_by_user(user_mail, include_completed=False, limit=1)
        return conversations[0] if conversations else None
    
    async def update_state(self, conversation_id: str, state) -> Conversation:
        """更新對話狀態"""
        conversation = await self.get_by_id(conversation_id)
        if not conversation:
            raise NotFoundError(f"對話 {conversation_id} 不存在")
        
        conversation.state = state
        conversation.last_updated = get_taiwan_time()
        return conversation
    
    async def add_message(
        self, 
        conversation_id: str, 
        message: ConversationMessage
    ) -> Optional[Conversation]:
        """向對話添加訊息"""
        conversation = await self.get_by_id(conversation_id)
        if not conversation:
            return None
        
        conversation.add_message(message)
        return conversation
    
    async def update(self, conversation: Conversation) -> Conversation:
        """更新對話記錄"""
        if conversation.id not in self._conversations:
            raise NotFoundError(f"對話 {conversation.id} 不存在")
        
        self._conversations[conversation.id] = conversation
        return conversation
    
    async def delete(self, conversation_id: str) -> bool:
        """刪除對話記錄"""
        conversation = await self.get_by_id(conversation_id)
        if not conversation:
            return False
        
        del self._conversations[conversation_id]
        
        # 從用戶列表中移除
        if conversation.user_mail in self._user_conversations:
            try:
                self._user_conversations[conversation.user_mail].remove(conversation_id)
            except ValueError:
                pass
        
        return True
    
    async def clear_conversation_messages(self, conversation_id: str) -> bool:
        """清空對話訊息"""
        conversation = await self.get_by_id(conversation_id)
        if not conversation:
            return False
        
        conversation.clear_messages()
        return True
    
    async def compress_conversation(
        self, 
        conversation_id: str, 
        summary_message: ConversationMessage
    ) -> Optional[Conversation]:
        """壓縮對話記錄"""
        conversation = await self.get_by_id(conversation_id)
        if not conversation:
            return None
        
        compressed_count = conversation.compress_messages(summary_message)
        print(f"對話 {conversation_id} 壓縮了 {compressed_count} 條用戶/助手訊息")
        
        return conversation
    
    async def get_active_conversations(self, user_mail: str) -> List[Conversation]:
        """獲取用戶的活躍對話"""
        conversations = await self.get_by_user(user_mail)
        return [conv for conv in conversations if conv.is_active]
    
    async def clean_old_conversations(self, before_date: datetime) -> int:
        """清理舊對話"""
        cleaned_count = 0
        conversations_to_delete = []
        
        for conv_id, conv in self._conversations.items():
            if conv.last_updated < before_date:
                conversations_to_delete.append(conv_id)
        
        for conv_id in conversations_to_delete:
            if await self.delete(conv_id):
                cleaned_count += 1
        
        return cleaned_count
    
    async def get_conversation_stats(self, user_mail: str) -> Dict[str, Any]:
        """獲取對話統計信息"""
        conversations = await self.get_by_user(user_mail)
        active_conversations = [conv for conv in conversations if conv.is_active]
        
        total_messages = sum(len(conv.messages) for conv in conversations)
        
        return {
            "total_conversations": len(conversations),
            "active_conversations": len(active_conversations),
            "total_messages": total_messages,
            "average_messages_per_conversation": total_messages / max(len(conversations), 1)
        }
    
    async def get_or_create(self, conversation_id: str, user_mail: str) -> Conversation:
        """獲取或創建對話記錄"""
        conversation = await self.get_by_id(conversation_id)
        if conversation:
            return conversation
        
        return await self.create(conversation_id, user_mail)