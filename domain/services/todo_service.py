"""
待辦事項業務邏輯服務
重構自原始 app.py 中的待辦事項相關功能
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from domain.models.todo import TodoItem, TodoStatus
from domain.repositories.todo_repository import TodoRepository
from config.settings import AppConfig
from shared.exceptions import BusinessLogicError, NotFoundError
from shared.utils.helpers import get_taiwan_time


class TodoSimilarityAnalyzer:
    """待辦事項相似度分析器"""
    
    @staticmethod
    def extract_features(content: str) -> Dict[str, Any]:
        """提取待辦事項的特徵"""
        content_lower = content.lower()
        
        # 時間相關關鍵字
        time_keywords = [
            "下午", "上午", "晚上", "早上", "今天", "明天", "後天",
            "週一", "週二", "週三", "週四", "週五", "週六", "週日",
            "月份", "小時", "分鐘", "點", "時", "分", "秒"
        ]
        
        # 動作關鍵字
        action_keywords = [
            "討論", "開會", "會議", "聯絡", "打電話", "發信", "寫",
            "完成", "處理", "檢查", "確認", "準備"
        ]
        
        # 提取人員（簡單的中文姓名或英文名模式）
        import re
        person_pattern = r"([A-Za-z]+|[\u4e00-\u9fff]{2,4})"
        potential_persons = re.findall(person_pattern, content)
        persons = [p for p in potential_persons if len(p) >= 2]
        
        return {
            "time_mentioned": any(keyword in content_lower for keyword in time_keywords),
            "persons": persons,
            "actions": [keyword for keyword in action_keywords if keyword in content_lower],
            "content_words": set(content_lower.split()),
        }
    
    @staticmethod
    def calculate_similarity(content1: str, content2: str) -> float:
        """計算兩個待辦事項的相似度（0-1之間）"""
        features1 = TodoSimilarityAnalyzer.extract_features(content1)
        features2 = TodoSimilarityAnalyzer.extract_features(content2)
        
        similarity_score = 0
        weight_total = 0
        
        # 人員相似度（權重：0.4）
        person_weight = 0.4
        if features1["persons"] or features2["persons"]:
            common_persons = set(features1["persons"]) & set(features2["persons"])
            total_persons = set(features1["persons"]) | set(features2["persons"])
            if total_persons:
                person_similarity = len(common_persons) / len(total_persons)
                similarity_score += person_similarity * person_weight
            weight_total += person_weight
        
        # 動作相似度（權重：0.3）
        action_weight = 0.3
        if features1["actions"] or features2["actions"]:
            common_actions = set(features1["actions"]) & set(features2["actions"])
            total_actions = set(features1["actions"]) | set(features2["actions"])
            if total_actions:
                action_similarity = len(common_actions) / len(total_actions)
                similarity_score += action_similarity * action_weight
            weight_total += action_weight
        
        # 內容詞彙相似度（權重：0.2）
        content_weight = 0.2
        common_words = features1["content_words"] & features2["content_words"]
        total_words = features1["content_words"] | features2["content_words"]
        if total_words:
            content_similarity = len(common_words) / len(total_words)
            similarity_score += content_similarity * content_weight
        weight_total += content_weight
        
        # 時間特徵相似度（權重：0.1）
        time_weight = 0.1
        if features1["time_mentioned"] == features2["time_mentioned"]:
            similarity_score += time_weight
        weight_total += time_weight
        
        # 正規化分數
        if weight_total > 0:
            return similarity_score / weight_total
        return 0


class TodoService:
    """待辦事項業務邏輯服務"""
    
    def __init__(self, config: AppConfig, todo_repository: TodoRepository):
        self.config = config
        self.todo_repository = todo_repository
        self.similarity_threshold = 0.6  # 相似度閾值
    
    async def create_todo(self, user_mail: str, content: str) -> TodoItem:
        """創建待辦事項"""
        if not content or not content.strip():
            raise BusinessLogicError("待辦事項內容不能為空")
        
        if len(content.strip()) > 500:
            raise BusinessLogicError("待辦事項內容過長（最多 500 字符）")
        
        # 檢查用戶是否已有太多待辦事項
        existing_todos = await self.todo_repository.get_pending_by_user(user_mail)
        if len(existing_todos) >= 50:  # 限制最多 50 個待辦事項
            raise BusinessLogicError("待辦事項過多，請先完成一些現有事項")
        
        return await self.todo_repository.create(user_mail, content.strip())
    
    async def smart_create_todo(self, user_mail: str, content: str) -> Tuple[TodoItem, List[Dict[str, Any]]]:
        """
        智能創建待辦事項，包含相似性檢查
        返回：(創建的待辦事項, 相似的待辦事項列表)
        """
        if not content or not content.strip():
            raise BusinessLogicError("待辦事項內容不能為空")
        
        # 檢查相似的待辦事項
        similar_todos = await self.check_similar_todos(user_mail, content.strip())
        
        # 如果有相似的待辦事項，返回相似項目但不創建
        if similar_todos:
            return None, similar_todos
        
        # 沒有相似項目，直接創建
        todo = await self.create_todo(user_mail, content.strip())
        return todo, []
    
    async def check_similar_todos(self, user_mail: str, content: str) -> List[Dict[str, Any]]:
        """檢查是否有相似的待辦事項"""
        pending_todos = await self.todo_repository.get_pending_by_user(user_mail)
        similar_todos = []
        
        for todo in pending_todos:
            similarity = TodoSimilarityAnalyzer.calculate_similarity(content, todo.content)
            if similarity > self.similarity_threshold:
                similar_todos.append({
                    "todo": todo,
                    "similarity": similarity,
                    "similarity_percent": int(similarity * 100)
                })
        
        # 按相似度排序
        similar_todos.sort(key=lambda x: x["similarity"], reverse=True)
        return similar_todos[:3]  # 最多返回 3 個相似項目
    
    async def get_user_todos(self, user_mail: str, include_completed: bool = False) -> List[TodoItem]:
        """獲取用戶的待辦事項"""
        if include_completed:
            return await self.todo_repository.get_by_user(user_mail)
        else:
            return await self.todo_repository.get_pending_by_user(user_mail)
    
    async def complete_todo(self, todo_id: str, user_mail: Optional[str] = None) -> TodoItem:
        """完成待辦事項"""
        todo = await self.todo_repository.get_by_id(todo_id)
        if not todo:
            raise NotFoundError(f"待辦事項 {todo_id} 不存在")
        
        # 驗證用戶權限
        if user_mail and todo.user_mail != user_mail:
            raise BusinessLogicError("無權限操作此待辦事項")
        
        if todo.is_completed:
            raise BusinessLogicError("待辦事項已完成")
        
        completed_todo = await self.todo_repository.mark_completed(todo_id)
        if not completed_todo:
            raise BusinessLogicError("完成待辦事項失敗")
        
        return completed_todo
    
    async def batch_complete_todos(self, todo_indices: List[int], user_mail: str) -> List[TodoItem]:
        """批量完成待辦事項（根據索引）"""
        pending_todos = await self.todo_repository.get_pending_by_user(user_mail)
        
        if not pending_todos:
            raise BusinessLogicError("沒有待辦事項可完成")
        
        completed_todos = []
        
        for index in todo_indices:
            # 檢查索引範圍
            if 0 <= index < len(pending_todos):
                todo = pending_todos[index]
                try:
                    completed_todo = await self.complete_todo(todo.id, user_mail)
                    completed_todos.append(completed_todo)
                except Exception as e:
                    print(f"完成待辦事項 {todo.id} 失敗: {e}")
        
        return completed_todos
    
    async def delete_todo(self, todo_id: str, user_mail: Optional[str] = None) -> bool:
        """刪除待辦事項"""
        todo = await self.todo_repository.get_by_id(todo_id)
        if not todo:
            return False
        
        # 驗證用戶權限
        if user_mail and todo.user_mail != user_mail:
            raise BusinessLogicError("無權限操作此待辦事項")
        
        return await self.todo_repository.delete(todo_id)
    
    async def get_user_stats(self, user_mail: str) -> Dict[str, Any]:
        """獲取用戶統計信息"""
        stats = await self.todo_repository.get_user_stats(user_mail)
        
        # 添加額外統計信息
        todos = await self.todo_repository.get_by_user(user_mail)
        
        if todos:
            # 計算平均完成時間
            completed_todos = [t for t in todos if t.is_completed and t.completed_at]
            if completed_todos:
                total_completion_time = sum(
                    (t.completed_at - t.created_at).total_seconds() 
                    for t in completed_todos
                )
                avg_completion_hours = total_completion_time / len(completed_todos) / 3600
                stats["average_completion_hours"] = round(avg_completion_hours, 2)
            
            # 最近 7 天的活動
            week_ago = get_taiwan_time() - timedelta(days=7)
            recent_todos = [t for t in todos if t.created_at >= week_ago]
            stats["recent_week_count"] = len(recent_todos)
        
        return stats
    
    async def clean_old_todos(self, retention_days: Optional[int] = None) -> Dict[str, int]:
        """清理舊的待辦事項"""
        days = retention_days or self.config.database.retention_days
        cutoff_date = get_taiwan_time() - timedelta(days=days)
        
        cleaned_count = await self.todo_repository.clean_old_todos(cutoff_date)
        
        return {
            "cleaned_count": cleaned_count,
            "cutoff_date": cutoff_date.isoformat(),
            "retention_days": days
        }
    
    async def get_todos_for_reminder(self) -> Dict[str, List[TodoItem]]:
        """獲取需要提醒的待辦事項（按用戶分組）"""
        # 獲取所有有待辦事項的用戶
        all_users = await self.todo_repository.get_all_users_with_todos()
        
        reminders = {}
        for user_mail in all_users:
            pending_todos = await self.todo_repository.get_pending_by_user(user_mail)
            if pending_todos:
                reminders[user_mail] = pending_todos
        
        return reminders
    
    async def search_todos(
        self, 
        user_mail: str, 
        keyword: Optional[str] = None,
        status: Optional[TodoStatus] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[TodoItem]:
        """搜索待辦事項"""
        todos = await self.todo_repository.get_by_user(user_mail)
        
        # 應用過濾條件
        filtered_todos = todos
        
        if keyword:
            keyword_lower = keyword.lower()
            filtered_todos = [
                todo for todo in filtered_todos 
                if keyword_lower in todo.content.lower()
            ]
        
        if status:
            filtered_todos = [
                todo for todo in filtered_todos 
                if todo.status == status
            ]
        
        if date_from:
            filtered_todos = [
                todo for todo in filtered_todos 
                if todo.created_at >= date_from
            ]
        
        if date_to:
            filtered_todos = [
                todo for todo in filtered_todos 
                if todo.created_at <= date_to
            ]
        
        return filtered_todos