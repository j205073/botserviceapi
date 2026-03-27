from datetime import datetime, timedelta
from typing import List, Dict

from openai import OpenAI, AzureOpenAI

# from flask import Flask, request, jsonify  # 已改用 Quart
from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import (
    Activity,
    Attachment,
    HeroCard,
    CardAction,
    ActionTypes,
    SuggestedActions,
    ActivityTypes,
)
from typing import Dict, Any
import os
import asyncio
import aiohttp
from dotenv import load_dotenv
import io
import pandas as pd
from docx import Document
from PyPDF2 import PdfReader
from PIL import Image
import base64
import urllib.request
import json
from urllib.parse import quote, urljoin
from graph_api import GraphAPI  # 假設你已經有這個模組
from token_manager import TokenManager  # 假設你已經有這個模組
from s3_manager import S3Manager
import sys
import logging
from quart import Quart, request, jsonify
from quart.helpers import make_response
import time
from threading import Timer
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import gzip
import pytz

logging.basicConfig(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
# gpt token數
max_tokens = 4000
# 初始化 Token 管理器和 Graph API（暫時註釋用於測試）
token_manager = TokenManager(
    tenant_id=os.getenv("TENANT_ID"),
    client_id=os.getenv("CLIENT_ID"),
    client_secret=os.getenv("CLIENT_SECRET"),
)
graph_api = GraphAPI(token_manager)

# 載入環境變數
load_dotenv()

# === Debug 參數 ===
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
DEBUG_ACCOUNT = os.getenv("DEBUG_ACCOUNT", "")  # 如果為空則使用實際用戶
print(f"Debug 模式: {DEBUG_MODE}")
if DEBUG_MODE and DEBUG_ACCOUNT:
    print(f"Debug 指定帳號: {DEBUG_ACCOUNT}")

#   清理邏輯
#   - 記憶體清理：達到 MAX_CONTEXT_MESSAGES 時自動清除該用戶記憶體
#   - S3上傳：每天早上7點台灣時間自動上傳所有待上傳的日誌

# === 對話管理參數 ===
CONVERSATION_RETENTION_DAYS = int(os.getenv("CONVERSATION_RETENTION_DAYS", "30"))
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "5"))
# === 稽核日誌參數 ===
# S3_UPLOAD_INTERVAL_HOURS = int(os.getenv("S3_UPLOAD_INTERVAL_HOURS", "24"))
# === 待辦事項提醒參數 ===
TODO_REMINDER_INTERVAL_SECONDS = int(
    os.getenv("TODO_REMINDER_INTERVAL_SECONDS", "3600")
)  # 預設1小時

# === S3 設定 ===
# 初始化 S3 管理器
s3_manager = S3Manager()

# Quart 應用設定
app = Quart(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

appId = os.getenv("BOT_APP_ID")
appPwd = os.getenv("BOT_APP_PASSWORD")
settings = BotFrameworkAdapterSettings(appId, appPwd)
adapter = BotFrameworkAdapter(settings)

# === 雙層存儲系統 ===
# 工作記憶體 - 用於 AI 對話處理（受筆數限制）
conversation_history = {}
conversation_message_counts = {}
conversation_timestamps = {}
# 使用者顯示名稱快取
user_display_names: Dict[str, str] = {}

# 稽核日誌 - 用於完整記錄和上傳 S3（按用戶郵箱分組）
audit_logs_by_user = {}  # {user_mail: [messages]}
audit_log_timestamps = {}  # {user_mail: timestamp}

# 待辦事項 - 用於個人助手功能（按用戶郵箱分組）
user_todos = {}  # {user_mail: {todo_id: {content, created, status}}}
todo_timestamps = {}  # {user_mail: timestamp}
todo_counter = 0  # 全局待辦事項 ID 計數器

# 用戶對話資訊 - 用於主動發送訊息
user_conversation_refs = {}  # {user_mail: conversation_reference}

# 用戶模型偏好 - 用於個人化模型選擇
user_model_preferences = {}  # {user_mail: model_name}

# 模型資訊定義
MODEL_INFO = {
    "gpt-4o": {
        "speed": "快速",
        "time": "5-10秒",
        "use_case": "日常對話",
        "timeout": 20,
    },
    "gpt-4o-mini": {
        "speed": "最快",
        "time": "3-5秒",
        "use_case": "簡單問題",
        "timeout": 15,
    },
    "gpt-5-mini": {
        "speed": "中等",
        "time": "15-30秒",
        "use_case": "推理任務",
        "timeout": 45,
    },
    "gpt-5-nano": {
        "speed": "最快",
        "time": "2-4秒",
        "use_case": "輕量查詢",
        "timeout": 10,
    },
    "gpt-5": {
        "speed": "較慢",
        "time": "60-120秒",
        "use_case": "複雜推理",
        "timeout": 120,
    },
    "gpt-5-chat-latest": {
        "speed": "快速",
        "time": "5-15秒",
        "use_case": "非推理版本",
        "timeout": 25,
    },
}

# 管理警示設定
ADMIN_ALERT_EMAIL = os.getenv("ADMIN_ALERT_EMAIL", "juncheng.liu@rinnai.com.tw")

# 台灣時區
taiwan_tz = pytz.timezone("Asia/Taipei")


# OpenAI API 配置
USE_AZURE_OPENAI = os.getenv("USE_AZURE_OPENAI", "true").lower() == "true"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")  # 主要對話模型
OPENAI_INTENT_MODEL = os.getenv("OPENAI_INTENT_MODEL", "gpt-5-mini")  # 意圖分析專用模型
OPENAI_SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini")  # 彙總專用模型
# Azure 部署名稱（需在 Azure Portal 建立對應部署並填入環境變數）
AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
AZURE_OPENAI_SUMMARY_DEPLOYMENT = os.getenv("AZURE_OPENAI_SUMMARY_DEPLOYMENT")
ENABLE_AI_INTENT_ANALYSIS = (
    os.getenv("ENABLE_AI_INTENT_ANALYSIS", "false").lower() == "true"
)  # 是否啟用AI意圖分析

if USE_AZURE_OPENAI:
    openai_client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version="2025-01-01-preview",
    )
    print("使用 Azure OpenAI 配置")
else:
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    print("使用 OpenAI 直接 API 配置")

# === 稽核日誌管理函數 ===


def log_message_to_audit(conversation_id, message, user_mail):
    """記錄訊息到稽核日誌（按用戶分組）"""
    if not user_mail:
        return

    current_time = time.time()
    taiwan_now = datetime.now(taiwan_tz)

    # 初始化用戶的稽核日誌
    if user_mail not in audit_logs_by_user:
        audit_logs_by_user[user_mail] = []
        audit_log_timestamps[user_mail] = current_time

    # 更新時間戳
    audit_log_timestamps[user_mail] = current_time

    # 創建日誌條目
    log_entry = {
        "timestamp": taiwan_now.isoformat(),
        "conversation_id": conversation_id,
        "role": message.get("role"),
        "content": message.get("content"),
        "user_mail": user_mail,
    }

    audit_logs_by_user[user_mail].append(log_entry)
    print(f"已記錄到 {user_mail} 的稽核日誌")

    # 即時增量存檔到本地
    try:
        s3_manager.append_single_log_to_file(user_mail, log_entry)
    except Exception as e:
        print(f"增量存檔失敗: {str(e)}")


async def upload_user_audit_logs(user_mail):
    """上傳指定用戶的稽核日誌到 S3"""
    if user_mail not in audit_logs_by_user or not audit_logs_by_user[user_mail]:
        return {"success": False, "message": "沒有找到該用戶的稽核日誌"}

    # 使用 S3Manager 上傳
    result = await s3_manager.upload_audit_logs(
        user_mail, audit_logs_by_user[user_mail]
    )

    if result["success"]:
        # 清除已上傳的日誌（保持記憶體清潔）
        audit_logs_by_user[user_mail] = []

    return result


def clear_user_memory_by_mail(user_mail):
    """根據用戶信箱清除該用戶的所有工作記憶體"""
    cleared_conversations = []

    # 找出該用戶的所有對話 ID
    conversations_to_clear = []
    for conversation_id in list(conversation_history.keys()):
        # 檢查該對話是否屬於該用戶（可以通過稽核日誌查找）
        if user_mail in audit_logs_by_user:
            for log_entry in audit_logs_by_user[user_mail]:
                if log_entry.get("conversation_id") == conversation_id:
                    if conversation_id not in conversations_to_clear:
                        conversations_to_clear.append(conversation_id)

    # 清除該用戶的所有對話記錄
    for conversation_id in conversations_to_clear:
        if conversation_id in conversation_history:
            del conversation_history[conversation_id]
            cleared_conversations.append(conversation_id)
        if conversation_id in conversation_message_counts:
            del conversation_message_counts[conversation_id]
        if conversation_id in conversation_timestamps:
            del conversation_timestamps[conversation_id]

    # 清除該用戶的待辦事項
    todo_count = 0
    if user_mail in user_todos:
        todo_count = len(user_todos[user_mail])
        del user_todos[user_mail]
    if user_mail in todo_timestamps:
        del todo_timestamps[user_mail]

    # 記錄清除動作到稽核日誌
    if cleared_conversations or todo_count > 0:
        clear_action = {
            "role": "system",
            "content": f"管理員清除用戶記憶體，影響 {len(cleared_conversations)} 個對話，{todo_count} 個待辦事項",
        }
        log_message_to_audit("ADMIN_ACTION", clear_action, user_mail)

    return len(cleared_conversations)


def clear_all_users_memory():
    """清除所有用戶的工作記憶體"""
    conversation_count = len(conversation_history)
    todo_count = sum(len(todos) for todos in user_todos.values())

    # 清除所有工作記憶體
    conversation_history.clear()
    conversation_message_counts.clear()
    conversation_timestamps.clear()

    # 清除所有待辦事項
    user_todos.clear()
    todo_timestamps.clear()

    # 記錄管理員動作
    if conversation_count > 0 or todo_count > 0:
        print(
            f"管理員清除所有用戶記憶體，影響 {conversation_count} 個對話，{todo_count} 個待辦事項"
        )

    return conversation_count


def calculate_seconds_until_next_7am():
    """計算到下次早上7點台灣時間的秒數"""
    now = datetime.now(taiwan_tz)
    next_7am = now.replace(hour=7, minute=0, second=0, microsecond=0)

    # 如果現在已經過了今天的7點，則設定為明天的7點
    if now >= next_7am:
        next_7am += timedelta(days=1)

    seconds_until = (next_7am - now).total_seconds()
    print(f"目前時間: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"下次上傳時間: {next_7am.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"距離下次上傳: {seconds_until:.0f} 秒 ({seconds_until/3600:.1f} 小時)")

    return int(seconds_until)


def daily_s3_upload():
    """每日自動上傳本機 ./local_audit_logs 的稽核日誌 - 每天早上7點台灣時間執行

    不再依賴記憶體 audit_logs_by_user，而是直接掃描目錄檔案並上傳。
    """
    taiwan_now = datetime.now(taiwan_tz)
    print(
        f"開始每日稽核日誌上傳... 執行時間: {taiwan_now.strftime('%Y-%m-%d %H:%M:%S')} 台灣時間"
    )

    async def upload_all():
        import re
        log_dir = "./local_audit_logs"
        if not os.path.exists(log_dir):
            print("沒有可上傳的檔案（local_audit_logs 不存在）")
            return

        pattern = re.compile(r"^(?P<mail>.+)_(?P<date>\d{4}-\d{2}-\d{2})\.json$")

        grouped = {}
        all_files = []
        for filename in os.listdir(log_dir):
            if not filename.endswith(".json"):
                continue
            m = pattern.match(filename)
            if not m:
                continue
            user_mail = m.group("mail")
            file_path = os.path.join(log_dir, filename)
            grouped.setdefault(user_mail, []).append(file_path)
            all_files.append(file_path)

        if not all_files:
            print("沒有可上傳的本機檔案")
            return

        total_success = 0
        total_failed = 0
        for user_mail, paths in grouped.items():
            user_success = 0
            user_failed = 0
            for p in sorted(paths, key=lambda p: os.path.getmtime(p)):
                try:
                    ok = await s3_manager.upload_file_to_s3(user_mail, p)
                    if ok:
                        user_success += 1
                    else:
                        user_failed += 1
                except Exception as e:
                    print(f"上傳檔案失敗: {p} - {e}")
                    user_failed += 1
            total_success += user_success
            total_failed += user_failed
            print(
                f"用戶 {user_mail} 上傳完成：共 {len(paths)} 檔，成功 {user_success}，失敗 {user_failed}"
            )

        print(
            f"每日上傳結束：用戶 {len(grouped)} 位，檔案 {len(all_files)} 個，成功 {total_success}，失敗 {total_failed}"
        )

    # 在新的事件迴圈中運行
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(upload_all())
        loop.close()
    except Exception as e:
        print(f"S3上傳任務執行失敗: {str(e)}")

    # 安排下次上傳 - 下次早上7點台灣時間
    seconds_until_7am = calculate_seconds_until_next_7am()
    Timer(seconds_until_7am, daily_s3_upload).start()


def hourly_todo_reminder():
    """每小時檢查待辦事項並發送提醒"""
    from datetime import datetime

    current_time = datetime.now().strftime("%H:%M:%S")
    print(f"[{current_time}] ⏰ 開始待辦事項提醒檢查...")

    # 清除過期待辦事項
    clean_old_todos()

    # 檢查所有用戶的待辦事項
    total_users = len(user_todos)
    users_with_todos = 0

    async def send_todo_reminders():
        nonlocal users_with_todos
        for user_mail in list(user_todos.keys()):
            pending_todos = get_user_pending_todos(user_mail)
            if len(pending_todos) > 0:
                users_with_todos += 1
                try:
                    # 發送 Teams 提醒訊息（使用 Adaptive Card）
                    if user_mail in user_conversation_refs:
                        try:
                            conversation_ref = user_conversation_refs[user_mail]
                            language = determine_language(user_mail)

                            async def send_reminder(turn_context):
                                await send_todo_reminder_card(
                                    turn_context, user_mail, pending_todos, language
                                )

                            # 使用正確的身份和 App ID 進行對話
                            await adapter.continue_conversation(
                                conversation_ref, send_reminder, bot_id=appId
                            )
                            print(
                                f"✅ 已發送提醒給 {user_mail}: {len(pending_todos)} 個待辦事項"
                            )
                        except Exception as send_error:
                            print(f"❌ 發送提醒失敗 {user_mail}: {str(send_error)}")
                    else:
                        print(f"⚠️  無法發送提醒給 {user_mail}: 缺少對話參考")

                except Exception as e:
                    print(f"發送待辦提醒失敗 {user_mail}: {str(e)}")

    print(f"📊 系統狀態：共 {total_users} 個用戶有待辦資料")

    # 在新的事件迴圈中運行
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_todo_reminders())
        loop.close()
        print(f"✅ 提醒檢查完成：{users_with_todos}/{total_users} 個用戶需要提醒")
    except Exception as e:
        print(f"❌ 待辦提醒任務執行失敗: {str(e)}")

    print(f"⏰ 下次檢查將在 {TODO_REMINDER_INTERVAL_SECONDS} 秒後執行")
    # 安排下次提醒
    Timer(TODO_REMINDER_INTERVAL_SECONDS, hourly_todo_reminder).start()


# 安排首次上傳 - 計算到下次早上7點台灣時間的時間
initial_seconds_until_7am = calculate_seconds_until_next_7am()
Timer(initial_seconds_until_7am, daily_s3_upload).start()


async def send_todo_reminder_card(
    turn_context: TurnContext, user_mail: str, pending_todos: list, language: str
):
    """發送待辦事項提醒卡片"""
    try:
        # 創建下拉選項
        choices = []
        for i, todo in enumerate(pending_todos):
            display_text = f"{i+1}. {todo['content']}"
            choices.append({"title": display_text, "value": str(i)})

        reminder_card = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": (
                        "📝 待辦事項提醒"
                        if language == "zh-TW"
                        else "📝 TODOリマインダー"
                    ),
                    "weight": "Bolder",
                    "size": "Medium",
                },
                {
                    "type": "TextBlock",
                    "text": (
                        f"您有 {len(pending_todos)} 個待辦事項："
                        if language == "zh-TW"
                        else f"{len(pending_todos)} 件のTODOがあります："
                    ),
                    "spacing": "Medium",
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selectedTodo",
                    "style": "compact",
                    "placeholder": (
                        "選擇要完成的事項..."
                        if language == "zh-TW"
                        else "完了するアイテムを選択..."
                    ),
                    "choices": choices,
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": (
                        "✅ 完成選中的事項"
                        if language == "zh-TW"
                        else "✅ 選択したアイテムを完了"
                    ),
                    "data": {"action": "completeTodo"},
                    "style": "positive",
                },
            ],
        }

        from botbuilder.schema import Attachment

        card_attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=reminder_card,
        )

        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=(
                    "⏰ 待辦事項提醒："
                    if language == "zh-TW"
                    else "⏰ TODOリマインダー："
                ),
                attachments=[card_attachment],
            )
        )

    except Exception as e:
        print(f"發送待辦提醒卡片失敗: {str(e)}")
        # 如果卡片發送失敗，回退到文字提醒
        fallback_text = f"📝 您有 {len(pending_todos)} 個待辦事項：\n\n"
        for i, todo in enumerate(pending_todos, 1):
            fallback_text += f"{i}. {todo['content']}\n"
        fallback_text += "\n回覆「@ok 編號」來標記完成事項"

        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=fallback_text)
        )


