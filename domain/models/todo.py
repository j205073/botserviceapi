"""
待辦事項數據模型
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum


class TodoStatus(Enum):
    """待辦事項狀態"""
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TodoItem:
    """待辦事項"""
    id: str
    user_mail: str
    content: str
    status: TodoStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    
    @property
    def is_pending(self) -> bool:
        """是否為待處理狀態"""
        return self.status == TodoStatus.PENDING
    
    @property
    def is_completed(self) -> bool:
        """是否已完成"""
        return self.status == TodoStatus.COMPLETED
    
    @property
    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self.status == TodoStatus.CANCELLED
    
    def mark_completed(self, completed_at: Optional[datetime] = None) -> None:
        """標記為已完成"""
        self.status = TodoStatus.COMPLETED
        self.completed_at = completed_at or datetime.now()
    
    def mark_cancelled(self, cancelled_at: Optional[datetime] = None) -> None:
        """標記為已取消"""
        self.status = TodoStatus.CANCELLED
        self.cancelled_at = cancelled_at or datetime.now()
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "id": self.id,
            "user_mail": self.user_mail,
            "content": self.content,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TodoItem':
        """從字典創建實例"""
        return cls(
            id=data["id"],
            user_mail=data["user_mail"],
            content=data["content"],
            status=TodoStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            cancelled_at=datetime.fromisoformat(data["cancelled_at"]) if data.get("cancelled_at") else None,
        )