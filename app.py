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


async def show_help_options(turn_context: TurnContext):
    # 創建建議動作
    suggested_actions = SuggestedActions(
        actions=[
            CardAction(title="今天菜單", type=ActionTypes.im_back, value="今天菜單"),
            CardAction(title="分機查詢", type=ActionTypes.im_back, value="分機查詢"),
            # 可以繼續添加更多選項
        ]
    )

    # 創建回覆訊息
    reply = Activity(
        type=ActivityTypes.message,
        text="請選擇以下選項:",
        suggested_actions=suggested_actions,
    )

    await turn_context.send_activity(reply)


async def call_openai(prompt, conversation_id):
    global conversation_history
    if conversation_id not in conversation_history:
        conversation_history[conversation_id] = []
        conversation_history[conversation_id].append(
            {
                "role": "system",
                "content": "你是一個智能助理。如果用戶使用中文提問，請用繁體中文回答。如果用戶使用其他語言提問，請使用跟用戶相同的語言回答。",
            }
        )

    conversation_history[conversation_id].append(
        {"role": "user", "content": str(prompt)}
    )

    try:
        response = openai.ChatCompletion.create(
            engine="gpt-4o-mini-deploy",
            messages=conversation_history[conversation_id],
            max_tokens=500,
            timeout=15,
        )
        message = response["choices"][0]["message"]
        conversation_history[conversation_id].append(message)
        return message["content"]
    except Exception as e:
        print(f"OpenAI API 錯誤: {str(e)}")
        return "抱歉，目前無法處理您的請求。"


async def summarize_text(text, conversation_id) -> str:
    """利用 OpenAI 進行文本摘要"""
    try:
        response = openai.ChatCompletion.create(
            engine="gpt-4o-mini-deploy",
            messages=[
                {"role": "system", "content": "你是一個智能助理，負責摘要文本內容。"},
                {"role": "user", "content": text},
            ],
            max_tokens=500,
        )
        message = response["choices"][0]["message"]
        conversation_history[conversation_id].append(message)
        return message["content"]
    except Exception as e:
        return f"摘要處理時發生錯誤：{str(e)}"


async def welcome_user(turn_context: TurnContext):
    user_name = turn_context.activity.from_property.name
    welcome_text = f"歡迎 {user_name} 使用 TR GPT 助理！\n我可以幫您：\n1. 回答問題\n2. 分析文件\n3. 提供建議\n\n請問有什麼我可以協助您的嗎？"
    await turn_context.send_activity(Activity(type="message", text=welcome_text))


async def message_handler(turn_context: TurnContext):
    try:
        user_id = turn_context.activity.from_property.id
        user_name = turn_context.activity.from_property.name
        print(f"收到來自用戶的訊息: {user_name} (ID: {user_id})")

        # # 確保保存 JSON 的目錄存在
        # log_dir = "./json_logs"
        # if not os.path.exists(log_dir):
        #     os.makedirs(log_dir)

        # # 轉換 turn_context 為字典
        # context_dict = {
        #     "activity": turn_context.activity.as_dict(),
        #     "user_id": user_id,
        #     "user_name": user_name,
        # }

        # # 保存到 json_log.json
        # log_file_path = os.path.join(log_dir, "json_log.json")
        # with open(log_file_path, "a") as f:
        #     json.dump(context_dict, f, ensure_ascii=False, indent=4)
        #     f.write("\n")  # 每次寫入一條日志後換行

        # 獲取附件
        attachments = turn_context.activity.attachments

        if turn_context.activity.text:
            user_message = turn_context.activity.text
            # 檢查是否為 /help 命令
            if user_message.lower() == "/help":
                await show_help_options(turn_context)
                return

            print(f"Current Request Is An Txt Messages: {user_message}")

            response_message = await call_openai(
                user_message, turn_context.activity.conversation.id
            )
            await turn_context.send_activity(
                Activity(type="message", text=response_message)
            )
        elif attachments and len(attachments) > 0:
            print("Current Request Is An File")
            for attachment in turn_context.activity.attachments:
                file_info = await download_attachment_and_write(attachment)
                if file_info:
                    file_text = await process_file(file_info)
                    summarized_text = await summarize_text(
                        file_text, turn_context.activity.conversation.id
                    )  # 文本摘要
                    await turn_context.send_activity(
                        Activity(type="message", text=summarized_text)
                    )

    except Exception as e:
        print(f"處理訊息時發生錯誤: {str(e)}")
        await turn_context.send_activity(
            Activity(type="message", text="處理訊息時發生錯誤，請稍後再試。")
        )


@app.route("/ping", methods=["GET"])
def ping():
    debuggerTest = os.getenv("debugInfo")
    return jsonify(
        {"status": "ok", "message": "Bot is alive", "debuggerTest": debuggerTest}
    )  # 使用 jsonify


@app.route("/api/messages", methods=["POST"])
def messages():
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