async def send_todo_list_card(
    turn_context: TurnContext, user_mail: str, pending_todos: list, language: str
):
    """發送待辦事項清單卡片（用於 @ls 查看指令）"""
    try:
        # 創建下拉選項
        choices = []
        for i, todo in enumerate(pending_todos):
            display_text = f"{i+1}. #{todo['id']}: {todo['content']}"
            choices.append({"title": display_text, "value": str(i)})

        todo_list_card = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": (
                        "📝 待辦事項清單" if language == "zh-TW" else "📝 TODOリスト"
                    ),
                    "weight": "Bolder",
                    "size": "Medium",
                },
                {
                    "type": "TextBlock",
                    "text": (
                        f"您有 {len(pending_todos)} 個待辦事項："
                        if language == "zh-TW"
                        else f"{len(pending_todos)} 件のTODOがあります："
                    ),
                    "spacing": "Medium",
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selectedTodo",
                    "style": "compact",
                    "placeholder": (
                        "選擇要完成的事項..."
                        if language == "zh-TW"
                        else "完了するアイテムを選択..."
                    ),
                    "choices": choices,
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": (
                        "✅ 完成選中的事項"
                        if language == "zh-TW"
                        else "✅ 選択したアイテムを完了"
                    ),
                    "data": {"action": "completeTodo"},
                    "style": "positive",
                }
            ],
        }

        from botbuilder.schema import Attachment

        card_attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=todo_list_card,
        )

        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=(
                    "📋 您的待辦事項：" if language == "zh-TW" else "📋 あなたのTODO："
                ),
                attachments=[card_attachment],
            )
        )

    except Exception as e:
        print(f"發送待辦清單卡片失敗: {str(e)}")
        # 如果卡片發送失敗，回退到文字清單
        fallback_text = f"📝 您有 {len(pending_todos)} 個待辦事項：\n\n"
        for i, todo in enumerate(pending_todos, 1):
            fallback_text += f"{i}. #{todo['id']}: {todo['content']}\n"
        fallback_text += "\n回覆「@ok 編號」來標記完成事項"

        suggested_replies = get_suggested_replies("@ls", user_mail)
        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=fallback_text,
                suggested_actions=SuggestedActions(actions=suggested_replies),
            )
        )


# === AI意圖分析系統 ===
async def analyze_user_intent(user_message: str) -> dict:
    """
    使用 AI 分析用戶意圖
    返回格式：{
        "is_existing_feature": true/false,
        "category": "todo|meeting|info|model",
        "action": "query|add|complete|book|cancel|...",
        "content": "相關內容",
        "confidence": 0.0-1.0
    }
    """
    if not user_message or not user_message.strip():
        return {
            "is_existing_feature": False,
            "category": "",
            "action": "",
            "content": "",
            "confidence": 0.0
        }
    
    try:
        # 構建優化的意圖分析 prompt
        system_mode = "azure" if USE_AZURE_OPENAI else "openai"
        
        # 根據模式決定是否支援模型切換
        model_features = ""
        if system_mode == "openai":
            model_features = """
🧠 模型選擇 (Model Selection):
  - category: "model"
  - action: "select" (切換/選擇模型)
  - 觸發詞: 切換模型、換模型、使用 gpt-4o、選擇模型等
"""

        system_prompt = f"""你是專業的意圖分析助手。分析用戶輸入並判斷是否符合以下現有功能，必須嚴格按照 JSON 格式回傳結果。

=== 現有功能分類 ===

📝 待辦事項管理 (TODO Management):
  - category: "todo"
  - actions:
    - query: 查詢/查看待辦事項、任務清單
    - add: 新增/添加待辦事項
    - smart_add: 智能新增待辦（含重複檢查）
    - complete: 完成/標記完成待辦事項

🏢 會議管理 (Meeting Management):
  - category: "meeting" 
  - actions:
    - book: 預約/預定會議室
    - query: 查詢會議、查看行程
    - cancel: 取消會議/預約

ℹ️ 資訊查詢 (Information Query):
  - category: "info"
  - actions:
    - user_info: 用戶個人資訊查詢（我是誰、我的部門、我的職稱、我的email等）
    - bot_info: 機器人介紹（你是誰、你的功能、自我介紹等）
    - help: 使用幫助、系統說明
    - status: 系統狀態查詢

{model_features}

=== 重要識別規則 ===
• "我是誰" → info.user_info (用戶查詢自己的身份)
• "你是誰" → info.bot_info (詢問機器人身份)  
• "我的部門/單位/職稱/email" → info.user_info
• "你會什麼/你的功能" → info.bot_info

=== 輸出格式 (必須是有效JSON) ===
{{
  "is_existing_feature": true/false,
  "category": "功能分類",
  "action": "具體動作", 
  "content": "相關內容",
  "confidence": 0.0到1.0之間的數值,
  "reason": "判斷依據"
}}

=== 判斷標準 ===
- 如果用戶輸入明確對應上述功能 → is_existing_feature: true, confidence: 0.8-0.95
- 如果可能相關但不確定 → is_existing_feature: true, confidence: 0.6-0.79  
- 如果完全無關（如天氣、數學題、寫報告等） → is_existing_feature: false, confidence: 0.0-0.5

現在請分析用戶輸入："{user_message}"

請直接返回JSON，不要添加任何其他文字或格式符號。"""

        # 選擇使用的模型和客戶端
        if USE_AZURE_OPENAI:
            model_name = "gpt-4o-mini"  # Azure 模式使用固定模型
            client = openai_client
            print(f"🤖 [意圖分析-Azure] 使用模型: {model_name}")
        else:
            # OpenAI 模式：優先使用穩定的模型，避免 gpt-5 系列的相容性問題
            intent_api_key = os.getenv("OPENAI_API_KEY")
            if not intent_api_key:
                print("⚠️ 未設置 OPENAI_API_KEY，無法進行意圖分析")
                return {
                    "is_existing_feature": False,
                    "category": "",
                    "action": "",
                    "content": "",
                    "confidence": 0.0
                }
            
            # 優先使用相容性好的模型
            original_model = OPENAI_INTENT_MODEL
            if original_model.startswith("gpt-5") or original_model.startswith("o1"):
                model_name = "gpt-4o-mini"  # 回退到穩定模型
                print(f"⚠️ [意圖分析-OpenAI] {original_model} 可能不穩定，改用 {model_name}")
            else:
                model_name = original_model
            
            client = OpenAI(api_key=intent_api_key)
            print(f"🤖 [意圖分析-OpenAI] 使用模型: {model_name}")

        print(f"📝 [意圖分析] 用戶輸入: {user_message}")

        # 構建訊息 - 針對不同模型的特殊處理
        if model_name.startswith("o1"):
            # o1 模型不支援 system role，需要合併到 user message
            combined_prompt = f"{system_prompt}\n\n用戶輸入: {user_message}"
            messages = [{"role": "user", "content": combined_prompt}]
        else:
            # 標準模型支援 system role
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]

        # 針對某些模型調整訊息格式
        if hasattr(globals(), 'normalize_messages_for_model'):
            messages = normalize_messages_for_model(messages, model_name)

        # 構建請求參數
        request_params = {
            "model": model_name,
            "messages": messages,
            "timeout": 20
        }
        
        # 根據模型類型添加適當的參數
        if model_name.startswith("gpt-5") or model_name.startswith("o1"):
            # gpt-5 和 o1 系列模型使用 max_completion_tokens 且不支援 temperature
            request_params["max_completion_tokens"] = 300
            print(f"🔧 [意圖分析] 使用 max_completion_tokens=300（{model_name}）")
        else:
            # 其他模型使用 max_tokens 和 temperature
            request_params["max_tokens"] = 300
            request_params["temperature"] = 0.1
            print(f"🔧 [意圖分析] 使用 max_tokens=300, temperature=0.1（{model_name}）")

        print(f"📤 [意圖分析] 發送請求...")
        
        # 調用 AI 分析
        try:
            response = client.chat.completions.create(**request_params)
            print(f"✅ [意圖分析] API 調用成功")
        except Exception as api_error:
            print(f"❌ [意圖分析] API 調用失敗: {api_error}")
            # 如果是參數問題，嘗試使用最基本的參數
            basic_params = {
                "model": model_name,
                "messages": messages
            }
            print(f"🔄 [意圖分析] 嘗試基本參數重試...")
            response = client.chat.completions.create(**basic_params)

        # 檢查回應是否存在
        if not response or not response.choices:
            print(f"❌ [意圖分析] API 回應為空或無效")
            return {
                "is_existing_feature": False,
                "category": "",
                "action": "",
                "content": "",
                "confidence": 0.0
            }

        # 解析回應
        message_content = response.choices[0].message.content
        if not message_content:
            print(f"❌ [意圖分析] 消息內容為空")
            return {
                "is_existing_feature": False,
                "category": "",
                "action": "",
                "content": "",
                "confidence": 0.0
            }

        result_text = message_content.strip()
        print(f"🎯 [意圖分析] AI回應: {result_text}")
        print(f"📏 [意圖分析] 回應長度: {len(result_text)} 字符")

        if not result_text:
            print(f"❌ [意圖分析] 回應內容為空字符串")
            return {
                "is_existing_feature": False,
                "category": "",
                "action": "",
                "content": "",
                "confidence": 0.0
            }

        # 清理並解析 JSON
        import json, re
        
        # 移除可能的 markdown 代碼塊標記
        cleaned_text = result_text
        if cleaned_text.startswith("```"):
            cleaned_text = re.sub(r'^```(?:json)?\n?', '', cleaned_text)
            cleaned_text = re.sub(r'\n?```$', '', cleaned_text)
            print(f"🧹 [意圖分析] 清理後內容: {cleaned_text}")

        try:
            parsed_result = json.loads(cleaned_text)
            print(f"✅ [意圖分析] JSON 解析成功")
        except json.JSONDecodeError as je:
            print(f"⚠️ [意圖分析] 初次 JSON 解析失敗: {je}")
            # 嘗試提取 JSON 對象
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned_text)
            if json_match:
                try:
                    extracted_json = json_match.group()
                    print(f"🔍 [意圖分析] 提取到的 JSON: {extracted_json}")
                    parsed_result = json.loads(extracted_json)
                    print(f"✅ [意圖分析] 提取的 JSON 解析成功")
                except json.JSONDecodeError as je2:
                    print(f"❌ [意圖分析] 提取的 JSON 解析失敗: {je2}")
                    raise ValueError(f"無法解析JSON: {cleaned_text}")
            else:
                print(f"❌ [意圖分析] 找不到 JSON 格式內容")
                raise ValueError(f"找不到有效的JSON格式: {cleaned_text}")

        # 正規化結果
        result = normalize_intent_output(parsed_result)
        
        print(f"✅ [意圖分析] 解析成功:")
        print(f"   類別: {result.get('category', 'N/A')}")
        print(f"   動作: {result.get('action', 'N/A')}")
        print(f"   現有功能: {result.get('is_existing_feature', False)}")
        print(f"   信心度: {result.get('confidence', 0.0)}")

        return result

    except Exception as e:
        print(f"❌ [意圖分析] 失敗: {str(e)}")
        return {
            "is_existing_feature": False,
            "category": "",
            "action": "",
            "content": "",
            "confidence": 0.0
        }


async def handle_intent_action(
    turn_context: TurnContext, user_mail: str, intent: dict
) -> bool:
    """
    根據意圖執行相對應的功能
    返回 True 表示已處理，False 表示未處理或失敗
    """
    try:
        category = intent.get("category")
        action = intent.get("action")
        content = intent.get("content", "").strip()
        language = determine_language(user_mail)

        # 處理待辦事項相關意圖
        if category == "todo":
            if action == "query":
                # 查詢待辦事項
                pending_todos = get_user_pending_todos(user_mail)
                if pending_todos:
                    await send_todo_list_card(
                        turn_context, user_mail, pending_todos, language
                    )
                    # 添加使用提示
                    hint_msg = (
                        "💡 小提示：下次可以直接輸入 `@ls` 快速查看待辦清單"
                        if language == "zh-TW"
                        else "💡 ヒント：次回は `@ls` で素早くTODOリストを確認できます"
                    )
                    await turn_context.send_activity(
                        Activity(type=ActivityTypes.message, text=hint_msg)
                    )
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text=(
                                "🎉 目前沒有待辦事項"
                                if language == "zh-TW"
                                else "🎉 現在はTODOがありません"
                            ),
                        )
                    )
                return True

            elif action == "smart_add" and content:
                # 智能新增待辦事項（包含相似性檢查）
                await smart_add_todo(turn_context, user_mail, content)
                return True

            elif action == "add" and content:
                # 新增待辦事項
                todo_id = add_todo_item(user_mail, content)
                if todo_id:
                    success_msg = (
                        f"✅ 已新增待辦事項：{content}"
                        if language == "zh-TW"
                        else f"✅ TODOを追加しました：{content}"
                    )
                    await turn_context.send_activity(
                        Activity(type=ActivityTypes.message, text=success_msg)
                    )

                    # 添加使用提示
                    hint_msg = (
                        "💡 小提示：下次可以使用 `@add 內容` 快速新增待辦"
                        if language == "zh-TW"
                        else "💡 ヒント：次回は `@add 内容` で素早くTODOを追加できます"
                    )
                    await turn_context.send_activity(
                        Activity(type=ActivityTypes.message, text=hint_msg)
                    )
                    return True

            elif action == "complete":
                # 顯示待辦清單供完成
                pending_todos = get_user_pending_todos(user_mail)
                if pending_todos:
                    await send_todo_list_card(
                        turn_context, user_mail, pending_todos, language
                    )
                    return True
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text=(
                                "🎉 沒有待辦事項需要完成"
                                if language == "zh-TW"
                                else "🎉 完了するTODOはありません"
                            ),
                        )
                    )
                    return True

        # 處理會議室相關意圖
        elif category == "meeting":
            if action == "book":
                # 顯示會議室預約表單
                await show_room_booking_options(turn_context, user_mail)
                hint_msg = (
                    "💡 小提示：也可以使用 `@book-room` 快速開啟預約表單"
                    if language == "zh-TW"
                    else "💡 ヒント：`@book-room` でも素早く予約フォームを開けます"
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=hint_msg)
                )
                return True

            elif action == "query":
                # 查詢會議室預約
                await show_my_bookings(turn_context, user_mail)
                hint_msg = (
                    "💡 小提示：也可以使用 `@query` 快速查看預約"
                    if language == "zh-TW"
                    else "💡 ヒント：`@query` でも素早く予約を確認できます"
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=hint_msg)
                )
                return True

            elif action == "cancel":
                # 取消會議室預約
                await show_cancel_booking_options(turn_context, user_mail)
                hint_msg = (
                    "💡 小提示：也可以使用 `@cancel-booking` 快速取消預約"
                    if language == "zh-TW"
                    else "💡 ヒント：`@cancel-booking` でも素早く予約をキャンセルできます"
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=hint_msg)
                )
                return True

        # 處理資訊查詢相關意圖
        elif category == "info":
            if action == "help":
                # 顯示功能說明
                await show_help_options(turn_context)
                return True
            elif action == "user_info":
                # 顯示用戶資訊
                await show_user_info(turn_context)
                return True
            elif action in ("bot_info", "you"):
                # 顯示機器人自我介紹
                await show_bot_intro(turn_context)
                return True
            elif action == "status":
                # 顯示系統狀態（可以擴展）
                status_msg = (
                    "🔧 系統運作正常\n💡 輸入 `@help` 查看所有功能"
                    if language == "zh-TW"
                    else "🔧 システムは正常に動作中\n💡 `@help` ですべての機能を確認できます"
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=status_msg)
                )
                return True
        # 處理模型切換（僅 OpenAI 模式有效）
        elif category == "model":
            if USE_AZURE_OPENAI:
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text="ℹ️ 目前使用 Azure OpenAI 模式，暫不支援模型切換",
                    )
                )
                return True

            desired = (content or "").strip().lower()
            # 若用戶直接提供可用模型，先嘗試直接切換
            if desired and desired in MODEL_INFO:
                user_model_preferences[user_mail] = desired
                model_info = MODEL_INFO[desired]
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=(
                            f"✅ 已切換至 {desired}\n⚡ 回應速度：{model_info['speed']}（{model_info['time']}）\n🎯 適用場景：{model_info['use_case']}"
                        ),
                    )
                )
                return True

            # 否則顯示模型選擇卡片
            current_model = user_model_preferences.get(user_mail, OPENAI_MODEL)
            model_info = MODEL_INFO.get(
                current_model, {"speed": "未知", "time": "未知", "use_case": "未知"}
            )

            model_card = {
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "🤖 AI 模型選擇",
                        "weight": "Bolder",
                        "size": "Medium",
                    },
                    {
                        "type": "TextBlock",
                        "text": f"目前使用：{current_model} ({model_info['speed']} {model_info['time']})",
                        "color": "Good",
                        "spacing": "Small",
                    },
                    {
                        "type": "Input.ChoiceSet",
                        "id": "selectedModel",
                        "style": "compact",
                        "value": current_model,
                        "choices": [
                            {
                                "title": f"gpt-4o ({MODEL_INFO['gpt-4o']['speed']} {MODEL_INFO['gpt-4o']['time']}) - {MODEL_INFO['gpt-4o']['use_case']}",
                                "value": "gpt-4o",
                            },
                            {
                                "title": f"gpt-4o-mini ({MODEL_INFO['gpt-4o-mini']['speed']} {MODEL_INFO['gpt-4o-mini']['time']}) - {MODEL_INFO['gpt-4o-mini']['use_case']}",
                                "value": "gpt-4o-mini",
                            },
                            {
                                "title": f"gpt-5-mini ({MODEL_INFO['gpt-5-mini']['speed']} {MODEL_INFO['gpt-5-mini']['time']}) - {MODEL_INFO['gpt-5-mini']['use_case']}",
                                "value": "gpt-5-mini",
                            },
                            {
                                "title": f"gpt-5-nano ({MODEL_INFO['gpt-5-nano']['speed']} {MODEL_INFO['gpt-5-nano']['time']}) - {MODEL_INFO['gpt-5-nano']['use_case']}",
                                "value": "gpt-5-nano",
                            },
                            {
                                "title": f"gpt-5 ({MODEL_INFO['gpt-5']['speed']} {MODEL_INFO['gpt-5']['time']}) - {MODEL_INFO['gpt-5']['use_case']}",
                                "value": "gpt-5",
                            },
                            {
                                "title": f"gpt-5-chat-latest ({MODEL_INFO['gpt-5-chat-latest']['speed']} {MODEL_INFO['gpt-5-chat-latest']['time']}) - {MODEL_INFO['gpt-5-chat-latest']['use_case']}",
                                "value": "gpt-5-chat-latest",
                            },
                        ],
                    },
                ],
                "actions": [
                    {
                        "type": "Action.Submit",
                        "title": "🔄 切換模型",
                        "data": {"action": "selectModel"},
                    }
                ],
            }

            from botbuilder.schema import Attachment as _Attachment

            card_attachment = _Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=model_card,
            )

            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="請選擇要切換的 AI 模型：",
                    attachments=[card_attachment],
                )
            )
            return True
    except Exception as e:
        print(f"處理意圖動作失敗: {e}")
        return False
    return False


