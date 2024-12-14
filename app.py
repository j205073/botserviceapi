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


# 修改 message_handler
async def message_handler(turn_context: TurnContext):
    if turn_context.activity.attachments:
        for attachment in turn_context.activity.attachments:
            if attachment.content_type.startswith("file"):
                # 取得檔案資訊
                file_info = attachment.content
                download_url = file_info.get("downloadUrl", "")
                file_type = attachment.content_type

                try:
                    # 下載檔案
                    async with aiohttp.ClientSession() as session:
                        async with session.get(download_url) as response:
                            file_content = await response.read()

                    # 處理檔案
                    analyzed_content = await process_file(file_content, file_type)

                    # 使用 OpenAI 分析內容
                    prompt = f"""請幫我分析這份檔案的內容：

{analyzed_content[:4000]}

請提供：
1. 文件主要內容摘要
2. 關鍵重點
3. 相關建議（如果適用）"""

                    response = await call_openai(
                        prompt, turn_context.activity.conversation.id
                    )
                    await turn_context.send_activity(
                        Activity(type="message", text=f"檔案分析結果：\n\n{response}")
                    )

                except Exception as e:
                    await turn_context.send_activity(
                        Activity(type="message", text=f"處理檔案時發生錯誤：{str(e)}")
                    )
    else:
        # 原有的文字處理邏輯
        user_message = turn_context.activity.text
        print(f"Received message: {user_message}")
        response_message = await call_openai(
            user_message, turn_context.activity.conversation.id
        )
        print(f"Response from OpenAI: {response_message}")
        await turn_context.send_activity(
            Activity(type="message", text=response_message)
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
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
    else:
        return {"status": 415}

    print("Received activity")

    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    async def aux_func(turn_context):
        await message_handler(turn_context)

    task = adapter.process_activity(activity, auth_header, aux_func)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(task)
    finally:
        loop.close()

    print("Processed activity")
    return {"status": 200}


# if __name__ == "__main__":
#     app.run(port=3978)

# if __name__ == "__main__":
#     port = os.getenv("PORT", "8000")
#     app.run(host="0.0.0.0", port=int(port))
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
