"""
Bot Framework 適配器
處理 Microsoft Bot Framework 的連接和消息路由
"""
from typing import Dict, Any, Callable, Awaitable
from botbuilder.core import (
    BotFrameworkAdapter, 
    BotFrameworkAdapterSettings,
    TurnContext,
    ActivityHandler
)
from botbuilder.schema import Activity

from config.settings import AppConfig
from presentation.bot.message_handler import TeamsMessageHandler
from shared.exceptions import BotFrameworkError
from shared.utils.helpers import get_user_email, determine_language


class CustomBotAdapter:
    """自定義 Bot 適配器"""
    
    def __init__(self, config: AppConfig, message_handler: TeamsMessageHandler):
        self.config = config
        self.message_handler = message_handler
        
        # 創建 Bot Framework 設定
        self.settings = BotFrameworkAdapterSettings(
            app_id=config.bot.app_id,
            app_password=config.bot.app_password
        )
        
        # 創建 Bot Framework 適配器
        self.adapter = BotFrameworkAdapter(self.settings)
        
        # 註冊錯誤處理器
        self.adapter.on_turn_error = self._on_turn_error
    
    async def _on_turn_error(self, context: TurnContext, error: Exception) -> None:
        """Turn 錯誤處理器"""
        print(f"❌ Bot Framework Turn 錯誤: {error}")
        
        try:
            # 發送錯誤消息給用戶
            await context.send_activity(
                Activity(
                    type="message",
                    text="抱歉，處理您的請求時發生錯誤。請稍後再試。"
                )
            )
        except Exception as send_error:
            print(f"❌ 發送錯誤消息失敗: {send_error}")
    
    async def process_activity(self, activity_data: Dict[str, Any], auth_header: str = "") -> Dict[str, Any]:
        """處理活動"""
        try:
            # 創建活動對象
            activity = Activity().deserialize(activity_data)
            
            # 創建處理器（重現原始 aux_func 邏輯）
            async def aux_func(turn_context):
                try:
                    if activity.type == "conversationUpdate":
                        # 處理成員加入
                        if activity.members_added:
                            for member in activity.members_added:
                                if member.id != activity.recipient.id:
                                    await self._welcome_user(turn_context)
                        # 處理成員離開
                        if activity.members_removed:
                            for member in activity.members_removed:
                                print(f"📤 用戶離開: {member.name} ({member.id})")
                    elif activity.type == "message":
                        await self.message_handler.handle_message(turn_context)
                except Exception as e:
                    print(f"Error in aux_func: {str(e)}")
                    return
            
            # 處理活動
            invoke_response = await self.adapter.process_activity(
                activity, 
                auth_header, 
                aux_func
            )
            
            return invoke_response
            
        except Exception as e:
            error_msg = f"處理 Bot 活動失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise BotFrameworkError(error_msg) from e
    
    def get_conversation_reference(self, activity: Activity):
        """獲取對話參考"""
        return TurnContext.get_conversation_reference(activity)


    async def _welcome_user(self, turn_context: TurnContext):
        """歡迎使用者 - 完整版本（從原始 app_bak.py 遷移）"""
        user_name = turn_context.activity.from_property.name

        try:
            user_mail = await get_user_email(turn_context)
        except Exception as e:
            print(f"取得用戶 email 時發生錯誤: {str(e)}")
            user_mail = None

        language = determine_language(user_mail)

        # 檢查是否使用 OpenAI API 來決定歡迎訊息內容
        model_switch_info_zh = ""
        model_switch_info_ja = ""

        if not self.config.openai.use_azure:
            model_switch_info_zh = """
🤖 AI 模型功能：
- 輸入 @model 可切換 AI 模型
- 支援 gpt-4o、gpt-5-mini、gpt-5-nano、gpt-5 等模型
- 預設使用：gpt-5-mini (輕量版推理模型)
"""
            model_switch_info_ja = """
🤖 AI モデル機能：
- @model を入力してAIモデルを切り替え
- gpt-4o、gpt-5-mini、gpt-5-nano、gpt-5 などのモデルに対応
- デフォルト：gpt-5-mini（推理タスク専用）
"""

        system_prompts = {
            "zh-TW": f"""歡迎 {user_name} 使用 TR GPT！

我可以協助您：
- 回答各種問題
- 多語言翻譯
- 智能建議與諮詢
- 個人待辦事項管理
{model_switch_info_zh}
對話設定：
- 對話記錄：最多 {self.config.database.max_context_messages} 筆訊息
- 待辦事項：保存 {self.config.database.retention_days} 天

有什麼我可以幫您的嗎？

(提示：輸入 @help 可快速查看系統功能)""",
            "ja": f"""{user_name} さん、TR GPT インテリジェントアシスタントへようこそ！

お手伝いできること：
- あらゆる質問への対応
- 多言語翻訳
- インテリジェントな提案とアドバイス
- 個人タスク管理
{model_switch_info_ja}
会話設定：
- 会話記録：最大 {self.config.database.max_context_messages} 件のメッセージ
- タスク：{self.config.database.retention_days} 日間保存

何かお力になれることはありますか？

(ヒント：@help と入力すると、システム機能を quickly 確認できます)
            """,
        }

        system_prompt = system_prompts.get(language, system_prompts["zh-TW"])
        welcome_text = system_prompt
        
        # 發送歡迎訊息並顯示幫助選項
        await self.message_handler.show_help_options(turn_context, welcome_text)


def create_bot_adapter(config: AppConfig, message_handler: TeamsMessageHandler) -> CustomBotAdapter:
    """創建 Bot 適配器"""
    return CustomBotAdapter(config, message_handler)