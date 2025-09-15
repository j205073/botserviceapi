"""
Teams Bot 卡片建構器
負責建構各種 Adaptive Cards 用於 Teams 介面
"""

from typing import List, Dict, Any, Optional
from botbuilder.schema import (
    Activity,
    ActivityTypes,
    Attachment,
    HeroCard,
    CardAction,
    ActionTypes,
)
from domain.models.todo import TodoItem
from shared.utils.helpers import get_taiwan_time
from datetime import timedelta
from config.meeting_rooms import get_meeting_rooms


class BaseCardBuilder:
    """卡片建構器基類"""

    def create_attachment(self, card_content: Dict[str, Any]) -> Attachment:
        """創建 Adaptive Card 附件"""
        return Attachment(
            content_type="application/vnd.microsoft.card.adaptive", content=card_content
        )

    def create_activity_with_card(self, card_content: Dict[str, Any]) -> Activity:
        """創建包含卡片的 Activity"""
        attachment = self.create_attachment(card_content)
        return Activity(type=ActivityTypes.message, attachments=[attachment])


class TodoCardBuilder(BaseCardBuilder):
    """待辦事項卡片建構器"""

    def build_add_todo_card(self, language: str = "zh") -> Activity:
        """建構新增待辦事項卡片"""
        texts = {
            "zh": {
                "title": "新增待辦事項",
                "placeholder": "請輸入待辦事項內容...",
                "button": "新增",
            },
            "en": {
                "title": "Add Todo Item",
                "placeholder": "Enter todo content...",
                "button": "Add",
            },
            "ja": {
                "title": "タスクの追加",
                "placeholder": "タスク内容を入力...",
                "button": "追加",
            },
        }

        text = texts.get(language, texts["zh"])

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"📝 {text['title']}",
                    "size": "Medium",
                    "weight": "Bolder",
                },
                {
                    "type": "Input.Text",
                    "id": "todoContent",
                    "placeholder": text["placeholder"],
                    "isMultiline": True,
                    "maxLength": 500,
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": f"✅ {text['button']}",
                    "data": {"action": "addTodo"},
                }
            ],
        }

        return self.create_activity_with_card(card_content)

    def build_todo_list_card(
        self, todos: List[TodoItem], language: str = "zh"
    ) -> Activity:
        """建構待辦事項清單卡片"""
        texts = {
            "zh": {
                "title": "📋 待辦事項清單",
                "empty": "目前沒有待辦事項",
                "complete_selected": "完成選取的項目",
                "select_placeholder": "選取要完成的項目",
            },
            "en": {
                "title": "📋 Todo List",
                "empty": "No pending todos",
                "complete_selected": "Complete Selected",
                "select_placeholder": "Select items to complete",
            },
            "ja": {
                "title": "📋 タスク一覧",
                "empty": "保留中のタスクはありません",
                "complete_selected": "選択したものを完了",
                "select_placeholder": "完了する項目を選択",
            },
        }

        text = texts.get(language, texts["zh"])

        if not todos:
            card_content = {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.3",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": text["title"],
                        "size": "Medium",
                        "weight": "Bolder",
                    },
                    {"type": "TextBlock", "text": f"🎉 {text['empty']}", "wrap": True},
                ],
            }
            return self.create_activity_with_card(card_content)

        # 建構待辦事項列表與下拉選項
        todo_items = []
        choices = []
        for idx, todo in enumerate(todos):
            i = idx + 1
            created_time = todo.created_at.strftime("%m/%d %H:%M")
            todo_items.append(
                {
                    "type": "TextBlock",
                    "text": f"{i}. {todo.content}",
                    "wrap": True,
                    "spacing": "Small",
                }
            )
            todo_items.append(
                {
                    "type": "TextBlock",
                    "text": f"   📅 {created_time}",
                    "size": "Small",
                    "color": "Accent",
                    "spacing": "None",
                }
            )
            # ChoiceSet 選項值使用 0-based 索引，與後端 batch_complete_todos 對齊
            choices.append({"title": f"{i}. {todo.content}", "value": str(idx)})

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"{text['title']} ({len(todos)})",
                    "size": "Medium",
                    "weight": "Bolder",
                },
                {"type": "Container", "items": todo_items},
                {
                    "type": "Input.ChoiceSet",
                    "id": "completedTodos",
                    "style": "compact",
                    "isMultiSelect": True,
                    "placeholder": text["select_placeholder"],
                    "choices": choices,
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": f"✅ {text['complete_selected']}",
                    "data": {"action": "completeTodos"},
                }
            ],
        }

        return self.create_activity_with_card(card_content)

    def build_similar_todos_confirmation_card(
        self,
        new_content: str,
        similar_todos: List[Dict[str, Any]],
        language: str = "zh",
    ) -> Activity:
        """建構相似待辦事項確認卡片"""
        texts = {
            "zh": {
                "title": "發現相似的待辦事項",
                "new_item": "新項目",
                "similar_items": "相似項目",
                "confirm_add": "確認新增",
                "similarity": "相似度",
            },
            "en": {
                "title": "Similar Todos Found",
                "new_item": "New Item",
                "similar_items": "Similar Items",
                "confirm_add": "Confirm Add",
                "similarity": "Similarity",
            },
            "ja": {
                "title": "類似タスクが見つかりました",
                "new_item": "新しい項目",
                "similar_items": "類似項目",
                "confirm_add": "追加を確認",
                "similarity": "類似度",
            },
        }

        text = texts.get(language, texts["zh"])

        # 建構相似項目列表
        similar_items = []
        for item in similar_todos:
            todo = item["todo"]
            similarity_percent = item["similarity_percent"]
            similar_items.append(
                {"type": "TextBlock", "text": f"• {todo.content}", "wrap": True}
            )
            similar_items.append(
                {
                    "type": "TextBlock",
                    "text": f"  {text['similarity']}: {similarity_percent}%",
                    "size": "Small",
                    "color": "Accent",
                    "spacing": "None",
                }
            )

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"⚠️ {text['title']}",
                    "size": "Medium",
                    "weight": "Bolder",
                    "color": "Warning",
                },
                {
                    "type": "TextBlock",
                    "text": f"**{text['new_item']}:**",
                    "weight": "Bolder",
                    "spacing": "Medium",
                },
                {
                    "type": "TextBlock",
                    "text": new_content,
                    "wrap": True,
                    "color": "Good",
                },
                {
                    "type": "TextBlock",
                    "text": f"**{text['similar_items']}:**",
                    "weight": "Bolder",
                    "spacing": "Medium",
                },
                {"type": "Container", "items": similar_items},
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": f"✅ {text['confirm_add']}",
                    "data": {
                        "action": "addTodo",
                        "todoContent": new_content,
                        "confirmed": True,
                    },
                }
            ],
        }

        return self.create_activity_with_card(card_content)


