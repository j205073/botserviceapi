"""
稽核日誌 Repository
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime

from domain.models.audit import AuditLog, AuditLogEntry, MessageRole
from shared.exceptions import RepositoryError
from shared.utils.helpers import generate_id, get_taiwan_time


class AuditRepository(ABC):
    """稽核日誌 Repository 接口"""
    
    @abstractmethod
    async def create_entry(
        self, 
        conversation_id: str,
        user_mail: str,
        role: MessageRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLogEntry:
        """創建稽核日誌條目"""
        pass
    
    @abstractmethod
    async def get_user_log(self, user_mail: str) -> Optional[AuditLog]:
        """獲取用戶的稽核日誌"""
        pass
    
    @abstractmethod
    async def get_entries_by_conversation(
        self, 
        conversation_id: str
    ) -> List[AuditLogEntry]:
        """根據對話 ID 獲取稽核條目"""
        pass
    
    @abstractmethod
    async def get_entries_by_user_after(
        self, 
        user_mail: str, 
        after_timestamp: datetime
    ) -> List[AuditLogEntry]:
        """獲取用戶在指定時間後的稽核條目"""
        pass
    
    @abstractmethod
    async def clear_user_entries_before(
        self, 
        user_mail: str, 
        before_timestamp: datetime
    ) -> int:
        """清除用戶指定時間前的稽核條目"""
        pass
    
    @abstractmethod
    async def get_all_users_with_logs(self) -> List[str]:
        """獲取所有有稽核日誌的用戶"""
        pass
    
    @abstractmethod
    async def get_user_log_summary(self, user_mail: str) -> Dict[str, Any]:
        """獲取用戶稽核日誌摘要"""
        pass
    
    @abstractmethod
    async def export_user_logs(self, user_mail: str) -> List[Dict[str, Any]]:
        """匯出用戶稽核日誌"""
        pass


class InMemoryAuditRepository(AuditRepository):
    """記憶體中的稽核日誌 Repository 實現"""
    
    def __init__(self):
        self._user_logs: Dict[str, AuditLog] = {}
        self._entry_counter = 0
    
    async def create_entry(
        self, 
        conversation_id: str,
        user_mail: str,
        role: MessageRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLogEntry:
        """創建稽核日誌條目"""
        self._entry_counter += 1
        entry_id = f"audit_{self._entry_counter}_{int(get_taiwan_time().timestamp())}"
        
        entry = AuditLogEntry(
            id=entry_id,
            conversation_id=conversation_id,
            user_mail=user_mail,
            role=role,
            content=content,
            timestamp=get_taiwan_time(),
            metadata=metadata or {}
        )
        
        # 確保用戶日誌存在
        if user_mail not in self._user_logs:
            self._user_logs[user_mail] = AuditLog(
                user_mail=user_mail,
                entries=[],
                last_updated=get_taiwan_time()
            )
        
        # 添加條目
        self._user_logs[user_mail].add_entry(entry)
        
        return entry
    
    async def get_user_log(self, user_mail: str) -> Optional[AuditLog]:
        """獲取用戶的稽核日誌"""
        return self._user_logs.get(user_mail)
    
    async def get_entries_by_conversation(
        self, 
        conversation_id: str
    ) -> List[AuditLogEntry]:
        """根據對話 ID 獲取稽核條目"""
        entries = []
        
        for user_log in self._user_logs.values():
            conversation_entries = user_log.get_entries_by_conversation(conversation_id)
            entries.extend(conversation_entries)
        
        # 按時間排序
        entries.sort(key=lambda x: x.timestamp)
        return entries
    
    async def get_entries_by_user_after(
        self, 
        user_mail: str, 
        after_timestamp: datetime
    ) -> List[AuditLogEntry]:
        """獲取用戶在指定時間後的稽核條目"""
        user_log = await self.get_user_log(user_mail)
        if not user_log:
            return []
        
        return user_log.get_entries_after(after_timestamp)
    
    async def clear_user_entries_before(
        self, 
        user_mail: str, 
        before_timestamp: datetime
    ) -> int:
        """清除用戶指定時間前的稽核條目"""
        user_log = await self.get_user_log(user_mail)
        if not user_log:
            return 0
        
        return user_log.clear_entries_before(before_timestamp)
    
    async def get_all_users_with_logs(self) -> List[str]:
        """獲取所有有稽核日誌的用戶"""
        return list(self._user_logs.keys())
    
    async def get_user_log_summary(self, user_mail: str) -> Dict[str, Any]:
        """獲取用戶稽核日誌摘要"""
        user_log = await self.get_user_log(user_mail)
        if not user_log:
            return {
                "user_mail": user_mail,
                "total_entries": 0,
                "last_updated": None,
                "conversations": 0,
                "role_stats": {}
            }
        
        # 統計對話數量
        conversations = set()
        role_stats = {}
        
        for entry in user_log.entries:
            conversations.add(entry.conversation_id)
            role_key = entry.role.value
            role_stats[role_key] = role_stats.get(role_key, 0) + 1
        
        return {
            "user_mail": user_mail,
            "total_entries": len(user_log.entries),
            "last_updated": user_log.last_updated.isoformat(),
            "conversations": len(conversations),
            "role_stats": role_stats
        }
    
    async def export_user_logs(self, user_mail: str) -> List[Dict[str, Any]]:
        """匯出用戶稽核日誌"""
        user_log = await self.get_user_log(user_mail)
        if not user_log:
            return []
        
        return [entry.to_dict() for entry in user_log.entries]
    
    async def get_logs_for_upload(self) -> Dict[str, AuditLog]:
        """獲取需要上傳的日誌（所有日誌）"""
        return self._user_logs.copy()
    
    async def clear_uploaded_logs(self, user_mails: List[str]) -> None:
        """清除已上傳的日誌"""
        for user_mail in user_mails:
            if user_mail in self._user_logs:
                self._user_logs[user_mail].entries.clear()
                self._user_logs[user_mail].last_updated = get_taiwan_time()