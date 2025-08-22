from datetime import datetime, timedelta
from typing import List, Dict

from openai import OpenAI, AzureOpenAI

from flask import Flask, request, jsonify
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

#   清理邏輯
#   - 記憶體清理：達到 MAX_CONTEXT_MESSAGES 時自動清除該用戶記憶體
#   - S3上傳：每24小時自動上傳所有待上傳的日誌

# === 對話管理參數 ===
CONVERSATION_RETENTION_DAYS = int(os.getenv("CONVERSATION_RETENTION_DAYS", "30"))
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "30"))
# === 稽核日誌參數 ===
S3_UPLOAD_INTERVAL_HOURS = int(os.getenv("S3_UPLOAD_INTERVAL_HOURS", "24"))
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
}

# 台灣時區
taiwan_tz = pytz.timezone("Asia/Taipei")


# OpenAI API 配置
USE_AZURE_OPENAI = os.getenv("USE_AZURE_OPENAI", "true").lower() == "true"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

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


def daily_s3_upload():
    """每日自動上傳所有用戶的稽核日誌"""
    print("開始每日稽核日誌上傳...")

    async def upload_all():
        for user_mail in list(audit_logs_by_user.keys()):
            if audit_logs_by_user[user_mail]:
                try:
                    result = await upload_user_audit_logs(user_mail)
                    print(f"用戶 {user_mail} 上傳結果: {result['message']}")
                except Exception as e:
                    print(f"上傳用戶 {user_mail} 的日誌失敗: {str(e)}")

    # 在新的事件迴圈中運行
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(upload_all())
        loop.close()
    except Exception as e:
        print(f"S3上傳任務執行失敗: {str(e)}")

    # 安排下次上傳
    Timer(S3_UPLOAD_INTERVAL_HOURS * 3600, daily_s3_upload).start()


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
                    # 構建提醒訊息
                    reminder_text = f"📝 您有 {len(pending_todos)} 個待辦事項：\n\n"
                    for i, todo in enumerate(pending_todos, 1):
                        reminder_text += f"{i}. {todo['content']}\n"
                    reminder_text += "\n回覆「@ok 編號」來標記完成事項"

                    # 發送 Teams 提醒訊息
                    if user_mail in user_conversation_refs:
                        try:
                            conversation_ref = user_conversation_refs[user_mail]

                            async def send_reminder(turn_context):
                                await turn_context.send_activity(
                                    Activity(
                                        type=ActivityTypes.message, text=reminder_text
                                    )
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


# 安排下次上傳
Timer(S3_UPLOAD_INTERVAL_HOURS * 3600, daily_s3_upload).start()


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
            CardAction(title="查看功能", type=ActionTypes.im_back, text="/help"),
        ]

    # 待辦事項完成後
    elif any(word in message_lower for word in ["完成", "done", "@ok"]):
        return [
            CardAction(title="查看剩餘待辦", type=ActionTypes.im_back, text="@ls"),
            CardAction(title="新增待辦", type=ActionTypes.im_back, text="@add "),
            CardAction(title="清空全部", type=ActionTypes.im_back, text="@cls"),
            CardAction(title="查看狀態", type=ActionTypes.im_back, text="/status"),
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
            CardAction(title="查看幫助", type=ActionTypes.im_back, text="/help"),
            CardAction(title="查看狀態", type=ActionTypes.im_back, text="/status"),
            CardAction(title="重新開始", type=ActionTypes.im_back, text="@開啟新對話"),
            CardAction(title="切換模型", type=ActionTypes.im_back, text="@model"),
        ]

    # 預設建議
    else:
        return [
            CardAction(title="查看待辦", type=ActionTypes.im_back, text="@ls"),
            CardAction(title="新增待辦", type=ActionTypes.im_back, text="@add "),
            CardAction(title="查看功能", type=ActionTypes.im_back, text="/help"),
            CardAction(title="切換模型", type=ActionTypes.im_back, text="@model"),
        ]


