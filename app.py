from datetime import datetime, timedelta
from typing import List, Dict

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
import openai
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
import sys
import logging

logging.basicConfig(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
# gpt token數
max_tokens = 2000
# 初始化 Token 管理器和 Graph API
token_manager = TokenManager(
    tenant_id=os.getenv("TENANT_ID"),
    client_id=os.getenv("CLIENT_ID"),
    client_secret=os.getenv("CLIENT_SECRET"),
)
graph_api = GraphAPI(token_manager)

# 載入環境變數
load_dotenv()

# Flask 應用設定
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 限制最大 16MB

appId = os.getenv("BOT_APP_ID")
appPwd = os.getenv("BOT_APP_PASSWORD")
settings = BotFrameworkAdapterSettings(appId, appPwd)
adapter = BotFrameworkAdapter(settings)

# 用於儲存會話歷史的字典
conversation_history = {}

# 初始化 Azure OpenAI
openai.api_type = "azure"
openai.api_key = os.getenv("AZURE_OPENAI_KEY")
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
openai.api_version = "2024-02-15-preview"


def sanitize_url(url):
    # 分解URL為基礎部分和路徑部分
    base = "https://rinnaitw-my.sharepoint.com"
    path = url.replace(base, "")

    # 對路徑部分進行編碼,但保留斜線
    encoded_path = "/".join(quote(segment) for segment in path.split("/"))

    # 重新組合URL
    sanitized_url = urljoin(base, encoded_path)

    return sanitized_url


async def download_attachment_and_write(attachment: Attachment) -> dict:
    """下載並儲存附件"""
    try:
        url = ""
        if isinstance(attachment.content, dict) and "downloadUrl" in attachment.content:
            url = attachment.content["downloadUrl"]

        # safeUrl = sanitize_url(attachment.content_url)
        print(f"attachment.downloadUrl: {url}")
        response = urllib.request.urlopen(url)
        headers = response.info()

        if headers["content-type"] == "application/json":
            data = bytes(json.load(response)["data"])
        else:
            data = response.read()

        # 將檔案保存在臨時目錄
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
        # print(f"下載附件時發生錯誤: {str(e)}")
        print(f"Downloading File Has Some Error: {str(e)}")
        return {}


async def process_file(file_info: dict) -> str:
    """處理不同類型的檔案"""
    try:
        content = io.BytesIO(file_info["data"])
        content_type = file_info["content_type"]

        if "pdf" in content_type.lower():
            reader = PdfReader(content)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return f"PDF 內容：\n{text}"

        elif "spreadsheet" in content_type.lower() or "excel" in content_type.lower():
            df = pd.read_excel(content)
            return f"Excel 內容：\n{df.to_string()}"

        elif "word" in content_type.lower() or "document" in content_type.lower():
            doc = Document(content)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return f"Word 內容：\n{text}"

        elif "text" in content_type.lower():
            return f"文字檔內容：\n{content.read().decode('utf-8')}"

        elif "image" in content_type.lower():
            image = Image.open(content)
            return f"圖片資訊：{image.format} 格式，大小 {image.size}"

        else:
            return f"不支援的檔案類型：{content_type}"

    except Exception as e:
        return f"處理檔案時發生錯誤：{str(e)}"


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


async def show_meetingroom_options(turn_context: TurnContext):
    suggested_actions = SuggestedActions(
        actions=[
            CardAction(
                title="@第一會議室", type=ActionTypes.im_back, text="@第一會議室"
            ),
            CardAction(
                title="@第二會議室", type=ActionTypes.im_back, text="@第二會議室"
            ),
            CardAction(
                title="@返回主選單", type=ActionTypes.im_back, text="@返回主選單"
            ),
        ]
    )
    await turn_context.send_activity(
        Activity(
            type=ActivityTypes.message,
            text="請選擇會議室:",
            suggested_actions=suggested_actions,
        )
    )


async def show_date_options(turn_context: TurnContext, room_id: str):
    from datetime import datetime, timedelta

    # 取得今天和明天的日期
    today = datetime.now()
    tomorrow = today + timedelta(days=1)

    # 取得會議室名稱
    room_name = get_localtion_by_email(room_id)

    suggested_actions = SuggestedActions(
        actions=[
            CardAction(
                title=f"@{room_name} {today.strftime('%m/%d')} 今天",
                type=ActionTypes.im_back,
                text=f"@{room_name} {today.strftime('%m/%d')} 今天",
            ),
            CardAction(
                title=f"@{room_name} {tomorrow.strftime('%m/%d')} 明天",
                type=ActionTypes.im_back,
                text=f"@{room_name} {tomorrow.strftime('%m/%d')} 明天",
            ),
            CardAction(
                title="@返回會議室選擇", type=ActionTypes.im_back, text="@返回主選單"
            ),
        ]
    )
    await turn_context.send_activity(
        Activity(
            type=ActivityTypes.message,
            text=f"請選擇{room_name}的預約日期:",
            suggested_actions=suggested_actions,
        )
    )


async def get_current_bookings(room_id: str, date: str) -> List[Dict]:
    """獲取會議室當前預約狀態
    取得指定會議室在特定日期的所有預約資訊
    包含預約時間、主題和預約人資訊
    """
    try:
        # 將日期字串轉換成 datetime
        if date == "today":
            target_date = datetime.now()
        elif date == "tomorrow":
            target_date = datetime.now() + timedelta(days=1)
        else:
            target_date = datetime.strptime(date, "%Y-%m-%d")

        # 設定查詢時間範圍
        start_time = target_date.replace(hour=8, minute=0)  # 上班時間 8:00
        end_time = target_date.replace(hour=17, minute=0)  # 下班時間 17:00

        # 取得會議室 email
        room_email = get_room_email(room_id)

        # 使用 await 等待 API 回應
        schedule_data = await graph_api.get_room_schedule(
            room_email=room_email, start_time=start_time, end_time=end_time
        )

        # 整理預約資訊
        bookings = []
        if "value" in schedule_data and schedule_data["value"]:
            schedule_info = schedule_data["value"][0]
            if "scheduleItems" in schedule_info:
                for item in schedule_info["scheduleItems"]:
                    # 處理時間格式
                    start_str = item["start"]["dateTime"].split(".")[0]
                    end_str = item["end"]["dateTime"].split(".")[0]

                    start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S")
                    end_time = datetime.strptime(end_str, "%Y-%m-%dT%H:%M:%S")

                    # UTC+8
                    start_time = start_time + timedelta(hours=8)
                    end_time = end_time + timedelta(hours=8)

                    booking = {
                        "start": start_time.strftime("%H:%M"),
                        "end": end_time.strftime("%H:%M"),
                        "subject": item["subject"],
                        "organizer": item.get("organizer", {})
                        .get("emailAddress", {})
                        .get("name", "未知"),
                    }
                    bookings.append(booking)

        return sorted(bookings, key=lambda x: x["start"])

    except Exception as e:
        print(f"獲取會議室預約狀況時發生錯誤: {str(e)}")
        return []


def get_room_email(room_id: str) -> str:
    """取得會議室電子郵件
    根據會議室 ID 或電子郵件地址返回對應的會議室電子郵件
    支援 ID 到 email 的轉換和直接 email 的驗證
    """
    room_mapping = {
        "1": "meetingroom01@rinnai.com.tw",
        "2": "meetingroom02@rinnai.com.tw",
    }

    # 如果包含 @ 符號，表示已經是 email
    if "@" in room_id:
        return room_id

    # 否則視為 ID，從 mapping 取得對應的 email
    return room_mapping.get(room_id)


def get_localtion_by_email(room_id: str) -> str:
    """取得會議室位置名稱
    根據會議室 ID 或電子郵件地址返回對應的會議室名稱
    例如：'第一會議室'、'第二會議室'
    """
    location_mapping = {
        "meetingroom01@rinnai.com.tw": "第一會議室",
        "meetingroom02@rinnai.com.tw": "第二會議室",
    }

    # 如果輸入是 email
    if "@" in room_id:
        return location_mapping.get(room_id)

    # 如果輸入是 ID，先轉換成 email
    email = get_room_email(room_id)
    return location_mapping.get(email) if email else None


async def show_available_slots(turn_context: TurnContext, room_id: str, date: str):
    """顯示可用時段
    列出指定日期的所有可用時段
    合併顯示現有的預約狀況和可預約時段
    """
    # 取得會議室名稱和 email
    room_email = get_room_email(room_id)
    room_name = get_localtion_by_email(room_id)

    # 設定查詢時間範圍（例如 8:00-17:00）
    if date == "today":
        base_date = datetime.now()
        date_display = "今天"
    elif date == "tomorrow":
        base_date = datetime.now() + timedelta(days=1)
        date_display = "明天"
    else:
        base_date = datetime.strptime(date, "%Y-%m-%d")
        date_display = base_date.strftime("%m/%d")

    start_time = base_date.replace(hour=8, minute=0, second=0, microsecond=0)
    end_time = base_date.replace(hour=17, minute=0, second=0, microsecond=0)

    # 從 Graph API 獲取會議室排程
    schedule_data = await graph_api.get_room_schedule(room_email, start_time, end_time)

    # 處理回傳的資料，找出可用時段
    available_slots = process_schedule_data(schedule_data)

    # 顯示當前預約狀況
    bookings = await get_current_bookings(room_email, date)

    # 格式化預約狀況文字
    schedule_text = f"{room_name} {date_display} 預約狀況：\n\n"
    if bookings:
        for booking in bookings:
            schedule_text += (
                f"• {booking['start']} - {booking['end']}: {booking['subject']}\n\n"
            )
    else:
        schedule_text += "目前尚無預約\n"

    schedule_text += (
        "\n\n(若希望時段未出現，\n\n可輸入ex.@第一會議室 今天 15:30 - 16:00 預約)"
    )
    # 匯總所有可用時段
    # slots_text = "\n可預約時段：\n" + "\n".join(
    #     [f"• {slot['start']} - {slot['end']} 可預約" for slot in available_slots]
    # )

    # 組合完整消息
    full_message = f"{schedule_text}"

    # 創建包含所有選項的 SuggestedActions
    suggested_actions = SuggestedActions(
        actions=[
            CardAction(
                title="@返回會議室選擇", type=ActionTypes.im_back, text="@返回主選單"
            )
        ]
        + [
            CardAction(
                title=f"@{room_name} {date_display} {slot['start']} - {slot['end']} 預約",
                type=ActionTypes.im_back,
                text=f"@{room_name} {date_display} {slot['start']} - {slot['end']} 預約",
            )
            for slot in available_slots
        ]
    )

    await turn_context.send_activity(
        Activity(
            type=ActivityTypes.message,
            text=full_message,
            suggested_actions=suggested_actions,
        )
    )


# async def show_available_slots(turn_context: TurnContext, room_id: str, date: str):
#     """顯示可用時段
#     列出指定日期的所有可用時段
#     同時顯示現有的預約狀況
#     """
#     # 取得會議室名稱和 email
#     room_email = get_room_email(room_id)
#     room_name = get_localtion_by_email(room_id)

#     # 設定查詢時間範圍（例如 8:00-17:00）
#     if date == "today":
#         base_date = datetime.now()
#         date_display = "今天"
#     elif date == "tomorrow":
#         base_date = datetime.now() + timedelta(days=1)
#         date_display = "明天"
#     else:
#         base_date = datetime.strptime(date, "%Y-%m-%d")
#         date_display = base_date.strftime("%m/%d")

#     start_time = base_date.replace(hour=8, minute=0, second=0, microsecond=0)
#     end_time = base_date.replace(hour=17, minute=0, second=0, microsecond=0)

#     # 從 Graph API 獲取會議室排程
#     schedule_data = await graph_api.get_room_schedule(room_email, start_time, end_time)

#     # 處理回傳的資料，找出可用時段
#     available_slots = process_schedule_data(schedule_data)

#     actions = [
#         CardAction(
#             title="@返回會議室選擇", type=ActionTypes.im_back, text="@返回主選單"
#         )
#     ]

#     # 根據可用時段建立選項
#     for slot in available_slots:
#         actions.append(
#             CardAction(
#                 title=f"@{room_name} {date_display} {slot['start']} - {slot['end']} 預約",
#                 type=ActionTypes.im_back,
#                 text=f"@{room_name} {date_display} {slot['start']} - {slot['end']} 預約",
#             ),
#         )

#     suggested_actions = SuggestedActions(actions=actions)

#     # 顯示當前預約狀況
#     schedule_text = f"{room_name} {date_display} 預約狀況：\n\n"
#     bookings = await get_current_bookings(room_email, date)

#     if bookings:
#         for booking in bookings:
#             schedule_text += (
#                 f"• {booking['start']} - {booking['end']}: {booking['subject']}\n\n"
#             )
#     else:
#         schedule_text += "目前尚無預約\n\n"

#     await turn_context.send_activity(
#         Activity(
#             type=ActivityTypes.message,
#             text=f"{schedule_text}請選擇預約時段:",
#             suggested_actions=suggested_actions,
#         )
#     )


# def process_schedule_data(schedule_data: Dict[str, Any]) -> List[Dict[str, str]]:
#     """處理會議室排程資料
#     分析會議室排程資料，找出可用的時段
#     排除已被預約的時間，返回可預約的時段列表
#     """
#     available_slots = []

#     # 工作時間從 8:00 到 17:00，每小時一個時段
#     work_hours = [
#         ("08:00", "08:30"),
#         ("08:30", "09:00"),
#         ("09:00", "09:30"),
#         ("09:30", "10:00"),
#         ("10:00", "10:30"),
#         ("10:30", "11:00"),
#         ("11:00", "11:30"),
#         ("11:30", "12:00"),
#         ("13:00", "13:30"),
#         ("13:30", "14:00"),
#         ("14:00", "14:30"),
#         ("14:30", "15:00"),
#         ("15:00", "15:30"),
#         ("15:30", "16:00"),
#         ("16:00", "16:30"),
#         ("16:30", "17:00"),
#     ]

#     # 從回應中取得已預約的時段
#     booked_slots = []
#     if "value" in schedule_data and schedule_data["value"]:
#         schedule_info = schedule_data["value"][0]
#         if "scheduleItems" in schedule_info:
#             for item in schedule_info["scheduleItems"]:
#                 # 修改時間解析方式
#                 start_str = item["start"]["dateTime"].split(".")[0]  # 移除毫秒部分
#                 end_str = item["end"]["dateTime"].split(".")[0]  # 移除毫秒部分

#                 start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S")
#                 end_time = datetime.strptime(end_str, "%Y-%m-%dT%H:%M:%S")

#                 # UTC+8
#                 start_time = start_time + timedelta(hours=8)
#                 end_time = end_time + timedelta(hours=8)

#                 booked_slots.append(
#                     {
#                         "start": start_time.strftime("%H:%M"),
#                         "end": end_time.strftime("%H:%M"),
#                         "subject": item["subject"],
#                     }
#                 )

#     # 尋找可用時段（排除已預約的時段）
#     for start, end in work_hours:
#         is_available = True
#         for booked in booked_slots:
#             # 檢查是否與已預約時段重疊
#             if (
#                 (start >= booked["start"] and start < booked["end"])
#                 or (end > booked["start"] and end <= booked["end"])
#                 or (start <= booked["start"] and end >= booked["end"])
#             ):
#                 is_available = False
#                 break

#         if is_available:
#             available_slots.append({"start": start, "end": end})

#     return available_slots


def process_schedule_data(schedule_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """處理會議室排程資料
    分析會議室排程資料，找出可用的時段
    排除已被預約的時間和已經過去的時段
    返回可預約的時段列表
    """
    available_slots = []

    # 獲取當前台灣時間
    current_time = datetime.now()
    current_hour = current_time.hour
    current_minute = current_time.minute

    # 生成當天的時段列表
    work_hours = [
        ("08:00", "08:30"),
        ("08:30", "09:00"),
        ("09:00", "09:30"),
        ("09:30", "10:00"),
        ("10:00", "10:30"),
        ("10:30", "11:00"),
        ("11:00", "11:30"),
        ("11:30", "12:00"),
        ("13:00", "13:30"),
        ("13:30", "14:00"),
        ("14:00", "14:30"),
        ("14:30", "15:00"),
        ("15:00", "15:30"),
        ("15:30", "16:00"),
        ("16:00", "16:30"),
        ("16:30", "17:00"),
    ]

    # 從回應中取得已預約的時段
    booked_slots = []
    if "value" in schedule_data and schedule_data["value"]:
        schedule_info = schedule_data["value"][0]
        if "scheduleItems" in schedule_info:
            for item in schedule_info["scheduleItems"]:
                start_str = item["start"]["dateTime"].split(".")[0]
                end_str = item["end"]["dateTime"].split(".")[0]

                start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S")
                end_time = datetime.strptime(end_str, "%Y-%m-%dT%H:%M:%S")

                # UTC+8
                start_time = start_time + timedelta(hours=8)
                end_time = end_time + timedelta(hours=8)

                booked_slots.append(
                    {
                        "start": start_time.strftime("%H:%M"),
                        "end": end_time.strftime("%H:%M"),
                        "subject": item["subject"],
                    }
                )

    # 尋找可用時段（排除已預約的時段和已經過去的時段）
    for start, end in work_hours:
        # 將時段轉換為小時和分鐘以便比較
        start_hour, start_minute = map(int, start.split(":"))

        # 檢查時段是否已經過去
        if current_hour > start_hour or (
            current_hour == start_hour and current_minute >= start_minute
        ):
            continue

        is_available = True
        for booked in booked_slots:
            # 檢查是否與已預約時段重疊
            if (
                (start >= booked["start"] and start < booked["end"])
                or (end > booked["start"] and end <= booked["end"])
                or (start <= booked["start"] and end >= booked["end"])
            ):
                is_available = False
                break

        if is_available:
            available_slots.append({"start": start, "end": end})

    return available_slots


# 在代碼頂部定義日籍主管的郵件列表
JAPANESE_MANAGER_EMAILS = [
    "tsutsumi@rinnai.com.tw",
    "ushimaru@rinnai.com.tw",
    "daiki.matsunami@rinnai.com.tw",
]


# 判斷語言的邏輯
def determine_language(user_mail: str):
    if user_mail is None:
        return "zh-TW"
    user_mail = user_mail.lower()
    # 檢查是否在日籍主管郵件列表中
    if user_mail in JAPANESE_MANAGER_EMAILS:
        return "ja"

    # 其他預設繁體中文
    return "zh-TW"


async def call_openai(prompt, conversation_id, user_mail=None):
    """呼叫 OpenAI API
    處理用戶的一般對話請求
    維護對話歷史記錄
    """
    global conversation_history

    if conversation_id not in conversation_history:
        conversation_history[conversation_id] = []

        language = determine_language(user_mail)

        # 設定系統提示詞
        system_prompts = {
            "zh-TW": "你是一個智能助理。如果用戶使用中文提問，請用繁體中文回答。如果用戶使用其他語言提問，請使用跟用戶相同的語言回答。",
            "ja": "あなたは知的アシスタントです。ユーザーが中国語で質問した場合は、繁体字中国語で回答してください。ユーザーが他の言語で質問した場合は、ユーザーと同じ言語で回答してください。",
        }

        system_prompt = system_prompts.get(language, system_prompts["zh-TW"])

        conversation_history[conversation_id].append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )

    conversation_history[conversation_id].append(
        {"role": "user", "content": str(prompt)}
    )

    try:
        response = openai.ChatCompletion.create(
            engine="gpt-4o-mini-deploy",
            messages=conversation_history[conversation_id],
            max_tokens=max_tokens,
            timeout=15,
        )
        message = response["choices"][0]["message"]
        conversation_history[conversation_id].append(message)
        return message["content"]
    except Exception as e:
        print(f"OpenAI API 錯誤: {str(e)}")
        return "抱歉，目前無法處理您的請求。"


async def summarize_text(text, conversation_id, user_mail=None) -> str:
    """文本摘要處理
    使用 OpenAI 對文本內容進行摘要
    用於處理文件內容的摘要
    """
    try:

        language = determine_language(user_mail)

        # 設定系統提示詞
        system_prompts = {
            "zh-TW": "你是一個智能助理，負責摘要文本內容。",
            "ja": "あなたはインテリジェントアシスタントであり、テキスト内容を要約する役割を担っています。",
        }

        system_prompt = system_prompts.get(language, system_prompts["zh-TW"])

        response = openai.ChatCompletion.create(
            engine="gpt-4o-mini-deploy",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=max_tokens,
        )
        message = response["choices"][0]["message"]
        conversation_history[conversation_id].append(message)
        return message["content"]
    except Exception as e:
        return f"摘要處理時發生錯誤：{str(e)}"


async def welcome_user(turn_context: TurnContext):
    """歡迎使用者
    當新使用者加入對話時顯示歡迎訊息
    介紹機器人的主要功能
    """
    user_name = turn_context.activity.from_property.name

    try:
        user_mail = await get_user_email(turn_context)
    except Exception as e:
        print(f"取得用戶 email 時發生錯誤: {str(e)}")

    language = determine_language(user_mail)

    # 設定系統提示詞
    system_prompts = {
        "zh-TW": f"""
歡迎 {user_name} 使用 TR GPT！

我可以協助您：
- 回答各種問題
- 文件分析與摘要
- 多語言翻譯
- 智能建議與諮詢
有什麼我可以幫您的嗎？

(提示：輸入 /help 可快速查看系統功能)""",
        "ja": f"""
{user_name} さん、TR GPT インテリジェントアシスタントへようこそ！
お手伝いできること：
- あらゆる質問への対応
- 文書分析とサマリー
- 多言語翻訳
- インテリジェントな提案とアドバイス
何かお力になれることはありますか？

(ヒント：/help と入力すると、システム機能を quickly 確認できます)
            """,
    }

    system_prompt = system_prompts.get(language, system_prompts["zh-TW"])

    welcome_text = system_prompt
    await show_help_options(turn_context, welcome_text)
    # await turn_context.send_activity(Activity(type="message", text=welcome_text))


async def get_user_email(turn_context: TurnContext) -> str:
    """查詢目前user mail"""
    try:
        # 檢查是否有 aad_object_id
        aad_object_id = turn_context.activity.from_property.aad_object_id

        if not aad_object_id:
            print("No AAD Object ID found")
            return None

        # 使用 Graph API 獲取用戶信息
        user_info = await graph_api.get_user_info(aad_object_id)

        # 返回郵件地址
        return user_info.get("mail")

    except Exception as e:
        print(f"取得用戶 email 時發生錯誤: {str(e)}")
        return None


async def message_handler(turn_context: TurnContext):
    try:
        user_id = turn_context.activity.from_property.id
        user_name = turn_context.activity.from_property.name
        user_mail = await get_user_email(turn_context) or f"{user_id}@unknown.com"

        print(f"Current User Info: {user_name} (ID: {user_id}) (Mail: {user_mail})")
        print(f"Full activity: {turn_context.activity}")

        try:
            # 確保保存 JSON 的目錄存在
            log_dir = "./json_logs"
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            # 轉換 turn_context 為字典
            context_dict = {
                "activity": turn_context.activity.as_dict(),
                "userinfo": {
                    "id": turn_context.activity.from_property.id,
                    "name": turn_context.activity.from_property.name,
                    "aadObjectId": getattr(
                        turn_context.activity.from_property, "aad_object_id", None
                    ),
                },
                "user_name": user_name,
            }

            # 保存到 json_log.json
            log_file_path = os.path.join(log_dir, "json_log.json")
            with open(log_file_path, "a", encoding="utf-8") as f:
                json.dump(context_dict, f, ensure_ascii=False, indent=4)
                f.write("\n")  # 每次寫入一條日誌後換行
        except Exception as e:
            print(f"Write Json Log Has Some Error: {str(e)}")

        if turn_context.activity.text and turn_context.activity.text.startswith("@"):
            # 移除 @ 前綴進行判斷
            user_message = turn_context.activity.text.lstrip("@")

            # 返回會議室選擇
            if user_message.lower() == "返回會議室選擇":
                await show_meetingroom_options(turn_context)
                return

            # 返回主選單
            if user_message.lower() == "返回主選單":
                await show_help_options(turn_context)
                return

            # 會議室預約流程
            elif user_message == "會議室預約":
                await show_meetingroom_options(turn_context)
                return

            # 會議室選擇
            elif user_message == "第一會議室":
                await show_date_options(turn_context, "1")
                return

            elif user_message == "第二會議室":
                await show_date_options(turn_context, "2")
                return

            # 時段預約邏輯
            elif " 預約" in user_message:
                # 解析預約信息
                parts = user_message.lstrip("@").split()
                room_name = parts[0]
                date_str = parts[1]
                time_slot = f"{parts[2]} - {parts[4]}"

                # 確定房間 ID
                room_id = "1" if room_name == "第一會議室" else "2"

                # 確定日期
                if date_str == "今天":
                    date = "today"
                elif date_str == "明天":
                    date = "tomorrow"
                else:
                    # 如果是具體日期，可能需要額外處理
                    date = datetime.strptime(date_str, "%m/%d").strftime("%Y-%m-%d")

                # 假設需要彈出確認視窗或直接處理預約
                if await is_slot_available(
                    room_id, date, time_slot.split(" - ")[0], time_slot.split(" - ")[1]
                ):
                    # 嘗試預約
                    user_mail = (
                        await get_user_email(turn_context) or f"{user_id}@unknown.com"
                    )
                    booking_result = await create_meeting(
                        room_id=room_id,
                        date=date,
                        start_time=time_slot.split(" - ")[0],
                        end_time=time_slot.split(" - ")[1],
                        user_name=user_name,
                        user_mail=user_mail,
                    )

                    if booking_result:
                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text=f"預約成功！已為您預約{room_name}{date_str}{time_slot}",
                            )
                        )
                    else:
                        await turn_context.send_activity(
                            Activity(
                                type=ActivityTypes.message,
                                text="預約失敗，請稍後再試。",
                            )
                        )
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="此時段已被預約，請選擇其他時段。",
                        )
                    )
                return

            # 日期選擇
            elif " 今天" in user_message or " 明天" in user_message:
                # 解析房間和日期
                parts = user_message.split()
                room_name = parts[0]
                date_type = parts[2]

                # 根據會議室名稱找對應的 room_id
                room_id = "1" if room_name == "第一會議室" else "2"

                date = "today" if date_type == "今天" else "tomorrow"
                await show_available_slots(turn_context, room_id, date)
                return

            # 主選單
            elif user_message == "返回主選單":
                await show_help_options(turn_context)
                return
        # 如果不是以 @ 開頭，則使用 OpenAI 處理
        else:
            # 附件
            attachments = turn_context.activity.attachments
            if turn_context.activity.text:
                if turn_context.activity.text.lower() == "/help":
                    await show_help_options(turn_context)
                    return
                user_mail = (
                    await get_user_email(turn_context) or f"{user_id}@unknown.com"
                )
                response_message = await call_openai(
                    turn_context.activity.text,
                    turn_context.activity.conversation.id,
                    user_mail=user_mail,
                )
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=response_message)
                )
            elif attachments and len(attachments) > 0:
                print("Current Request Is An File")
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=f"檔案分析功能開發中",
                    )
                )
                # user_mail = (
                #     await get_user_email(turn_context) or f"{user_id}@unknown.com"
                # )
                # for attachment in turn_context.activity.attachments:
                #     file_info = await download_attachment_and_write(attachment)
                #     if file_info:
                #         file_text = await process_file(file_info)
                #         summarized_text = await summarize_text(
                #             file_text,
                #             turn_context.activity.conversation.id,
                #             user_mail=user_mail,
                #         )
                #         await turn_context.send_activity(
                #             Activity(type=ActivityTypes.message, text=summarized_text)
                #         )
    except Exception as e:
        print(f"處理訊息時發生錯誤: {str(e)}")
        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=f"處理訊息時發生錯誤，請稍後再試。 {str(e)}",
            )
        )


