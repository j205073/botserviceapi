import asyncio
import os
import httpx
import json

async def check_webhooks():
    token = os.getenv("ASANA_ACCESS_TOKEN", "")
    workspace = os.getenv("ASANA_WORKSPACE_GID", "1208041237608650")
    
    if not token:
        print("❌ 找不到 ASANA_ACCESS_TOKEN，請檢查 .env 檔案。")
        return

    print("🔍 正在列出 Asana Webhooks...")
    url = "https://app.asana.com/api/1.0/webhooks"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"workspace": workspace}

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"❌ 查詢失敗: {resp.text}")
            return
        
        data = resp.json().get("data", [])
        if not data:
            print("ℹ️ 目前沒有任何作用中的 Webhook。")
            return

        for hook in data:
            gid = hook.get("gid")
            target = hook.get("target")
            resource = hook.get("resource", {}).get("name", "Unknown Resource")
            active = hook.get("active")
            filters = hook.get("filters", [])
            
            print(f"\n--- Webhook: {gid} ---")
            print(f"📍 目標 URL: {target}")
            print(f"📦 監聽對象: {resource}")
            print(f"✅ 狀態: {'作用中' if active else '停用'}")
            print(f"📡 過濾器 (Filters):")
            has_story = False
            for f in filters:
                rtype = f.get("resource_type")
                action = f.get("action")
                print(f"   - {rtype} ({action})")
                if rtype == "story":
                    has_story = True
            
            if not has_story:
                print("⚠️  警告：此 Webhook 尚未監聽 'story' 事件，因此評論不會有通知！")
                print("👉 請執行 'python refresh_webhook.py' 來更新。")

if __name__ == "__main__":
    asyncio.run(check_webhooks())
