"""
從 Microsoft Graph API 撈出組織內所有不重複的部門名稱。
用法：python scripts/list_departments.py
"""
import asyncio
import os
import sys

# 讓 import 找到專案根目錄
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import aiohttp


async def main():
    tenant_id = os.getenv("TENANT_ID", "")
    client_id = os.getenv("CLIENT_ID", "")
    client_secret = os.getenv("CLIENT_SECRET", "")

    if not all([tenant_id, client_id, client_secret]):
        print("❌ 缺少 TENANT_ID / CLIENT_ID / CLIENT_SECRET 環境變數")
        return

    # 1. 取得 token
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    token_data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data=token_data) as resp:
            if resp.status != 200:
                print(f"❌ Token 取得失敗: {resp.status} - {await resp.text()}")
                return
            token = (await resp.json())["access_token"]

        # 2. 分頁撈所有 user 的 department
        headers = {"Authorization": f"Bearer {token}"}
        departments = set()
        user_count = 0
        url = "https://graph.microsoft.com/v1.0/users?$select=displayName,department,mail&$top=999"

        while url:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    print(f"❌ Graph API 失敗: {resp.status} - {await resp.text()}")
                    return
                data = await resp.json()

            for user in data.get("value", []):
                user_count += 1
                dept = (user.get("department") or "").strip()
                if dept:
                    departments.add(dept)

            url = data.get("@odata.nextLink")

    # 3. 輸出結果
    print(f"\n📊 共掃描 {user_count} 位使用者，發現 {len(departments)} 個不重複部門：\n")
    for dept in sorted(departments):
        print(f"  - {dept}")

    # 4. 建議 KB_DEPARTMENT_MAP 模板
    print(f"\n💡 建議 KB_DEPARTMENT_MAP 模板（請依實際知識庫 slug 調整）：\n")
    suggested = {}
    for dept in sorted(departments):
        suggested[dept] = f"{dept.lower().replace(' ', '-')}-kb"
    import json
    print(json.dumps(suggested, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
