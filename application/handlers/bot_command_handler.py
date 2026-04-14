"""
Bot 命令處理器
處理所有 @command 格式的命令
"""
import logging
from typing import Dict, Any, Callable, Awaitable
from botbuilder.core import TurnContext
from botbuilder.schema import Activity, ActivityTypes

logger = logging.getLogger(__name__)

from application.dtos.bot_dtos import BotInteractionDTO, CommandExecutionDTO
from domain.services.conversation_service import ConversationService
from domain.services.meeting_service import MeetingService
from config.settings import AppConfig
from shared.utils.helpers import determine_language


class BotCommandHandler:
    """Bot 命令處理器"""
    
    def __init__(
        self,
        config: AppConfig,
        conversation_service: ConversationService,
        meeting_service: MeetingService
    ):
        self.config = config
        self.conversation_service = conversation_service
        self.meeting_service = meeting_service
        
        # 命令映射
        self.command_handlers: Dict[str, Callable[[TurnContext, BotInteractionDTO, CommandExecutionDTO], Awaitable[None]]] = {
            "help": self._handle_help_command,
            "book-room": self._handle_book_room_command,
            "check-booking": self._handle_check_booking_command,
            "cancel-booking": self._handle_cancel_booking_command,
            "info": self._handle_info_command,
            "you": self._handle_you_command,
            "status": self._handle_status_command,
            "new-chat": self._handle_new_chat_command,
            "model": self._handle_model_command,
            "it": self._handle_it_command,
            "itt": self._handle_itt_command,
            "itls": self._handle_itls_command,
            "t": self._handle_t_command,
            "kb": self._handle_kb_command,
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
            logger.error("處理命令時發生錯誤: %s", e)
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
        try:
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
"""
            
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

    async def _handle_it_command(
        self,
        turn_context: TurnContext,
        user_info: BotInteractionDTO,
        command_dto: CommandExecutionDTO,
    ) -> None:
        """處理 @it 命令：顯示 IT 提單卡片"""
        try:
            # 取得語言與服務
            language = determine_language(user_info.user_mail)
            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)

            card = svc.build_issue_card(language, user_info.user_name or "", user_info.user_mail)
            await turn_context.send_activity(card)
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 無法顯示 IT 提單：{str(e)}",
                )
            )

    async def _handle_itt_command(
        self,
        turn_context: TurnContext,
        user_info: BotInteractionDTO,
        command_dto: CommandExecutionDTO,
    ) -> None:
        """處理 @itt 命令：顯示 IT 代提單卡片（含提出人 Email 欄位）"""
        try:
            language = determine_language(user_info.user_mail)
            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)

            card = svc.build_itt_issue_card(language, user_info.user_name or "", user_info.user_mail)
            await turn_context.send_activity(card)
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 無法顯示 IT 代提單：{str(e)}",
                )
            )

    async def _handle_itls_command(
        self,
        turn_context: TurnContext,
        user_info: BotInteractionDTO,
        command_dto: CommandExecutionDTO,
    ) -> None:
        """處理 @itls 命令：列出使用者的 IT 支援單"""
        try:
            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)

            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text="🔍 查詢中，請稍候...")
            )

            result = await svc.query_my_tickets(user_info.user_mail)

            from features.it_support.cards import build_my_tickets_card
            card = build_my_tickets_card(result["incomplete"], result["recent_completed"])
            await turn_context.send_activity(card)
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 查詢 IT 工單失敗：{str(e)}",
                )
            )

    async def _handle_t_command(
        self,
        turn_context: TurnContext,
        user_info: BotInteractionDTO,
        command_dto: CommandExecutionDTO,
    ) -> None:
        """處理 @t 命令：顯示發送訊息給使用者的卡片（僅 IT 人員可用）"""
        try:
            # 權限檢查
            self.logger.info("@t 權限檢查: user_mail=%s, lower=%s, it_staff=%s",
                             user_info.user_mail, user_info.user_mail.lower(), self.config.it_staff_emails)
            if user_info.user_mail.lower() not in self.config.it_staff_emails:
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text="❌ 此功能僅限 IT 人員使用。")
                )
                return

            language = determine_language(user_info.user_mail)
            from core.container import get_container
            from domain.repositories.user_repository import UserRepository
            from app import user_conversation_refs, user_display_names

            container = get_container()
            user_repo: UserRepository = container.get(UserRepository)

            # 建立可發送對象清單（從全域 user_conversation_refs 取得有連線的使用者）
            user_choices = []
            for email, ref in user_conversation_refs.items():
                if not ref:
                    continue
                profile = await user_repo.get_profile(email)
                dept = profile.department if profile and profile.department else ""
                display = (profile.display_name if profile and profile.display_name
                           else user_display_names.get(email, email.split("@")[0]))
                title = f"{dept}-{display}" if dept else display
                user_choices.append({"title": title, "value": email})

            # 依 title 排序
            user_choices.sort(key=lambda c: c["title"])

            from features.it_support.cards import build_send_message_card
            card = build_send_message_card(language, user_choices)
            await turn_context.send_activity(card)
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 無法顯示發送訊息卡片：{str(e)}",
                )
            )

    async def _handle_kb_command(
        self,
        turn_context: TurnContext,
        user_info: BotInteractionDTO,
        command_dto: CommandExecutionDTO,
    ) -> None:
        """處理 @kb 命令：知識庫查詢
        - @kb：依使用者部門自動匹配可用知識庫
        - @kb <密碼>：管理員模式，列出所有知識庫
        """
        import os
        import json
        kb_password = os.getenv("KB_ACCESS_PASSWORD", "rinnai")
        language = determine_language(user_info.user_mail)

        if command_dto.parameters:
            # 有參數 → 驗證密碼，顯示所有知識庫
            provided_password = command_dto.parameters[0].strip()
            if provided_password != kb_password:
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text="❌ 密碼錯誤，請重新輸入。")
                )
                return

            try:
                from features.it_support.kb_client import KBVectorClient
                kb_client = KBVectorClient()
                kb_list = await kb_client.list_kbs()
                if not kb_list:
                    await turn_context.send_activity(
                        Activity(type=ActivityTypes.message, text="⚠️ 目前無可用的知識庫，請稍後再試。")
                    )
                    return

                from features.it_support.cards import build_kb_query_card
                card = build_kb_query_card(language, kb_list)
                await turn_context.send_activity(card)
            except Exception as e:
                logger.exception("KB 查詢卡片顯示失敗: %s", e)
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=f"❌ 無法載入知識庫：{str(e)}")
                )
            return

        # 無參數 → 依使用者部門自動匹配知識庫
        try:
            from core.container import get_container
            from infrastructure.external.graph_api_client import GraphAPIClient
            from features.it_support.kb_client import KBVectorClient

            container = get_container()
            graph_client: GraphAPIClient = container.get(GraphAPIClient)

            # 取得使用者部門
            user_department = ""
            try:
                user_profile = await graph_client.get_user_info(user_info.user_mail)
                if user_profile:
                    user_department = (user_profile.get("department") or "").strip()
            except Exception as e:
                logger.warning("⚠️ KB: 無法取得使用者部門: %s", e)

            if not user_department:
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text="⚠️ 您的帳號尚未設定所屬單位，無法自動匹配知識庫。\n請聯繫 IT 人員於 Azure AD 設定您的部門資訊。",
                    )
                )
                return

            # 從 KB_DEPARTMENT_MAP 匹配部門對應的知識庫 slug
            dept_map_raw = os.getenv("KB_DEPARTMENT_MAP", "{}")
            try:
                dept_map: dict = json.loads(dept_map_raw)
            except json.JSONDecodeError:
                dept_map = {}

            matched_slugs: list = []
            matched = dept_map.get(user_department)
            if not matched:
                # 模糊匹配
                for key, slugs in dept_map.items():
                    if key in user_department or user_department in key:
                        matched = slugs
                        break
            if matched:
                if isinstance(matched, str):
                    matched_slugs.append(matched)
                elif isinstance(matched, list):
                    matched_slugs.extend(matched)

            # 加入個人專屬 KB（KB_USER_MAP）
            user_map_raw = os.getenv("KB_USER_MAP", "{}")
            try:
                user_map: dict = json.loads(user_map_raw)
            except json.JSONDecodeError:
                user_map = {}
            user_kbs = user_map.get(user_info.user_mail) or user_map.get(user_info.user_mail.lower()) or []
            if isinstance(user_kbs, str):
                user_kbs = [user_kbs]
            for slug in user_kbs:
                if slug not in matched_slugs:
                    matched_slugs.append(slug)

            if not matched_slugs:
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=f"⚠️ 您的單位「{user_department}」尚未設定對應的知識庫。\n請聯繫 IT 人員為您的部門開通知識庫服務。",
                    )
                )
                return

            # 取得完整 KB 清單（含 displayName），篩選出使用者有權的
            kb_client = KBVectorClient()
            all_kbs = await kb_client.list_kbs()
            all_kb_map = {kb.get("slug"): kb for kb in all_kbs}

            user_kb_list = []
            for slug in matched_slugs:
                if slug in all_kb_map:
                    user_kb_list.append(all_kb_map[slug])
                else:
                    # API 沒回傳但有設定，用 slug 當 displayName
                    user_kb_list.append({"slug": slug, "displayName": slug})

            from features.it_support.cards import build_kb_query_card
            card = build_kb_query_card(language, user_kb_list)
            await turn_context.send_activity(card)
        except Exception as e:
            logger.exception("KB 部門匹配查詢失敗: %s", e)
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=f"❌ 無法載入知識庫：{str(e)}")
            )

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
