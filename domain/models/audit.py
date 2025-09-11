"""
稽核日誌數據模型
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class MessageRole(Enum):
    """訊息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class AuditLogEntry:
    """稽核日誌條目"""
    id: str
    conversation_id: str
    user_mail: str
    role: MessageRole
    content: str
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_mail": self.user_mail,
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata or {}
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AuditLogEntry':
        """從字典創建實例"""
        return cls(
            id=data["id"],
            conversation_id=data["conversation_id"],
            user_mail=data["user_mail"],
            role=MessageRole(data["role"]),
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata")
        )


@dataclass
class AuditLog:
    """用戶稽核日誌集合"""
    user_mail: str
    entries: list[AuditLogEntry]
    last_updated: datetime
    
    def add_entry(self, entry: AuditLogEntry) -> None:
        """添加條目"""
        self.entries.append(entry)
        self.last_updated = datetime.now()
    
    def get_entries_by_conversation(self, conversation_id: str) -> list[AuditLogEntry]:
        """獲取特定對話的條目"""
        return [entry for entry in self.entries if entry.conversation_id == conversation_id]
    
    def get_entries_after(self, timestamp: datetime) -> list[AuditLogEntry]:
        """獲取指定時間後的條目"""
        return [entry for entry in self.entries if entry.timestamp > timestamp]
    
    def clear_entries_before(self, timestamp: datetime) -> int:
        """清除指定時間前的條目，返回清除數量"""
        original_count = len(self.entries)
        self.entries = [entry for entry in self.entries if entry.timestamp >= timestamp]
        return original_count - len(self.entries)
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "user_mail": self.user_mail,
            "entries": [entry.to_dict() for entry in self.entries],
            "last_updated": self.last_updated.isoformat(),
            "entry_count": len(self.entries)
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AuditLog':
        """從字典創建實例"""
        return cls(
            user_mail=data["user_mail"],
            entries=[AuditLogEntry.from_dict(entry_data) for entry_data in data["entries"]],
            last_updated=datetime.fromisoformat(data["last_updated"])
        )