async def is_slot_available(
    room_id: str, date: str, start_time: str, end_time: str
) -> bool:
    """檢查會議室時段可用性
    確認指定的時間區間是否可以預約
    檢查是否與現有預約時段重疊
    """

    try:
        # 處理日期
        if date == "today":
            base_date = datetime.now()
        elif date == "tomorrow":
            base_date = datetime.now() + timedelta(days=1)
        else:
            base_date = datetime.strptime(date, "%Y-%m-%d")

        # 組合日期和時間
        start_datetime = datetime.combine(
            base_date.date(), datetime.strptime(start_time, "%H:%M").time()
        )
        end_datetime = datetime.combine(
            base_date.date(), datetime.strptime(end_time, "%H:%M").time()
        )

        # 取得會議室排程
        schedule = await graph_api.get_room_schedule(
            room_email=get_room_email(room_id),
            start_time=start_datetime,
            end_time=end_datetime,
        )

        # 檢查時段衝突
        if "value" in schedule and schedule["value"]:
            schedule_info = schedule["value"][0]
            if "scheduleItems" in schedule_info:
                for booking in schedule_info["scheduleItems"]:
                    booking_start = datetime.fromisoformat(
                        booking["start"]["dateTime"].replace("Z", "+00:00")
                    )
                    booking_end = datetime.fromisoformat(
                        booking["end"]["dateTime"].replace("Z", "+00:00")
                    )

                    # UTC+8
                    booking_start = booking_start + timedelta(hours=8)
                    booking_end = booking_end + timedelta(hours=8)

                    if (
                        (
                            start_datetime >= booking_start
                            and start_datetime < booking_end
                        )
                        or (
                            end_datetime > booking_start and end_datetime <= booking_end
                        )
                        or (
                            start_datetime <= booking_start
                            and end_datetime >= booking_end
                        )
                    ):
                        return False

        return True

    except Exception as e:
        print(f"檢查時段可用性時發生錯誤: {str(e)}")
        return False


