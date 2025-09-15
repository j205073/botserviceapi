"""
共用工具函數
"""
import re
import time
import json
import asyncio
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import pytz


# 台灣時區
TAIWAN_TZ = pytz.timezone("Asia/Taipei")


def get_taiwan_time() -> datetime:
    """獲取台灣時間"""
    return datetime.now(TAIWAN_TZ)


def determine_language(user_mail: Optional[str]) -> str:
    """根據用戶郵箱判斷語言"""
    if not user_mail:
        return "zh-TW"
    
    # 簡單的語言判斷邏輯，可以根據需要擴展
    if any(domain in user_mail.lower() for domain in ['.jp', 'japan']):
        return "ja"
    elif any(domain in user_mail.lower() for domain in ['.vn', 'vietnam']):
        return "vi"
    else:
        return "zh-TW"


def clean_json_response(response_text: str) -> str:
    """清理 AI 回應中的 JSON"""
    if not response_text:
        return ""
    
    # 移除 markdown 代碼塊標記
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\n?', '', cleaned)
        cleaned = re.sub(r'\n?```$', '', cleaned)
    
    return cleaned.strip()


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """從文本中提取 JSON 對象"""
    try:
        # 首先嘗試直接解析
        return json.loads(text)
    except json.JSONDecodeError:
        # 嘗試提取 JSON 對象
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
    
    return None


def generate_id() -> str:
    """生成唯一 ID"""
    return f"{int(time.time())}{int(time.time() * 1000000) % 1000000}"


def safe_get(data: Dict[str, Any], key: str, default: Any = None) -> Any:
    """安全獲取字典值"""
    return data.get(key, default)


def truncate_text(text: str, max_length: int = 100) -> str:
    """截斷文本"""
    if not text:
        return ""
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length - 3] + "..."