# === 智能建議回覆系統 ===


def get_suggested_replies(user_message, user_mail=None):
    """根據用戶訊息產生智能建議回覆"""
    from botbuilder.schema import CardAction, ActionTypes

    message_lower = user_message.lower()

    # 感謝類型
    if any(word in message_lower for word in ["謝謝", "感謝", "thanks", "thank you"]):
        return [
            CardAction(title="不客氣", type=ActionTypes.im_back, text="不客氣"),
            CardAction(
                title="很高興能幫到您", type=ActionTypes.im_back, text="很高興能幫到您"
            ),
            CardAction(
                title="隨時為您服務", type=ActionTypes.im_back, text="隨時為您服務"
            ),
            CardAction(title="😊", type=ActionTypes.im_back, text="😊"),
        ]

    # 問候類型
    elif any(word in message_lower for word in ["你好", "hi", "hello", "早安", "晚安"]):
        return [
            CardAction(
                title="需要協助嗎？", type=ActionTypes.im_back, text="需要什麼協助嗎？"
            ),
            CardAction(title="查看待辦事項", type=ActionTypes.im_back, text="@ls"),
            CardAction(title="新增待辦", type=ActionTypes.im_back, text="@add "),
            CardAction(title="查看功能", type=ActionTypes.im_back, text="@help"),
        ]

    # 待辦事項完成後
    elif any(word in message_lower for word in ["完成", "done", "@ok"]):
        return [
            CardAction(title="查看剩餘待辦", type=ActionTypes.im_back, text="@ls"),
            CardAction(title="新增待辦", type=ActionTypes.im_back, text="@add "),
            CardAction(title="清空全部", type=ActionTypes.im_back, text="@cls"),
            CardAction(title="查看狀態", type=ActionTypes.im_back, text="@status"),
        ]

    # 待辦相關操作
    elif any(word in user_message for word in ["@add", "@ls", "@cls"]):
        return [
            CardAction(title="@add 新增待辦", type=ActionTypes.im_back, text="@add "),
            CardAction(title="@ls 查看清單", type=ActionTypes.im_back, text="@ls"),
            CardAction(title="@ok 標記完成", type=ActionTypes.im_back, text="@ok "),
            CardAction(title="@cls 清空全部", type=ActionTypes.im_back, text="@cls"),
        ]

    # 模型相關
    elif "@model" in user_message:
        return [
            CardAction(
                title="快速模型", type=ActionTypes.im_back, text="@model gpt-4o"
            ),
            CardAction(title="強大模型", type=ActionTypes.im_back, text="@model gpt-5"),
            CardAction(title="查看所有", type=ActionTypes.im_back, text="@model"),
            CardAction(title="保持目前", type=ActionTypes.im_back, text="好的"),
        ]

    # 錯誤或需要幫助
    elif any(word in message_lower for word in ["錯誤", "error", "問題", "help"]):
        return [
            CardAction(title="查看幫助", type=ActionTypes.im_back, text="@help"),
            CardAction(title="查看狀態", type=ActionTypes.im_back, text="@status"),
            CardAction(title="重新開始", type=ActionTypes.im_back, text="@new-chat"),
            CardAction(title="切換模型", type=ActionTypes.im_back, text="@model"),
        ]

    # 預設建議
    else:
        return [
            CardAction(title="查看待辦", type=ActionTypes.im_back, text="@ls"),
            CardAction(title="新增待辦", type=ActionTypes.im_back, text="@add "),
            CardAction(title="查看功能", type=ActionTypes.im_back, text="@help"),
            CardAction(title="切換模型", type=ActionTypes.im_back, text="@model"),
        ]


# === 待辦事項管理函數 ===


def extract_todo_features(content):
    """提取待辦事項的特徵：時間、人員、物件"""
    import re

    content_lower = content.lower()

    # 時間相關關鍵字
    time_keywords = [
        "下午",
        "上午",
        "晚上",
        "早上",
        "今天",
        "明天",
        "後天",
        "週一",
        "週二",
        "週三",
        "週四",
        "週五",
        "週六",
        "週日",
        "月份",
        "小時",
        "分鐘",
        "點",
        "時",
        "分",
        "秒",
    ]

    # 提取人員（假設包含常見中文姓名或英文名）
    person_pattern = r"([A-Za-z]+|[\u4e00-\u9fff]{2,4})"
    potential_persons = re.findall(person_pattern, content)

    # 動作關鍵字（通常表示要做的事）
    action_keywords = [
        "討論",
        "開會",
        "會議",
        "聯絡",
        "打電話",
        "發信",
        "寫",
        "完成",
        "處理",
        "檢查",
        "確認",
        "準備",
    ]

    features = {
        "time_mentioned": any(keyword in content_lower for keyword in time_keywords),
        "persons": [p for p in potential_persons if len(p) >= 2],  # 過濾太短的字串
        "actions": [keyword for keyword in action_keywords if keyword in content_lower],
        "content_words": set(content_lower.split()),
    }

    return features


def calculate_todo_similarity(todo1_content, todo2_content):
    """計算兩個待辦事項的相似度（0-1之間）"""
    features1 = extract_todo_features(todo1_content)
    features2 = extract_todo_features(todo2_content)

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


async def check_similar_todos(user_mail, new_content):
    """檢查是否有相似的待辦事項"""
    if user_mail not in user_todos:
        return []

    similar_todos = []
    pending_todos = get_user_pending_todos(user_mail)

    for todo in pending_todos:
        similarity = calculate_todo_similarity(new_content, todo["content"])
        if similarity > 0.6:  # 相似度閾值
            similar_todos.append({"todo": todo, "similarity": similarity})

    return sorted(similar_todos, key=lambda x: x["similarity"], reverse=True)


async def smart_add_todo(turn_context: TurnContext, user_mail: str, content: str):
    """智能新增待辦事項，包含相似性檢查"""
    # 檢查相似的待辦事項
    similar_todos = await check_similar_todos(user_mail, content)

    if similar_todos:
        language = determine_language(user_mail)

        # 構建相似項目的文字描述
        similar_list = ""
        for i, item in enumerate(similar_todos[:3], 1):  # 最多顯示3個相似項目
            todo = item["todo"]
            similarity_percent = int(item["similarity"] * 100)
            similar_list += f"{i}. #{todo['id']}: {todo['content']} (相似度: {similarity_percent}%)\n"

        confirmation_text = (
            f"⚠️ 發現相似的待辦事項：\n{similar_list}\n是否仍要新增「{content}」？"
            if language == "zh-TW"
            else f"⚠️ 類似のTODOが見つかりました：\n{similar_list}\n「{content}」を追加しますか？"
        )

        # 創建確認卡片
        confirmation_card = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [{"type": "TextBlock", "text": confirmation_text, "wrap": True}],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "✅ 仍要新增" if language == "zh-TW" else "✅ 追加する",
                    "data": {"action": "confirmAddTodo", "todoContent": content},
                    "style": "positive",
                },
                {
                    "type": "Action.Submit",
                    "title": "❌ 取消" if language == "zh-TW" else "❌ キャンセル",
                    "data": {"action": "cancelAddTodo"},
                    "style": "default",
                },
            ],
        }

        from botbuilder.schema import Attachment

        card_attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=confirmation_card,
        )

        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text="檢查重複項目中...",
                attachments=[card_attachment],
            )
        )
        return None

    else:
        # 沒有相似項目，直接新增
        todo_id = add_todo_item(user_mail, content)
        if todo_id:
            language = determine_language(user_mail)
            success_msg = (
                f"✅ 已新增待辦事項 #{todo_id}：{content}"
                if language == "zh-TW"
                else f"✅ TODO #{todo_id} を追加しました：{content}"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=success_msg)
            )
            return todo_id
        return None


def add_todo_item(user_mail, content):
    """新增待辦事項"""
    global todo_counter

    if not user_mail:
        return None

    current_time = time.time()
    taiwan_now = datetime.now(taiwan_tz)

    # 初始化用戶的待辦事項清單
    if user_mail not in user_todos:
        user_todos[user_mail] = {}
        todo_timestamps[user_mail] = current_time

    # 生成新的待辦事項 ID
    todo_counter += 1
    todo_id = str(todo_counter)

    # 創建待辦事項
    todo_item = {
        "id": todo_id,
        "content": content.strip(),
        "created": taiwan_now.isoformat(),
        "created_timestamp": current_time,
        "status": "pending",
    }

    user_todos[user_mail][todo_id] = todo_item
    todo_timestamps[user_mail] = current_time

    print(f"新增待辦事項 #{todo_id}: {content} (用戶: {user_mail})")
    return todo_id


def get_user_pending_todos(user_mail):
    """取得用戶的待辦事項"""
    if user_mail not in user_todos:
        return []

    pending_todos = []
    for todo_id, todo in user_todos[user_mail].items():
        if todo["status"] == "pending":
            pending_todos.append(todo)

    return sorted(pending_todos, key=lambda x: x["created"])


def mark_todo_completed(user_mail, todo_ids):
    """標記待辦事項為已完成"""
    if user_mail not in user_todos:
        return []

    completed_items = []
    for todo_id in todo_ids:
        if (
            todo_id in user_todos[user_mail]
            and user_todos[user_mail][todo_id]["status"] == "pending"
        ):
            user_todos[user_mail][todo_id]["status"] = "completed"
            user_todos[user_mail][todo_id]["completed"] = datetime.now(
                taiwan_tz
            ).isoformat()
            completed_items.append(user_todos[user_mail][todo_id])

    return completed_items


def clean_old_todos():
    """清除過期的待辦事項"""
    current_time = time.time()
    retention_seconds = CONVERSATION_RETENTION_DAYS * 24 * 3600

    for user_mail in list(user_todos.keys()):
        if user_mail in todo_timestamps:
            if current_time - todo_timestamps[user_mail] > retention_seconds:
                # 清除整個用戶的待辦事項
                del user_todos[user_mail]
                del todo_timestamps[user_mail]
                print(f"清除過期待辦事項: {user_mail}")
            else:
                # 清除個別過期的待辦事項
                todos_to_remove = []
                for todo_id, todo in user_todos[user_mail].items():
                    if current_time - todo["created_timestamp"] > retention_seconds:
                        todos_to_remove.append(todo_id)

                for todo_id in todos_to_remove:
                    del user_todos[user_mail][todo_id]
                    print(f"清除過期待辦事項 #{todo_id}: {user_mail}")


# === 工作記憶體管理函數 ===


def clear_user_conversation(conversation_id, user_mail):
    """清除指定用戶的工作對話記錄（不影響稽核日誌）"""
    # 記錄清除動作到稽核日誌
    clear_action = {"role": "system", "content": "用戶主動清除對話記錄（開啟新對話）"}
    log_message_to_audit(conversation_id, clear_action, user_mail)

    # 清除工作記憶體
    if conversation_id in conversation_history:
        del conversation_history[conversation_id]
    if conversation_id in conversation_message_counts:
        del conversation_message_counts[conversation_id]
    if conversation_id in conversation_timestamps:
        del conversation_timestamps[conversation_id]

    print(f"已清除工作對話記錄: {conversation_id}（稽核日誌保留）")


async def confirm_new_conversation(turn_context: TurnContext):
    """確認開啟新對話"""
    conversation_id = turn_context.activity.conversation.id
    user_mail = await get_user_email(turn_context)
    language = determine_language(user_mail)

    # 清除對話記錄
    clear_user_conversation(conversation_id, user_mail)

    confirm_messages = {
        "zh-TW": f"新對話已開始！\n\n工作記憶已清除，您現在可以開始全新的對話。\n\n系統設定提醒：\n• 對話記錄：最多保留 {MAX_CONTEXT_MESSAGES} 筆訊息\n• 待辦事項：保存 {CONVERSATION_RETENTION_DAYS} 天\n• 完整記錄：每日備份至雲端\n\n有什麼我可以幫您的嗎？",
        "ja": f"新しい会話が開始されました！\n\n作業メモリがクリアされ、新しい会話を開始できます。\n\nシステム設定：\n• 会話記録：最大 {MAX_CONTEXT_MESSAGES} 件のメッセージを保持\n• タスク：{CONVERSATION_RETENTION_DAYS} 日間保存\n• 完全記録：毎日クラウドにバックアップ\n\n何かお手伝いできることはありますか？",
    }

    message_text = confirm_messages.get(language, confirm_messages["zh-TW"])
    await show_help_options(turn_context, message_text)


async def manage_conversation_history_with_limit_check(
    conversation_id, new_message, user_mail
):
    """帶有限制檢查的對話歷史管理（雙重記錄）"""
    current_time = time.time()

    # 記錄到稽核日誌
    log_message_to_audit(conversation_id, new_message, user_mail)

    # 管理工作記憶體
    if conversation_id not in conversation_history:
        conversation_history[conversation_id] = []
        conversation_timestamps[conversation_id] = current_time
        conversation_message_counts[conversation_id] = 0

    conversation_timestamps[conversation_id] = current_time
    conversation_history[conversation_id].append(new_message)

    if new_message.get("role") in ["user", "assistant"]:
        conversation_message_counts[conversation_id] += 1

    # 如果超過限制，進行自動壓縮（只影響工作記憶體）
    if conversation_message_counts[conversation_id] > MAX_CONTEXT_MESSAGES:
        await compress_conversation_history(conversation_id, user_mail)


async def compress_conversation_history(conversation_id, user_mail):
    """壓縮對話歷史（只影響工作記憶體，不影響稽核日誌）"""
    if conversation_id not in conversation_history:
        return

    messages = conversation_history[conversation_id]
    system_msgs = [msg for msg in messages if msg.get("role") == "system"]
    user_assistant_msgs = [
        msg for msg in messages if msg.get("role") in ["user", "assistant"]
    ]

    if len(user_assistant_msgs) > 0:
        # 使用 AI 智能摘要，包含所有對話歷史
        conversation_text = "\n".join(
            [
                f"{msg.get('role', '')}: {msg.get('content', '')}"
                for msg in user_assistant_msgs
            ]
        )
        summary = await summarize_text(
            f"請摘要以下對話內容，保留重要信息、用戶姓名、討論主題等關鍵信息：\n{conversation_text}",
            conversation_id,
            user_mail,
        )

        # 針對不支援 system 的模型（o1*），將摘要訊息 role 改為 user
        if USE_AZURE_OPENAI:
            current_model = "o1-mini"
        else:
            current_model = user_model_preferences.get(user_mail, OPENAI_MODEL)

        role_for_summary = (
            "system" if not (current_model.lower().startswith("o1")) else "user"
        )

        summary_msg = {
            "role": role_for_summary,
            "content": f"對話摘要（重要信息）：{summary}",
        }
        conversation_history[conversation_id] = system_msgs + [summary_msg]

        # 記錄壓縮動作到稽核日誌
        compress_action = {
            "role": "system",
            "content": f"系統自動壓縮對話記錄，將 {len(user_assistant_msgs)} 筆訊息彙總為AI摘要：{summary}",
        }
        log_message_to_audit(conversation_id, compress_action, user_mail)
    else:
        conversation_history[conversation_id] = system_msgs

    conversation_message_counts[conversation_id] = 0


# === API 路由 ===


# 測試 API 是否正常運作
@app.route("/api/test", methods=["GET", "POST"])
async def test_api():
    """測試 API 端點"""
    return await make_response(
        jsonify({"status": "API is working", "method": request.method}), 200
    )


# 顯示所有路由
@app.route("/api/routes", methods=["GET"])
async def list_routes():
    """列出所有註冊的路由"""
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append(
            {
                "endpoint": rule.endpoint,
                "methods": list(rule.methods),
                "rule": str(rule.rule),
            }
        )
    return await make_response(jsonify({"routes": routes}), 200)


