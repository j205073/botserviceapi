from flask import Flask, request, jsonify
from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity
import os
import openai
import asyncio
from dotenv import load_dotenv

import io
import pandas as pd
from docx import Document
from PyPDF2 import PdfReader
from PIL import Image
from openpyxl import load_workbook

# 載入環境變數
load_dotenv()

# Flask 應用設定
app = Flask(__name__)

appId = os.getenv("BOT_APP_ID")
appPwd = os.getenv("BOT_APP_PASSWORD")
# BotAdapter 設定
settings = BotFrameworkAdapterSettings(appId, appPwd)
adapter = BotFrameworkAdapter(settings)

# 用於儲存會話歷史的字典
conversation_history = {}

# b1 = os.getenv("BOT_APP_ID")
# b2 = os.getenv("BOT_APP_PASSWORD")
# 初始化 Azure OpenAI
openai.api_type = "azure"
openai.api_key = os.getenv("AZURE_OPENAI_KEY")
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
openai.api_version = "2024-02-15-preview"


@app.route("/ping", methods=["GET"])
def ping():
    debuggerTest = os.getenv("debugInfo")
    return jsonify(
        {"status": "ok", "message": "Bot is alive", "debuggerTest": debuggerTest}
    )  # 使用 jsonify


async def call_openai(prompt, conversation_id):
    global conversation_history
    if conversation_id not in conversation_history:
        conversation_history[conversation_id] = []
        # 初始化對話時加入系統提示
        conversation_history[conversation_id].append(
            {
                "role": "system",
                "content": "你是一個智能助理。如果用戶使用中文提問，請用繁體中文回答。如果用戶使用其他語言提問，請使用相同的語言回答。",
            }
        )
    # conversation_history[conversation_id].append({"role": "user", "content": prompt})
    conversation_history[conversation_id].append(
        {"role": "user", "content": str(prompt)}
    )

    try:
        response = openai.ChatCompletion.create(
            engine="gpt-4o-mini-deploy",
            messages=conversation_history[conversation_id],
            max_tokens=500,
            timeout=15,  # 設置超時（秒） 123
        )
    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        return "抱歉，目前無法處理您的請求。"

    message = response["choices"][0]["message"]
    conversation_history[conversation_id].append(message)

    return message["content"]


# Bot 處理消息的邏輯


