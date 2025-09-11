"""
用戶數據模型
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from botbuilder.schema import ConversationReference


@dataclass
class UserProfile:
    """用戶資料"""
    email: str
    display_name: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None
    preferred_language: str = "zh-TW"
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def update_activity(self) -> None:
        """更新最後活動時間"""
        self.last_active = datetime.now()
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "email": self.email,
            "display_name": self.display_name,
            "department": self.department,
            "title": self.title,
            "preferred_language": self.preferred_language,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'UserProfile':
        """從字典創建實例"""
        return cls(
            email=data["email"],
            display_name=data.get("display_name"),
            department=data.get("department"),
            title=data.get("title"),
            preferred_language=data.get("preferred_language", "zh-TW"),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_active=datetime.fromisoformat(data["last_active"]),
            metadata=data.get("metadata", {})
        )


@dataclass
class UserSession:
    """用戶會話"""
    user_mail: str
    conversation_reference: Optional[ConversationReference] = None
    model_preference: Optional[str] = None
    session_data: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    
    def update_model_preference(self, model: str) -> None:
        """更新模型偏好"""
        self.model_preference = model
        self.last_updated = datetime.now()
    
    def update_conversation_reference(self, ref: ConversationReference) -> None:
        """更新對話參考"""
        self.conversation_reference = ref
        self.last_updated = datetime.now()
    
    def set_session_data(self, key: str, value: Any) -> None:
        """設置會話數據"""
        self.session_data[key] = value
        self.last_updated = datetime.now()
    
    def get_session_data(self, key: str, default: Any = None) -> Any:
        """獲取會話數據"""
        return self.session_data.get(key, default)
    
    def clear_session_data(self) -> None:
        """清空會話數據"""
        self.session_data.clear()
        self.last_updated = datetime.now()
    
    def to_dict(self) -> dict:
        """轉換為字典 (不包含 ConversationReference，因為它不能直接序列化)"""
        return {
            "user_mail": self.user_mail,
            "model_preference": self.model_preference,
            "session_data": self.session_data,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "has_conversation_reference": self.conversation_reference is not None
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'UserSession':
        """從字典創建實例"""
        return cls(
            user_mail=data["user_mail"],
            model_preference=data.get("model_preference"),
            session_data=data.get("session_data", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_updated=datetime.fromisoformat(data["last_updated"])
        )