@app.route("/api/audit/upload-all", methods=["GET"])
async def upload_all_users():
    """掃描本機 ./local_audit_logs 檔案，依使用者分組後上傳至 S3。

    回傳：用戶數量（括號含檔案數），以及各用戶上傳結果摘要。
    """
    try:
        import re

        log_dir = "./local_audit_logs"
        if not os.path.exists(log_dir):
            return await make_response(
                jsonify(
                    {
                        "success": True,
                        "message": "沒有可上傳的檔案（資料夾不存在）",
                        "users_processed": 0,
                        "total_files": 0,
                        "details": [],
                    }
                ),
                200,
            )

        # 依使用者信箱分組檔案：檔名格式 {mail}_{YYYY-MM-DD}.json
        pattern = re.compile(r"^(?P<mail>.+)_(?P<date>\d{4}-\d{2}-\d{2})\.json$")
        grouped = {}
        all_files = []

        for filename in os.listdir(log_dir):
            if not filename.endswith(".json"):
                continue
            m = pattern.match(filename)
            if not m:
                continue
            user_mail = m.group("mail")
            file_path = os.path.join(log_dir, filename)
            grouped.setdefault(user_mail, []).append(file_path)
            all_files.append(file_path)

        if not all_files:
            return await make_response(
                jsonify(
                    {
                        "success": True,
                        "message": "沒有可上傳的本地檔案",
                        "users_processed": 0,
                        "total_files": 0,
                        "details": [],
                    }
                ),
                200,
            )

        results = []
        total_success = 0
        total_failed = 0

        # 對每位用戶的檔案逐一上傳
        for user_mail, paths in grouped.items():
            user_success = 0
            user_failed = 0
            # 依修改時間排序（舊→新），亦可直接原順序
            paths_sorted = sorted(paths, key=lambda p: os.path.getmtime(p))
            for p in paths_sorted:
                try:
                    ok = await s3_manager.upload_file_to_s3(user_mail, p)
                    if ok:
                        user_success += 1
                    else:
                        user_failed += 1
                except Exception as e:
                    print(f"上傳檔案失敗: {p} - {e}")
                    user_failed += 1

            total_success += user_success
            total_failed += user_failed
            results.append(
                {
                    "user": user_mail,
                    "files": len(paths),
                    "success": user_success,
                    "failed": user_failed,
                }
            )

        users_processed = len(grouped)
        total_files = len(all_files)
        message = f"已處理 {users_processed} 位用戶（{total_files} 個檔案）"
        if total_failed:
            message += f"，成功 {total_success}，失敗 {total_failed}"

        response_data = {
            "success": True,
            "message": message,
            "users_processed": users_processed,
            "total_files": total_files,
            "success_files": total_success,
            "failed_files": total_failed,
            "details": results,
        }
        return await make_response(jsonify(response_data), 200)
    except Exception as e:
        error_data = {"success": False, "message": str(e)}
        return await make_response(jsonify(error_data), 500)


@app.route("/api/audit/upload/<user_mail>", methods=["GET"])
async def manual_upload_audit_logs(user_mail):
    """手動上傳指定用戶的稽核日誌"""
    try:
        result = await upload_user_audit_logs(user_mail)

        if result["success"]:
            return await make_response(
                jsonify(
                    {
                        "success": True,
                        "message": result["message"],
                        "user_mail": user_mail,
                        "upload_time": datetime.now(taiwan_tz).isoformat(),
                    }
                )
            )
        else:
            return await make_response(
                jsonify(
                    {
                        "success": False,
                        "message": result["message"],
                        "user_mail": user_mail,
                    }
                ),
                400,
            )
    except Exception as e:
        print(f"手動上傳稽核日誌API錯誤: {str(e)}")
        return await make_response(
            jsonify({"success": False, "message": f"系統錯誤: {str(e)}"}), 500
        )


@app.route("/api/audit/status/<user_mail>", methods=["GET"])
async def get_audit_status(user_mail):
    """查詢用戶稽核日誌狀態"""
    try:
        log_count = len(audit_logs_by_user.get(user_mail, []))
        last_activity = audit_log_timestamps.get(user_mail)

        status = {
            "user_mail": user_mail,
            "pending_logs": log_count,
            "last_activity": (
                datetime.fromtimestamp(last_activity, taiwan_tz).isoformat()
                if last_activity
                else None
            ),
            "retention_days": CONVERSATION_RETENTION_DAYS,
        }

        return await make_response(jsonify(status))
    except Exception as e:
        return await make_response(
            jsonify({"error": "Internal Server Error", "message": str(e)}), 500
        )


@app.route("/api/audit/summary", methods=["GET"])
async def get_audit_summary():
    """取得所有用戶的稽核日誌摘要"""
    try:
        summary = {
            "total_users": len(audit_logs_by_user),
            "total_pending_logs": sum(
                len(logs) for logs in audit_logs_by_user.values()
            ),
            "retention_days": CONVERSATION_RETENTION_DAYS,
            "s3_bucket": s3_manager.bucket_name,
            "users": [],
        }

        for user_mail, logs in audit_logs_by_user.items():
            if logs:
                summary["users"].append(
                    {
                        "user_mail": user_mail,
                        "pending_logs": len(logs),
                        "last_activity": (
                            datetime.fromtimestamp(
                                audit_log_timestamps.get(user_mail, 0), taiwan_tz
                            ).isoformat()
                            if audit_log_timestamps.get(user_mail)
                            else None
                        ),
                    }
                )

        return await make_response(jsonify(summary))
    except Exception as e:
        return await make_response(
            jsonify({"error": "Internal Server Error", "message": str(e)}), 500
        )


@app.route("/api/audit/files", methods=["GET"])
async def list_audit_files():
    """列出 S3 中的稽核日誌檔案"""
    try:
        user_mail = request.args.get("user_mail")
        date_filter = request.args.get("date")  # YYYY-MM-DD 格式
        include_download_url = (
            request.args.get("include_download_url", "false").lower() == "true"
        )
        expiration = int(
            request.args.get("expiration", "3600")
        )  # Pre-Signed URL 過期時間

        files = s3_manager.list_s3_audit_files(
            user_mail=user_mail, date_filter=date_filter
        )

        # 如果需要，為每個檔案生成 Pre-Signed URL
        if include_download_url:
            for file_info in files:
                presigned_url = s3_manager.generate_presigned_download_url(
                    file_info["key"], expiration
                )
                file_info["presigned_download_url"] = presigned_url

        return await make_response(
            jsonify(
                {
                    "success": True,
                    "files": files,
                    "total_files": len(files),
                    "filters": {
                        "user_mail": user_mail,
                        "date": date_filter,
                        "include_download_url": include_download_url,
                        "url_expiration": expiration if include_download_url else None,
                    },
                }
            )
        )
    except Exception as e:
        return await make_response(jsonify({"success": False, "message": str(e)}), 500)


@app.route("/api/audit/download/<path:s3_key>", methods=["GET"])
async def get_download_url(s3_key):
    """取得稽核日誌檔案的 Pre-Signed 下載 URL"""
    try:
        # 取得 URL 過期時間參數（秒），預設 1 小時
        expiration = int(request.args.get("expiration", "3600"))

        # 生成 Pre-Signed URL
        download_url = s3_manager.generate_presigned_download_url(s3_key, expiration)

        if download_url is None:
            return await make_response(
                jsonify({"success": False, "message": "無法生成下載連結或檔案不存在"}),
                404,
            )

        # 解析檔案資訊
        key_parts = s3_key.split("/")
        file_info = {
            "success": True,
            "download_url": download_url,
            "s3_key": s3_key,
            "expires_in": expiration,
            "file_info": {},
        }

        if len(key_parts) >= 4 and key_parts[0] == "trgpt":
            file_info["file_info"] = {
                "user_mail": key_parts[1],
                "date": key_parts[2],
                "filename": key_parts[3].replace(".gz", ""),
            }

        return await make_response(jsonify(file_info))

    except ValueError:
        return await make_response(
            jsonify({"success": False, "message": "過期時間參數格式錯誤"}), 400
        )
    except Exception as e:
        return await make_response(jsonify({"success": False, "message": str(e)}), 500)


@app.route("/api/audit/bucket-info", methods=["GET"])
async def get_s3_bucket_info():
    """取得 S3 Bucket 資訊"""
    try:
        info = s3_manager.get_bucket_info()
        return await make_response(jsonify(info))
    except Exception as e:
        return await make_response(
            jsonify({"error": "Internal Server Error", "message": str(e)}), 500
        )


@app.route("/api/audit/local-files", methods=["GET"])
async def get_local_audit_files():
    """查看本地稽核日誌檔案狀態"""
    try:
        log_dir = "./local_audit_logs"
        files = []

        if os.path.exists(log_dir):
            for filename in os.listdir(log_dir):
                if filename.endswith(".json"):
                    file_path = os.path.join(log_dir, filename)
                    file_stats = os.stat(file_path)

                    # 讀取檔案內容以獲取記錄數量
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            logs = json.load(f)
                            record_count = len(logs) if isinstance(logs, list) else 0
                    except:
                        record_count = -1

                    files.append(
                        {
                            "filename": filename,
                            "path": file_path,
                            "size": file_stats.st_size,
                            "modified": datetime.fromtimestamp(
                                file_stats.st_mtime, taiwan_tz
                            ).isoformat(),
                            "record_count": record_count,
                        }
                    )

        return await make_response(
            jsonify(
                {
                    "success": True,
                    "local_directory": log_dir,
                    "files": sorted(files, key=lambda x: x["modified"], reverse=True),
                    "total_files": len(files),
                }
            )
        )

    except Exception as e:
        return await make_response(jsonify({"success": False, "message": str(e)}), 500)


@app.route("/api/memory/clear", methods=["GET"])
async def clear_user_memory():
    """清除用戶記憶體 API"""
    try:
        user_mail = request.args.get("user_mail")

        if user_mail:
            # 清除特定用戶的記憶體
            cleared_count = clear_user_memory_by_mail(user_mail)
            return await make_response(
                jsonify(
                    {
                        "success": True,
                        "message": f"已清除用戶 {user_mail} 的記憶體",
                        "cleared_conversations": cleared_count,
                        "user_mail": user_mail,
                    }
                )
            )
        else:
            # 清除所有用戶的記憶體
            cleared_count = clear_all_users_memory()
            return await make_response(
                jsonify(
                    {
                        "success": True,
                        "message": "已清除所有用戶的記憶體",
                        "cleared_conversations": cleared_count,
                        "scope": "all_users",
                    }
                )
            )

    except Exception as e:
        return await make_response(jsonify({"success": False, "message": str(e)}), 500)


# === 其他原有函數保持不變（略，包含所有會議室相關函數） ===
# 為了節省空間，這裡省略了原有的函數，實際使用時需要保留所有原有函數

# 判斷語言的邏輯
JAPANESE_MANAGER_EMAILS = [
    "tsutsumi@rinnai.com.tw",
    "ushimaru@rinnai.com.tw",
    "daiki.matsunami@rinnai.com.tw",
]


def determine_language(user_mail: str):
    if user_mail is None:
        return "zh-TW"
    user_mail = user_mail.lower()
    if user_mail in JAPANESE_MANAGER_EMAILS:
        return "ja"
    return "zh-TW"


async def get_real_user_email(
    turn_context: TurnContext, fallback_user_mail: str = None
) -> str:
    """獲取真實的用戶郵箱（支援 Debug 模式）"""
    # Debug 模式：如果指定了 DEBUG_ACCOUNT，直接返回該帳號
    if DEBUG_MODE and DEBUG_ACCOUNT:
        print(f"Debug 模式：使用指定帳號 {DEBUG_ACCOUNT}")
        return DEBUG_ACCOUNT

    try:
        aad_object_id = turn_context.activity.from_property.aad_object_id
        if not aad_object_id:
            return fallback_user_mail or "unknown@debug.com"
        user_info = await graph_api.get_user_info(aad_object_id)
        return user_info.get(
            "userPrincipalName", fallback_user_mail or "unknown@debug.com"
        )
    except Exception as e:
        print(f"取得真實用戶 email 時發生錯誤: {str(e)}")
        return fallback_user_mail or "unknown@debug.com"


async def get_user_email(turn_context: TurnContext) -> str:
    """查詢目前user mail"""
    try:
        # Debug 模式：如果指定了 DEBUG_ACCOUNT，直接返回該帳號
        if DEBUG_MODE and DEBUG_ACCOUNT:
            print(f"Debug 模式：使用指定帳號 {DEBUG_ACCOUNT}")
            return DEBUG_ACCOUNT

        aad_object_id = turn_context.activity.from_property.aad_object_id
        if not aad_object_id:
            print("No AAD Object ID found")
            return None
        user_info = await graph_api.get_user_info(aad_object_id)
        return user_info.get("mail")
        # return "test@example.com"  # 返回測試用戶
    except Exception as e:
        print(f"取得用戶 email 時發生錯誤: {str(e)}")
        return None


# === 修改 call_openai 函數 ===
async def call_openai(prompt, conversation_id, user_mail=None):
    """呼叫 OpenAI API - 雙重記錄版本"""
    global conversation_history

    # 檢查是否是預約相關問題
    booking_keywords = ["預約", "會議", "成功", "查詢"]
    is_booking_query = any(keyword in prompt for keyword in booking_keywords)

    if is_booking_query and user_mail:
        try:
            meetings = await get_user_meetings(user_mail)
            booking_info = (
                "您今天沒有會議室預約。" if not meetings else "您今天的預約如下:\n" 
            )
            for meeting in meetings:
                booking_info += f"- {meeting['location']}: {meeting['start']}-{meeting['end']} {meeting['subject']}\n"
            prompt = f"{prompt}\n\n實際預約資訊:\n{booking_info}"
        except Exception as e:
            print(f"查詢預約時發生錯誤: {str(e)}")
            prompt = f"{prompt}\n\n無法查詢到預約資訊,原因: {str(e)}"

    if conversation_id not in conversation_history:
        conversation_history[conversation_id] = []
        conversation_message_counts[conversation_id] = 0
        conversation_timestamps[conversation_id] = time.time()
        language = determine_language(user_mail)

        if not USE_AZURE_OPENAI:
            system_prompts = {
                "zh-TW": "你是一個智能助理，負責協助用戶處理各種問題和任務。",
                "ja": "あなたはインテリジェントアシスタントであり、ユーザーの様々な質問やタスクをサポートします。",
            }
            system_prompt = system_prompts.get(language, system_prompts["zh-TW"])
            system_message = {"role": "system", "content": system_prompt}
            await manage_conversation_history_with_limit_check(
                conversation_id, system_message, user_mail
            )

    # 記錄用戶訊息
    user_message = {"role": "user", "content": str(prompt)}
    await manage_conversation_history_with_limit_check(
        conversation_id, user_message, user_mail
    )

    response = None

    try:
        if USE_AZURE_OPENAI:
            response =   openai_client.chat.completions.create(
                model="o1-mini",
                messages=normalize_messages_for_model(
                    conversation_history[conversation_id], "o1-mini"
                ),
                max_completion_tokens=max_tokens,
                timeout=15,
            )
            print(f"使用 Azure OpenAI - 模型: o1-mini")
        else:
            # 使用用戶選擇的模型，如果沒有選擇則使用預設
            model_engine = user_model_preferences.get(user_mail, OPENAI_MODEL)

            # 根據模型設定 timeout 和參數
            if model_engine in MODEL_INFO:
                timeout_value = MODEL_INFO[model_engine]["timeout"]
            else:
                timeout_value = 30  # 預設值

            if model_engine.startswith("gpt-5"):
                extra_params = {}
                if model_engine == "gpt-5":
                    extra_params = {"reasoning_effort": "medium", "verbosity": "medium"}
                elif model_engine == "gpt-5-mini":
                    extra_params = {"reasoning_effort": "low", "verbosity": "medium"}
                elif model_engine == "gpt-5-nano":
                    extra_params = {"reasoning_effort": "minimal", "verbosity": "low"}
                else:
                    extra_params = {}

                response =  openai_client.chat.completions.create(
                    model=model_engine,
                    messages=normalize_messages_for_model(
                        conversation_history[conversation_id], model_engine
                    ),
                    timeout=timeout_value,
                    **extra_params,
                )
            else:
                response =  openai_client.chat.completions.create(
                    model=model_engine,
                    messages=normalize_messages_for_model(
                        conversation_history[conversation_id], model_engine
                    ),
                    max_tokens=max_tokens,
                    temperature=0.7,
                    top_p=0.9,
                    frequency_penalty=0.1,
                    presence_penalty=0.1,
                    timeout=25,
                )

            print(f"使用 OpenAI 直接 API - 模型: {model_engine}")
        if response is None:
            raise ValueError("OpenAI API 未返回任何回應")

        try:
            # 記錄助手回應
            message = response.choices[0].message
            assistant_message = {"role": "assistant", "content": message.content}
            await manage_conversation_history_with_limit_check(
                conversation_id, assistant_message, user_mail
            )
        except Exception as e:
            print(f"通知管理員失敗: {e}")

        return message.content

    except Exception as e:
        error_msg = str(e)
        print(f"OpenAI API 錯誤: {error_msg}")

        # 記錄錯誤到稽核日誌
        error_log = {"role": "system", "content": f"API 錯誤：{error_msg}"}
        log_message_to_audit(conversation_id, error_log, user_mail)

        # 嘗試通知管理員
        try:
            await notify_admin_of_error(error_msg, user_mail, conversation_id)
        except Exception as notify_err:
            print(f"通知管理員失敗: {notify_err}")

        return "抱歉，服務暫時不可用，請稍後再試。"