async def create_meeting(
    room_id: str,
    date: str,
    start_time: str,
    end_time: str,
    user_name: str,
    user_mail: str,
):
    """建立會議預約
    在指定的會議室建立新的會議預約
    設定會議主題、時間和與會者
    """
    try:
        # 取得user email
        room_email = get_room_email(room_id)
        # user_emal = "juncheng.liu@rinnai.com.tw"
        location = get_localtion_by_email(room_id)

        start_datetime = convert_to_datetime(date, start_time)
        end_datetime = convert_to_datetime(date, end_time)

        # 建立會議
        result = await graph_api.create_meeting(  # 加上 await
            location=location,  # 修正拼寫 localtion -> location
            room_email=room_email,
            subject=f"{user_name} 的會議(gpt)",
            start_time=start_datetime,
            end_time=end_datetime,
            attendees=[user_mail],
        )

        return True if result else False

    except Exception as e:
        print(f"建立會議時發生錯誤: {str(e)}")
        return False


def convert_to_datetime(date: str, time: str) -> datetime:
    """轉換日期和時間字串為 datetime 物件"""
    if date == "today":
        base_date = datetime.now()
    elif date == "tomorrow":
        base_date = datetime.now() + timedelta(days=1)
    else:
        base_date = datetime.strptime(date, "%Y-%m-%d")

    time_parts = time.split(":")
    return base_date.replace(
        hour=int(time_parts[0]), minute=int(time_parts[1]), second=0, microsecond=0
    )


