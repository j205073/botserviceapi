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
    return jsonify({"status": "ok", "message": "Bot is alive"})  # 使用 jsonify


async def call_openai(prompt, conversation_id):
    global conversation_history
    if conversation_id not in conversation_history:
        conversation_history[conversation_id] = []

    # conversation_history[conversation_id].append({"role": "user", "content": prompt})
    conversation_history[conversation_id].append(
        {"role": "user", "content": str(prompt)}
    )

    try:
        response = openai.ChatCompletion.create(
            engine="gpt-4o-mini-deploy",
            messages=conversation_history[conversation_id],
            max_tokens=500,
            timeout=15,  # 設置超時（秒）
        )
    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        return "抱歉，目前無法處理您的請求。"

    message = response["choices"][0]["message"]
    conversation_history[conversation_id].append(message)

    return message["content"]


# Bot 處理消息的邏輯
async def message_handler(turn_context: TurnContext):
    user_message = turn_context.activity.text
    print(f"Received message: {user_message}")  # 檢查訊息是否到達此處
    conversation_id = turn_context.activity.conversation.id
    response_message = await call_openai(
        user_message, conversation_id
    )  # 這裡應該觸發 call_openai
    print(f"Response from OpenAI: {response_message}")  # 檢查回應內容
    await turn_context.send_activity(Activity(type="message", text=response_message))


@app.route("/api/messages", methods=["POST"])
def messages():
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
    else:
        return {"status": 415}

    print("Received activity")  # 日誌輸出，檢查是否進入這裡

    activity = Activity().deserialize(body)
    auth_header = (
        request.headers["Authorization"] if "Authorization" in request.headers else ""
    )

    async def aux_func(turn_context):
        await message_handler(turn_context)

    task = adapter.process_activity(activity, auth_header, aux_func)

    try:
        asyncio.run(task)
    except Exception as e:
        print(f"Error in processing activity: {e}")

    print("Processed activity")  # 日誌輸出，檢查是否進入這裡

    return {"status": 200}


# if __name__ == "__main__":
#     app.run(port=3978)

if __name__ == "__main__":
    port = os.getenv("PORT", "8000")
    app.run(host="0.0.0.0", port=int(port))