# === 保留所有原有函數（略） ===
# 以下函數保持不變，需要完整保留：


def sanitize_url(url):
    base = "https://rinnaitw-my.sharepoint.com"
    path = url.replace(base, "")
    encoded_path = "/".join(quote(segment) for segment in path.split("/"))
    sanitized_url = urljoin(base, encoded_path)
    return sanitized_url


async def notify_admin_of_error(error_msg: str, user_mail: str, conversation_id: str):
    """當出現服務不可用訊息時，主動通知管理員 Teams 帳號並附上錯誤內容。"""
    try:
        admin_mail = (ADMIN_ALERT_EMAIL or "").lower()
        if not admin_mail:
            print("未設定 ADMIN_ALERT_EMAIL，略過管理員通知")
            return

        # 避免訊息過長
        safe_error = (error_msg or "").strip()
        if len(safe_error) > 1500:
            safe_error = safe_error[:1500] + "... (truncated)"

        # 需要先有管理員的對話參考
        if admin_mail not in user_conversation_refs:
            print(f"尚未建立管理員對話參考，無法主動通知: {admin_mail}")
            return

        conversation_ref = user_conversation_refs[admin_mail]

        # 嘗試取得顯示名稱
        display_name = user_display_names.get(user_mail) or "(unknown)"

        async def send_alert(turn_context: TurnContext):
            text = (
                "🚨 系統錯誤通知\n"
                f"使用者: {display_name} <{user_mail}>\n"
                f"對話ID: {conversation_id}\n"
                f"錯誤: {safe_error}"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=text)
            )

        await adapter.continue_conversation(conversation_ref, send_alert, bot_id=appId)
        print(f"已通知管理員 {admin_mail} 錯誤: {safe_error}")
    except Exception as e:
        print(f"notify_admin_of_error 失敗: {e}")


def normalize_messages_for_model(messages: List[Dict[str, str]], model: str):
    """若模型不支援 system 角色，將 system 內容合併至第一個 user 訊息前置文字。

    - 目前假設 gpt-5 系列與部分 Azure 部署不接受 system 角色。
    - 保守處理：遇到不支援就降級為 user 前置說明，避免 400 錯誤。
    """

    def supports_system_role(m: str) -> bool:
        # 已知 family：o1*, gpt-5* 不支援 system 角色
        ml = (m or "").lower()
        return ml.startswith("gpt")

    if supports_system_role(model):
        return messages

    sys_contents = [m.get("content", "") for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]
    if not sys_contents:
        return other_msgs

    preface = "[System instructions]\n" + "\n\n".join(sys_contents).strip()
    if other_msgs:
        first = other_msgs[0].copy()
        first["content"] = f"{preface}\n\n{first.get('content', '')}"
        return [first] + other_msgs[1:]
    else:
        return [{"role": "user", "content": preface}]


def normalize_intent_output(result: Dict[str, Any]) -> Dict[str, Any]:
    """規整 AI 意圖輸出，確保 category 與 confidence 合理對應。

    - category 僅允許 {todo, meeting, info, model}，其他一律視為非現有功能。
    - confidence 介於 [0, 1]，缺省為 0.0。
    - 若 category 非法則強制 is_existing_feature=False, confidence=0.0。
    - 保留 action/content 原樣，不做硬編碼判斷。
    """
    allowed = {"todo", "meeting", "info", "model"}
    out = dict(result or {})
    cat = (out.get("category") or "").strip().lower()
    conf = out.get("confidence")

    # 規範 confidence
    try:
        conf = float(conf)
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    if cat not in allowed:
        out["is_existing_feature"] = False
        out["category"] = ""
        out["confidence"] = 0.0
        return out

    # 合法類別：若模型未提供 is_existing_feature，按類別存在判定為 True
    if "is_existing_feature" not in out:
        out["is_existing_feature"] = True

    out["category"] = cat
    out["confidence"] = conf
    return out


async def download_attachment_and_write(attachment: Attachment) -> dict:
    """下載並儲存附件"""
    try:
        url = ""
        if isinstance(attachment.content, dict) and "downloadUrl" in attachment.content:
            url = attachment.content["downloadUrl"]

        print(f"attachment.downloadUrl: {url}")
        response = urllib.request.urlopen(url)
        headers = response.info()

        if headers["content-type"] == "application/json":
            data = bytes(json.load(response)["data"])
        else:
            data = response.read()

        local_filename = os.path.join(os.getcwd(), "temp", attachment.name)
        os.makedirs(os.path.dirname(local_filename), exist_ok=True)

        with open(local_filename, "wb") as out_file:
            out_file.write(data)

        return {
            "filename": attachment.name,
            "local_path": local_filename,
            "content_type": headers["content-type"],
            "data": data,
        }
    except Exception as e:
        print(f"Downloading File Has Some Error: {str(e)}")
        return {}


async def get_user_meetings(user_mail: str) -> List[Dict]:
    """查詢使用者的會議預約"""
    try:
        today = datetime.now()
        start_time = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = today.replace(hour=23, minute=59, second=59, microsecond=999999)

        calendar_data = await graph_api.get_user_calendar(
            user_mail=user_mail, start_time=start_time, end_time=end_time
        )

        if not calendar_data or "value" not in calendar_data:
            print("No calendar data found")
            return []

        meetings = []
        for event in calendar_data["value"]:
            if not event.get("location"):
                continue

            location_name = event["location"].get("displayName", "")
            if not any(
                room_name in location_name
                for room_name in [
                    "第一會議室",
                    "第二會議室",
                    "工廠大會議室",
                    "工廠小會議室",
                    "研修教室",
                    "公務車",
                ]
            ):
                continue

            start_time = datetime.fromisoformat(
                event["start"]["dateTime"].replace("Z", "+00:00")
            ) + timedelta(hours=8)

            end_time = datetime.fromisoformat(
                event["end"]["dateTime"].replace("Z", "+00:00")
            ) + timedelta(hours=8)

            meetings.append(
                {
                    "id": event.get("id", ""),
                    "subject": event.get("subject", "未命名會議"),
                    "location": location_name,
                    "start": start_time.strftime("%H:%M"),
                    "end": end_time.strftime("%H:%M"),
                    "organizer": event.get("organizer", {})
                    .get("emailAddress", {})
                    .get("name", "未知"),
                    "is_organizer": event.get("organizer", {})
                    .get("emailAddress", {})
                    .get("address", "")
                    == user_mail,
                }
            )

        return sorted(meetings, key=lambda x: x["start"])

    except Exception as e:
        print(f"查詢使用者會議時發生錯誤: {str(e)}")
        return []


async def summarize_text(text, conversation_id, user_mail=None) -> str:
    try:
        language = determine_language(user_mail)
        system_prompts = {
            "zh-TW": "你是一個智能助理，負責摘要文本內容。請提供簡潔、準確的摘要。",
            "ja": "あなたはインテリジェントアシスタントであり、テキスト内容を要約する役割を担っています。簡潔で正確な要約を提供してください。",
        }
        system_prompt = system_prompts.get(language, system_prompts["zh-TW"])

        if USE_AZURE_OPENAI:
            # 以環境變數指定 Azure 部署名稱，避免找不到部署
            deployment = AZURE_OPENAI_SUMMARY_DEPLOYMENT
            az_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ]
            response =  openai_client.chat.completions.create(
                model=deployment,
                messages=normalize_messages_for_model(az_messages, deployment),
                max_tokens=max_tokens,
            )
        else:
            # 使用全局參數的彙總模型
            summary_model = OPENAI_SUMMARY_MODEL
            print(f"🔧 [文本摘要] 使用彙總模型: {summary_model}")

            summary_messages = normalize_messages_for_model(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                summary_model,
            )

            if summary_model.startswith("gpt-"):
                response =  openai_client.chat.completions.create(
                    model=summary_model,
                    messages=summary_messages,
                    reasoning_effort="low",
                    verbosity="low",
                    timeout=20,
                )
            else:
                response =  openai_client.chat.completions.create(
                    model=summary_model,
                    messages=summary_messages,
                    max_tokens=max_tokens,
                    temperature=0.3,
                    timeout=20,
                )

        message = response.choices[0].message
        return message.content

    except Exception as e:
        err = str(e)
        if "does not exist" in err and "deployment" in err.lower():
            print(
                "Azure OpenAI 部署不存在或名稱不正確。請設定 AZURE_OPENAI_SUMMARY_DEPLOYMENT 為實際的部署名稱，"
                "或至 Azure Portal 建立對應的 Chat Completions 部署。"
            )
        return f"摘要處理時發生錯誤：{err}"


async def welcome_user(turn_context: TurnContext):
    """歡迎使用者 - 更新版本"""
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

    if not USE_AZURE_OPENAI:
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
- 對話記錄：最多 {MAX_CONTEXT_MESSAGES} 筆訊息
- 待辦事項：保存 {CONVERSATION_RETENTION_DAYS} 天

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
- 会話記録：最大 {MAX_CONTEXT_MESSAGES} 件のメッセージ
- タスク：{CONVERSATION_RETENTION_DAYS} 日間保存

何かお力になれることはありますか？

(ヒント：@help と入力すると、システム機能を quickly 確認できます)
            """,
    }

    system_prompt = system_prompts.get(language, system_prompts["zh-TW"])
    welcome_text = system_prompt
    await show_help_options(turn_context, welcome_text)


# === 修改 message_handler 函數 ===
async def message_handler(turn_context: TurnContext): 
    try:
        user_id = turn_context.activity.from_property.id
        user_name = turn_context.activity.from_property.name
        user_mail = await get_user_email(turn_context) or f"{user_id}@unknown.com"
        conversation_id = turn_context.activity.conversation.id

        print(f"Current User Info: {user_name} (ID: {user_id}) (Mail: {user_mail})")

        # 儲存用戶的對話參考與顯示名稱，用於主動發送訊息與通知
        from botbuilder.core import TurnContext

        user_conversation_refs[user_mail] = TurnContext.get_conversation_reference(
            turn_context.activity
        )
        if user_mail:
            user_display_names[user_mail] = user_name or user_display_names.get(
                user_mail
            )

        # 處理 Adaptive Card 回應
        if turn_context.activity.value:
            card_action = turn_context.activity.value.get("action")

            # 處理功能選擇
            if card_action == "selectFunction":
                selected_function = turn_context.activity.value.get("selectedFunction")
                if selected_function:
                    # 特殊處理新增待辦事項
                    if selected_function == "@addTodo":
                        await show_add_todo_card(turn_context, user_mail)
                        return
                    # 特殊處理查看待辦清單
                    elif selected_function == "@ls":
                        # 直接執行 @ls 邏輯
                        pending_todos = get_user_pending_todos(user_mail)
                        if pending_todos:
                            language = determine_language(user_mail)
                            await send_todo_list_card(
                                turn_context, user_mail, pending_todos, language
                            )
                        else:
                            suggested_actions = get_suggested_replies(
                                "無待辦事項", user_mail
                            )
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
                        return
                    # 特殊處理會議室預約
                    elif selected_function == "@book-room":
                        await show_room_booking_options(turn_context, user_mail)
                        return
                    # 特殊處理查詢預約
                    elif selected_function == "@check-booking":
                        await show_my_bookings(turn_context, user_mail)
                        return
                    # 特殊處理取消預約
                    elif selected_function == "@cancel-booking":
                        await show_cancel_booking_options(turn_context, user_mail)
                        return
                    # 特殊處理個人資訊
                    elif selected_function == "@info":
                        await show_user_info(turn_context)
                        return
                    # 特殊處理機器人介紹
                    elif selected_function == "@you":
                        await show_bot_intro(turn_context)
                        return
                    # 特殊處理模型選擇
                    elif selected_function == "@model":
                        # 直接顯示模型選擇卡片（僅限 OpenAI 模式）
                        if USE_AZURE_OPENAI:
                            await turn_context.send_activity(
                                Activity(
                                    type=ActivityTypes.message,
                                    text="ℹ️ 目前使用 Azure OpenAI 服務\n📱 模型：o1-mini（固定）\n⚡ 此模式不支援模型切換",
                                )
                            )
                            return

                        # OpenAI 模式：直接顯示模型選擇卡片
                        current_model = user_model_preferences.get(
                            user_mail, OPENAI_MODEL
                        )
                        model_info = MODEL_INFO.get(
                            current_model,
                            {"speed": "未知", "time": "未知", "use_case": "未知"},
                        )

                        # 創建 Adaptive Card
                        model_card = {
                            "type": "AdaptiveCard",
                            "version": "1.4",
                            "body": [
                                {
                                    "type": "TextBlock",
                                    "text": "🤖 AI 模型選擇",
                                    "weight": "Bolder",
                                    "size": "Medium",
                                },
                                {
                                    "type": "TextBlock",
                                    "text": f"目前使用：{current_model} ({model_info['speed']} {model_info['time']})",
                                    "color": "Good",
                                    "spacing": "Small",
                                },
                                {
                                    "type": "Input.ChoiceSet",
                                    "id": "selectedModel",
                                    "style": "compact",
                                    "value": current_model,
                                    "choices": [
                                        {
                                            "title": f"gpt-4o ({MODEL_INFO['gpt-4o']['speed']} {MODEL_INFO['gpt-4o']['time']}) - {MODEL_INFO['gpt-4o']['use_case']}",
                                            "value": "gpt-4o",
                                        },
                                        {
                                            "title": f"gpt-4o-mini ({MODEL_INFO['gpt-4o-mini']['speed']} {MODEL_INFO['gpt-4o-mini']['time']}) - {MODEL_INFO['gpt-4o-mini']['use_case']}",
                                            "value": "gpt-4o-mini",
                                        },
                                        {
                                            "title": f"gpt-5-mini ({MODEL_INFO['gpt-5-mini']['speed']} {MODEL_INFO['gpt-5-mini']['time']}) - {MODEL_INFO['gpt-5-mini']['use_case']}",
                                            "value": "gpt-5-mini",
                                        },
                                        {
                                            "title": f"gpt-5-nano ({MODEL_INFO['gpt-5-nano']['speed']} {MODEL_INFO['gpt-5-nano']['time']}) - {MODEL_INFO['gpt-5-nano']['use_case']}",
                                            "value": "gpt-5-nano",
                                        },
                                        {
                                            "title": f"gpt-5 ({MODEL_INFO['gpt-5']['speed']} {MODEL_INFO['gpt-5']['time']}) - {MODEL_INFO['gpt-5']['use_case']}",
                                            "value": "gpt-5",
                                        },
                                        {
                                            "title": f"gpt-5-chat-latest ({MODEL_INFO['gpt-5-chat-latest']['speed']} {MODEL_INFO['gpt-5-chat-latest']['time']}) - {MODEL_INFO['gpt-5-chat-latest']['use_case']}",
                                            "value": "gpt-5-chat-latest",
                                        },
                                    ],
                                },
                            ],
                            "actions": [
                                {
                                    "type": "Action.Submit",
                                    "title": "🔄 切換模型",
                                    "data": {"action": "selectModel"},
                                }
                            ],
                        }

                        from botbuilder.schema import Attachment

                        card_attachment = Attachment(
                            content_type="application/vnd.microsoft.card.adaptive",
                            content=model_card,
                        )

                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text="請選擇要切換的 AI 模型：",
                                attachments=[card_attachment],
                            )
                        )
                        return
                    else:
                        # 模擬用戶輸入選擇的功能（處理其他未特殊處理的功能）
                        turn_context.activity.text = selected_function
                        # 繼續處理，不要 return

            # 處理會議室預約
            elif card_action == "bookRoom":
                await handle_room_booking(turn_context, user_mail)
                return

            # 處理會議室預約取消
            elif card_action == "cancelBooking":
                await handle_cancel_booking(turn_context, user_mail)
                return

            # 處理新增待辦事項
            elif card_action == "addTodoItem":
                todo_content = turn_context.activity.value.get(
                    "todoContent", ""
                ).strip()
                if todo_content:
                    todo_id = add_todo_item(user_mail, todo_content)
                    if todo_id:
                        # 產生建議回覆
                        suggested_replies = get_suggested_replies(
                            f"完成新增", user_mail
                        )

                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text=f"✅ 已新增待辦事項 #{todo_id}：{todo_content}",
                                suggested_actions=(
                                    SuggestedActions(actions=suggested_replies)
                                    if suggested_replies
                                    else None
                                ),
                            )
                        )
                    else:
                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message, text="❌ 新增待辦事項失敗"
                            )
                        )
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="❌ 請輸入待辦事項內容",
                        )
                    )
                return

            # 處理完成待辦事項
            # 處理完成待辦事項
            elif card_action == "completeTodo":
                selected_index = turn_context.activity.value.get("selectedTodo")
                if selected_index is not None:
                    # 將索引轉換為實際的待辦事項ID
                    pending_todos = get_user_pending_todos(user_mail)
                    try:
                        todo_index = int(selected_index)
                        if 0 <= todo_index < len(pending_todos):
                            actual_todo_id = pending_todos[todo_index]["id"]
                            # 完成選中的待辦事項
                            completed_items = mark_todo_completed(
                                user_mail, [actual_todo_id]
                            )
                            if completed_items:
                                await turn_context.send_activity(
                                    Activity(
                                        type=ActivityTypes.message,
                                        text=f"✅ 已完成待辦事項 #{actual_todo_id}",
                                    )
                                )
                            else:
                                await turn_context.send_activity(
                                    Activity(
                                        type=ActivityTypes.message,
                                        text="❌ 完成待辦事項失敗",
                                    )
                                )
                        else:
                            await turn_context.send_activity(
                                Activity(
                                    type=ActivityTypes.message,
                                    text="❌ 選擇的待辦事項不存在",
                                )
                            )
                    except ValueError:
                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text="❌ 無效的待辦事項選擇",
                            )
                        )
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="❌ 未選擇要完成的待辦事項",
                        )
                    )
                return

            # 處理模型選擇
            elif card_action == "selectModel":
                if USE_AZURE_OPENAI:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="ℹ️ Azure OpenAI 模式不支援模型切換",
                        )
                    )
                    return

                selected_model = turn_context.activity.value.get("selectedModel") 
                if selected_model and selected_model in MODEL_INFO:
                    user_model_preferences[user_mail] = selected_model
                    model_info = MODEL_INFO[selected_model]
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text=f"✅ 已切換至 {selected_model}\n⚡ 回應速度：{model_info['speed']}（{model_info['time']}）\n🎯 適用場景：{model_info['use_case']}",
                        )
                    )
                return

        # 清理日誌檔案邏輯保持不變...
        # try:
        #     log_dir = "./json_logs"
        #     log_file_path = os.path.join(log_dir, "json_log.json")
        #     if os.path.exists(log_file_path):
        #         os.remove(log_file_path)
        #         print("Log file has been deleted.")
        #     if os.path.exists(log_dir) and not os.listdir(log_dir):
        #         os.rmdir(log_dir)
        #         print("Empty log directory has been removed.")
        # except Exception as e:
        #     print(f"Delete Log File Error: {str(e)}")

        # === 自然語言意圖分析 ===
        # 先檢查是否為指令模式
        if turn_context.activity.text and turn_context.activity.text.startswith("@"):
            # 移除 @ 與前後空白，並小寫化，避免尾端空白或大小寫導致判斷失敗
            user_message = turn_context.activity.text.lstrip("@").strip().lower()

            # 處理開啟新對話指令
            if user_message == "new-chat":
                await confirm_new_conversation(turn_context)
                return

            if user_message == "who":
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=user_mail)
                )
                await show_self_info(turn_context, user_mail)
                return

            if user_message == "help":
                await show_help_options(turn_context)
                return

            if user_message == "info":
                await show_user_info(turn_context)
                return

            if user_message == "you":
                await show_bot_intro(turn_context)
                return

            if user_message == "check-booking":
                await show_my_bookings(turn_context, user_mail)
                return
                
            if user_message == "cancel-booking":
                await show_cancel_booking_options(turn_context, user_mail)
                return

            # 更新狀態查詢指令
            if user_message == "status":
                msg_count = conversation_message_counts.get(conversation_id, 0)
                audit_count = len(audit_logs_by_user.get(user_mail, []))
                pending_todos = get_user_pending_todos(user_mail)
                status_text = f"""當前對話狀態：
