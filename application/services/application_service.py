"""
應用程式服務協調器（ApplicationService）

定位與職責
- 作為應用層的流程協調器（Orchestrator / Facade），將多個領域服務（Todo、Meeting、Conversation、Audit）
  與基礎設施（OpenAI、Graph、S3）串接成「穩定、可重用」的應用介面，供上層（Bot、API、排程）呼叫。
- 提供統一入口點以便：
  1) 降低呼叫端對各服務細節的耦合
  2) 集中處理跨服務的流程、錯誤處理、日誌/稽核與權限檢查
  3) 讓未來新增介面（REST/CLI/Job）可以重用相同邏輯

目前使用情境
- `app.py` 的 `call_openai()` 會透過 DI 取得 `ApplicationService` 並呼叫 `process_user_message()`
  作為對話/意圖分析的統一協調入口。
- `execute_todo_workflow()` 與 `execute_meeting_workflow()` 為「預留的應用層工作流程入口」，
  目前主要由 Presentation 層直接呼叫領域服務；日後如要開 API 或其他程式，可直接調用這兩個方法。

設計建議
- Presentation/Bot/UI 僅處理 I/O 與資料展示；業務流程盡量封裝在 ApplicationService
  （或領域服務）中，讓行為可被多種介面重用。
"""
from typing import Dict, Any, Optional, List
from datetime import datetime

from domain.services.todo_service import TodoService
from domain.services.conversation_service import ConversationService
from domain.services.meeting_service import MeetingService
from domain.services.intent_service import IntentService
from domain.services.audit_service import AuditService
from infrastructure.external.openai_client import OpenAIClient
from infrastructure.external.graph_api_client import GraphAPIClient
from infrastructure.external.s3_client import S3Client
from config.settings import AppConfig
from shared.exceptions import BusinessLogicError
from shared.utils.helpers import get_taiwan_time


