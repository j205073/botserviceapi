"""
KB-Vector-Service 知識庫查詢客戶端
透過 Azure AD Client Credentials 認證，呼叫 /api/v1/ask 取得知識庫建議
"""
import os
import time
import logging
import asyncio
import aiohttp
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# KB API 的 Azure AD scope（對應 INTEGRATION_GUIDE.md）
_KB_DEFAULT_SCOPE = "api://de281045-d27f-4549-972a-0b331178668a/.default"


class KBVectorClient:
    """知識庫向量搜尋客戶端"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self.base_url = (base_url or os.getenv(
            "KB_API_URL", "https://kb-vector-service.azurewebsites.net"
        )).rstrip("/")
        self.tenant_id = tenant_id or os.getenv("TENANT_ID", "")
        self.client_id = client_id or os.getenv("CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("CLIENT_SECRET", "")
        self.scope = os.getenv("KB_API_SCOPE", _KB_DEFAULT_SCOPE)

        # Token 快取
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._token_lock = asyncio.Lock()

    async def _ensure_token(self) -> str:
        """取得或刷新 Azure AD Token（Client Credentials Flow）"""
        async with self._token_lock:
            if self._access_token and time.time() < (self._token_expires_at - 300):
                return self._access_token

            token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data=data) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error("KB Token 取得失敗: %s - %s", resp.status, text)
                        raise RuntimeError(f"KB Token 取得失敗: {resp.status}")
                    body = await resp.json()
                    self._access_token = body["access_token"]
                    self._token_expires_at = time.time() + body.get("expires_in", 3600)

            return self._access_token

    async def list_kbs(self, timeout: int = 10) -> list:
        """
        呼叫 GET /api/v1/kbs 列出有權存取的知識庫。

        Returns:
            list of dict，每筆含 slug, displayName 等欄位。
        """
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{self.base_url}/api/v1/kbs"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("KB list_kbs 回應異常: %s - %s", resp.status, text)
                    return []
                return await resp.json()

    async def ask(self, question: str, role: str = "it", kb_name: str = "", timeout: int = 15) -> Dict[str, Any]:
        """
        呼叫 KB-Vector-Service /api/v1/{kb}/ask（多知識庫）或 /api/v1/ask（向後相容）。

        Args:
            question: 使用者的問題描述
            role: "user"（親切回覆）或 "it"（專業詳細，含 score/contentPreview）
            kb_name: 知識庫 slug（如 "it-kb", "cs-kb"），空字串則使用向後相容端點
            timeout: 請求逾時秒數

        Returns:
            {"answer": str, "sources": list, "role": str, "kb": str}
            查無資料時 sources 為空陣列。
        """
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}

        if kb_name:
            url = f"{self.base_url}/api/v1/{kb_name}/ask"
        else:
            url = f"{self.base_url}/api/v1/ask"
        params = {"question": question, "role": role}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("KB API 回應異常: %s - %s", resp.status, text)
                    return {"answer": "", "sources": [], "role": role}
                return await resp.json()

    async def ask_safe(self, question: str, role: str = "it", kb_name: str = "", timeout: int = 15) -> Dict[str, Any]:
        """ask() 的安全包裝，任何例外都回傳空結果，不影響主流程。"""
        try:
            return await self.ask(question, role=role, kb_name=kb_name, timeout=timeout)
        except Exception as e:
            logger.warning("KB 知識庫查詢失敗（不影響主流程）: %s", e)
            return {"answer": "", "sources": [], "role": role}
