"""
Bot 命令處理器
處理所有 @command 格式的命令
"""
from typing import Dict, Any, Callable, Awaitable
from botbuilder.core import TurnContext
from botbuilder.schema import Activity, ActivityTypes

from application.dtos.bot_dtos import BotInteractionDTO, CommandExecutionDTO
from domain.services.todo_service import TodoService
from domain.services.conversation_service import ConversationService
from domain.services.meeting_service import MeetingService
from config.settings import AppConfig
from shared.utils.helpers import determine_language, get_suggested_replies


class BotCommandHandler:
    """Bot 命令處理器"""
    
    def __init__(
        self,
        config: AppConfig,
        todo_service: TodoService,
        conversation_service: ConversationService,
        meeting_service: MeetingService
    ):
        self.config = config
        self.todo_service = todo_service
        self.conversation_service = conversation_service
        self.meeting_service = meeting_service
        
        # 命令映射
        self.command_handlers: Dict[str, Callable[[TurnContext, BotInteractionDTO, CommandExecutionDTO], Awaitable[None]]] = {
            "help": self._handle_help_command,
            "ls": self._handle_list_todos_command,
            "add": self._handle_add_todo_command,
            "done": self._handle_complete_todo_command,
            "book-room": self._handle_book_room_command,
            "check-booking": self._handle_check_booking_command,
            "cancel-booking": self._handle_cancel_booking_command,
            "info": self._handle_info_command,
            "you": self._handle_you_command,
            "status": self._handle_status_command,
            "new-chat": self._handle_new_chat_command,
            "model": self._handle_model_command,
        }
    
    async def handle_command(self, turn_context: TurnContext, user_info: BotInteractionDTO) -> None:
        """處理命令"""
        try:
            command_dto = CommandExecutionDTO.parse_command(
                user_info.message_text,
                user_info.user_mail,
                user_info.conversation_id
            )
            
            handler = self.command_handlers.get(command_dto.command)
            if handler:
                await handler(turn_context, user_info, command_dto)
            else:
                await self._handle_unknown_command(turn_context, command_dto)
                
        except ValueError as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 命令格式錯誤：{str(e)}"
                )
            )
        except Exception as e:
            print(f"處理命令時發生錯誤: {e}")
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="❌ 處理命令時發生錯誤，請稍後再試。"
                )
            )
    
    async def _handle_help_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @help 命令"""
        language = determine_language(user_info.user_mail)
        
        # 從 presentation 層導入卡片建構器
        from presentation.cards.card_builders import HelpCardBuilder
        help_card_builder = HelpCardBuilder()
        
        welcome_msg = {
            "zh": "🛠️ 功能選單",
            "en": "🛠️ Function Menu",
            "ja": "🛠️ 機能メニュー"
        }.get(language, "🛠️ 功能選單")
        
        include_model = not self.config.openai.use_azure
        card = help_card_builder.build_help_card(language, welcome_msg, include_model_option=include_model)
        await turn_context.send_activity(card)
    
    async def _handle_list_todos_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @ls 命令"""
        todos = await self.todo_service.get_user_todos(user_info.user_mail, include_completed=False)
        language = determine_language(user_info.user_mail)
        
        if todos:
            from presentation.cards.card_builders import TodoCardBuilder
            todo_card_builder = TodoCardBuilder()
            card = todo_card_builder.build_todo_list_card(todos, language)
            await turn_context.send_activity(card)
        else:
            suggested_actions = get_suggested_replies("無待辦事項", user_info.user_mail)
            from botbuilder.schema import SuggestedActions
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="🎉 目前沒有待辦事項",
                    suggested_actions=SuggestedActions(actions=suggested_actions) if suggested_actions else None,
                )
            )
    
    async def _handle_add_todo_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @add 命令"""
        if not command_dto.parameters:
            # 沒有參數，顯示新增待辦事項卡片
            language = determine_language(user_info.user_mail)
            from presentation.cards.card_builders import TodoCardBuilder
            todo_card_builder = TodoCardBuilder()
            card = todo_card_builder.build_add_todo_card(language)
            await turn_context.send_activity(card)
            return
        
        # 有參數，直接新增待辦事項
        content = " ".join(command_dto.parameters)
        try:
            todo, similar_todos = await self.todo_service.smart_create_todo(user_info.user_mail, content)
            
            if similar_todos:
                # 有相似的待辦事項
                language = determine_language(user_info.user_mail)
                from presentation.cards.card_builders import TodoCardBuilder
                todo_card_builder = TodoCardBuilder()
                card = todo_card_builder.build_similar_todos_confirmation_card(
                    content, similar_todos, language
                )
                await turn_context.send_activity(card)
            elif todo:
                # 成功新增
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=f"✅ 已新增待辦事項：{todo.content}"
                    )
                )
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 新增待辦事項失敗：{str(e)}"
                )
            )
    
    async def _handle_complete_todo_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @done 命令"""
        if not command_dto.parameters:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="❌ 請指定要完成的待辦事項編號，例如：@done 1,2,3"
                )
            )
            return
        
        try:
            # 解析待辦事項索引
            indices_str = ",".join(command_dto.parameters)
            indices = [int(idx.strip()) - 1 for idx in indices_str.split(",") if idx.strip().isdigit()]  # 轉換為 0-based 索引
            
            if not indices:
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text="❌ 請提供有效的待辦事項編號"
                    )
                )
                return
            
            completed_todos = await self.todo_service.batch_complete_todos(indices, user_info.user_mail)
            
            if completed_todos:
                completed_text = "\n".join([f"• {todo.content}" for todo in completed_todos])
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=f"✅ 已完成 {len(completed_todos)} 項待辦事項：\n{completed_text}"
                    )
                )
            else:
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text="❌ 無法完成指定的待辦事項"
                    )
                )
        except ValueError:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="❌ 請提供有效的數字編號，例如：@done 1,2,3"
                )
            )
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 完成待辦事項時發生錯誤：{str(e)}"
                )
            )
    
    async def _handle_book_room_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @book-room 命令"""
        language = determine_language(user_info.user_mail)
        from presentation.cards.card_builders import MeetingCardBuilder
        meeting_card_builder = MeetingCardBuilder()
        card = meeting_card_builder.build_room_booking_card(language)
        await turn_context.send_activity(card)
    
    async def _handle_check_booking_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @check-booking 命令"""
        bookings = await self.meeting_service.get_user_meetings(user_info.user_mail)
        language = determine_language(user_info.user_mail)
        
        if bookings:
            from presentation.cards.card_builders import MeetingCardBuilder
            meeting_card_builder = MeetingCardBuilder()
            card = meeting_card_builder.build_my_bookings_card(bookings, language)
            await turn_context.send_activity(card)
        else:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="📅 目前沒有預約的會議室",
                )
            )
    
    async def _handle_cancel_booking_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @cancel-booking 命令"""
        bookings = await self.meeting_service.get_user_meetings(user_info.user_mail)
        language = determine_language(user_info.user_mail)
        
        if bookings:
            from presentation.cards.card_builders import MeetingCardBuilder
            meeting_card_builder = MeetingCardBuilder()
            card = meeting_card_builder.build_cancel_booking_card(bookings, language)
            await turn_context.send_activity(card)
        else:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="📅 目前沒有可取消的會議室預約",
                )
            )
    
    async def _handle_info_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @info 命令"""
        # 獲取用戶統計信息
        try:
            todo_stats = await self.todo_service.get_user_stats(user_info.user_mail)
            # 取得模型現況（優先顯示使用者偏好於 OpenAI 模式）
            if self.config.openai.use_azure:
                mode_text = "Azure OpenAI"
                model_text = "o1-mini（固定）"
            else:
                mode_text = "OpenAI"
                try:
                    from app import user_model_preferences
                    model_text = user_model_preferences.get(user_info.user_mail, self.config.openai.model)
                except Exception:
                    model_text = self.config.openai.model
            
            info_text = f"""
👤 **用戶資訊**
• 姓名: {user_info.user_name or '未知'}
• 郵箱: {user_info.user_mail}

🤖 **系統狀態**
• 模式: {mode_text}
• 模型: {model_text}
• AI 意圖分析: {"啟用" if self.config.enable_ai_intent_analysis else "停用"}

📊 **統計資訊**
• 待辦事項總數: {todo_stats.get('total_count', 0)}
• 已完成: {todo_stats.get('completed_count', 0)}
• 待處理: {todo_stats.get('pending_count', 0)}
• 本周新增: {todo_stats.get('recent_week_count', 0)}
"""
            
            if todo_stats.get('average_completion_hours'):
                info_text += f"• 平均完成時間: {todo_stats['average_completion_hours']:.1f} 小時"
            
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=info_text
                )
            )
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"👤 **用戶資訊**\n• 姓名: {user_info.user_name or '未知'}\n• 郵箱: {user_info.user_mail}"
                )
            )
    
    async def _handle_you_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @you 命令"""
        language = determine_language(user_info.user_mail)
        from presentation.cards.card_builders import HelpCardBuilder
        help_card_builder = HelpCardBuilder()
        card = help_card_builder.build_bot_intro_card(language)
        await turn_context.send_activity(card)
    
    async def _handle_status_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @status 命令"""
        # 與 @info 對齊：統一顯示個人與系統資訊
        await self._handle_info_command(turn_context, user_info, command_dto)
    
    async def _handle_new_chat_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @new-chat 命令"""
        try:
            # 清除用戶的工作記憶體（保留稽核日誌）
            await self.conversation_service.clear_working_memory(user_info.user_mail)
            
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="🆕 已清除對話記憶，開始新的對話！"
                )
            )
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 清除對話記憶時發生錯誤：{str(e)}"
                )
            )
    
    async def _handle_model_command(
        self, 
        turn_context: TurnContext, 
        user_info: BotInteractionDTO, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理 @model 命令"""
        if self.config.openai.use_azure:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="ℹ️ 目前使用 Azure OpenAI 服務\n📱 模型：o1-mini（固定）\n⚡ 此模式不支援模型切換",
                )
            )
            return
        
        # OpenAI 模式：顯示模型選擇
        from presentation.cards.card_builders import ModelSelectionCardBuilder
        model_card_builder = ModelSelectionCardBuilder()
        card = model_card_builder.build_model_selection_card(user_info.user_mail)
        await turn_context.send_activity(card)
    
    async def _handle_unknown_command(
        self, 
        turn_context: TurnContext, 
        command_dto: CommandExecutionDTO
    ) -> None:
        """處理未知命令"""
        available_commands = ", ".join([f"@{cmd}" for cmd in self.command_handlers.keys()])
        
        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=f"❓ 未知命令：@{command_dto.command}\n\n可用命令：\n{available_commands}\n\n使用 @help 查看完整功能列表。"
            )
        )