class HelpCardBuilder(BaseCardBuilder):
    """說明卡片建構器"""

    def build_help_card(
        self,
        language: str = "zh",
        welcome_msg: str = None,
        include_model_option: Optional[bool] = None,
    ) -> Activity:
        """建構說明卡片"""
        texts = {
            "zh": {
                "functions": [
                    {
                        "title": "📋 查看待辦",
                        "value": "@ls",
                        "desc": "查看目前的待辦事項",
                    },
                    {
                        "title": "➕ 新增待辦",
                        "value": "@addTodo",
                        "desc": "新增待辦事項",
                    },
                    {
                        "title": "🏢 預約會議室",
                        "value": "@book-room",
                        "desc": "預約會議室",
                    },
                    {
                        "title": "📅 查看預約",
                        "value": "@check-booking",
                        "desc": "查看我的會議室預約",
                    },
                    {
                        "title": "❌ 取消預約",
                        "value": "@cancel-booking",
                        "desc": "取消會議室預約",
                    },
                    {
                        "title": "👤 個人資訊",
                        "value": "@info",
                        "desc": "查看個人資訊和統計",
                    },
                    {
                        "title": "🤖 關於TR GPT",
                        "value": "@you",
                        "desc": "了解機器人功能",
                    },
                ]
            },
            "en": {
                "functions": [
                    {
                        "title": "📋 List Todos",
                        "value": "@ls",
                        "desc": "View current todo items",
                    },
                    {
                        "title": "➕ Add Todo",
                        "value": "@addTodo",
                        "desc": "Add new todo item",
                    },
                    {
                        "title": "🏢 Book Room",
                        "value": "@book-room",
                        "desc": "Book meeting room",
                    },
                    {
                        "title": "📅 Check Booking",
                        "value": "@check-booking",
                        "desc": "View my room bookings",
                    },
                    {
                        "title": "❌ Cancel Booking",
                        "value": "@cancel-booking",
                        "desc": "Cancel room booking",
                    },
                    {
                        "title": "👤 Profile",
                        "value": "@info",
                        "desc": "View profile and statistics",
                    },
                    {
                        "title": "🤖 About TR GPT",
                        "value": "@you",
                        "desc": "Learn about bot features",
                    },
                ]
            },
            "ja": {
                "functions": [
                    {
                        "title": "📋 タスク表示",
                        "value": "@ls",
                        "desc": "現在のタスクを表示",
                    },
                    {
                        "title": "➕ タスク追加",
                        "value": "@addTodo",
                        "desc": "新しいタスクを追加",
                    },
                    {
                        "title": "🏢 会議室予約",
                        "value": "@book-room",
                        "desc": "会議室を予約",
                    },
                    {
                        "title": "📅 予約確認",
                        "value": "@check-booking",
                        "desc": "私の会議室予約を確認",
                    },
                    {
                        "title": "❌ 予約キャンセル",
                        "value": "@cancel-booking",
                        "desc": "会議室予約をキャンセル",
                    },
                    {
                        "title": "👤 プロフィール",
                        "value": "@info",
                        "desc": "プロフィールと統計を表示",
                    },
                    {
                        "title": "🤖 ボットについて (TR GPT)",
                        "value": "@you",
                        "desc": "ボット機能について学ぶ",
                    },
                ]
            },
        }

        text = texts.get(language, texts["zh"])

        # 動態補上模型切換（預設由配置判斷：OpenAI 模式才顯示）
        if include_model_option is None:
            try:
                from core.container import get_container
                from config.settings import AppConfig

                cfg: AppConfig = get_container().get(AppConfig)
                include_model_option = not cfg.openai.use_azure
            except Exception:
                include_model_option = False

        functions = list(text["functions"])  # copy
        if include_model_option:
            lang = language or "zh"
            is_zh = lang.startswith("zh")
            is_en = lang.startswith("en")
            title = (
                "🤖 選擇 AI 模型"
                if is_zh
                else ("🤖 Select AI Model" if is_en else "🤖 AIモデル選択")
            )
            desc = (
                "在 OpenAI 模式下切換模型"
                if is_zh
                else (
                    "Switch model in OpenAI mode"
                    if is_en
                    else "OpenAIモードでモデル切替"
                )
            )
            functions.append(
                {
                    "title": title,
                    "value": "@model",
                    "desc": desc,
                }
            )

        # 建構功能選擇項目
        choices = []
        for func in functions:
            choices.append({"title": func["title"], "value": func["value"]})

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": welcome_msg or "🛠️ 功能選單",
                    "size": "Medium",
                    "weight": "Bolder",
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selectedFunction",
                    "style": "compact",
                    "choices": choices,
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "執行功能",
                    "data": {"action": "selectFunction"},
                }
            ],
        }

        return self.create_activity_with_card(card_content)

    def build_bot_intro_card(self, language: str = "zh") -> Activity:
        """建構機器人介紹卡片"""
        texts = {
            "zh": {
                "title": "🤖 台灣林內 GPT",
                "description": "我是您的智能助手，專為台灣林內公司設計，提供以下服務：",
                "features": [
                    "📋 待辦事項管理 - 新增、查看、完成待辦事項",
                    "🏢 會議室預約 - 預約、查看、取消會議室",
                    "💬 智能對話 - AI 驅動的問答系統",
                    "📊 個人統計 - 查看您的使用統計資訊",
                    "🌍 多語言支援 - 支援中文、英文、日文",
                ],
                "footer": "使用 @help 查看所有可用功能",
            },
            "en": {
                "title": "🤖 Taiwan Rinnai GPT",
                "description": "I'm your intelligent assistant designed for Taiwan Rinnai, providing:",
                "features": [
                    "📋 Todo Management - Add, view, complete todos",
                    "🏢 Room Booking - Book, view, cancel meeting rooms",
                    "💬 Smart Chat - AI-powered Q&A system",
                    "📊 Personal Stats - View your usage statistics",
                    "🌍 Multi-language - Chinese, English, Japanese support",
                ],
                "footer": "Use @help to see all available functions",
            },
            "ja": {
                "title": "🤖 台湾リンナイ GPT",
                "description": "台湾リンナイ向けに設計されたインテリジェントアシスタントです：",
                "features": [
                    "📋 タスク管理 - タスクの追加、表示、完了",
                    "🏢 会議室予約 - 会議室の予約、確認、キャンセル",
                    "💬 スマートチャット - AI搭載のQ&Aシステム",
                    "📊 個人統計 - 使用統計の確認",
                    "🌍 多言語対応 - 中国語、英語、日本語をサポート",
                ],
                "footer": "@help ですべての機能を確認",
            },
        }

        text = texts.get(language, texts["zh"])

        # 建構功能項目
        feature_items = []
        for feature in text["features"]:
            feature_items.append(
                {"type": "TextBlock", "text": feature, "wrap": True, "spacing": "Small"}
            )

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": text["title"],
                    "size": "Medium",
                    "weight": "Bolder",
                },
                {
                    "type": "TextBlock",
                    "text": text["description"],
                    "wrap": True,
                    "spacing": "Medium",
                },
                {"type": "Container", "items": feature_items, "spacing": "Medium"},
                {
                    "type": "TextBlock",
                    "text": f"💡 {text['footer']}",
                    "wrap": True,
                    "color": "Accent",
                    "spacing": "Medium",
                },
            ],
        }

        return self.create_activity_with_card(card_content)


