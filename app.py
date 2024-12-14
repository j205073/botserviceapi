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
settings = BotFrameworkAdapterSettings(appId, appPwd)
adapter = BotFrameworkAdapter(settings)

# 用於儲存會話歷史的字典
conversation_history = {}

# 初始化 Azure OpenAI
openai.api_type = "azure"
openai.api_key = os.getenv("AZURE_OPENAI_KEY")
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
openai.api_version = "2024-02-15-preview"


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "message": "Bot is alive"})


async def call_openai(prompt, conversation_id):
    global conversation_history
    if conversation_id not in conversation_history:
        conversation_history[conversation_id] = []
        conversation_history[conversation_id].append(
            {
                "role": "system",
                "content": "你是一個智能助理。如果用戶使用中文提問，請用繁體中文回答。如果用戶使用其他語言提問，請使用相同的語言回答。",
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
        print(f"Error calling OpenAI: {e}")
        return "抱歉，目前無法處理您的請求。"


async def welcome_user(turn_context: TurnContext):
    user_name = turn_context.activity.from_property.name
    welcome_text = f"歡迎 {user_name} 使用 TR GPT 助理！\n我可以幫您：\n1. 回答問題\n2. 提供建議\n\n請問有什麼我可以協助您的嗎？"
    await turn_context.send_activity(Activity(type="message", text=welcome_text))


async def message_handler(turn_context: TurnContext):
    try:
        # 獲取用戶信息
        user_id = turn_context.activity.from_property.id
        user_name = turn_context.activity.from_property.name
        print(f"Received message from user: {user_name} (ID: {user_id})")

        # 只處理文字消息
        if turn_context.activity.text:
            user_message = turn_context.activity.text
            print(f"Received text message: {user_message}")

            response_message = await call_openai(
                user_message, turn_context.activity.conversation.id
            )
            print(f"OpenAI response: {response_message}")

            await turn_context.send_activity(
                Activity(type="message", text=response_message)
            )
        else:
            await turn_context.send_activity(
                Activity(type="message", text="很抱歉，我目前只能處理文字訊息。")
            )

    except Exception as e:
        print(f"Error in message_handler: {str(e)}")
        await turn_context.send_activity(
            Activity(type="message", text="處理訊息時發生錯誤，請稍後再試。")
        )


@app.route("/api/messages", methods=["POST"])
def messages():
    print("=== Starting message processing ===")
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
        print(f"Request body: {body}")
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

    print("=== Message processing completed ===")
    return {"status": 200}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
