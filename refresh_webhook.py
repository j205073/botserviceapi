import asyncio
import os
import httpx
from core.dependencies import setup_dependency_injection
from features.it_support.service import ITSupportService

async def refresh_asana_webhook():
    print("🔄 正在嘗試刷新 Asana Webhook 過濾器...")
    
    # 這裡我們需要用戶提供當前 Bot 的外部 URL (例如 ngrok 或正式 Domain)
    # 如果用戶沒提供，我們可以嘗試從環境變數或提示輸入
    target_url = input("請輸入您的 Bot Webhook 外部 URL (例如 https://your-domain.com/api/asana/webhook): ").strip()
    
    if not target_url:
        print("❌ 必須提供 URL 才能建立 Webhook。")
        return

    container = setup_dependency_injection()
    service = container.get(ITSupportService)
    
    # 建立 Webhook (會呼叫我們剛優化過、包含 story filter 的 create_webhook)
    result = await service.setup_webhook(target_url)
    
    if result.get("success"):
        print(f"✅ Webhook 建立成功！Asana GID: {result['data'].get('data', {}).get('gid')}")
        print("💡 現在 Asana 應該會開始傳送 'story' (評論) 事件到您的服務器了。")
    else:
        print(f"❌ 建立失敗: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(refresh_asana_webhook())