• 工作記憶：{msg_count}/{MAX_CONTEXT_MESSAGES} 筆訊息
• 稽核日誌：{audit_count} 筆完整記錄
• 待辦事項：{len(pending_todos)} 筆待處理
• 稽核保存期限：{CONVERSATION_RETENTION_DAYS} 天"""
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=status_text)
                )
                return

            # 其他@指令繼續在後面處理（保持向後兼容）
        elif turn_context.activity.text and not turn_context.activity.text.startswith(
            "@"
        ):
            user_message = turn_context.activity.text.strip()

            if ENABLE_AI_INTENT_ANALYSIS:
                # === AI 優先意圖分析系統（可由環境變數開關） ===
                print(f"🎯 [AI意圖分析] 開始分析用戶意圖: {user_message}")

                ai_intent = await analyze_user_intent(user_message)
                print(f"🤖 [AI分析結果] {ai_intent}")

                # 判斷是否為現有功能
                if (
                    ai_intent.get("is_existing_feature", False)
                    and ai_intent.get("confidence", 0) > 0.7
                    and ai_intent.get("category")
                ):
                    print(
                        f"✅ [現有功能] 識別為: {ai_intent['category']}.{ai_intent['action']}"
                    )

                    # 執行現有功能
                    success = await handle_intent_action(
                        turn_context, user_mail, ai_intent
                    )
                    if success:
                        print("🎉 [處理成功] 功能執行完成")
                        return
                    else:
                        print("⚠️ [處理失敗] 功能執行失敗，轉為AI對話")
                else:
                    print("💭 [非現有功能] 轉交主要AI處理 (AI意圖分析未命中或信心不足)")
            else:
                print("ℹ️ 已停用 AI 意圖分析（ENABLE_AI_INTENT_ANALYSIS=false）")

            # 進入主要AI對話
            # 發送 loading 訊息
            language = determine_language(user_mail)
            loading_messages = {
                "zh-TW": "🤔 思考更長時間以取得更佳回答...",
                "ja": "🤔 考え中です。少々お待ちください...",
            }
            loading_text = loading_messages.get(language, loading_messages["zh-TW"])

            # 發送 typing 活動
            await turn_context.send_activity(Activity(type="typing"))
            loading_activity = await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=loading_text)
            )

            # 呼叫 OpenAI
            response_message = await call_openai(
                turn_context.activity.text,
                conversation_id,
                user_mail=user_mail,
            )

            # 發送實際回應
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=response_message)
            )

            # 檔案處理
            attachments = turn_context.activity.attachments
            if attachments and len(attachments) > 0:
                print("Current Request Is An File")
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=f"檔案分析功能目前暫不開放，請見諒!",
                    )
                )
    except Exception as e:
        print(f"處理訊息時發生錯誤: {str(e)}")
        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=f"處理訊息時發生錯誤，請稍後再試。 {str(e)}",
            )
        )


@app.route("/ping", methods=["GET"])
async def ping():
    debuggerTest = os.getenv("debugInfo")
    return await make_response(
        jsonify(
            {"status": "ok", "message": "Bot is alive", "debuggerTest": debuggerTest}
        )
    )


@app.route("/api/messages", methods=["POST"])
async def messages():
    print("=== 開始處理訊息 ===")
    if "application/json" in request.headers["Content-Type"]:
        body = await request.get_json()
        print(f"請求內容: {json.dumps(body, ensure_ascii=False, indent=2)}")
    else:
        return {"status": 415}

    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")
    print(f"Authorization header: {auth_header[:50] if auth_header else '(空白)'}")
    print(f"Current Bot App ID: {os.getenv('BOT_APP_ID') or '(空白)'}")

    async def aux_func(turn_context):
        try:
            if activity.type == "conversationUpdate" and activity.members_added:
                for member in activity.members_added:
                    if member.id != activity.recipient.id:
                        await welcome_user(turn_context)
            elif activity.type == "message":
                await message_handler(turn_context)
        except Exception as e:
            print(f"Error in aux_func: {str(e)}")
            return

    try:
        await adapter.process_activity(activity, auth_header, aux_func)
    except Exception as e:
        print(f"Error processing message: {str(e)}")
        return {"status": 401}

    print("=== 訊息處理完成 ===")
    return {"status": 200}


async def show_user_info(turn_context: TurnContext):
    """顯示用戶個人資訊"""
    try:
        # Debug 模式處理
        if DEBUG_MODE and DEBUG_ACCOUNT:
            # 在 Debug 模式下顯示模擬資訊
            info_text = f"""👤 **個人資訊** (Debug 模式)

📧 **郵箱**：{DEBUG_ACCOUNT}
👨‍💼 **姓名**：Debug 用戶
🏢 **部門**：測試部門
📱 **職稱**：系統測試員
📞 **電話**：未設定

⚠️ 這是 Debug 模式的模擬資訊"""

            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=info_text)
            )
            return

        # 一般模式
        aad_object_id = turn_context.activity.from_property.aad_object_id
        if not aad_object_id:
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text="❌ 無法取得用戶ID")
            )
            return

        user_info = await graph_api.get_user_info(aad_object_id)

        if user_info:
            # 取得電話資訊（優先使用 businessPhones，其次 mobilePhone）
            phone = "未設定"
            if user_info.get("businessPhones") and len(user_info["businessPhones"]) > 0:
                phone = user_info["businessPhones"][0]
            elif user_info.get("mobilePhone"):
                phone = user_info["mobilePhone"]

            # 取得部門資訊
            department = user_info.get("department", "未設定")
            if not department or department == "None":
                department = "未設定"

            info_text = f"""👤 **個人資訊**

📧 **郵箱**：{user_info.get('userPrincipalName', '未知')}
👨‍💼 **姓名**：{user_info.get('displayName', '未知')}
🏢 **部門**：{department}
📱 **職稱**：{user_info.get('jobTitle', '未設定')}
📞 **電話**：{phone}"""
        else:
            info_text = "❌ 無法取得用戶資訊"

        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=info_text)
        )

    except Exception as e:
        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message, text=f"❌ 取得用戶資訊時發生錯誤：{str(e)}"
            )
        )


async def show_self_info(turn_context: TurnContext, user_mail: str):
    """取得user資訊"""
    await turn_context.send_activity(
        Activity(type=ActivityTypes.message, text=f"測試用戶: {user_mail}")
    )


async def show_bot_intro(turn_context: TurnContext):
    """顯示機器人自我介紹（官方語氣）。"""
    try:
        user_mail = await get_user_email(turn_context)
        language = determine_language(user_mail)

        if language == "ja":
            header = "🤖 このボットについて"
            fallback = (
                "本ボットは、最新の大規模言語モデル（LLM）を活用した社内向け AI アシスタントです（TR GPT／台湾リンナイ情報課 開発）。\n"
                "以下の機能を、Microsoft Teams を通じて安全かつ一貫した体験で提供します。\n\n"
                "• インテリジェントQA／要約・翻訳・提案\n"
                "• 個人効率化：TODO 管理（追加・一覧・完了通知）\n"
                "• 行動連携：会議室の検索／予約／取消、スケジュール確認\n"
                "• システム連携：Microsoft Graph、Azure/OpenAI\n\n"
                "使い方のヒント：\n"
                "- `@help` で機能一覧を表示\n"
                "- `@info` で自分の情報を表示\n"
                "- `@you` でこの紹介を表示"
            )
        else:
            header = "🤖 關於本機器人"
            fallback = (
                "本機器人（TR GPT）是結合最新大型語言模型（LLM）的企業內部 AI 助理，"
                "透過 Microsoft Teams 提供安全一致的智慧體驗。\n\n"
                "• 智能問答與內容整理：摘要、翻譯、建議\n"
                "• 個人效率：待辦事項管理（新增、清單、完成提醒）\n"
                "• 行程協作：會議室查詢／預約／取消與行程檢視\n"
                "• 系統整合：Microsoft Graph、Azure/OpenAI\n\n"
                "使用提示：\n"
                "- 輸入 `@help` 檢視功能與指令\n"
                "- 輸入 `@info` 取得個人資訊\n"
                "- 輸入 `@you` 查看此介紹"
            )

        text = f"{header}\n\n{fallback}"
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=text)
        )
    except Exception as e:
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=f"❌ 顯示自我介紹時發生錯誤：{e}")
        )


async def show_add_todo_card(turn_context: TurnContext, user_mail: str):
    """顯示新增待辦事項輸入卡片"""
    language = determine_language(user_mail)

    todo_card = {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "📝 新增待辦事項" if language == "zh-TW" else "📝 タスクを追加",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "Input.Text",
                "id": "todoContent",
                "placeholder": (
                    "請輸入待辦事項內容..."
                    if language == "zh-TW"
                    else "タスクの内容を入力してください..."
                ),
                "maxLength": 200,
                "isMultiline": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ 新增" if language == "zh-TW" else "✅ 追加",
                "data": {"action": "addTodoItem"},
            }
        ],
    }

    from botbuilder.schema import Attachment

    card_attachment = Attachment(
        content_type="application/vnd.microsoft.card.adaptive", content=todo_card
    )

    await turn_context.send_activity(
        Activity(
            type=ActivityTypes.message,
            text=(
                "請填寫待辦事項內容："
                if language == "zh-TW"
                else "タスクの内容を記入してください："
            ),
            attachments=[card_attachment],
        )
    )


async def show_help_options(turn_context: TurnContext, welcomeMsg: str = None):
    # 取得用戶語言設定
    user_id = turn_context.activity.from_property.id
    user_name = turn_context.activity.from_property.name
    user_mail = await get_user_email(turn_context) or f"{user_id}@unknown.com"
    language = determine_language(user_mail)

    # 檢查是否使用 OpenAI API 來決定功能選項
    model_switch_info_zh = ""
    model_switch_info_ja = ""
    model_actions = []

    if not USE_AZURE_OPENAI:
        model_switch_info_zh = """

🤖 **AI 模型功能**：
- 輸入 @model 可切換 AI 模型
- 支援 gpt-4o、gpt-5-mini、gpt-5-nano、gpt-5 等模型
- 預設使用：gpt-5-mini (輕量版推理模型)"""

        model_switch_info_ja = """

🤖 **AI モデル機能**：
- @model を入力してAIモデルを切り替え
- gpt-4o、gpt-5-mini、gpt-5-nano、gpt-5 などのモデルに対応
- デフォルト：gpt-5-mini（推理タスク専用）"""

        model_actions = [
            {
                "title": (
                    "🤖 切換 AI 模型" if language == "zh-TW" else "🤖 AIモデル切替"
                ),
                "value": "@model",
            }
        ]

    # 建立功能說明
    help_info = {
        "zh-TW": f"""📚 **系統功能說明**：

🤖 您正在使用 TR GPT — 由台灣林內資訊課開發的企業 AI 助理。

💬 **基本功能**：
- 智能問答與多語言翻譯
- 即時語言偵測與回應

{model_switch_info_zh}

🏢 **會議室功能**、

📊 **系統指令**：
- @help - 查看功能說明
- @info - 查看個人資訊
- @you - 關於本機器人""",
        "ja": f"""📚 **システム機能説明**：

🤖 本ボットは TR GPT です（台湾リンナイ情報課が開発）。

💬 **基本機能**：
- インテリジェントQA、翻訳
- リアルタイム言語検出と応答

{model_switch_info_ja}

🏢 **会議室機能**、