# === 待辦事項管理函數 ===


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
        "zh-TW": f"新對話已開始！\n\n工作記憶已清除，您現在可以開始全新的對話。\n\n系統設定提醒：\n• 工作記憶保存 {CONVERSATION_RETENTION_DAYS} 天\n• 每個對話最多保留 {MAX_CONTEXT_MESSAGES} 筆上下文記錄\n• 稽核日誌保存 {CONVERSATION_RETENTION_DAYS} 天（完整記錄）\n\n有什麼我可以幫您的嗎？",
        "ja": f"新しい会話が開始されました！\n\n作業メモリがクリアされ、新しい会話を開始できます。\n\nシステム設定：\n• 作業メモリは {CONVERSATION_RETENTION_DAYS} 日間保存\n• 各会話で最大 {MAX_CONTEXT_MESSAGES} 件のコンテキストを保持\n• 監査ログは {CONVERSATION_RETENTION_DAYS} 日間保存（完全記録）\n\n何かお手伝いできることはありますか？",
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

        summary_msg = {"role": "system", "content": f"對話摘要（重要信息）：{summary}"}
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
@app.route("/api/audit/upload-all", methods=["POST"])
async def upload_all_users():
    """上傳所有用戶的稽核日誌"""
    try:
        results = []
        for user_mail in list(audit_logs_by_user.keys()):
            if audit_logs_by_user[user_mail]:
                result = await upload_user_audit_logs(user_mail)
                results.append({"user": user_mail, "result": result})

        return await make_response(
            jsonify(
                {
                    "success": True,
                    "message": f"已處理 {len(results)} 個用戶",
                    "details": results,
                }
            )
        )
    except Exception as e:
        return await make_response(jsonify({"success": False, "message": str(e)}), 500)


@app.route("/api/audit/upload/<user_mail>", methods=["POST"])
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


@app.route("/api/audit/test-upload", methods=["POST"])
async def test_upload_audit_logs():
    """測試用：立即上傳所有待上傳的稽核日誌"""
    try:
        results = []
        upload_count = 0

        for user_mail in list(audit_logs_by_user.keys()):
            if audit_logs_by_user[user_mail]:
                result = await upload_user_audit_logs(user_mail)
                results.append({"user": user_mail, "result": result})
                if result["success"]:
                    upload_count += 1

        return await make_response(
            jsonify(
                {
                    "success": True,
                    "message": f"測試上傳完成，成功上傳 {upload_count} 個用戶的日誌",
                    "details": results,
                    "total_processed": len(results),
                }
            )
        )
    except Exception as e:
        return await make_response(jsonify({"success": False, "message": str(e)}), 500)


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


@app.route("/api/memory/clear", methods=["POST"])
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


async def get_user_email(turn_context: TurnContext) -> str:
    """查詢目前user mail"""
    try:
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

    try:
        if USE_AZURE_OPENAI:
            response = openai_client.chat.completions.create(
                model="o1-mini",
                messages=conversation_history[conversation_id],
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

                response = openai_client.chat.completions.create(
                    model=model_engine,
                    messages=conversation_history[conversation_id],
                    timeout=timeout_value,
                    **extra_params,
                )
            else:
                response = openai_client.chat.completions.create(
                    model=model_engine,
                    messages=conversation_history[conversation_id],
                    max_tokens=max_tokens,
                    temperature=0.7,
                    top_p=0.9,
                    frequency_penalty=0.1,
                    presence_penalty=0.1,
                    timeout=25,
                )

            print(f"使用 OpenAI 直接 API - 模型: {model_engine}")

        # 記錄助手回應
        message = response.choices[0].message
        assistant_message = {"role": "assistant", "content": message.content}
        await manage_conversation_history_with_limit_check(
            conversation_id, assistant_message, user_mail
        )

        return message.content

    except Exception as e:
        error_msg = str(e)
        print(f"OpenAI API 錯誤: {error_msg}")

        # 記錄錯誤到稽核日誌
        error_log = {"role": "system", "content": f"API 錯誤：{error_msg}"}
        log_message_to_audit(conversation_id, error_log, user_mail)

        return "抱歉，服務暫時不可用，請稍後再試。"


# === 保留所有原有函數（略） ===
# 以下函數保持不變，需要完整保留：


def sanitize_url(url):
    base = "https://rinnaitw-my.sharepoint.com"
    path = url.replace(base, "")
    encoded_path = "/".join(quote(segment) for segment in path.split("/"))
    sanitized_url = urljoin(base, encoded_path)
    return sanitized_url


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
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini-deploy",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=max_tokens,
            )
        else:
            summary_model = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini")

            if summary_model.startswith("gpt-5"):
                response = openai_client.chat.completions.create(
                    model=summary_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    reasoning_effort="low",
                    verbosity="low",
                    timeout=20,
                )
            else:
                response = openai_client.chat.completions.create(
                    model=summary_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.3,
                    timeout=20,
                )

        message = response.choices[0].message
        return message.content

    except Exception as e:
        return f"摘要處理時發生錯誤：{str(e)}"