@app.route("/ping", methods=["GET"])
def ping():
    debuggerTest = os.getenv("debugInfo")
    return jsonify(
        {"status": "ok", "message": "Bot is alive", "debuggerTest": debuggerTest}
    )  # 使用 jsonify


@app.route("/user/<user_id>", methods=["GET"])
def user(user_id):
    """
    用戶資訊 API

    參數:
    - user_id: 用戶 ID (必填)
    """
    try:
        # 執行異步操作
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        user_info = loop.run_until_complete(graph_api.get_user_info(user_id))
        loop.close()

        return jsonify(
            {
                "status": "ok",
                "user_info": user_info,
            }
        )
    except Exception as e:
        print(f"獲取用戶資訊時發生錯誤: {str(e)}")
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@app.route("/api/room/schedule/<room_id>", methods=["GET"])
def get_room_schedule_api(room_id):
    """
    查詢會議室排程 API

    參數:
    - room_id: 會議室 ID (必填)
    - date: 日期 (選填，格式：YYYY-MM-DD，預設今天)
    """
    try:
        # 取得日期參數，如果沒有就用今天
        date_str = request.args.get("date")
        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                return (
                    jsonify(
                        {
                            "error": "Invalid date format",
                            "message": "日期格式應為 YYYY-MM-DD",
                        }
                    ),
                    400,
                )
        else:
            target_date = datetime.now()

        # 設定時間範圍 (8:00-17:00)
        start_datetime = target_date.replace(hour=8, minute=0, second=0, microsecond=0)
        end_datetime = target_date.replace(hour=17, minute=0, second=0, microsecond=0)

        # 取得會議室 email
        room_email = get_room_email(room_id)
        if not room_email:
            return (
                jsonify(
                    {"error": "Invalid room ID", "message": f"找不到會議室: {room_id}"}
                ),
                400,
            )

        # 執行異步查詢
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        schedule_data = loop.run_until_complete(
            graph_api.get_room_schedule(
                room_email=room_email, start_time=start_datetime, end_time=end_datetime
            )
        )
        loop.close()

        # 處理排程資料
        bookings = []
        if "value" in schedule_data and schedule_data["value"]:
            schedule_info = schedule_data["value"][0]
            if "scheduleItems" in schedule_info:
                for item in schedule_info["scheduleItems"]:
                    start_str = item["start"]["dateTime"].split(".")[0]
                    end_str = item["end"]["dateTime"].split(".")[0]

                    start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S")
                    end_time = datetime.strptime(end_str, "%Y-%m-%dT%H:%M:%S")

                    # UTC+8
                    start_time = start_time + timedelta(hours=8)
                    end_time = end_time + timedelta(hours=8)

                    bookings.append(
                        {
                            "start": start_time.strftime("%H:%M"),
                            "end": end_time.strftime("%H:%M"),
                            "subject": item["subject"],
                            "organizer": item.get("organizer", {})
                            .get("emailAddress", {})
                            .get("name", "未知"),
                        }
                    )

        return jsonify(
            {
                "room_id": room_id,
                "room_email": room_email,
                "date": target_date.strftime("%Y-%m-%d"),
                "bookings": sorted(bookings, key=lambda x: x["start"]),
                "working_hours": {"start": "08:00", "end": "17:00"},
            }
        )

    except Exception as e:
        print(f"獲取會議室排程時發生錯誤: {str(e)}")
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@app.route("/api/messages", methods=["POST"])
def messages():
    """訊息路由處理
    處理所有進入的 HTTP 請求
    將請求轉發給適當的處理函數
    """
    print("=== 開始處理訊息 ===")
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
        print(f"請求內容: {json.dumps(body, ensure_ascii=False, indent=2)}")
    else:
        return {"status": 415}

    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

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
        task = adapter.process_activity(activity, auth_header, aux_func)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(task)
        loop.close()
    except Exception as e:
        print(f"Error processing message: {str(e)}")
        return {"status": 401}

    print("=== 訊息處理完成 ===")
    return {"status": 200}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
