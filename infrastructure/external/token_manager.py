"""
OAuth Token 管理器
處理 Microsoft Graph API 的認證和 Token 管理
"""
import asyncio
from typing import Optional, Dict, Any
import aiohttp
import time
from datetime import datetime, timedelta

from config.settings import AppConfig
from shared.exceptions import AuthenticationError


class TokenManager:
    """OAuth Token 管理器"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.tenant_id = config.graph_api.tenant_id
        self.client_id = config.graph_api.client_id
        self.client_secret = config.graph_api.client_secret
        
        # Token 快取
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[float] = None
        self._token_lock = asyncio.Lock()
    
    @property
    def token_endpoint(self) -> str:
        """Token 端點 URL"""
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
    
    async def get_access_token(self, force_refresh: bool = False) -> str:
        """獲取 Access Token"""
        async with self._token_lock:
            # 檢查現有 Token 是否有效
            if not force_refresh and self._is_token_valid():
                return self._access_token
            
            # 獲取新的 Token
            await self._refresh_token()
            
            if not self._access_token:
                raise AuthenticationError("無法獲取 Access Token")
            
            return self._access_token
    
    def _is_token_valid(self) -> bool:
        """檢查 Token 是否有效"""
        if not self._access_token or not self._token_expires_at:
            return False
        
        # 提前 5 分鐘過期以確保安全
        return time.time() < (self._token_expires_at - 300)
    
    async def _refresh_token(self) -> None:
        """刷新 Token"""
        try:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.token_endpoint, data=data) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise AuthenticationError(f"Token 請求失敗: {response.status} - {response_text}")
                    
                    response_data = await response.json()
                    
                    self._access_token = response_data.get("access_token")
                    expires_in = response_data.get("expires_in", 3600)
                    
                    if not self._access_token:
                        raise AuthenticationError("回應中缺少 access_token")
                    
                    # 設置過期時間
                    self._token_expires_at = time.time() + expires_in
                    
                    print(f"✅ 成功獲取 Access Token，有效期：{expires_in} 秒")
                    
        except aiohttp.ClientError as e:
            raise AuthenticationError(f"網路請求失敗: {str(e)}") from e
        except Exception as e:
            raise AuthenticationError(f"Token 刷新失敗: {str(e)}") from e
    
    async def validate_token(self) -> Dict[str, Any]:
        """驗證 Token 有效性"""
        try:
            token = await self.get_access_token()
            
            # 使用 Token 調用簡單的 Graph API 端點進行驗證
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://graph.microsoft.com/v1.0/organization",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        org_info = await response.json()
                        return {
                            "valid": True,
                            "expires_at": datetime.fromtimestamp(self._token_expires_at).isoformat(),
                            "organization": org_info.get("value", [{}])[0]
                        }
                    else:
                        return {
                            "valid": False,
                            "error": f"驗證失敗: {response.status}"
                        }
                        
        except Exception as e:
            return {
                "valid": False,
                "error": str(e)
            }
    
    async def revoke_token(self) -> bool:
        """撤銷 Token"""
        try:
            if not self._access_token:
                return True
            
            # Microsoft 不支援客戶端憑證流程的 Token 撤銷
            # 我們只需要清除本地快取
            async with self._token_lock:
                self._access_token = None
                self._token_expires_at = None
            
            print("✅ Token 快取已清除")
            return True
            
        except Exception as e:
            print(f"❌ 撤銷 Token 失敗: {e}")
            return False
    
    def get_token_info(self) -> Dict[str, Any]:
        """獲取 Token 資訊"""
        return {
            "has_token": bool(self._access_token),
            "is_valid": self._is_token_valid(),
            "expires_at": datetime.fromtimestamp(self._token_expires_at).isoformat() if self._token_expires_at else None,
            "seconds_until_expiry": int(self._token_expires_at - time.time()) if self._token_expires_at else None
        }
    
    async def test_authentication(self) -> Dict[str, Any]:
        """測試認證設定"""
        try:
            # 驗證配置
            if not self.tenant_id:
                return {"success": False, "error": "TENANT_ID 未設置"}
            if not self.client_id:
                return {"success": False, "error": "CLIENT_ID 未設置"}
            if not self.client_secret:
                return {"success": False, "error": "CLIENT_SECRET 未設置"}
            
            # 嘗試獲取 Token
            token = await self.get_access_token(force_refresh=True)
            
            # 驗證 Token
            validation_result = await self.validate_token()
            
            return {
                "success": True,
                "message": "認證測試成功",
                "token_info": self.get_token_info(),
                "validation": validation_result
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "認證測試失敗"
            }