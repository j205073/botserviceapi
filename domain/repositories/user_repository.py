"""
用戶 Repository
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime
from botbuilder.schema import ConversationReference

from domain.models.user import UserProfile, UserSession
from shared.exceptions import RepositoryError, NotFoundError
from shared.utils.helpers import get_taiwan_time
from infrastructure.external.graph_api_client import GraphAPIClient


class UserRepository(ABC):
    """用戶 Repository 接口"""
    
    @abstractmethod
    async def create_profile(self, email: str, **kwargs) -> UserProfile:
        """創建用戶資料"""
        pass
    
    @abstractmethod
    async def get_profile(self, email: str) -> Optional[UserProfile]:
        """獲取用戶資料"""
        pass
    
    @abstractmethod
    async def update_profile(self, profile: UserProfile) -> UserProfile:
        """更新用戶資料"""
        pass
    
    @abstractmethod
    async def delete_profile(self, email: str) -> bool:
        """刪除用戶資料"""
        pass
    
    @abstractmethod
    async def create_session(self, user_mail: str) -> UserSession:
        """創建用戶會話"""
        pass
    
    @abstractmethod
    async def get_session(self, user_mail: str) -> Optional[UserSession]:
        """獲取用戶會話"""
        pass
    
    @abstractmethod
    async def update_session(self, session: UserSession) -> UserSession:
        """更新用戶會話"""
        pass
    
    @abstractmethod
    async def delete_session(self, user_mail: str) -> bool:
        """刪除用戶會話"""
        pass
    
    @abstractmethod
    async def get_all_profiles(self) -> List[UserProfile]:
        """獲取所有用戶資料"""
        pass
    
    @abstractmethod
    async def get_active_sessions(self) -> List[UserSession]:
        """獲取所有活躍會話"""
        pass
    
    @abstractmethod
    async def update_user_activity(self, email: str) -> None:
        """更新用戶活動時間"""
        pass


class InMemoryUserRepository(UserRepository):
    """記憶體中的用戶 Repository 實現"""
    
    def __init__(self, graph_client: GraphAPIClient):
        self._profiles: Dict[str, UserProfile] = {}
        self._sessions: Dict[str, UserSession] = {}
        self._display_names: Dict[str, str] = {}  # email -> display_name cache
        self.graph_client = graph_client
    
    async def create_profile(self, email: str, **kwargs) -> UserProfile:
        """創建用戶資料（優先從 Graph API 讀取）。"""
        if email in self._profiles:
            raise RepositoryError(f"用戶 {email} 已存在")

        display_name = kwargs.get('display_name')
        department = kwargs.get('department')
        title = kwargs.get('title')
        metadata = kwargs.get('metadata', {})
        preferred_language = kwargs.get('preferred_language', 'zh-TW')

        # 從 Graph 取得用戶資訊
        try:
            info = await self.graph_client.get_user_info(email)
            if info:
                display_name = info.get('displayName') or display_name
                department = info.get('department') or department
                title = info.get('jobTitle') or title
                # 保留部分欄位於 metadata，避免模型膨脹
                metadata.update({
                    'userPrincipalName': info.get('userPrincipalName'),
                    'mail': info.get('mail'),
                    'officeLocation': info.get('officeLocation'),
                })
        except Exception as e:
            # 失敗時採用備援：以 email 前綴當作名稱
            if not display_name and '@' in email:
                display_name = email.split('@')[0]

        profile = UserProfile(
            email=email,
            display_name=display_name,
            department=department,
            title=title,
            preferred_language=preferred_language,
            created_at=get_taiwan_time(),
            last_active=get_taiwan_time(),
            metadata=metadata
        )

        self._profiles[email] = profile

        # 更新顯示名稱快取
        if profile.display_name:
            self._display_names[email] = profile.display_name

        return profile
    
    async def get_profile(self, email: str) -> Optional[UserProfile]:
        """獲取用戶資料"""
        return self._profiles.get(email)
    
    async def update_profile(self, profile: UserProfile) -> UserProfile:
        """更新用戶資料"""
        if profile.email not in self._profiles:
            raise NotFoundError(f"用戶 {profile.email} 不存在")
        
        self._profiles[profile.email] = profile
        
        # 更新顯示名稱快取
        if profile.display_name:
            self._display_names[profile.email] = profile.display_name
        
        return profile
    
    async def delete_profile(self, email: str) -> bool:
        """刪除用戶資料"""
        if email in self._profiles:
            del self._profiles[email]
            if email in self._display_names:
                del self._display_names[email]
            return True
        return False

    async def clear_profiles(self) -> None:
        """清空所有用戶資料與顯示名稱快取（管理用途）。"""
        self._profiles.clear()
        self._display_names.clear()
    
    async def create_session(self, user_mail: str) -> UserSession:
        """創建用戶會話"""
        session = UserSession(
            user_mail=user_mail,
            created_at=get_taiwan_time(),
            last_updated=get_taiwan_time()
        )
        
        self._sessions[user_mail] = session
        return session
    
    async def get_session(self, user_mail: str) -> Optional[UserSession]:
        """獲取用戶會話"""
        return self._sessions.get(user_mail)
    
    async def update_session(self, session: UserSession) -> UserSession:
        """更新用戶會話"""
        self._sessions[session.user_mail] = session
        return session
    
    async def delete_session(self, user_mail: str) -> bool:
        """刪除用戶會話"""
        if user_mail in self._sessions:
            del self._sessions[user_mail]
            return True
        return False

    async def clear_sessions(self) -> None:
        """清空所有用戶會話（管理用途）。"""
        self._sessions.clear()

    async def purge_inactive_profiles(self, inactive_days: int = 30) -> int:
        """清除超過指定天數未活動的用戶資料，回傳清除數量。"""
        cutoff = get_taiwan_time()
        to_delete = [
            email for email, profile in self._profiles.items()
            if (cutoff - profile.last_active).days >= inactive_days
        ]
        for email in to_delete:
            await self.delete_profile(email)
        return len(to_delete)
    
    async def get_all_profiles(self) -> List[UserProfile]:
        """獲取所有用戶資料"""
        return list(self._profiles.values())
    
    async def get_active_sessions(self) -> List[UserSession]:
        """獲取所有活躍會話"""
        return list(self._sessions.values())
    
    async def update_user_activity(self, email: str) -> None:
        """更新用戶活動時間"""
        profile = await self.get_profile(email)
        if profile:
            profile.update_activity()
    
    async def get_or_create_profile(
        self, 
        email: str, 
        **defaults
    ) -> UserProfile:
        """獲取或創建用戶資料"""
        profile = await self.get_profile(email)
        if profile:
            await self.update_user_activity(email)
            return profile
        
        return await self.create_profile(email, **defaults)
    
    async def get_or_create_session(self, user_mail: str) -> UserSession:
        """獲取或創建用戶會話"""
        session = await self.get_session(user_mail)
        if session:
            return session
        
        return await self.create_session(user_mail)
    
    async def set_conversation_reference(
        self, 
        user_mail: str, 
        conversation_ref: ConversationReference
    ) -> None:
        """設置用戶對話參考"""
        session = await self.get_or_create_session(user_mail)
        session.update_conversation_reference(conversation_ref)
    
    async def get_conversation_reference(
        self, 
        user_mail: str
    ) -> Optional[ConversationReference]:
        """獲取用戶對話參考"""
        session = await self.get_session(user_mail)
        return session.conversation_reference if session else None
    
    async def set_model_preference(self, user_mail: str, model: str) -> None:
        """設置用戶模型偏好"""
        session = await self.get_or_create_session(user_mail)
        session.update_model_preference(model)
    
    async def get_model_preference(self, user_mail: str) -> Optional[str]:
        """獲取用戶模型偏好"""
        session = await self.get_session(user_mail)
        return session.model_preference if session else None
    
    async def get_display_name(self, email: str) -> Optional[str]:
        """獲取用戶顯示名稱"""
        return self._display_names.get(email)
    
    async def set_display_name(self, email: str, display_name: str) -> None:
        """設置用戶顯示名稱"""
        self._display_names[email] = display_name
        
        # 同時更新資料
        profile = await self.get_profile(email)
        if profile:
            profile.display_name = display_name
    
    async def get_user_stats(self) -> Dict[str, Any]:
        """獲取用戶統計信息"""
        return {
            "total_profiles": len(self._profiles),
            "total_sessions": len(self._sessions),
            "users_with_display_names": len(self._display_names),
            "recent_active_users": len([
                p for p in self._profiles.values() 
                if (get_taiwan_time() - p.last_active).days <= 7
            ])
        }