async def welcome_user(turn_context: TurnContext):
    """歡迎使用者 - 更新版本"""
    user_name = turn_context.activity.from_property.name

    try:
        user_mail = await get_user_email(turn_context)
    except Exception as e:
        print(f"取得用戶 email 時發生錯誤: {str(e)}")
        user_mail = None

    language = determine_language(user_mail)

    system_prompts = {
        "zh-TW": f"""歡迎 {user_name} 使用 TR GPT！

我可以協助您：
- 回答各種問題
- 多語言翻譯
- 智能建議與諮詢

對話設定：
- 工作記憶保存期限：{CONVERSATION_RETENTION_DAYS} 天

有什麼我可以幫您的嗎？

(提示：輸入 /help 可快速查看系統功能)""",
        "ja": f"""{user_name} さん、TR GPT インテリジェントアシスタントへようこそ！

お手伝いできること：
- あらゆる質問への対応
- 多言語翻訳
- インテリジェントな提案とアドバイス

会話設定：
- 作業メモリ保存期間：{CONVERSATION_RETENTION_DAYS} 日
- コンテキスト保持数：{MAX_CONTEXT_MESSAGES} 件のメッセージ
- 監査ログ保存期間：{CONVERSATION_RETENTION_DAYS} 日（完全記録）
- 上限に達した場合は新しい会話を選択可能

何かお力になれることはありますか？

(ヒント：/help と入力すると、システム機能を quickly 確認できます)
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

        # 儲存用戶的對話參考，用於主動發送訊息
        from botbuilder.core import TurnContext

        user_conversation_refs[user_mail] = TurnContext.get_conversation_reference(
            turn_context.activity
        )

        # 處理 Adaptive Card 回應（模型選擇）
        if (
            turn_context.activity.value
            and turn_context.activity.value.get("action") == "selectModel"
        ):
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
        try:
            log_dir = "./json_logs"
            log_file_path = os.path.join(log_dir, "json_log.json")
            if os.path.exists(log_file_path):
                os.remove(log_file_path)
                print("Log file has been deleted.")
            if os.path.exists(log_dir) and not os.listdir(log_dir):
                os.rmdir(log_dir)
                print("Empty log directory has been removed.")
        except Exception as e:
            print(f"Delete Log File Error: {str(e)}")

        if turn_context.activity.text and turn_context.activity.text.startswith("@"):
            user_message = turn_context.activity.text.lstrip("@")

            # 處理開啟新對話指令
            if user_message == "開啟新對話":
                await confirm_new_conversation(turn_context)
                return

            # 處理新增待辦事項指令
            if user_message == "add":
                # 只輸入 @add 沒有內容
                # 添加建議回覆
                suggested_actions = get_suggested_replies("@add 提示", user_mail)

                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text="請在 @add 後面輸入待辦事項內容，例如：@add 明天開會",
                        suggested_actions=(
                            SuggestedActions(actions=suggested_actions)
                            if suggested_actions
                            else None
                        ),
                    )
                )
                return
            elif user_message.startswith("add "):
                todo_content = user_message[4:].strip()  # 移除 "add " 前綴
                if todo_content:
                    todo_id = add_todo_item(user_mail, todo_content)
                    if todo_id:
                        # 產生建議回覆
                        suggested_replies = get_suggested_replies(
                            f"@add {todo_content}", user_mail
                        )

                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text=f"✅ 已新增待辦事項 #{todo_id}：{todo_content}",
                                suggested_actions=SuggestedActions(
                                    actions=suggested_replies
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
                            text="請在 @add 後面輸入待辦事項內容，例如：@add 明天開會",
                        )
                    )
                return

            # 處理列出待辦事項指令
            if user_message == "ls":
                pending_todos = get_user_pending_todos(user_mail)
                if pending_todos:
                    todos_text = f"📝 您有 {len(pending_todos)} 個待辦事項：\n\n"
                    for i, todo in enumerate(pending_todos, 1):
                        todos_text += f"{i}. #{todo['id']}: {todo['content']}\n"
                    todos_text += "\n回覆「@ok 編號」來標記完成事項"
                    suggested_replies = get_suggested_replies("@ls", user_mail)
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text=todos_text,
                            suggested_actions=SuggestedActions(
                                actions=suggested_replies
                            ),
                        )
                    )
                else:
                    # 添加建議回覆
                    suggested_actions = get_suggested_replies("無待辦事項", user_mail)

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

            # 處理標記完成指令
            if user_message == "ok":
                # 只輸入 @ok 沒有編號
                # 添加建議回覆
                suggested_actions = get_suggested_replies("@ok 提示", user_mail)

                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text="請輸入要完成的編號，例如：@ok 1 或 @ok 1,2,3",
                        suggested_actions=(
                            SuggestedActions(actions=suggested_actions)
                            if suggested_actions
                            else None
                        ),
                    )
                )
                return
            elif user_message.startswith("ok "):
                todo_ids_text = user_message[3:].strip()  # 移除 "ok " 前綴
                try:
                    # 解析編號，支援多個編號（用逗號或空格分隔）
                    todo_ids = []
                    for id_str in todo_ids_text.replace(",", " ").split():
                        if id_str.isdigit():
                            todo_ids.append(id_str)

                    if todo_ids:
                        completed_items = mark_todo_completed(user_mail, todo_ids)
                        if completed_items:
                            completed_text = "✅ 已標記完成：\n"
                            for item in completed_items:
                                completed_text += (
                                    f"• #{item['id']}: {item['content']}\n"
                                )

                            # 添加建議回覆
                            suggested_actions = get_suggested_replies(
                                "@ok 完成", user_mail
                            )

                            await turn_context.send_activity(
                                Activity(
                                    type=ActivityTypes.message,
                                    text=completed_text,
                                    suggested_actions=(
                                        SuggestedActions(actions=suggested_actions)
                                        if suggested_actions
                                        else None
                                    ),
                                )
                            )
                        else:
                            await turn_context.send_activity(
                                Activity(
                                    type=ActivityTypes.message,
                                    text="❌ 找不到指定的待辦事項編號",
                                )
                            )
                    else:
                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text="請輸入正確的編號，例如：@ok 1 或 @ok 1,2,3",
                            )
                        )
                except Exception as e:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message, text="❌ 處理完成指令時發生錯誤"
                        )
                    )
                return

            # 處理模型選擇指令
            if user_message == "model":
                # 檢查是否使用 Azure OpenAI
                if USE_AZURE_OPENAI:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="ℹ️ 目前使用 Azure OpenAI 服務\n📱 模型：o1-mini（固定）\n⚡ 此模式不支援模型切換",
                        )
                    )
                    return

                current_model = user_model_preferences.get(user_mail, OPENAI_MODEL)
                model_info = MODEL_INFO.get(
                    current_model, {"speed": "未知", "time": "未知", "use_case": "未知"}
                )

                # 創建 Adaptive Card
                model_card = {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"📱 AI 模型選擇",
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
                            ],
                        },
                    ],
                    "actions": [
                        {
                            "type": "Action.Submit",
                            "title": "✅ 確認選擇",
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
                        text="🤖 AI 模型選擇\n\n💡 **如何切換模型**：\n1️⃣ 輸入 `@model` 打開模型選擇卡片\n2️⃣ 從下拉選單選擇適合的模型\n3️⃣ 點選「✅ 確認選擇」完成切換\n\n📊 **預設模型**：gpt-5-mini（推理任務專用）",
                        attachments=[card_attachment],
                    )
                )
                return
            elif user_message.startswith("model "):
                # 直接切換模型：@model gpt-4o
                if USE_AZURE_OPENAI:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="ℹ️ Azure OpenAI 模式不支援模型切換\n📱 固定使用：o1-mini",
                        )
                    )
                    return

                model_name = user_message[6:].strip()
                if model_name in MODEL_INFO:
                    user_model_preferences[user_mail] = model_name
                    model_info = MODEL_INFO[model_name]
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text=f"✅ 已切換至 {model_name}\n⚡ 回應速度：{model_info['speed']}（{model_info['time']}）\n🎯 適用場景：{model_info['use_case']}",
                        )
                    )
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text=f"❌ 不支援的模型：{model_name}\n請使用 @model 查看可用模型",
                        )
                    )
                return

            # 處理清除所有待辦事項指令
            if user_message == "cls":
                pending_todos = get_user_pending_todos(user_mail)
                if len(pending_todos) > 0:
                    # 清除該用戶的所有待辦事項
                    if user_mail in user_todos:
                        cleared_count = len(user_todos[user_mail])
                        user_todos[user_mail].clear()
                        # 添加建議回覆
                        suggested_actions = get_suggested_replies("清除完成", user_mail)

                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text=f"🗑️ 已清除 {cleared_count} 個待辦事項",
                                suggested_actions=(
                                    SuggestedActions(actions=suggested_actions)
                                    if suggested_actions
                                    else None
                                ),
                            )
                        )
                    else:
                        # 添加建議回覆
                        suggested_actions = get_suggested_replies(
                            "無待辦事項", user_mail
                        )

                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text="🎉 目前沒有待辦事項需要清除",
                                suggested_actions=(
                                    SuggestedActions(actions=suggested_actions)
                                    if suggested_actions
                                    else None
                                ),
                            )
                        )
                else:
                    # 添加建議回覆
                    suggested_actions = get_suggested_replies("無待辦事項", user_mail)

                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="🎉 目前沒有待辦事項需要清除",
                            suggested_actions=(
                                SuggestedActions(actions=suggested_actions)
                                if suggested_actions
                                else None
                            ),
                        )
                    )
                return

            # 原有的會議室預約邏輯保持不變...
            # （這裡省略所有會議室相關的處理邏輯，保持原樣）

        else:
            attachments = turn_context.activity.attachments
            if turn_context.activity.text:

                if turn_context.activity.text.lower() == "/who":
                    await turn_context.send_activity(
                        Activity(type=ActivityTypes.message, text=user_mail)
                    )
                    await show_self_info(turn_context, user_mail)
                    return

                if turn_context.activity.text.lower() == "/help":
                    await show_help_options(turn_context)
                    return

                # 更新狀態查詢指令
                if turn_context.activity.text.lower() == "/status":
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
            elif attachments and len(attachments) > 0:
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


# === 原有的會議室相關函數保持不變 ===
# （這裡省略所有會議室相關函數，實際使用時需要完整保留）


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


async def show_self_info(turn_context: TurnContext, user_mail: str):
    """取得user資訊"""
    await turn_context.send_activity(
        Activity(type=ActivityTypes.message, text=f"測試用戶: {user_mail}")
    )


async def show_help_options(turn_context: TurnContext, welcomeMsg: str = None):
    suggested_actions = SuggestedActions(
        actions=[
            CardAction(
                title="@會議室預約", type=ActionTypes.im_back, text="@會議室預約"
            )
        ]
    )

    display_text = (
        f"{welcomeMsg}\n或者請選擇以下選項:" if welcomeMsg else "請選擇以下選項:"
    )

    reply = Activity(
        type=ActivityTypes.message,
        text=display_text,
        suggested_actions=suggested_actions,
    )

    await turn_context.send_activity(reply)


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