async def process_file(file_content, file_type):
    """處理不同類型的檔案"""
    content = io.BytesIO(file_content)

    try:
        if file_type == "application/pdf":
            reader = PdfReader(content)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return f"PDF 內容：\n{text}"

        elif (
            file_type
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            df = pd.read_excel(content)
            return f"Excel 內容：\n{df.to_string()}"

        elif (
            file_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            doc = Document(content)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return f"Word 內容：\n{text}"

        elif file_type == "text/plain":
            return f"文字檔內容：\n{content.read().decode('utf-8')}"

        elif file_type.startswith("image/"):
            image = Image.open(content)
            return f"收到圖片：{image.format} 格式，大小 {image.size}"

        else:
            return f"收到不支援的檔案類型：{file_type}"

    except Exception as e:
        return f"處理檔案時發生錯誤：{str(e)}"


# 添加歡迎訊息處理
async def welcome_user(turn_context: TurnContext):
    welcome_text = "歡迎使用 TR GPT 助理！\n我可以幫您：\n1. 回答問題\n2. 分析文件\n3. 提供建議\n\n請問有什麼我可以協助您的嗎？"
    await turn_context.send_activity(Activity(type="message", text=welcome_text))


# 修改 message_handler
async def message_handler(turn_context: TurnContext):
    try:
        if turn_context.activity.attachments:
            print("Received attachment")  # 增加日誌
            for attachment in turn_context.activity.attachments:
                print(f"Attachment type: {attachment.content_type}")  # 增加日誌
                if attachment.content_type.startswith("file"):
                    file_info = attachment.content
                    download_url = file_info.get("downloadUrl", "")
                    file_type = attachment.content_type

                    print(f"Processing file: {file_type}")  # 增加日誌
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(download_url) as response:
                                if response.status == 200:
                                    file_content = await response.read()
                                else:
                                    print(
                                        f"Failed to download file: {response.status}"
                                    )  # 增加日誌
                                    await turn_context.send_activity(
                                        Activity(
                                            type="message",
                                            text="無法下載檔案，請稍後再試。",
                                        )
                                    )
                                    return

                        analyzed_content = await process_file(file_content, file_type)
                        prompt = f"分析以下內容：\n{analyzed_content[:4000]}"
                        response = await call_openai(
                            prompt, turn_context.activity.conversation.id
                        )

                        await turn_context.send_activity(
                            Activity(
                                type="message", text=f"檔案分析結果：\n\n{response}"
                            )
                        )

                    except Exception as e:
                        print(f"Error processing file: {str(e)}")  # 增加日誌
                        await turn_context.send_activity(
                            Activity(
                                type="message", text=f"處理檔案時發生錯誤：{str(e)}"
                            )
                        )
        else:
            user_message = turn_context.activity.text
            print(f"Received text message: {user_message}")  # 修改日誌
            if user_message:  # 確保消息不是 None
                response_message = await call_openai(
                    user_message, turn_context.activity.conversation.id
                )
                print(f"OpenAI response: {response_message}")  # 修改日誌
                await turn_context.send_activity(
                    Activity(type="message", text=response_message)
                )

    except Exception as e:
        print(f"Error in message_handler: {str(e)}")  # 增加日誌
        await turn_context.send_activity(
            Activity(type="message", text="處理訊息時發生錯誤，請稍後再試。")
        )


# async def message_handler(turn_context: TurnContext):
#     user_message = turn_context.activity.text
#     print(f"Received message: {user_message}")  # 檢查訊息是否到達此處
#     conversation_id = turn_context.activity.conversation.id
#     response_message = await call_openai(user_message, conversation_id)

#     print(f"Response from OpenAI: {response_message}")  # 檢查回應內容
#     await turn_context.send_activity(Activity(type="message", text=response_message))


@app.route("/api/messages", methods=["POST"])
def messages():
    print("=== Starting message processing ===")  # 新增
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
        print(f"Request body type: {type(body)}")  # 新增
        print(f"Request content: {body}")  # 新增
    else:
        print("Invalid content type")  # 新增
        return {"status": 415}

    print("Deserializing activity")  # 新增
    activity = Activity().deserialize(body)
    print(f"Activity type: {activity.type}")  # 新增

    if hasattr(activity, "attachments"):
        print(f"Attachments found: {len(activity.attachments)}")  # 新增
        if activity.attachments:
            for att in activity.attachments:
                print(f"Attachment type: {att.content_type}")  # 新增

    auth_header = request.headers.get("Authorization", "")

    async def aux_func(turn_context):
        print(f"Processing activity of type: {turn_context.activity.type}")  # 新增
        if turn_context.activity.attachments:
            print("Processing attachment in aux_func")  # 新增
            for attachment in turn_context.activity.attachments:
                try:
                    print(
                        f"Processing attachment of type: {attachment.content_type}"
                    )  # 新增
                    # ... 其餘的附件處理代碼 ...
                except Exception as e:
                    print(f"Error processing attachment: {str(e)}")  # 新增
                    raise
        else:
            await message_handler(turn_context)

    task = adapter.process_activity(activity, auth_header, aux_func)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(task)
    except Exception as e:
        print(f"Error in message processing: {str(e)}")  # 新增
        raise
    finally:
        loop.close()

    print("=== Message processing completed ===")  # 新增
    return {"status": 200}


# @app.route("/api/messages", methods=["POST"])
# def messages():
#     if "application/json" in request.headers["Content-Type"]:
#         body = request.json
#     else:
#         return {"status": 415}

#     print("Received activity")

#     activity = Activity().deserialize(body)
#     auth_header = request.headers.get("Authorization", "")

#     # async def aux_func(turn_context):
#     #     await message_handler(turn_context)
#     async def aux_func(turn_context):
#         if activity.type == "conversationUpdate" and activity.members_added:
#             for member in activity.members_added:
#                 if member.id != activity.recipient.id:
#                     await welcome_user(turn_context)
#         elif activity.type == "message":
#             await message_handler(turn_context)

#     task = adapter.process_activity(activity, auth_header, aux_func)

#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#     try:
#         loop.run_until_complete(task)
#     finally:
#         loop.close()

#     print("Processed activity")
#     return {"status": 200}


# if __name__ == "__main__":
#     app.run(port=3978)

# if __name__ == "__main__":
#     port = os.getenv("PORT", "8000")
#     app.run(host="0.0.0.0", port=int(port))
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
