"""
Bot 相關的數據傳輸對象 (DTOs)
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass
class BotInteractionDTO:
    """Bot 互動數據傳輸對象"""
    user_id: str
    user_name: Optional[str]
    user_mail: str
    conversation_id: str
    message_text: str
    card_action: Optional[str] = None
    card_data: Optional[Dict[str, Any]] = None


@dataclass
class CommandExecutionDTO:
    """命令執行數據傳輸對象"""
    command: str
    parameters: List[str]
    user_mail: str
    conversation_id: str
    raw_message: str
    
    @classmethod
    def parse_command(cls, message: str, user_mail: str, conversation_id: str) -> 'CommandExecutionDTO':
        """解析命令"""
        if not message.startswith('@'):
            raise ValueError("不是有效的命令格式")
        
        parts = message[1:].split()
        command = parts[0] if parts else ""
        parameters = parts[1:] if len(parts) > 1 else []
        
        return cls(
            command=command,
            parameters=parameters,
            user_mail=user_mail,
            conversation_id=conversation_id,
            raw_message=message
        )


@dataclass
class ChatResponseDTO:
    """聊天回應數據傳輸對象"""
    text: str
    suggested_actions: Optional[List[str]] = None
    card_attachment: Optional[Dict[str, Any]] = None
    requires_followup: bool = False


@dataclass
class TodoActionDTO:
    """待辦事項操作數據傳輸對象"""
    action_type: str  # add, complete, list, delete
    content: Optional[str] = None
    todo_ids: Optional[List[str]] = None
    todo_indices: Optional[List[int]] = None


@dataclass
class MeetingActionDTO:
    """會議操作數據傳輸對象"""
    action_type: str  # book, cancel, list
    room_id: Optional[str] = None
    subject: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    date: Optional[str] = None
    attendees: Optional[str] = None
    meeting_id: Optional[str] = None


@dataclass
class IntentAnalysisDTO:
    """意圖分析數據傳輸對象"""
    intent: str
    confidence: float
    entities: Dict[str, Any]
    original_message: str
    suggested_action: Optional[str] = None


@dataclass
class UserContextDTO:
    """用戶上下文數據傳輸對象"""
    user_mail: str
    conversation_id: str
    language: str
    model_preference: Optional[str] = None
    recent_messages: Optional[List[str]] = None