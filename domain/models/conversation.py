"""
對話記錄數據模型
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum
from .audit import MessageRole


class ConversationState(Enum):
    """對話狀態"""
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class ConversationMessage:
    """對話訊息"""
    role: MessageRole
    content: str
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata or {}
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ConversationMessage':
        """從字典創建實例"""
        return cls(
            role=MessageRole(data["role"]),
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata")
        )


@dataclass
class Conversation:
    """對話記錄"""
    id: str
    user_mail: str
    messages: List[ConversationMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    last_activity_at: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    is_active: bool = True
    state: ConversationState = ConversationState.ACTIVE
    
    def add_message(self, message: ConversationMessage) -> None:
        """添加訊息"""
        self.messages.append(message)
        self.message_count += 1
        self.last_updated = datetime.now()
    
    def get_recent_messages(self, limit: int) -> List[ConversationMessage]:
        """獲取最近的訊息"""
        return self.messages[-limit:] if self.messages else []
    
    def get_user_assistant_messages(self) -> List[ConversationMessage]:
        """獲取用戶和助手的訊息（排除系統訊息）"""
        return [
            msg for msg in self.messages 
            if msg.role in [MessageRole.USER, MessageRole.ASSISTANT]
        ]
    
    def get_system_messages(self) -> List[ConversationMessage]:
        """獲取系統訊息"""
        return [
            msg for msg in self.messages 
            if msg.role == MessageRole.SYSTEM
        ]
    
    def clear_messages(self) -> None:
        """清空訊息記錄"""
        self.messages.clear()
        self.message_count = 0
        self.last_updated = datetime.now()
    
    def compress_messages(self, summary_message: ConversationMessage) -> int:
        """壓縮訊息，保留系統訊息和摘要"""
        system_messages = self.get_system_messages()
        user_assistant_count = len(self.get_user_assistant_messages())
        
        # 保留系統訊息和摘要
        self.messages = system_messages + [summary_message]
        self.message_count = len(self.messages)
        self.last_updated = datetime.now()
        
        return user_assistant_count
    
    def deactivate(self) -> None:
        """停用對話"""
        self.is_active = False
        self.last_updated = datetime.now()
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "id": self.id,
            "user_mail": self.user_mail,
            "messages": [msg.to_dict() for msg in self.messages],
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "message_count": self.message_count,
            "is_active": self.is_active
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Conversation':
        """從字典創建實例"""
        return cls(
            id=data["id"],
            user_mail=data["user_mail"],
            messages=[ConversationMessage.from_dict(msg_data) for msg_data in data["messages"]],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_updated=datetime.fromisoformat(data["last_updated"]),
            message_count=data["message_count"],
            is_active=data.get("is_active", True)
        )