class ApplicationService:
    """應用程式服務協調器

    目的
    - 將「待辦、會議、對話、稽核」等跨服務流程整合為穩定方法，供外部程式直接使用。

    使用方式（透過 DI 取得）
    - container.get(ApplicationService)
    - await application_service.process_user_message(user_mail, message, conversation_id)
    - await application_service.execute_todo_workflow(user_mail, "create", content="...")
    - await application_service.execute_meeting_workflow(user_mail, "list_bookings")

    注意
    - 請在此層做跨服務的組合、錯誤與稽核處理，不要把純展示邏輯放進來。
    - 實際資料存取與業務規則仍以「領域服務（TodoService/MeetingService/...）」為主。
    """
    
    def __init__(
        self,
        config: AppConfig,
        todo_service: TodoService,
        conversation_service: ConversationService,
        meeting_service: MeetingService,
        intent_service: IntentService,
        audit_service: AuditService,
        openai_client: OpenAIClient,
        graph_client: GraphAPIClient,
        s3_client: S3Client
    ):
        self.config = config
        self.todo_service = todo_service
        self.conversation_service = conversation_service
        self.meeting_service = meeting_service
        self.intent_service = intent_service
        self.audit_service = audit_service
        self.openai_client = openai_client
        self.graph_client = graph_client
        self.s3_client = s3_client
    
    async def process_user_message(
        self,
        user_mail: str,
        message: str,
        conversation_id: str,
        use_intent_analysis: bool = None
    ) -> Dict[str, Any]:
        """處理用戶訊息的完整流程（對話/意圖協調入口）

        功能
        - 可選擇是否啟用 AI 意圖分析；啟用時會先判斷意圖，再依意圖呼叫待辦/會議相關流程；
          未啟用則直接走一般對話服務。

        參數
        - user_mail: 使用者 Email
        - message: 使用者輸入訊息
        - conversation_id: 對話識別（供對話上下文與稽核）
        - use_intent_analysis: 覆寫系統設定，是否啟用意圖分析（None 則使用環境設定）

        回傳
        - Dict，包含成功旗標與可能的欄位：intent/todos/ai_response 等
        """
        try:
            # ConversationService 已經會處理訊息記錄，這裡不需要重複記錄
            # await self.audit_service.log_message(...)
            
            # 決定是否使用意圖分析
            if use_intent_analysis is None:
                use_intent_analysis = self.config.enable_ai_intent_analysis
            
            response_data = {"success": True}
            
            if use_intent_analysis:
                # 使用意圖分析處理
                intent_result = await self.intent_service.analyze_intent(message)
                response_data["intent"] = intent_result
                
                # 根據意圖執行相應操作
                if intent_result.action == "add" and intent_result.category == "todo":
                    content = intent_result.content or message
                    todo_result = await self.todo_service.smart_create_todo(user_mail, content)
                    response_data["todo_result"] = todo_result
                
                elif intent_result.action == "query" and intent_result.category == "todo":
                    todos = await self.todo_service.get_user_todos(user_mail, include_completed=False)
                    response_data["todos"] = [todo.to_dict() for todo in todos]
                
                elif intent_result.action == "book" and intent_result.category == "meeting":
                    # 顯示會議室預約選項
                    response_data["action"] = "show_booking_options"
                
                else:
                    # 使用對話服務處理
                    ai_response = await self.conversation_service.get_ai_response(
                        conversation_id, user_mail, message
                    )
                    response_data["ai_response"] = ai_response
            else:
                # 直接使用對話服務
                ai_response = await self.conversation_service.get_ai_response(
                    conversation_id, user_mail, message
                )
                response_data["ai_response"] = ai_response
            
            # ConversationService 已經會處理回應記錄，這裡不需要重複記錄
            # await self.audit_service.log_message(...)
            
            return response_data
            
        except Exception as e:
            error_msg = f"處理用戶訊息失敗: {str(e)}"
            print(f"❌ {error_msg}")
            
            # 記錄錯誤到稽核日誌
            await self.audit_service.log_message(conversation_id, {
                "role": "system",
                "content": f"錯誤: {error_msg}",
                "timestamp": get_taiwan_time().isoformat()
            }, user_mail)
            
            return {
                "success": False,
                "error": error_msg
            }
    
    async def execute_todo_workflow(
        self,
        user_mail: str,
        action: str,
        **kwargs
    ) -> Dict[str, Any]:
        """執行待辦事項工作流程（應用層統一入口）

        功能
        - 封裝 Todo 的常見操作（create/list/complete/stats），讓 API/CLI/排程/其他 Bot 直接使用。

        參數
        - user_mail: 使用者 Email
        - action: 操作類型（create/list/complete/stats）
        - kwargs: 各操作所需參數，例如 create 需要 content；complete 需要 todo_indices

        回傳
        - Dict，含成功旗標與對應結果資料

        範例
        - await execute_todo_workflow(user, "create", content="開會前準備投影片")
        - await execute_todo_workflow(user, "complete", todo_indices=[1,3])
        """
        try:
            if action == "create":
                content = kwargs.get("content")
                if not content:
                    raise BusinessLogicError("待辦事項內容不能為空")
                
                todo, similar_todos = await self.todo_service.smart_create_todo(user_mail, content)
                return {
                    "success": True,
                    "todo": todo.to_dict() if todo else None,
                    "similar_todos": similar_todos
                }
            
            elif action == "list":
                include_completed = kwargs.get("include_completed", False)
                todos = await self.todo_service.get_user_todos(user_mail, include_completed)
                return {
                    "success": True,
                    "todos": [todo.to_dict() for todo in todos]
                }
            
            elif action == "complete":
                todo_indices = kwargs.get("todo_indices", [])
                completed_todos = await self.todo_service.batch_complete_todos(todo_indices, user_mail)
                return {
                    "success": True,
                    "completed_todos": [todo.to_dict() for todo in completed_todos]
                }
            
            elif action == "stats":
                stats = await self.todo_service.get_user_stats(user_mail)
                return {
                    "success": True,
                    "stats": stats
                }
            
            else:
                raise BusinessLogicError(f"不支援的待辦事項操作: {action}")
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def execute_meeting_workflow(
        self,
        user_mail: str,
        action: str,
        **kwargs
    ) -> Dict[str, Any]:
        """執行會議室工作流程（應用層統一入口）

        功能
        - 提供會議室相關操作的協調入口（list_rooms/check_availability/book/list_bookings/cancel）。
        - 內部委派給 MeetingService，並在此層統一回應結構與錯誤處理。

        參數
        - user_mail: 使用者 Email（作為 organizer 或查詢目標）
        - action: 操作類型（list_rooms/check_availability/book/list_bookings/cancel）
        - kwargs: 各操作所需參數，例如
            - check_availability: room_emails, start_time, end_time（建議 +08:00）
            - book: booking_data（包含 room_id/date/start_time/end_time/subject）
            - cancel: booking_id

        回傳
        - Dict，含成功旗標與對應結果資料

        範例
        - await execute_meeting_workflow(user, "list_bookings")
        - await execute_meeting_workflow(user, "book", booking_data={...})
        """
        try:
            if action == "list_rooms":
                # 由 MeetingService 統一存取 Graph API
                rooms = await self.meeting_service.list_meeting_rooms_graph()
                return {"success": True, "rooms": rooms}
            
            elif action == "check_availability":
                room_emails = kwargs.get("room_emails", [])
                start_time = kwargs.get("start_time")
                end_time = kwargs.get("end_time")
                availability = await self.meeting_service.check_room_availability(room_emails, start_time, end_time)
                return {"success": True, "availability": availability}
            
            elif action == "book":
                booking_data = kwargs.get("booking_data", {})
                result = await self.meeting_service.book_meeting_room(user_mail, booking_data)
                return result
            
            elif action == "list_bookings":
                bookings = await self.meeting_service.get_user_meetings(user_mail)
                return {
                    "success": True,
                    "bookings": bookings
                }
            
            elif action == "cancel":
                booking_id = kwargs.get("booking_id")
                result = await self.meeting_service.cancel_meeting(user_mail, booking_id)
                return result
            
            else:
                raise BusinessLogicError(f"不支援的會議室操作: {action}")
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_user_dashboard(self, user_mail: str) -> Dict[str, Any]:
        """獲取用戶儀表板資料"""
        try:
            # 並行獲取各種資料
            import asyncio
            
            tasks = [
                self.todo_service.get_user_stats(user_mail),
                self.todo_service.get_user_todos(user_mail, include_completed=False),
                self.meeting_service.get_user_meetings(user_mail),
                self.conversation_service.get_conversation_summary(user_mail)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 處理結果
            todo_stats = results[0] if not isinstance(results[0], Exception) else {}
            pending_todos = results[1] if not isinstance(results[1], Exception) else []
            meetings = results[2] if not isinstance(results[2], Exception) else []
            conversation_summary = results[3] if not isinstance(results[3], Exception) else {}
            
            return {
                "success": True,
                "user_mail": user_mail,
                "dashboard": {
                    "todo_stats": todo_stats,
                    "pending_todos": [todo.to_dict() for todo in pending_todos[:5]],  # 最多 5 個
                    "upcoming_meetings": meetings[:3],  # 最多 3 個
                    "conversation_summary": conversation_summary
                },
                "timestamp": get_taiwan_time().isoformat()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"獲取用戶儀表板失敗: {str(e)}"
            }
    
    async def perform_system_maintenance(self) -> Dict[str, Any]:
        """執行系統維護任務"""
        try:
            maintenance_results = {}
            
            # 清理舊的待辦事項
            try:
                cleanup_result = await self.todo_service.clean_old_todos()
                maintenance_results["todo_cleanup"] = cleanup_result
            except Exception as e:
                maintenance_results["todo_cleanup"] = {"error": str(e)}
            
            # 上傳稽核日誌到 S3
            try:
                upload_result = await self.audit_service.upload_all_users_audit_logs()
                maintenance_results["audit_upload"] = upload_result
            except Exception as e:
                maintenance_results["audit_upload"] = {"error": str(e)}
            
            # 清理舊的對話記憶體
            try:
                memory_cleanup = await self.conversation_service.cleanup_old_conversations()
                maintenance_results["memory_cleanup"] = memory_cleanup
            except Exception as e:
                maintenance_results["memory_cleanup"] = {"error": str(e)}
            
            return {
                "success": True,
                "maintenance_results": maintenance_results,
                "timestamp": get_taiwan_time().isoformat()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"系統維護失敗: {str(e)}"
            }
    
    async def get_system_health(self) -> Dict[str, Any]:
        """獲取系統健康狀態"""
        try:
            health_checks = {}
            
            # 檢查 OpenAI 連接
            try:
                openai_test = await self.openai_client.test_connection()
                health_checks["openai"] = openai_test
            except Exception as e:
                health_checks["openai"] = {"success": False, "error": str(e)}
            
            # 檢查 Graph API 連接
            try:
                async with self.graph_client as graph:
                    graph_test = await graph.test_connection()
                health_checks["graph_api"] = graph_test
            except Exception as e:
                health_checks["graph_api"] = {"success": False, "error": str(e)}
            
            # 檢查 S3 連接
            try:
                s3_test = await self.s3_client.test_connection()
                health_checks["s3"] = s3_test
            except Exception as e:
                health_checks["s3"] = {"success": False, "error": str(e)}
            
            # 計算總體健康狀態
            successful_checks = sum(1 for check in health_checks.values() if check.get("success", False))
            total_checks = len(health_checks)
            health_percentage = (successful_checks / total_checks) * 100 if total_checks > 0 else 0
            
            overall_status = "healthy" if health_percentage == 100 else "degraded" if health_percentage >= 50 else "unhealthy"
            
            return {
                "success": True,
                "overall_status": overall_status,
                "health_percentage": health_percentage,
                "individual_checks": health_checks,
                "timestamp": get_taiwan_time().isoformat()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"健康檢查失敗: {str(e)}"
            }
