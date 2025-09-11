"""
待辦事項 Repository
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime
import time

from domain.models.todo import TodoItem, TodoStatus
from shared.exceptions import RepositoryError, NotFoundError
from shared.utils.helpers import generate_id, get_taiwan_time


class TodoRepository(ABC):
    """待辦事項 Repository 接口"""
    
    @abstractmethod
    async def create(self, user_mail: str, content: str) -> TodoItem:
        """創建待辦事項"""
        pass
    
    @abstractmethod
    async def get_by_id(self, todo_id: str) -> Optional[TodoItem]:
        """根據 ID 獲取待辦事項"""
        pass
    
    @abstractmethod
    async def get_by_user(self, user_mail: str) -> List[TodoItem]:
        """獲取用戶的所有待辦事項"""
        pass
    
    @abstractmethod
    async def get_pending_by_user(self, user_mail: str) -> List[TodoItem]:
        """獲取用戶的待辦事項（僅未完成）"""
        pass
    
    @abstractmethod
    async def update(self, todo: TodoItem) -> TodoItem:
        """更新待辦事項"""
        pass
    
    @abstractmethod
    async def delete(self, todo_id: str) -> bool:
        """刪除待辦事項"""
        pass
    
    @abstractmethod
    async def mark_completed(self, todo_id: str) -> Optional[TodoItem]:
        """標記待辦事項為已完成"""
        pass
    
    @abstractmethod
    async def clean_old_todos(self, before_date: datetime) -> int:
        """清理舊的待辦事項"""
        pass
    
    @abstractmethod
    async def get_user_stats(self, user_mail: str) -> Dict[str, int]:
        """獲取用戶統計信息"""
        pass


class InMemoryTodoRepository(TodoRepository):
    """記憶體中的待辦事項 Repository 實現"""
    
    def __init__(self):
        self._todos: Dict[str, TodoItem] = {}
        self._user_todos: Dict[str, List[str]] = {}  # user_mail -> [todo_ids]
        self._counter = 0
    
    async def create(self, user_mail: str, content: str) -> TodoItem:
        """創建待辦事項"""
        self._counter += 1
        todo_id = f"{int(time.time())}_{self._counter}"
        
        todo = TodoItem(
            id=todo_id,
            user_mail=user_mail,
            content=content.strip(),
            status=TodoStatus.PENDING,
            created_at=get_taiwan_time()
        )
        
        self._todos[todo_id] = todo
        
        # 更新用戶待辦事項列表
        if user_mail not in self._user_todos:
            self._user_todos[user_mail] = []
        self._user_todos[user_mail].append(todo_id)
        
        return todo
    
    async def get_by_id(self, todo_id: str) -> Optional[TodoItem]:
        """根據 ID 獲取待辦事項"""
        return self._todos.get(todo_id)
    
    async def get_by_user(self, user_mail: str) -> List[TodoItem]:
        """獲取用戶的所有待辦事項"""
        todo_ids = self._user_todos.get(user_mail, [])
        todos = []
        
        for todo_id in todo_ids:
            if todo_id in self._todos:
                todos.append(self._todos[todo_id])
        
        # 按創建時間排序
        todos.sort(key=lambda x: x.created_at)
        return todos
    
    async def get_pending_by_user(self, user_mail: str) -> List[TodoItem]:
        """獲取用戶的待辦事項（僅未完成）"""
        all_todos = await self.get_by_user(user_mail)
        return [todo for todo in all_todos if todo.is_pending]
    
    async def update(self, todo: TodoItem) -> TodoItem:
        """更新待辦事項"""
        if todo.id not in self._todos:
            raise NotFoundError(f"待辦事項 {todo.id} 不存在")
        
        self._todos[todo.id] = todo
        return todo
    
    async def delete(self, todo_id: str) -> bool:
        """刪除待辦事項"""
        if todo_id not in self._todos:
            return False
        
        todo = self._todos[todo_id]
        del self._todos[todo_id]
        
        # 從用戶列表中移除
        if todo.user_mail in self._user_todos:
            try:
                self._user_todos[todo.user_mail].remove(todo_id)
            except ValueError:
                pass
        
        return True
    
    async def mark_completed(self, todo_id: str) -> Optional[TodoItem]:
        """標記待辦事項為已完成"""
        todo = await self.get_by_id(todo_id)
        if not todo:
            return None
        
        todo.mark_completed()
        return await self.update(todo)
    
    async def clean_old_todos(self, before_date: datetime) -> int:
        """清理舊的待辦事項"""
        cleaned_count = 0
        todos_to_delete = []
        
        for todo_id, todo in self._todos.items():
            if todo.created_at < before_date:
                todos_to_delete.append(todo_id)
        
        for todo_id in todos_to_delete:
            if await self.delete(todo_id):
                cleaned_count += 1
        
        return cleaned_count
    
    async def get_user_stats(self, user_mail: str) -> Dict[str, int]:
        """獲取用戶統計信息"""
        todos = await self.get_by_user(user_mail)
        
        stats = {
            "total": len(todos),
            "pending": sum(1 for todo in todos if todo.is_pending),
            "completed": sum(1 for todo in todos if todo.is_completed),
            "cancelled": sum(1 for todo in todos if todo.is_cancelled)
        }
        
        return stats
    
    async def get_all_users_with_todos(self) -> List[str]:
        """獲取所有有待辦事項的用戶"""
        return list(self._user_todos.keys())
    
    async def batch_mark_completed(self, todo_ids: List[str]) -> List[TodoItem]:
        """批量標記待辦事項為已完成"""
        completed_todos = []
        
        for todo_id in todo_ids:
            todo = await self.mark_completed(todo_id)
            if todo:
                completed_todos.append(todo)
        
        return completed_todos