class MeetingCardBuilder(BaseCardBuilder):
    """會議室卡片建構器"""

    def build_room_booking_card(self, language: str = "zh") -> Activity:
        """建構會議室預約卡片"""
        texts = {
            "zh": {
                "title": "🏢 預約會議室",
                "room_label": "選擇會議室",
                "date_label": "日期",
                "start_time_label": "開始時間",
                "end_time_label": "結束時間",
                "subject_label": "會議主題",
                "attendees_label": "與會者 (選填)",
                "book_button": "預約",
            },
            "en": {
                "title": "🏢 Book Meeting Room",
                "room_label": "Select Room",
                "date_label": "Date",
                "start_time_label": "Start Time",
                "end_time_label": "End Time",
                "subject_label": "Subject",
                "attendees_label": "Attendees (Optional)",
                "book_button": "Book",
            },
            "ja": {
                "title": "🏢 会議室予約",
                "room_label": "会議室選択",
                "date_label": "日付",
                "start_time_label": "開始時間",
                "end_time_label": "終了時間",
                "subject_label": "会議件名",
                "attendees_label": "参加者 (任意)",
                "book_button": "予約",
            },
        }

        text = texts.get(language, texts["zh"])

        # 會議室選項從設定載入
        rooms = get_meeting_rooms()
        room_choices = [
            {"title": r["displayName"], "value": r["emailAddress"]} for r in rooms
        ]

        # 預設日期時間（台灣時區）
        now = get_taiwan_time()
        date_value = now.strftime("%Y-%m-%d")
        # 將預設開始時間對齊到下一個 30 分鐘刻度，結束時間預設 +1 小時
        minute = now.minute
        if minute < 30:
            start_aligned = now.replace(minute=30, second=0, microsecond=0)
        else:
            start_aligned = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        end_aligned = start_aligned + timedelta(hours=1)
        start_time_value = start_aligned.strftime("%H:%M")
        end_time_value = end_aligned.strftime("%H:%M")

        # 時間選單（每 30 分鐘一個選項），使用 ChoiceSet 以獲得較佳的滾動/列表體驗於 Teams
        def build_time_choices() -> list:
            choices = []
            for h in range(0, 24):
                for m in (0, 30):
                    value = f"{h:02d}:{m:02d}"
                    # 顯示文字加上 AM/PM 提示，提升易讀性
                    ampm = "AM" if h < 12 else "PM"
                    title = f"{value} ({ampm})"
                    choices.append({"title": title, "value": value})
            return choices

        time_choices = build_time_choices()

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": text["title"],
                    "size": "Medium",
                    "weight": "Bolder",
                },
                {
                    "type": "Input.Text",
                    "id": "subject",
                    "label": text["subject_label"],
                    "placeholder": "請輸入會議主題",
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selectedRoom",
                    "label": text["room_label"],
                    "style": "compact",
                    "choices": room_choices,
                },
                {
                    "type": "Input.Date",
                    "id": "selectedDate",
                    "label": text["date_label"],
                    "value": date_value,
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "startTime",
                    "label": text["start_time_label"],
                    "style": "expanded",
                    "choices": time_choices,
                    "value": start_time_value,
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "endTime",
                    "label": text["end_time_label"],
                    "style": "expanded",
                    "choices": time_choices,
                    "value": end_time_value,
                },
                # {
                #     "type": "Input.Text",
                #     "id": "attendees",
                #     "label": text["attendees_label"],
                #     "placeholder": "email1@company.com, email2@company.com"
                # }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": f"📅 {text['book_button']}",
                    "data": {"action": "bookRoom"},
                }
            ],
        }

        return self.create_activity_with_card(card_content)

    def build_my_bookings_card(
        self, bookings: List[Dict[str, Any]], language: str = "zh"
    ) -> Activity:
        """建構我的預約卡片"""
        texts = {
            "zh": {"title": "📅 我的會議室預約", "no_bookings": "目前沒有預約"},
            "en": {"title": "📅 My Room Bookings", "no_bookings": "No bookings found"},
            "ja": {"title": "📅 私の会議室予約", "no_bookings": "予約はありません"},
        }

        text = texts.get(language, texts["zh"])

        if not bookings:
            card_content = {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.3",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": text["title"],
                        "size": "Medium",
                        "weight": "Bolder",
                    },
                    {"type": "TextBlock", "text": text["no_bookings"], "wrap": True},
                ],
            }
            return self.create_activity_with_card(card_content)

        # 建構預約列表
        booking_items = []
        for booking in bookings:
            # 主旨後綴：若非發起人，顯示 (與會)
            subject = booking.get("subject", "未命名會議")
            if not booking.get("is_organizer", True):
                subject = f"{subject} (與會)"
            booking_items.append(
                {
                    "type": "TextBlock",
                    "text": f"🏢 {subject}",
                    "weight": "Bolder",
                    "wrap": True,
                }
            )
            booking_items.append(
                {
                    "type": "TextBlock",
                    "text": f"📍 {booking.get('location', '會議室')}",
                    "spacing": "None",
                }
            )
            booking_items.append(
                {
                    "type": "TextBlock",
                    "text": f"🕐 {booking.get('start_time', '')} - {booking.get('end_time', '')}",
                    "spacing": "None",
                    "color": "Accent",
                }
            )

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"{text['title']} ({len(bookings)})",
                    "size": "Medium",
                    "weight": "Bolder",
                },
                {"type": "Container", "items": booking_items, "spacing": "Medium"},
            ],
        }

        return self.create_activity_with_card(card_content)

    def build_cancel_booking_card(
        self, bookings: List[Dict[str, Any]], language: str = "zh"
    ) -> Activity:
        """建構取消預約卡片"""
        texts = {
            "zh": {
                "title": "❌ 取消會議室預約",
                "select_label": "選擇要取消的預約",
                "cancel_button": "取消預約",
            },
            "en": {
                "title": "❌ Cancel Room Booking",
                "select_label": "Select booking to cancel",
                "cancel_button": "Cancel Booking",
            },
            "ja": {
                "title": "❌ 会議室予約キャンセル",
                "select_label": "キャンセルする予約を選択",
                "cancel_button": "予約キャンセル",
            },
        }

        text = texts.get(language, texts["zh"])

        # 建構預約選擇項目
        choices = []
        for booking in bookings:
            subject = booking.get("subject", "未命名")
            if not booking.get("is_organizer", True):
                subject = f"{subject} (與會)"
            start_time = booking.get("start_time", "")
            end_time = booking.get("end_time", "")
            title = f"{subject} ({start_time} - {end_time})"
            choices.append({"title": title, "value": booking.get("id", "")})

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": text["title"],
                    "size": "Medium",
                    "weight": "Bolder",
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selectedBooking",
                    "label": text["select_label"],
                    "choices": choices,
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": text["cancel_button"],
                    "data": {"action": "cancelBooking"},
                }
            ],
        }

        return self.create_activity_with_card(card_content)