class AsyncRetry:
    """異步重試裝飾器"""
    
    def __init__(
        self, 
        max_attempts: int = 3, 
        delay: float = 1.0, 
        backoff: float = 2.0,
        exceptions: tuple = (Exception,)
    ):
        self.max_attempts = max_attempts
        self.delay = delay
        self.backoff = backoff
        self.exceptions = exceptions
    
    def __call__(self, func):
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = self.delay
            
            for attempt in range(self.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except self.exceptions as e:
                    last_exception = e
                    if attempt == self.max_attempts - 1:
                        break
                    
                    print(f"嘗試 {attempt + 1} 失敗: {str(e)}, {current_delay:.1f}秒後重試")
                    await asyncio.sleep(current_delay)
                    current_delay *= self.backoff
            
            raise last_exception
        
        return wrapper


def validate_email(email: str) -> bool:
    """驗證郵箱格式"""
    if not email:
        return False
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def normalize_text(text: str) -> str:
    """標準化文本"""
    if not text:
        return ""
    
    # 去除多餘空白
    text = re.sub(r'\s+', ' ', text.strip())
    return text


def format_duration(seconds: float) -> str:
    """格式化時間長度"""
    if seconds < 1:
        return f"{seconds:.3f}s"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m{secs:.0f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h{minutes}m"


class PerformanceTimer:
    """性能計時器"""
    
    def __init__(self, name: str = "操作"):
        self.name = name
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = time.time()
        duration = end_time - self.start_time
        print(f"⏱️ {self.name} 耗時: {format_duration(duration)}")


def create_error_response(
    error_code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """創建標準錯誤回應"""
    response = {
        "success": False,
        "error_code": error_code,
        "message": message,
        "timestamp": get_taiwan_time().isoformat()
    }
    
    if details:
        response["details"] = details
    
    return response


def create_success_response(
    data: Optional[Any] = None,
    message: str = "操作成功"
) -> Dict[str, Any]:
    """創建標準成功回應"""
    response = {
        "success": True,
        "message": message,
        "timestamp": get_taiwan_time().isoformat()
    }
    
    if data is not None:
        response["data"] = data
    
    return response


async def get_user_email(turn_context) -> Optional[str]:
    """
    從 Teams/Bot Framework 取得目前使用者的郵箱。

    解析順序：
    1) 若 `from.id` 本身是郵箱則直接使用。
    2) 透過 Teams Roster API 取成員資訊（TeamsInfo.get_member）。
    3) 透過 AAD Object ID 呼叫 Microsoft Graph 取得 `mail`/`userPrincipalName`。

    備註：若環境未設好權限或 Graph 無法連線，將回傳 None，呼叫端需自行處理後備值。
    """
    try:
        # 1) 直接從 from.id 判斷（有些通道會帶 email）
        if getattr(turn_context, "activity", None) and getattr(turn_context.activity, "from_property", None):
            user_id = turn_context.activity.from_property.id
            if isinstance(user_id, str) and "@" in user_id:
                return user_id

        # 2) 優先用 Teams Roster 取 member.email
        try:
            from botbuilder.teams.teams_info import TeamsInfo  # 延遲載入避免非 Teams 環境報錯

            member = await TeamsInfo.get_member(turn_context, turn_context.activity.from_property.id)
            # TeamsChannelAccount 可能同時有 email 與 user_principal_name
            email = getattr(member, "email", None) or getattr(member, "user_principal_name", None)
            if email:
                return email
        except Exception:
            # 可能非 Teams 環境、或無權限；忽略並進入下一步
            pass

        # 3) 使用 AAD Object ID 向 Graph 查詢
        try:
            aad_object_id = getattr(turn_context.activity.from_property, "aad_object_id", None)
            if aad_object_id:
                # 透過組態建立 Graph API 用戶端（避免與 GraphAPIClient 的雙向依賴）
                from core.container import get_container
                from config.settings import AppConfig
                from token_manager import TokenManager as LegacyTokenManager
                from graph_api import GraphAPI

                container = get_container()
                cfg: AppConfig = container.get(AppConfig)

                tm = LegacyTokenManager(
                    cfg.graph_api.tenant_id,
                    cfg.graph_api.client_id,
                    cfg.graph_api.client_secret,
                )
                graph = GraphAPI(tm)
                user = await graph.get_user_info(aad_object_id)
                email = user.get("mail") or user.get("userPrincipalName")
                if email:
                    return email
        except Exception:
            # Graph 無法連線或權限不足時忽略
            pass

        return None
    except Exception as e:
        print(f"獲取用戶郵箱失敗: {e}")
        return None


def get_suggested_replies(user_message: str, user_mail: Optional[str] = None):
    """
    根據用戶消息生成建議回覆（回傳 CardAction 物件，供 SuggestedActions 使用）。

    注意：Bot Framework 的 SuggestedActions 需要 [CardAction]，
    不能是純字串，否則會出現反序列化錯誤。
    """
    # 延遲載入，避免在無 BotFramework 環境時導致 import 問題
    try:
        from botbuilder.schema import CardAction, ActionTypes
    except Exception:
        # 若無法導入（非運行於 Bot 環境），回退為純字串列表
        CardAction = None
        ActionTypes = None

    suggestions: List[str] = []

    # 根據消息內容提供建議
    message_lower = user_message.lower() if user_message else ""

    if "todo" in message_lower or "待辦" in message_lower:
        suggestions.extend(["@ls", "@add 新待辦事項"])

    if "meeting" in message_lower or "會議" in message_lower:
        suggestions.extend(["@book-room", "@check-booking"])

    if "help" in message_lower or "幫助" in message_lower:
        suggestions.extend(["@help", "@you"])

    # 默認建議
    if not suggestions:
        suggestions = ["@help", "@ls", "@book-room"]

    suggestions = suggestions[:3]

    # 如果可用，轉為 CardAction；否則回傳字串（供非 Bot 環境調試）
    if CardAction and ActionTypes:
        return [
            CardAction(title=s, type=ActionTypes.im_back, text=s)
            for s in suggestions
        ]
    else:
        return suggestions