📊 **システムコマンド**：
- @help - 機能説明表示
- @info - 個人情報表示
- @you - このボットについて""",
    }

    # 建立 Adaptive Card 下拉選單
    choices = [
        {
            "title": "📝 新增待辦事項" if language == "zh-TW" else "📝 タスク追加",
            "value": "@addTodo",
        },
        {
            "title": "📋 查看待辦清單" if language == "zh-TW" else "📋 タスクリスト",
            "value": "@ls",
        },
        {
            "title": "🏢 會議室預約" if language == "zh-TW" else "🏢 会議室予約",
            "value": "@book-room",
        },
        {
            "title": "📅 查詢預約" if language == "zh-TW" else "📅 予約確認",
            "value": "@check-booking",
        },
        {
            "title": "❌ 取消預約" if language == "zh-TW" else "❌ 予約キャンセル",
            "value": "@cancel-booking",
        },
        {
            "title": "👤 個人資訊" if language == "zh-TW" else "👤 個人情報",
            "value": "@info",
        },
        {
            "title": (
                "🤖 關於此機器人" if language == "zh-TW" else "🤖 このボットについて"
            ),
            "value": "@you",
        },
    ]

    # 如果是 OpenAI 模式，加入模型切換選項
    if model_actions:
        choices.insert(2, model_actions[0])

    help_card = {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "🛠️ 功能選單" if language == "zh-TW" else "🛠️ 機能メニュー",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "TextBlock",
                "text": help_info.get(language, help_info["zh-TW"]),
                "wrap": True,
                "spacing": "Medium",
            },
            {
                "type": "Input.ChoiceSet",
                "id": "selectedFunction",
                "style": "compact",
                "placeholder": (
                    "選擇功能..." if language == "zh-TW" else "機能を選択..."
                ),
                "choices": choices,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ 執行功能" if language == "zh-TW" else "✅ 実行",
                "data": {"action": "selectFunction"},
            }
        ],
    }

    # 建立訊息
    display_text = f"{welcomeMsg}\n\n" if welcomeMsg else ""
    display_text += (
        "請選擇下方功能："
        if language == "zh-TW"
        else "以下から機能を選択してください："
    )

    from botbuilder.schema import Attachment

    card_attachment = Attachment(
        content_type="application/vnd.microsoft.card.adaptive", content=help_card
    )

    reply = Activity(
        type=ActivityTypes.message, text=display_text, attachments=[card_attachment]
    )

    await turn_context.send_activity(reply)


async def show_room_booking_options(turn_context: TurnContext, user_mail: str):
    """顯示會議室預約選項"""
    language = determine_language(user_mail)

    # 取得可用會議室
    try:
        rooms_data = await graph_api.get_available_rooms()
        rooms = rooms_data.get("value", [])
    except:
        # 使用 Rinnai 會議室清單
        rooms = [
            {
                "displayName": "第一會議室",
                "emailAddress": "meetingroom01@rinnai.com.tw",
            },
            {
                "displayName": "第二會議室",
                "emailAddress": "meetingroom02@rinnai.com.tw",
            },
            {
                "displayName": "工廠大會議室",
                "emailAddress": "meetingroom04@rinnai.com.tw",
            },
            {
                "displayName": "工廠小會議室",
                "emailAddress": "meetingroom05@rinnai.com.tw",
            },
            {"displayName": "研修教室", "emailAddress": "meetingroom03@rinnai.com.tw"},
            {"displayName": "公務車", "emailAddress": "rinnaicars@rinnai.com.tw"},
        ]

    # 產生日期選項（從今天開始到未來7天，但如果今天已經過了18:00，則從明天開始）
    from datetime import datetime, timedelta

    current_time = datetime.now(taiwan_tz)

    # 如果現在已經過了18:00，從明天開始
    start_offset = 1 if current_time.hour >= 18 else 0

    date_choices = []
    for i in range(start_offset, start_offset + 8):
        date = current_time + timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        display_date = date.strftime("%m/%d (%a)")

        if i == 0:
            display_date = (
                f"今天 {display_date}"
                if language == "zh-TW"
                else f"今日 {display_date}"
            )
        elif i == 1 or (i == 0 and start_offset == 1):
            display_date = (
                f"明天 {display_date}"
                if language == "zh-TW"
                else f"明日 {display_date}"
            )

        date_choices.append({"title": display_date, "value": date_str})

    # 產生時間選項（8:00-18:30，每30分鐘）
    time_choices = []
    for hour in range(8, 19):
        for minute in [0, 30]:
            if hour == 18 and minute == 30:  # 18:30 是最後一個可用時段
                break
            time_str = f"{hour:02d}:{minute:02d}"
            time_choices.append({"title": time_str, "value": time_str})

    # 添加提示：系統會驗證時間有效性
    time_note = (
        "\n💡 提示：系統會自動驗證時間有效性和會議室可用性"
        if language == "zh-TW"
        else "\n💡 ヒント：システムが自動的に時間の有効性と会議室の可用性を確認します"
    )

    # 產生會議室選項
    room_choices = []
    for room in rooms:
        room_choices.append(
            {"title": room["displayName"], "value": room["emailAddress"]}
        )

    booking_card = {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "🏢 會議室預約" if language == "zh-TW" else "🏢 会議室予約",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "Input.Text",
                "id": "meetingSubject",
                "placeholder": (
                    "請輸入會議主題..."
                    if language == "zh-TW"
                    else "会議のテーマを入力..."
                ),
                "maxLength": 100,
            },
            {
                "type": "TextBlock",
                "text": "選擇會議室：" if language == "zh-TW" else "会議室を選択：",
                "weight": "Bolder",
                "spacing": "Medium",
            },
            {
                "type": "Input.ChoiceSet",
                "id": "selectedRoom",
                "style": "compact",
                "placeholder": (
                    "選擇會議室..." if language == "zh-TW" else "会議室を選択..."
                ),
                "choices": room_choices,
            },
            {
                "type": "TextBlock",
                "text": "選擇日期：" if language == "zh-TW" else "日付を選択：",
                "weight": "Bolder",
                "spacing": "Medium",
            },
            {
                "type": "Input.ChoiceSet",
                "id": "selectedDate",
                "style": "compact",
                "placeholder": (
                    "選擇日期..." if language == "zh-TW" else "日付を選択..."
                ),
                "choices": date_choices,
            },
            {
                "type": "TextBlock",
                "text": "開始時間：" if language == "zh-TW" else "開始時間：",
                "weight": "Bolder",
                "spacing": "Medium",
            },
            {
                "type": "Input.ChoiceSet",
                "id": "startTime",
                "style": "compact",
                "placeholder": (
                    "選擇開始時間..." if language == "zh-TW" else "開始時間を選択..."
                ),
                "choices": time_choices,
            },
            {
                "type": "TextBlock",
                "text": "結束時間：" if language == "zh-TW" else "終了時間：",
                "weight": "Bolder",
                "spacing": "Medium",
            },
            {
                "type": "Input.ChoiceSet",
                "id": "endTime",
                "style": "compact",
                "placeholder": (
                    "選擇結束時間..." if language == "zh-TW" else "終了時間を選択..."
                ),
                "choices": time_choices,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ 預約會議室" if language == "zh-TW" else "✅ 会議室予約",
                "data": {"action": "bookRoom"},
            }
        ],
    }

    from botbuilder.schema import Attachment

    card_attachment = Attachment(
        content_type="application/vnd.microsoft.card.adaptive", content=booking_card
    )

    await turn_context.send_activity(
        Activity(
            type=ActivityTypes.message,
            text=(
                "請填寫會議室預約資訊："
                if language == "zh-TW"
                else "会議室予約情報を入力してください："
            ),
            attachments=[card_attachment],
        )
    )


async def show_my_bookings(turn_context: TurnContext, user_mail: str):
    """顯示用戶的會議室預約"""
    language = determine_language(user_mail)

    try:
        # 取得真實的用戶郵箱
        real_user_email = await get_real_user_email(turn_context, user_mail)

        if "@unknown.com" in real_user_email:
            error_msg = (
                "❌ 無法取得有效的用戶郵箱"
                if language == "zh-TW"
                else "❌ 有効なユーザーメールアドレスを取得できません"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        # 查詢未來30天的預約（只查自己的）
        from datetime import datetime, timedelta

        start_time = datetime.now(taiwan_tz)
        end_time = start_time + timedelta(days=30)

        # 發送查詢中的訊息
        loading_msg = (
            "📅 正在查詢您的會議室預約..."
            if language == "zh-TW"
            else "📅 会議室予約を確認中..."
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=loading_msg)
        )

        events_data = await graph_api.get_user_calendarView(
            real_user_email, start_time, end_time
        )
        events = events_data.get("value", [])

        # 過濾出會議室相關的預約（包含 Rinnai 會議室）
        room_emails = [
            "meetingroom01@rinnai.com.tw",
            "meetingroom02@rinnai.com.tw",
            "meetingroom03@rinnai.com.tw",
            "meetingroom04@rinnai.com.tw",
            "meetingroom05@rinnai.com.tw",
            "rinnaicars@rinnai.com.tw",
        ]

        room_bookings = []
        for event in events:
            # 只顯示從當前時間開始的會議
            event_start = datetime.fromisoformat(
                event["start"]["dateTime"].replace("Z", "+00:00")
            )
            # 轉換為台灣時間進行比較
            if event_start.tzinfo is None:
                # 如果沒有時區信息，假設是UTC
                event_start = event_start.replace(tzinfo=pytz.UTC)
            event_start_tw = event_start.astimezone(taiwan_tz)
            current_time = datetime.now(taiwan_tz)
            if event_start_tw <= current_time:
                continue

            # 檢查會議的與會者中是否包含會議室
            attendees = event.get("attendees", [])

            # 判斷用戶是主辦者還是參與者
            organizer_email = (
                event.get("organizer", {}).get("emailAddress", {}).get("address", "")
            )
            is_organizer = organizer_email.lower() == real_user_email.lower()

            for attendee in attendees:
                email = attendee.get("emailAddress", {}).get("address", "")
                if email in room_emails:
                    room_bookings.append(
                        {
                            "id": event["id"],
                            "subject": event.get("subject", "無主題"),
                            "start": event["start"]["dateTime"],
                            "end": event["end"]["dateTime"],
                            "room_email": email,
                            "location": event.get("location", {}).get(
                                "displayName", email
                            ),
                            "is_organizer": is_organizer,
                        }
                    )
                    break

        if not room_bookings:
            no_bookings_msg = (
                "📅 您目前沒有會議室預約"
                if language == "zh-TW"
                else "📅 現在会議室の予約はありません"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=no_bookings_msg)
            )
            return

        # 顯示預約列表
        bookings_text = (
            f"📅 **您的會議室預約** ({len(room_bookings)} 個)：\n\n"
            if language == "zh-TW"
            else f"📅 **あなたの会議室予約** ({len(room_bookings)} 件)：\n\n"
        )

        for i, booking in enumerate(room_bookings, 1):
            print(
                f"查詢預約 - 原始時間字串: start={booking['start']}, end={booking['end']}"
            )

            # 處理不同的時間格式
            start_str = booking["start"]
            end_str = booking["end"]

            # 如果時間字串已經包含時區信息但不是Z結尾
            if "T" in start_str and (
                "+" in start_str or "-" in start_str.split("T")[1]
            ):
                start_dt = datetime.fromisoformat(start_str)
                end_dt = datetime.fromisoformat(end_str)
            else:
                # 處理Z結尾的UTC時間或無時區的時間
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

            print(f"查詢預約 - 解析後時間: start_dt={start_dt}, end_dt={end_dt}")

            # 轉換為台灣時間
            if start_dt.tzinfo is None:
                # 如果沒有時區信息，假設是UTC
                start_dt = start_dt.replace(tzinfo=pytz.UTC)
                end_dt = end_dt.replace(tzinfo=pytz.UTC)

            start_tw = start_dt.astimezone(taiwan_tz)
            end_tw = end_dt.astimezone(taiwan_tz)
            print(f"查詢預約 - 轉換台灣時間: start_tw={start_tw}, end_tw={end_tw}")
            print(
                f"查詢預約 - 格式化時間: {start_tw.strftime('%H:%M')} - {end_tw.strftime('%H:%M')}"
            )

            # 測試：如果顯示01:00，檢查是否正確加了8小時
            test_utc = datetime(2025, 8, 24, 1, 0, tzinfo=pytz.UTC)  # UTC 01:00
            test_tw = test_utc.astimezone(taiwan_tz)  # 應該是台灣09:00
            print(
                f"測試時區轉換: UTC {test_utc.strftime('%H:%M')} -> 台灣 {test_tw.strftime('%H:%M')}"
            )

            # 判斷身份標示
            role_indicator = (
                ""
                if booking["is_organizer"]
                else " (參與)" if language == "zh-TW" else " (参加)"
            )

            bookings_text += f"""**{i}. {booking['subject']}{role_indicator}**
🏢 會議室：{booking['location']}
📅 日期：{start_tw.strftime('%Y/%m/%d (%a)')}
⏰ 時間：{start_tw.strftime('%H:%M')} - {end_tw.strftime('%H:%M')}

