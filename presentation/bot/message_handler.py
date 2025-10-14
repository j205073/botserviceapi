"""
Teams Bot 訊息處理器
處理所有來自 Teams 的用戶互動，包括文字訊息和卡片互動
"""

from typing import Dict, Any, Optional
from botbuilder.core import TurnContext
from botbuilder.schema import Activity, ActivityTypes, SuggestedActions

from domain.models.user import UserProfile
from domain.services.todo_service import TodoService
from domain.services.conversation_service import ConversationService
from domain.services.meeting_service import MeetingService
from domain.services.intent_service import IntentService
from application.handlers.bot_command_handler import BotCommandHandler
from application.dtos.bot_dtos import BotInteractionDTO
from config.settings import AppConfig
from presentation.cards.card_builders import (
    TodoCardBuilder,
    HelpCardBuilder,
    MeetingCardBuilder,
    ModelSelectionCardBuilder,
    UploadCardBuilder,
)
from shared.utils.helpers import (
    get_user_email,
    determine_language,
    get_suggested_replies,
)
from shared.exceptions import OpenAIServiceError
from botbuilder.schema import ActionTypes, CardAction, SuggestedActions


class TeamsMessageHandler:
    """Teams 訊息處理器"""

    def __init__(
        self,
        config: AppConfig,
        todo_service: TodoService,
        conversation_service: ConversationService,
        meeting_service: MeetingService,
        intent_service: IntentService,
        command_handler: BotCommandHandler,
    ):
        self.config = config
        self.todo_service = todo_service
        self.conversation_service = conversation_service
        self.meeting_service = meeting_service
        self.intent_service = intent_service
        self.command_handler = command_handler

        # Card builders
        self.todo_card_builder = TodoCardBuilder()
        self.help_card_builder = HelpCardBuilder()
        self.meeting_card_builder = MeetingCardBuilder()
        self.model_card_builder = ModelSelectionCardBuilder()
        self.upload_card_builder = UploadCardBuilder()

    async def handle_message(self, turn_context: TurnContext) -> None:
        """處理 Teams 訊息"""
        try:
            # 提取用戶信息
            user_info = await self._extract_user_info(turn_context)

            # 更新用戶會話參考
            await self._update_user_conversation_ref(turn_context, user_info)

            # 處理卡片互動
            if turn_context.activity.value:
                await self._handle_card_interaction(turn_context, user_info)
                return

            # 若含有附件且最近建立 IT 單，嘗試附加圖片
            if turn_context.activity.attachments:
                handled = await self._try_attach_images(turn_context, user_info)
                if handled:
                    return

            # 處理文字訊息
            await self._handle_text_message(turn_context, user_info)

        except Exception as e:
            print(f"處理訊息時發生錯誤: {e}")
            await self._send_error_response(turn_context)

    async def _extract_user_info(self, turn_context: TurnContext) -> BotInteractionDTO:
        """提取用戶信息"""
        user_id = turn_context.activity.from_property.id
        user_name = turn_context.activity.from_property.name
        user_mail = await get_user_email(turn_context) or f"{user_id}@unknown.com"
        conversation_id = turn_context.activity.conversation.id

        # Debug 模式處理
        if self.config.debug_mode and self.config.debug_account:
            user_mail = self.config.debug_account

        print(f"Current User Info: {user_name} (ID: {user_id}) (Mail: {user_mail})")

        return BotInteractionDTO(
            user_id=user_id,
            user_name=user_name,
            user_mail=user_mail,
            conversation_id=conversation_id,
            message_text=turn_context.activity.text or "",
            card_action=(
                turn_context.activity.value.get("action")
                if turn_context.activity.value
                else None
            ),
        )

    async def _update_user_conversation_ref(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """更新用戶會話參考"""
        conversation_ref = TurnContext.get_conversation_reference(turn_context.activity)
        # 這裡應該透過服務來更新，而不是直接操作全域變數
        # 暫時保持相容性
        from app import user_conversation_refs, user_display_names

        user_conversation_refs[user_info.user_mail] = conversation_ref
        if user_info.user_mail:
            user_display_names[user_info.user_mail] = (
                user_info.user_name or user_display_names.get(user_info.user_mail)
            )

    async def _handle_card_interaction(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """處理卡片互動"""
        card_action = turn_context.activity.value.get("action")

        if card_action == "selectFunction":
            await self._handle_function_selection(turn_context, user_info)
        elif card_action == "addTodo":
            await self._handle_add_todo_card(turn_context, user_info)
        elif card_action == "completeTodos":
            await self._handle_complete_todos(turn_context, user_info)
        elif card_action == "bookRoom":
            await self._handle_book_room(turn_context, user_info)
        elif card_action == "cancelBooking":
            await self._handle_cancel_booking(turn_context, user_info)
        elif card_action == "selectModel":
            await self._handle_model_selection(turn_context, user_info)
        elif card_action == "submitIT":
            await self._handle_submit_it_issue(turn_context, user_info)
        elif card_action == "uploadOption":
            await self._handle_upload_option(turn_context, user_info)

    async def _handle_submit_it_issue(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """提交 IT 提單並建立 Asana 任務"""
        try:
            form = {
                "summary": turn_context.activity.value.get("summary"),
                "description": turn_context.activity.value.get("description"),
                "category": turn_context.activity.value.get("category"),
                "priority": turn_context.activity.value.get("priority"),
            }

            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)
            result = await svc.submit_issue(form, user_info.user_name or "", user_info.user_mail)

            if result.get("success"):
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=result.get("message", "✅ 已建立 IT Issue"))
                )
                # Immediately show upload options HeroCard so user can attach files easily
                try:
                    language = determine_language(user_info.user_mail)
                    upload_card = self.upload_card_builder.build_file_upload_options_card(language)
                    await turn_context.send_activity(upload_card)
                except Exception:
                    pass
                # If the submit action also includes attachments (e.g., pasted images), try to upload immediately
                if turn_context.activity.attachments:
                    try:
                        handled = await self._try_attach_images(turn_context, user_info)
                        # If handled, no extra message needed beyond what _try_attach_images sends
                    except Exception:
                        pass

                # No URL-based uploads anymore; users can paste/attach images directly
            else:
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=f"❌ {result.get('error', '提交失敗')}")
                )
        except Exception as e:
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=f"❌ 提交 IT 提單時發生錯誤：{str(e)}")
            )

    async def _handle_function_selection(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """處理功能選擇"""
        selected_function = turn_context.activity.value.get("selectedFunction")
        if not selected_function:
            return

        # 映射功能到處理器
        function_handlers = {
            "@addTodo": self._show_add_todo_card,
            "@ls": self._show_todo_list,
            "@it": self._show_it_issue_card,
            "@upload": self._show_upload_card,
            "@book-room": self._show_room_booking_options,
            "@check-booking": self._show_my_bookings,
            "@cancel-booking": self._show_cancel_booking_options,
            "@info": self._show_user_info,
            "@you": self._show_bot_intro,
            "@model": self._show_model_selection,
        }

        handler = function_handlers.get(selected_function)
        if handler:
            await handler(turn_context, user_info)

    async def _show_it_issue_card(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示 IT 提單卡片"""
        from core.container import get_container
        from features.it_support.service import ITSupportService

        language = determine_language(user_info.user_mail)
        svc: ITSupportService = get_container().get(ITSupportService)
        card = svc.build_issue_card(language, user_info.user_name or "", user_info.user_mail)
        await turn_context.send_activity(card)

    async def _show_upload_card(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示檔案上傳引導 HeroCard"""
        language = determine_language(user_info.user_mail)
        # 顯示含 1/2/3 選項的 HeroCard（im_back）
        card = self.upload_card_builder.build_file_upload_options_card(language)
        await turn_context.send_activity(card)

    async def _handle_upload_option(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        opt = str(turn_context.activity.value.get("opt"))
        language = determine_language(user_info.user_mail)
        tips = {
            "zh": {
                "1": "請直接在此對話視窗貼上圖片（或拖曳圖片）後送出，我會自動附加到最近建立的 IT 單。",
                "2": "目前不建議以網址上傳，請改用貼上圖片或 Teams 附件按鈕。",
                "3": "請使用訊息列的附件（迴紋針）按鈕選擇檔案，送出後我會自動附加到最近建立的 IT 單。",
            },
            "en": {
                "1": "Paste or drag the image here and send it; I'll attach it to your latest IT ticket.",
                "2": "URL uploads are not recommended; please paste image or use the attachment button.",
                "3": "Use the attachment (paperclip) button to upload; I'll attach it to your latest IT ticket.",
            },
            "ja": {
                "1": "このチャットに画像を貼り付け／ドラッグして送信してください。最新のITチケットに自動添付します。",
                "2": "URL 経由のアップロードは推奨しません。画像を貼り付けるか、添付ボタンをご利用ください。",
                "3": "メッセージ欄のクリップアイコンからファイルを添付してください。最新のITチケットに自動添付します。",
            },
        }
        text = tips.get(language, tips["zh"]).get(opt)
        if text:
            await turn_context.send_activity(Activity(type=ActivityTypes.message, text=text))

    async def _handle_text_message(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """處理文字訊息"""
        user_message = user_info.message_text.strip()

        # 上傳選項快捷回覆（HeroCard im_back）
        if user_message in ["1", "2", "3"]:
            language = determine_language(user_info.user_mail)
            tips = {
                "zh": {
                    "1": "請直接在此對話視窗貼上圖片（或拖曳圖片）後送出，我會自動附加到最近建立的 IT 單。",
                    "2": "目前不建議以網址上傳，請改用貼上圖片或 Teams 附件按鈕。",
                    "3": "請使用訊息列的附件（迴紋針）按鈕選擇檔案，送出後我會自動附加到最近建立的 IT 單。",
                },
                "en": {
                    "1": "Paste or drag the image here and send it; I'll attach it to your latest IT ticket.",
                    "2": "URL uploads are not recommended; please paste image or use the attachment button.",
                    "3": "Use the attachment (paperclip) button to upload; I'll attach it to your latest IT ticket.",
                },
                "ja": {
                    "1": "このチャットに画像を貼り付け／ドラッグして送信してください。最新のITチケットに自動添付します。",
                    "2": "URL 経由のアップロードは推奨しません。画像を貼り付けるか、添付ボタンをご利用ください。",
                    "3": "メッセージ欄のクリップアイコンからファイルを添付してください。最新のITチケットに自動添付します。",
                },
            }
            t = tips.get(language, tips["zh"]).get(user_message)
            if t:
                await turn_context.send_activity(Activity(type=ActivityTypes.message, text=t))
                return

        # 支援 /help 或 help 顯示功能選單（對齊 app_bak 行為）
        if user_message.lower() in ["/help", "help", "@help"]:
            language = determine_language(user_info.user_mail)
            include_model = not self.config.openai.use_azure
            welcome_msg = {
                "zh": "🛠️ 功能選單",
                "en": "🛠️ Function Menu",
                "ja": "🛠️ 機能メニュー",
            }.get(language, "🛠️ 功能選單")
            help_card = self.help_card_builder.build_help_card(
                language, welcome_msg, include_model_option=include_model
            )
            await turn_context.send_activity(help_card)
            return

        # 處理歡迎訊息
        if user_message.lower() in ["hi", "hello", "你好", "嗨"]:
            await self._send_welcome_message(turn_context, user_info)
            return

        # 處理命令
        if user_message.startswith("@"):
            await self.command_handler.handle_command(turn_context, user_info)
            return

        # 處理一般對話（使用 AI 意圖分析或直接 OpenAI 調用）
        if self.config.enable_ai_intent_analysis:
            await self._handle_intent_based_response(turn_context, user_info)
        else:
            await self._handle_direct_openai_response(turn_context, user_info)

    async def _handle_intent_based_response(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """基於意圖分析的回應處理"""
        try:
            intent_result = await self.intent_service.analyze_intent(
                user_info.message_text
            )

            if intent_result.action == "add" and intent_result.category == "todo":
                content = intent_result.content or user_info.message_text
                await self._handle_smart_todo_add(turn_context, user_info, content)
            elif intent_result.action == "query" and intent_result.category == "todo":
                await self._show_todo_list(turn_context, user_info)
            elif intent_result.action == "book" and intent_result.category == "meeting":
                await self._show_room_booking_options(turn_context, user_info)
            elif intent_result.action == "query" and intent_result.category == "meeting":
                await self._show_my_bookings(turn_context, user_info)
            elif intent_result.action == "cancel" and intent_result.category == "meeting":
                await self._show_cancel_booking_options(turn_context, user_info)
            elif intent_result.category == "info":
                if intent_result.action in ("user_info", "status"):
                    await self._show_user_info(turn_context, user_info)
                elif intent_result.action == "bot_info" or intent_result.action == "help":
                    # bot_info/幫助都導向說明/介紹
                    await self._show_bot_intro(turn_context, user_info)
                else:
                    await self._show_user_info(turn_context, user_info)
            elif intent_result.category == "model" and intent_result.action == "select":
                await self._show_model_selection(turn_context, user_info)
            else:
                # 進入主要AI對話 預設回應 由Openai回覆
                # 發送 loading 訊息
                language = determine_language(user_info.user_mail)
                loading_messages = {
                    "zh-TW": "🤔 思考更長時間以取得更佳回答...",
                    "ja": "🤔 考え中です。少々お待ちください...",
                }
                loading_text = loading_messages.get(language, loading_messages["zh-TW"])

                # 發送 typing 活動
                await turn_context.send_activity(Activity(type="typing"))
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=loading_text)
                )

                await self._handle_direct_openai_response(turn_context, user_info)

        except Exception as e:
            print(f"意圖分析失敗: {e}")
            await self._handle_direct_openai_response(turn_context, user_info)

    async def _handle_direct_openai_response(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """直接 OpenAI 回應處理"""
        # 依模式決定使用的模型（OpenAI 模式支援 per-user 偏好）
        model_arg = None
        if not self.config.openai.use_azure:
            try:
                from app import user_model_preferences
                model_arg = user_model_preferences.get(
                    user_info.user_mail, self.config.openai.model
                )
            except Exception:
                model_arg = self.config.openai.model

        try:
            if model_arg:
                response = await self.conversation_service.get_ai_response(
                    user_info.conversation_id,
                    user_info.user_mail,
                    user_info.message_text,
                    model=model_arg,
                )
            else:
                response = await self.conversation_service.get_ai_response(
                    user_info.conversation_id,
                    user_info.user_mail,
                    user_info.message_text,
                )

            suggested_actions = get_suggested_replies(
                user_info.message_text, user_info.user_mail
            )

            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=response,
                    suggested_actions=(
                        SuggestedActions(actions=suggested_actions)
                        if suggested_actions
                        else None
                    ),
                )
            )
        except OpenAIServiceError as openai_error:
            error_hint = str(openai_error) or "OpenAI 服務暫時無法回應"
            fallback_text = (
                "⚠️ 呼叫 OpenAI 模型時發生問題，暫時無法提供回覆。\n"
                "請稍後再試，或輸入 @model 改用其他模型。"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=fallback_text)
            )
            print(f"OpenAIServiceError while responding: {error_hint}")
        except Exception as unexpected_error:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="⚠️ 目前無法取得模型回覆，請稍後再試一次。",
                )
            )
            print(f"Unexpected error in _handle_direct_openai_response: {unexpected_error}")

    async def _try_attach_images(self, turn_context: TurnContext, user_info: BotInteractionDTO) -> bool:
        """If message has file attachments and user has a recent IT task, upload them to Asana.
        Returns True if handled (uploaded or error responded), else False.
        """
        try:
            atts = turn_context.activity.attachments or []
            files = []
            # Accept general file attachments
            for a in atts:
                ctype = (getattr(a, "content_type", None) or "").lower()
                name = getattr(a, "name", None) or ""
                url = getattr(a, "content_url", None) or getattr(a, "contentUrl", None)
                # Teams file info attachments (e.g., application/vnd.microsoft.teams.file.download.info)
                if not url and ctype == "application/vnd.microsoft.teams.file.download.info":
                    content = getattr(a, "content", None) or {}
                    if isinstance(content, dict):
                        url = content.get("downloadUrl")
                        # Try resolve a better filename
                        if not name:
                            name = content.get("name") or name
                        ft = content.get("fileType")
                        generic = (not name) or (name.lower() in ("file", "file.bin", "image", "image.jpg", "original", "upload", "upload.bin")) or ("." not in name)
                        if generic and ft:
                            from datetime import datetime
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            name = f"upload_{ts}.{ft}"
                # Skip card attachments
                if ctype.startswith("application/vnd.microsoft.card"):
                    continue
                # Handle data URL (e.g., Bot Emulator inline data)
                if url and str(url).startswith("data:"):
                    try:
                        header, b64data = str(url).split(",", 1)
                        import base64
                        mime = "application/octet-stream"
                        if ":" in header and ";" in header:
                            mime = header.split(":", 1)[1].split(";", 1)[0] or mime
                        # If mime still unknown, try to sniff from bytes
                        data_bytes = base64.b64decode(b64data)
                        if not mime or mime == "application/octet-stream":
                            try:
                                # Simple magic sniff for common types
                                if data_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                                    mime = "image/png"
                                elif data_bytes.startswith(b"\xff\xd8"):
                                    mime = "image/jpeg"
                                elif data_bytes.startswith(b"GIF8"):
                                    mime = "image/gif"
                                elif data_bytes.startswith(b"RIFF") and b"WEBP" in data_bytes[:16]:
                                    mime = "image/webp"
                                elif data_bytes.startswith(b"%PDF"):
                                    mime = "application/pdf"
                                elif data_bytes.startswith(b"PK\x03\x04"):
                                    mime = "application/zip"
                            except Exception:
                                pass
                        # Infer extension if name missing or generic (e.g., 'original')
                        generic = (not name) or (name.lower() in ("file", "file.bin", "image", "image.jpg", "original", "upload", "upload.bin")) or ("." not in name)
                        if generic:
                            ext_map = {
                                "image/png": "png",
                                "image/jpeg": "jpg",
                                "image/jpg": "jpg",
                                "image/gif": "gif",
                                "image/webp": "webp",
                                "image/bmp": "bmp",
                                "image/heic": "heic",
                                "application/pdf": "pdf",
                                "application/zip": "zip",
                                "text/plain": "txt",
                                "application/msword": "doc",
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                                "application/vnd.ms-excel": "xls",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
                                "application/vnd.ms-powerpoint": "ppt",
                                "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
                            }
                            ext = ext_map.get(mime, "bin")
                            from datetime import datetime
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            name = f"screenshot_{ts}.{ext}"
                        files.append({"data": data_bytes, "name": name or "file.bin", "ctype": mime})
                        continue
                    except Exception:
                        pass
                if url:
                    # Derive filename from URL if name missing or generic
                    generic = (not name) or (name.lower() in ("file", "file.bin", "image", "image.jpg", "original", "upload", "upload.bin")) or ("." not in name)
                    if generic:
                        try:
                            from urllib.parse import urlparse, unquote
                            path = urlparse(url).path
                            base = path.rsplit("/", 1)[-1]
                            if base:
                                name = unquote(base)
                        except Exception:
                            pass
                    # If still generic after URL parse, synthesize from content-type
                    generic2 = (not name) or (name.lower() in ("file", "file.bin", "image", "image.jpg", "original", "upload", "upload.bin")) or ("." not in name)
                    if generic2:
                        ext_map = {
                            "image/png": "png",
                            "image/jpeg": "jpg",
                            "image/jpg": "jpg",
                            "image/gif": "gif",
                            "image/webp": "webp",
                            "image/bmp": "bmp",
                            "image/heic": "heic",
                            "application/pdf": "pdf",
                            "application/zip": "zip",
                            "text/plain": "txt",
                            "application/msword": "doc",
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                            "application/vnd.ms-excel": "xls",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
                            "application/vnd.ms-powerpoint": "ppt",
                            "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
                        }
                        ext = ext_map.get(ctype, "bin")
                        from datetime import datetime
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        name = f"upload_{ts}.{ext}"
                    files.append({"url": url, "name": name or "file.bin", "ctype": ctype or "application/octet-stream"})
            if not files:
                return False

            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)
            gid = svc.get_recent_task_gid(user_info.user_mail)
            if not gid:
                # Hint user to create task first
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text="ℹ️ 請先使用 @it 建立 IT 單，再上傳檔案，我會自動附加。")
                )
                return True

            # Try attach each image by URL
            ok = 0
            for a in files:
                name = a.get("name") or "file.bin"
                ctype = a.get("ctype") or "application/octet-stream"
                if "data" in a:
                    result = await svc.attach_image_bytes(user_info.user_mail, a["data"], name, ctype)
                else:
                    url = a["url"]
                    result = await svc.attach_image_from_url(user_info.user_mail, url, name, ctype)
                if result.get("success"):
                    ok += 1
                else:
                    await turn_context.send_activity(
                        Activity(type=ActivityTypes.message, text=f"❌ 檔案上傳失敗：{result.get('error')}")
                    )

            if ok:
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=f"✅ 已上傳 {ok} 個檔案至最近的 IT 單")
                )
            return True
        except Exception as e:
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=f"❌ 上傳檔案時發生錯誤：{str(e)}")
            )
            return True

    async def _send_welcome_message(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """發送歡迎訊息"""
        language = determine_language(user_info.user_mail)
        welcome_msg = {
            "zh": "🎉 歡迎使用台灣林內 GPT！\n我可以協助您管理待辦事項、預約會議室等功能。",
            "en": "🎉 Welcome to Taiwan Rinnai GPT!\nI can help you manage todos, book meeting rooms, and more.",
            "ja": "🎉 台湾リンナイGPTへようこそ！\nタスク管理、会議室予約などをサポートします。",
        }.get(language, "🎉 歡迎使用台灣林內 GPT！")

        include_model = not self.config.openai.use_azure
        help_card = self.help_card_builder.build_help_card(language, welcome_msg, include_model_option=include_model)
        await turn_context.send_activity(help_card)

    async def _show_add_todo_card(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示新增待辦事項卡片"""
        language = determine_language(user_info.user_mail)
        card = self.todo_card_builder.build_add_todo_card(language)
        await turn_context.send_activity(card)

    async def _show_todo_list(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示待辦事項清單"""
        todos = await self.todo_service.get_user_todos(
            user_info.user_mail, include_completed=False
        )
        language = determine_language(user_info.user_mail)

        if todos:
            card = self.todo_card_builder.build_todo_list_card(todos, language)
            await turn_context.send_activity(card)
            # 小提示（對齊 app_bak 互動風格）
            hint_msg = (
                "💡 小提示：下次可以直接輸入 `@ls` 快速查看待辦清單"
                if language == "zh-TW"
                else "💡 ヒント：次回は `@ls` で素早くTODOリストを確認できます"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=hint_msg)
            )
        else:
            suggested_actions = get_suggested_replies("無待辦事項", user_info.user_mail)
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="🎉 目前沒有待辦事項",
                    suggested_actions=(
                        SuggestedActions(actions=suggested_actions)
                        if suggested_actions
                        else None
                    ),
                )
            )

    async def _show_room_booking_options(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示會議室預約選項"""
        language = determine_language(user_info.user_mail)
        card = self.meeting_card_builder.build_room_booking_card(language)
        await turn_context.send_activity(card)
        # 小提示
        hint_msg = (
            "💡 小提示：也可以使用 `@book-room` 快速開啟預約表單"
            if language == "zh-TW"
            else "💡 ヒント：`@book-room` でも素早く予約フォームを開けます"
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=hint_msg)
        )

    async def _show_my_bookings(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示我的預約"""
        bookings = await self.meeting_service.get_user_meetings(user_info.user_mail)
        language = determine_language(user_info.user_mail)

        if bookings:
            card = self.meeting_card_builder.build_my_bookings_card(bookings, language)
            await turn_context.send_activity(card)
            hint_msg = (
                "💡 小提示：也可以使用 `@check-booking` 快速查看預約"
                if language == "zh-TW"
                else "💡 ヒント：`@check-booking` でも素早く予約を確認できます"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=hint_msg)
            )
        else:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="📅 目前沒有預約的會議室",
                )
            )

    async def _show_cancel_booking_options(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示取消預約選項"""
        bookings = await self.meeting_service.get_user_meetings(user_info.user_mail)
        language = determine_language(user_info.user_mail)

        if bookings:
            card = self.meeting_card_builder.build_cancel_booking_card(
                bookings, language
            )
            await turn_context.send_activity(card)
            hint_msg = (
                "💡 小提示：也可以使用 `@cancel-booking` 快速取消預約"
                if language == "zh-TW"
                else "💡 ヒント：`@cancel-booking` でも素早く予約をキャンセルできます"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=hint_msg)
            )
        else:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="📅 目前沒有可取消的會議室預約",
                )
            )

    async def _show_user_info(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示用戶資訊（擴充為更完整的個人檔案）。"""
        # 基本欄位
        lines = [
            "👤 **用戶資訊**",
            f"• 姓名: {user_info.user_name or '未知'}",
            f"• 郵箱: {user_info.user_mail}",
            f"• 用戶ID: {user_info.user_id}",
        ]

        # 系統狀態（模式/模型/意圖分析）
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
        lines += [
            "",
            "🤖 **系統狀態**",
            f"• 模式: {mode_text}",
            f"• 模型: {model_text}",
            f"• AI 意圖分析: {'啟用' if self.config.enable_ai_intent_analysis else '停用'}",
        ]

        # 透過 Graph 取得更完整的資料（部門/職稱/電話/分機等）
        try:
            from core.container import get_container
            from infrastructure.external.graph_api_client import GraphAPIClient

            container = get_container()
            graph: GraphAPIClient = container.get(GraphAPIClient)

            async with graph:
                profile = await graph.get_user_rich_profile(user_info.user_mail)
                manager = await graph.get_user_manager(user_info.user_mail)
                extension = graph.try_extract_extension(profile)

            dept = profile.get("department")
            title = profile.get("jobTitle")
            company = profile.get("companyName")
            office = profile.get("officeLocation")
            mobile = profile.get("mobilePhone")
            biz_phones = profile.get("businessPhones") or []
            employee_id = profile.get("employeeId")
            org = profile.get("employeeOrgData") or {}
            cost_center = org.get("costCenter")
            division = org.get("division")
            mgr_name = ((manager or {}).get("displayName")) if manager else None

            if dept:
                lines.append(f"• 部門: {dept}")
            if title:
                lines.append(f"• 職稱: {title}")
            if company:
                lines.append(f"• 公司: {company}")
            if office:
                lines.append(f"• 辦公室: {office}")
            if extension:
                lines.append(f"• 分機: {extension}")
            if mobile:
                lines.append(f"• 手機: {mobile}")
            if biz_phones:
                lines.append(f"• 電話: {'、'.join(biz_phones)}")
            if employee_id:
                lines.append(f"• 員工編號: {employee_id}")
            if cost_center or division:
                cc = f"成本中心: {cost_center}" if cost_center else None
                dv = f"事業群: {division}" if division else None
                org_line = "、".join([v for v in [cc, dv] if v])
                if org_line:
                    lines.append(f"• {org_line}")
            if mgr_name:
                lines.append(f"• 主管: {mgr_name}")
        except Exception as e:
            # 若 Graph 取資料失敗，僅顯示基本欄位
            pass

        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text="\n".join(lines))
        )

    async def _show_bot_intro(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示機器人介紹"""
        language = determine_language(user_info.user_mail)
        intro_card = self.help_card_builder.build_bot_intro_card(language)
        await turn_context.send_activity(intro_card)

    async def _show_model_selection(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """顯示模型選擇"""
        if self.config.openai.use_azure:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="ℹ️ 目前使用 Azure OpenAI 服務\n📱 模型：o1-mini（固定）\n⚡ 此模式不支援模型切換",
                )
            )
            return

        # OpenAI 模式：顯示模型選擇卡片
        card = self.model_card_builder.build_model_selection_card(user_info.user_mail)
        await turn_context.send_activity(card)

    async def _handle_add_todo_card(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """處理新增待辦事項卡片"""
        content = turn_context.activity.value.get("todoContent", "").strip()
        if content:
            await self._handle_smart_todo_add(turn_context, user_info, content)

    async def _handle_smart_todo_add(
        self, turn_context: TurnContext, user_info: BotInteractionDTO, content: str
    ) -> None:
        """智能新增待辦事項"""
        try:
            todo, similar_todos = await self.todo_service.smart_create_todo(
                user_info.user_mail, content
            )

            if similar_todos:
                # 有相似的待辦事項，顯示確認卡片
                language = determine_language(user_info.user_mail)
                card = self.todo_card_builder.build_similar_todos_confirmation_card(
                    content, similar_todos, language
                )
                await turn_context.send_activity(card)
            elif todo:
                # 成功新增
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=f"✅ 已新增待辦事項：{todo.content}",
                    )
                )
                # 小提示
                language = determine_language(user_info.user_mail)
                hint_msg = (
                    "💡 小提示：下次可以使用 `@add 內容` 快速新增待辦"
                    if language == "zh-TW"
                    else "💡 ヒント：次回は `@add 内容` で素早くTODOを追加できます"
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=hint_msg)
                )
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message, text=f"❌ 新增待辦事項失敗：{str(e)}"
                )
            )

    async def _handle_complete_todos(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """處理完成待辦事項"""
        completed_indices_str = turn_context.activity.value.get("completedTodos", "")

        if not completed_indices_str:
            return

        try:
            # 解析完成的待辦事項索引
            completed_indices = [
                int(idx.strip())
                for idx in completed_indices_str.split(",")
                if idx.strip()
            ]

            if completed_indices:
                completed_todos = await self.todo_service.batch_complete_todos(
                    completed_indices, user_info.user_mail
                )

                if completed_todos:
                    completed_text = "\n".join(
                        [f"• {todo.content}" for todo in completed_todos]
                    )
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text=f"✅ 已完成 {len(completed_todos)} 項待辦事項：\n{completed_text}",
                        )
                    )
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message, text="❌ 無法完成指定的待辦事項"
                        )
                    )
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 完成待辦事項時發生錯誤：{str(e)}",
                )
            )

    async def _handle_book_room(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """處理會議室預約"""
        # 從卡片提取預約信息
        booking_data = {
            "room_id": turn_context.activity.value.get("selectedRoom"),
            "date": turn_context.activity.value.get("selectedDate"),
            "start_time": turn_context.activity.value.get("startTime"),
            "end_time": turn_context.activity.value.get("endTime"),
            "subject": turn_context.activity.value.get("subject", ""),
            # "attendees": turn_context.activity.value.get("attendees", "")
        }

        try:
            booking_result = await self.meeting_service.book_meeting_room(
                user_info.user_mail, booking_data
            )

            if booking_result.get("success"):
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=f"✅ 成功預約會議室：{booking_data['subject']}",
                    )
                )
            else:
                error_msg = booking_result.get("error", "未知錯誤")
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message, text=f"❌ 預約失敗：{error_msg}"
                    )
                )
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"❌ 預約會議室時發生錯誤：{str(e)}",
                )
            )

    async def _handle_cancel_booking(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """處理取消預約"""
        booking_id = turn_context.activity.value.get("selectedBooking")

        if not booking_id:
            return

        try:
            cancel_result = await self.meeting_service.cancel_meeting(
                user_info.user_mail, booking_id
            )

            if cancel_result.get("success"):
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text="✅ 已成功取消會議室預約")
                )
            else:
                error_msg = cancel_result.get("error", "未知錯誤")
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message, text=f"❌ 取消預約失敗：{error_msg}"
                    )
                )
        except Exception as e:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message, text=f"❌ 取消預約時發生錯誤：{str(e)}"
                )
            )

    async def _handle_model_selection(
        self, turn_context: TurnContext, user_info: BotInteractionDTO
    ) -> None:
        """處理模型選擇"""
        selected_model = turn_context.activity.value.get("selectedModel")

        if selected_model:
            # 更新用戶模型偏好
            # 這裡應該透過用戶服務來更新
            from app import user_model_preferences, MODEL_INFO

            user_model_preferences[user_info.user_mail] = selected_model

            model_info = MODEL_INFO.get(selected_model, {})
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=f"✅ 已切換到模型：{selected_model}\n{model_info.get('use_case', '')}",
                )
            )

    async def _send_error_response(self, turn_context: TurnContext) -> None:
        """發送錯誤回應"""
        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text="❌ 處理您的請求時發生錯誤，請稍後再試。",
            )
        )

    async def show_help_options(
        self, turn_context: TurnContext, welcome_msg: str = None
    ):
        """顯示幫助選項（從原始 app_bak.py 遷移）"""
        # 取得用戶語系
        user_id = turn_context.activity.from_property.id
        user_mail = await get_user_email(turn_context) or f"{user_id}@unknown.com"
        language = determine_language(user_mail)

        # 使用 HelpCardBuilder 輸出 Adaptive Card（與 app_bak 一致透過 Attachment）
        welcome_text = welcome_msg or {
            "zh-TW": "🛠️ 功能選單",
            "en": "🛠️ Function Menu",
            "ja": "🛠️ 機能メニュー",
        }.get(language, "🛠️ 功能選單")

        card = self.help_card_builder.build_help_card(language, welcome_text)
        await turn_context.send_activity(card)