class ModelSelectionCardBuilder(BaseCardBuilder):
    """模型選擇卡片建構器"""

    def build_model_selection_card(self, user_mail: str) -> Activity:
        """建構模型選擇卡片"""
        # 模型資訊維持來源於 app.MODULE_INFO；預設模型改由配置取得
        from app import user_model_preferences, MODEL_INFO
        from core.container import get_container
        from config.settings import AppConfig

        # 透過配置取得預設模型，避免依賴 OPENAI_MODEL 常數
        try:
            config = get_container().get(AppConfig)
            default_model = config.openai.model or "gpt-4o-mini"
        except Exception:
            default_model = "gpt-4o-mini"

        current_model = user_model_preferences.get(user_mail, default_model)

        # 建構模型選擇項目
        choices = []
        for model_name, info in MODEL_INFO.items():
            title = f"{model_name} - {info.get('use_case', '')}"
            choices.append({"title": title, "value": model_name})

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "🤖 選擇 AI 模型",
                    "size": "Medium",
                    "weight": "Bolder",
                },
                {
                    "type": "TextBlock",
                    "text": f"目前使用：{current_model}",
                    "color": "Accent",
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selectedModel",
                    "label": "選擇新模型",
                    "value": current_model,
                    "choices": choices,
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "切換模型",
                    "data": {"action": "selectModel"},
                }
            ],
        }

        return self.create_activity_with_card(card_content)