"""

        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=bookings_text)
        )

    except Exception as e:
        error_msg = (
            f"❌ 查詢預約失敗：{str(e)}"
            if language == "zh-TW"
            else f"❌ 予約確認に失敗しました：{str(e)}"
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=error_msg)
        )


async def show_cancel_booking_options(turn_context: TurnContext, user_mail: str):
    """顯示取消預約選項"""
    language = determine_language(user_mail)

    try:
        # 取得真實的用戶郵箱
        real_user_email = await get_real_user_email(turn_context, user_mail)

        if "@unknown.com" in real_user_email:
            error_msg = (
                "❌ 無法取得有效的用戶郵箱"
                if language == "zh-TW"
                else "❌ 有効なユーザーメールアドレスを取得できません"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        # 查詢未來的預約
        from datetime import datetime, timedelta

        start_time = datetime.now(taiwan_tz)
        end_time = start_time + timedelta(days=30)  # 查詢未來30天

        events_data = await graph_api.get_user_calendarView(
            real_user_email, start_time, end_time
        )
        events = events_data.get("value", [])

        # 過濾出會議室相關的預約
        room_emails = [
            "meetingroom01@rinnai.com.tw",
            "meetingroom02@rinnai.com.tw",
            "meetingroom03@rinnai.com.tw",
            "meetingroom04@rinnai.com.tw",
            "meetingroom05@rinnai.com.tw",
            "rinnaicars@rinnai.com.tw",
        ]

        room_bookings = []
        for event in events:
            # 只顯示未來的預約（可以取消的）
            event_start = datetime.fromisoformat(
                event["start"]["dateTime"].replace("Z", "+00:00")
            )
            # 轉換為台灣時間進行比較
            if event_start.tzinfo is None:
                # 如果沒有時區信息，假設是UTC
                event_start = event_start.replace(tzinfo=pytz.UTC)
            event_start_tw = event_start.astimezone(taiwan_tz)
            current_time = datetime.now(taiwan_tz)
            if event_start_tw <= current_time:
                continue

            attendees = event.get("attendees", [])
            for attendee in attendees:
                email = attendee.get("emailAddress", {}).get("address", "")
                if email in room_emails:
                    room_bookings.append(
                        {
                            "id": event["id"],
                            "subject": event.get("subject", "無主題"),
                            "start": event["start"]["dateTime"],
                            "end": event["end"]["dateTime"],
                            "room_email": email,
                            "location": event.get("location", {}).get(
                                "displayName", email
                            ),
                        }
                    )
                    break

        if not room_bookings:
            no_bookings_msg = (
                "📅 您目前沒有可取消的會議室預約"
                if language == "zh-TW"
                else "📅 キャンセル可能な会議室予約はありません"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=no_bookings_msg)
            )
            return

        # 創建取消預約的 Adaptive Card - 使用下拉選單+取消按鈕
        choices = []
        for booking in room_bookings:
            print(
                f"取消預約 - 原始時間字串: start={booking['start']}, end={booking['end']}"
            )

            # 處理不同的時間格式
            start_str = booking["start"]
            end_str = booking["end"]

            # 如果時間字串已經包含時區信息但不是Z結尾
            if "T" in start_str and (
                "+" in start_str or "-" in start_str.split("T")[1]
            ):
                start_dt = datetime.fromisoformat(start_str)
                end_dt = datetime.fromisoformat(end_str)
            else:
                # 處理Z結尾的UTC時間或無時區的時間
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

            print(f"取消預約 - 解析後時間: start_dt={start_dt}, end_dt={end_dt}")

            # 轉換為台灣時間
            if start_dt.tzinfo is None:
                # 如果沒有時區信息，假設是UTC
                start_dt = start_dt.replace(tzinfo=pytz.UTC)
                end_dt = end_dt.replace(tzinfo=pytz.UTC)

            start_tw = start_dt.astimezone(taiwan_tz)
            end_tw = end_dt.astimezone(taiwan_tz)
            print(f"取消預約 - 轉換台灣時間: start_tw={start_tw}, end_tw={end_tw}")
            print(
                f"取消預約 - 格式化時間: {start_tw.strftime('%H:%M')} - {end_tw.strftime('%H:%M')}"
            )

            display_text = f"{booking['subject']} - {booking['location']} ({start_tw.strftime('%m/%d %H:%M')}-{end_tw.strftime('%H:%M')})"
            print(f"顯示文字: {display_text}")

            choices.append({"title": display_text, "value": booking["id"]})

        cancel_card = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": (
                        "❌ 取消會議預約"
                        if language == "zh-TW"
                        else "❌ 会議予約キャンセル"
                    ),
                    "weight": "Bolder",
                    "size": "Medium",
                },
                {
                    "type": "TextBlock",
                    "text": (
                        f"您有 {len(room_bookings)} 個可取消的會議："
                        if language == "zh-TW"
                        else f"{len(room_bookings)} 件のキャンセル可能な会議があります："
                    ),
                    "spacing": "Medium",
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selectedBooking",
                    "style": "compact",
                    "placeholder": (
                        "選擇要取消的會議..."
                        if language == "zh-TW"
                        else "キャンセルする会議を選択..."
                    ),
                    "choices": choices,
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": (
                        "❌ 取消選中的會議"
                        if language == "zh-TW"
                        else "❌ 選択した会議をキャンセル"
                    ),
                    "data": {"action": "cancelBooking"},
                    "style": "destructive",
                },
            ],
        }
        from botbuilder.schema import Attachment

        card_attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive", content=cancel_card
        )

        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=(
                    "請選擇要取消的預約："
                    if language == "zh-TW"
                    else "キャンセルする予約を選択してください："
                ),
                attachments=[card_attachment],
            )
        )

    except Exception as e:
        error_msg = (
            f"❌ 取得預約列表失敗：{str(e)}"
            if language == "zh-TW"
            else f"❌ 予約リスト取得に失敗しました：{str(e)}"
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=error_msg)
        )


async def handle_cancel_booking(turn_context: TurnContext, user_mail: str):
    """處理取消預約"""
    language = determine_language(user_mail)

    try:
        card_data = turn_context.activity.value
        event_id = card_data.get("selectedBooking")

        if not event_id:
            error_msg = (
                "❌ 請選擇要取消的預約"
                if language == "zh-TW"
                else "❌ キャンセルする予約を選択してください"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        # 取得真實的用戶郵箱
        real_user_email = await get_real_user_email(turn_context, user_mail)

        if "@unknown.com" in real_user_email:
            error_msg = (
                "❌ 無法取得有效的用戶郵箱"
                if language == "zh-TW"
                else "❌ 有効なユーザーメールアドレスを取得できません"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        # 發送取消中的訊息
        loading_msg = (
            "❌ 正在取消預約..." if language == "zh-TW" else "❌ 予約をキャンセル中..."
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=loading_msg)
        )

        # 執行取消
        success = await graph_api.delete_meeting(real_user_email, event_id)

        if success:
            success_msg = (
                "✅ 會議預約已成功取消"
                if language == "zh-TW"
                else "✅ 会議予約が正常にキャンセルされました"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=success_msg)
            )

            # 取消成功後，檢查是否還有會議，有的話重新顯示更新的取消預約選項
            await update_cancel_booking_list_if_needed(turn_context, user_mail)
        else:
            error_msg = (
                "❌ 取消預約失敗"
                if language == "zh-TW"
                else "❌ 予約のキャンセルに失敗しました"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )

    except Exception as e:
        error_str = str(e)
        # 檢查是否為已經刪除的會議
        if "ErrorItemNotFound" in error_str or "not found" in error_str.lower():
            friendly_msg = (
                "✅ 此會議已經被取消，或可能已被其他人取消"
                if language == "zh-TW"
                else "✅ この会議は既にキャンセルされているか、他の人によってキャンセルされた可能性があります"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=friendly_msg)
            )

            # 重新顯示更新的取消預約選項（如果還有會議的話）
            await update_cancel_booking_list_if_needed(turn_context, user_mail)
        else:
            error_msg = (
                f"❌ 取消預約時發生錯誤：{error_str}"
                if language == "zh-TW"
                else f"❌ 予約キャンセル中にエラーが発生しました：{error_str}"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )


async def handle_complete_todo(turn_context: TurnContext, user_mail: str):
    """處理完成待辦事項"""
    language = determine_language(user_mail)

    try:
        card_data = turn_context.activity.value
        selected_todo_index = card_data.get("selectedTodo")

        if selected_todo_index is None:
            error_msg = (
                "❌ 請選擇要完成的事項"
                if language == "zh-TW"
                else "❌ 完了するアイテムを選択してください"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        todo_index = int(selected_todo_index)

        # 獲取用戶的待辦事項
        if user_mail not in user_todos:
            user_todos[user_mail] = {}

        pending_todos = get_user_pending_todos(user_mail)

        if todo_index >= len(pending_todos):
            error_msg = (
                "❌ 選擇的事項不存在"
                if language == "zh-TW"
                else "❌ 選択されたアイテムが存在しません"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        # 標記為完成
        todo_to_complete = pending_todos[todo_index]
        todo_id = todo_to_complete["id"]

        # 在用戶的待辦字典中找到並標記為完成
        if todo_id in user_todos[user_mail]:
            user_todos[user_mail][todo_id]["status"] = "completed"
            user_todos[user_mail][todo_id]["completed_at"] = datetime.now(
                taiwan_tz
            ).isoformat()
        else:
            error_msg = (
                "❌ 待辦事項不存在"
                if language == "zh-TW"
                else "❌ TODOアイテムが存在しません"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        success_msg = (
            f"✅ 已完成：{todo_to_complete['content']}"
            if language == "zh-TW"
            else f"✅ 完了しました：{todo_to_complete['content']}"
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=success_msg)
        )

        # 檢查是否還有其他待辦事項，如果有的話重新發送清單卡片
        remaining_todos = get_user_pending_todos(user_mail)
        if len(remaining_todos) > 0:
            await send_todo_list_card(
                turn_context, user_mail, remaining_todos, language
            )
        else:
            all_done_msg = (
                "🎉 所有待辦事項都完成了！"
                if language == "zh-TW"
                else "🎉 すべてのTODOが完了しました！"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=all_done_msg)
            )

    except Exception as e:
        error_msg = (
            f"❌ 完成事項時發生錯誤：{str(e)}"
            if language == "zh-TW"
            else f"❌ アイテム完了中にエラーが発生しました：{str(e)}"
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=error_msg)
        )


async def update_cancel_booking_list_if_needed(
    turn_context: TurnContext, user_mail: str
):
    """檢查是否還有會議，有的話重新顯示取消預約選項"""
    language = determine_language(user_mail)

    try:
        # 取得真實的用戶郵箱
        real_user_email = await get_real_user_email(turn_context, user_mail)
        if "@unknown.com" in real_user_email:
            return

        # 查詢未來的預約
        from datetime import datetime, timedelta

        start_time = datetime.now(taiwan_tz)
        end_time = start_time + timedelta(days=30)  # 查詢未來30天

        events_data = await graph_api.get_user_calendarView(
            real_user_email, start_time, end_time
        )
        events = events_data.get("value", [])

        # 過濾出會議室相關的預約
        room_emails = [
            "meetingroom01@rinnai.com.tw",
            "meetingroom02@rinnai.com.tw",
            "meetingroom03@rinnai.com.tw",
            "meetingroom04@rinnai.com.tw",
            "meetingroom05@rinnai.com.tw",
            "rinnaicars@rinnai.com.tw",
        ]

        room_bookings = []
        for event in events:
            # 只顯示未來的預約（可以取消的）
            event_start = datetime.fromisoformat(
                event["start"]["dateTime"].replace("Z", "+00:00")
            )
            # 轉換為台灣時間進行比較
            event_start_tw = event_start.astimezone(taiwan_tz)
            current_time = datetime.now(taiwan_tz)
            if event_start_tw <= current_time:
                continue

            attendees = event.get("attendees", [])
            for attendee in attendees:
                email = attendee.get("emailAddress", {}).get("address", "")
                if email in room_emails:
                    room_bookings.append(event)
                    break

        # 只有當還有會議時才重新顯示列表
        if len(room_bookings) > 0:
            await show_cancel_booking_options(turn_context, user_mail)
        else:
            no_more_msg = (
                "✅ 您已經沒有可取消的會議了"
                if language == "zh-TW"
                else "✅ キャンセル可能な会議はもうありません"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=no_more_msg)
            )

    except Exception as e:
        print(f"更新取消列表時發生錯誤: {str(e)}")
        # 錯誤時不做任何處理，避免干擾用戶


async def handle_room_booking(turn_context: TurnContext, user_mail: str):
    """處理會議室預約提交"""
    language = determine_language(user_mail)

    try:
        card_data = turn_context.activity.value

        # 取得表單數據
        subject = card_data.get("meetingSubject", "").strip()
        room_email = card_data.get("selectedRoom")
        date_str = card_data.get("selectedDate")
        start_time_str = card_data.get("startTime")
        end_time_str = card_data.get("endTime")

        # 驗證必填欄位
        if not all([subject, room_email, date_str, start_time_str, end_time_str]):
            error_msg = (
                "❌ 請填寫所有必要資訊"
                if language == "zh-TW"
                else "❌ 必要情報をすべて入力してください"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        # 解析時間
        from datetime import datetime, timedelta

        try:
            # 組合日期和時間
            start_datetime_str = f"{date_str} {start_time_str}:00"
            end_datetime_str = f"{date_str} {end_time_str}:00"

            start_time = datetime.strptime(start_datetime_str, "%Y-%m-%d %H:%M:%S")
            end_time = datetime.strptime(end_datetime_str, "%Y-%m-%d %H:%M:%S")

            # 設定時區
            start_time = taiwan_tz.localize(start_time)
            end_time = taiwan_tz.localize(end_time)

            # 驗證時間邏輯
            if start_time >= end_time:
                error_msg = (
                    "❌ 結束時間必須晚於開始時間"
                    if language == "zh-TW"
                    else "❌ 終了時間は開始時間より後でなければなりません"
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=error_msg)
                )
                return

            # 驗證不能預約過去的時間
            current_time = datetime.now(taiwan_tz)
            # if start_time <= current_time:
            #     error_msg = (
            #         "❌ 不能預約過去的時間，請選擇未來的時段"
            #         if language == "zh-TW"
            #         else "❌ 過去の時間は予約できません。将来の時間を選択してください"
            #     )
            #     await turn_context.send_activity(
            #         Activity(type=ActivityTypes.message, text=error_msg)
            #     )
            #     return

            # 驗證會議時間至少30分鐘
            duration = (end_time - start_time).total_seconds() / 60
            if duration < 30:
                error_msg = (
                    "❌ 會議時間至少需要30分鐘"
                    if language == "zh-TW"
                    else "❌ 会議時間は最低30分必要です"
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=error_msg)
                )
                return

        except ValueError as e:
            error_msg = (
                "❌ 日期時間格式錯誤"
                if language == "zh-TW"
                else "❌ 日時フォーマットエラー"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )
            return

        # 取得會議室名稱
        try:
            rooms_data = await graph_api.get_available_rooms()
            rooms = rooms_data.get("value", [])
            room_name = next(
                (
                    room["displayName"]
                    for room in rooms
                    if room["emailAddress"] == room_email
                ),
                room_email,
            )
        except:
            room_name = room_email

        # 檢查會議室是否在該時段已被預約
        try:
            # 擴展檢查範圍，確保能抓到所有相關事件
            check_start = start_time - timedelta(hours=1)
            check_end = end_time + timedelta(hours=1)

            print(f"=== 開始檢查會議室衝突 ===")
            print(f"會議室: {room_email}")
            print(f"新預約時間: {start_time} - {end_time}")
            print(f"檢查範圍: {check_start} - {check_end}")

            # 先嘗試查詢會議室的行事曆，如果失敗則查詢用戶自己的行事曆
            room_events = None
            try:
                room_events = await graph_api.get_user_calendarView(
                    user_email=room_email, start_time=check_start, end_time=check_end
                )
                print(f"成功查詢會議室行事曆")
            except Exception as room_error:
                print(f"查詢會議室行事曆失敗: {room_error}")
                # 改查用戶自己的行事曆，看是否有包含該會議室的預約
                real_user_email = await get_real_user_email(turn_context, user_mail)
                print(f"改查用戶 {real_user_email} 的行事曆")
                room_events = await graph_api.get_user_calendarView(
                    user_email=real_user_email,
                    start_time=check_start,
                    end_time=check_end,
                )

            print(f"API 回傳結果: {room_events}")

            # 檢查是否有時間衝突
            if "value" in room_events and room_events["value"]:
                print(f"檢查會議室 {room_email} 在 {start_time} - {end_time} 的衝突")
                print(f"找到 {len(room_events['value'])} 個現有預約")

                for existing_event in room_events["value"]:
                    # 如果查詢的是用戶行事曆，需要檢查事件是否包含目標會議室
                    if room_email not in str(
                        room_events
                    ):  # 簡單判斷是否查詢會議室行事曆
                        attendees = existing_event.get("attendees", [])
                        room_found = False
                        for attendee in attendees:
                            if (
                                attendee.get("emailAddress", {}).get("address", "")
                                == room_email
                            ):
                                room_found = True
                                break
                        if not room_found:
                            continue  # 跳過不包含目標會議室的事件
                    existing_start_str = existing_event["start"]["dateTime"]
                    existing_end_str = existing_event["end"]["dateTime"]

                    # 處理時區 - 統一轉換到台灣時區進行比較
                    if existing_start_str.endswith("Z"):
                        existing_start = datetime.fromisoformat(
                            existing_start_str.replace("Z", "+00:00")
                        ).astimezone(taiwan_tz)
                        existing_end = datetime.fromisoformat(
                            existing_end_str.replace("Z", "+00:00")
                        ).astimezone(taiwan_tz)
                    elif "T" in existing_start_str and (
                        "+" in existing_start_str
                        or "-" in existing_start_str.split("T")[1]
                    ):
                        # 已有時區信息，直接解析並轉換
                        existing_start = datetime.fromisoformat(
                            existing_start_str
                        ).astimezone(taiwan_tz)
                        existing_end = datetime.fromisoformat(
                            existing_end_str
                        ).astimezone(taiwan_tz)
                    else:
                        # 無時區信息，假設是UTC並轉換
                        existing_start = (
                            datetime.fromisoformat(existing_start_str)
                            .replace(tzinfo=pytz.UTC)
                            .astimezone(taiwan_tz)
                        )
                        existing_end = (
                            datetime.fromisoformat(existing_end_str)
                            .replace(tzinfo=pytz.UTC)
                            .astimezone(taiwan_tz)
                        )

                    # 確保新預約時間也是台灣時區（標準化）
                    if start_time.tzinfo != taiwan_tz:
                        start_time_normalized = start_time.astimezone(taiwan_tz)
                        end_time_normalized = end_time.astimezone(taiwan_tz)
                    else:
                        start_time_normalized = start_time
                        end_time_normalized = end_time

                    # 檢查時間重疊 (邊界相接不算重疊，只有真正重疊才不允許)
                    # 例如：09:00-09:30 和 09:30-10:00 是可以的（相接）
                    # 但是：08:00-10:00 和 09:00-09:30 是不可以的（重疊）
                    # 重疊判斷：新開始 < 現有結束 AND 新結束 > 現有開始 AND 不是剛好相接
                    is_overlapping = (
                        start_time_normalized < existing_end
                        and end_time_normalized > existing_start
                        and not (
                            start_time_normalized == existing_end
                            or end_time_normalized == existing_start
                        )
                    )

                    existing_subject = existing_event.get("subject", "未命名會議")
                    print(
                        f"現有預約: {existing_subject} ({existing_start} - {existing_end})"
                    )
                    print(
                        f"新預約（標準化）: {start_time_normalized} - {end_time_normalized}"
                    )
                    print(f"原始新預約: {start_time} - {end_time}")
                    print(f"重疊條件檢查:")
                    print(
                        f"  start_time_normalized < existing_end: {start_time_normalized < existing_end}"
                    )
                    print(
                        f"  end_time_normalized > existing_start: {end_time_normalized > existing_start}"
                    )
                    print(
                        f"  start_time_normalized == existing_end: {start_time_normalized == existing_end}"
                    )
                    print(
                        f"  end_time_normalized == existing_start: {end_time_normalized == existing_start}"
                    )
                    print(f"是否重疊: {is_overlapping}")

                    if is_overlapping:
                        # 檢查是否為用戶相關的會議（主辦者或參與者）
                        real_user_email = await get_real_user_email(
                            turn_context, user_mail
                        )
                        is_user_related = False

                        # 檢查主辦者
                        organizer_email = (
                            existing_event.get("organizer", {})
                            .get("emailAddress", {})
                            .get("address", "")
                        )
                        if organizer_email.lower() == real_user_email.lower():
                            is_user_related = True

                        # 檢查參與者
                        if not is_user_related:
                            attendees = existing_event.get("attendees", [])
                            for attendee in attendees:
                                attendee_email = attendee.get("emailAddress", {}).get(
                                    "address", ""
                                )
                                if attendee_email.lower() == real_user_email.lower():
                                    is_user_related = True
                                    break

                        # 根據是否相關決定顯示內容
                        if is_user_related:
                            error_msg = (
                                f"❌ 該會議室在 {existing_start.strftime('%H:%M')}-{existing_end.strftime('%H:%M')} 已被預約\n"
                                f"預約主題：{existing_subject}\n請選擇其他時段"
                                if language == "zh-TW"
                                else f"❌ その会議室は {existing_start.strftime('%H:%M')}-{existing_end.strftime('%H:%M')} に予約されています\n"
                                f"予約テーマ：{existing_subject}\n他の時間を選択してください"
                            )
                        else:
                            error_msg = (
                                f"❌ 該會議室在 {existing_start.strftime('%H:%M')}-{existing_end.strftime('%H:%M')} 已被預約"
                                if language == "zh-TW"
                                else f"❌ その会議室は {existing_start.strftime('%H:%M')}-{existing_end.strftime('%H:%M')} に予約されています"
                            )
                        await turn_context.send_activity(
                            Activity(type=ActivityTypes.message, text=error_msg)
                        )
                        return

        except Exception as e:
            print(f"檢查會議室可用性時發生錯誤: {str(e)}")
            print(f"錯誤類型: {type(e)}")
            import traceback

            print(f"完整錯誤: {traceback.format_exc()}")

            # 如果檢查失敗，記錄詳細信息但允許預約繼續（避免阻擋正常預約）
            print("⚠️ 會議室衝突檢查失敗，但允許預約繼續")
            # 不再阻擋預約，讓用戶可以正常預約

        # 發送確認中的訊息
        loading_msg = (
            "📅 正在預約會議室..." if language == "zh-TW" else "📅 会議室を予約中..."
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=loading_msg)
        )

        try:
            # 取得真實的用戶郵箱
            real_user_email = await get_real_user_email(turn_context, user_mail)

            # 如果用戶郵箱還是包含 @unknown.com，使用預設郵箱或拋出錯誤
            if "@unknown.com" in real_user_email:
                error_msg = (
                    "❌ 無法取得有效的用戶郵箱，請確保您已正確登入"
                    if language == "zh-TW"
                    else "❌ 有効なユーザーメールアドレスを取得できません"
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=error_msg)
                )
                return

            # 建立會議
            meeting_result = await graph_api.create_meeting(
                organizer_email=real_user_email,
                location=room_name,
                room_email=room_email,
                subject=subject,
                start_time=start_time,
                end_time=end_time,
                attendees=[],  # 可以後續擴展添加與會者
            )

            # 成功訊息
            success_msg = (
                f"""✅ **會議室預約成功！**

📋 **會議主題**：{subject}
🏢 **會議室**：{room_name}
📅 **日期**：{start_time.strftime('%Y/%m/%d (%a)')}
⏰ **時間**：{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}

會議已新增到您的行事曆中。"""
                if language == "zh-TW"
                else f"""✅ **会議室予約成功！**

📋 **会議テーマ**：{subject}
🏢 **会議室**：{room_name}
📅 **日付**：{start_time.strftime('%Y/%m/%d (%a)')}
⏰ **時間**：{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}

会議がカレンダーに追加されました。"""
            )

            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=success_msg)
            )

        except Exception as e:
            error_msg = (
                f"❌ 預約失敗：{str(e)}"
                if language == "zh-TW"
                else f"❌ 予約に失敗しました：{str(e)}"
            )
            await turn_context.send_activity(
                Activity(type=ActivityTypes.message, text=error_msg)
            )

    except Exception as e:
        error_msg = (
            f"❌ 處理預約時發生錯誤：{str(e)}"
            if language == "zh-TW"
            else f"❌ 予約処理中にエラーが発生しました：{str(e)}"
        )
        await turn_context.send_activity(
            Activity(type=ActivityTypes.message, text=error_msg)
        )


# === 啟動定時器 === 在程式啟動時直接啟動
daily_s3_upload()  # S3 上傳
hourly_todo_reminder()  # 待辦事項提醒

# 程式進入點
if __name__ == "__main__":
    import hypercorn.asyncio
    import hypercorn.config

    config = hypercorn.config.Config()
    config.bind = ["0.0.0.0:8000"]
    asyncio.run(hypercorn.asyncio.serve(app, config))
