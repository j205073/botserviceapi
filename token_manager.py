import requests
from datetime import datetime, timedelta
import json
import os
from typing import Optional, Dict, Any


class TokenManager:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expiry = None
        self.refresh_margin_minutes = 5

    def get_token(self) -> str:
        """獲取有效的 access token"""
        if not self.is_token_valid():
            self._fetch_new_token()
        return self.access_token

    def is_token_valid(self) -> bool:
        """檢查 token 是否還有效"""
        if not self.access_token or not self.token_expiry:
            return False
        return (
            datetime.now() + timedelta(minutes=self.refresh_margin_minutes)
            < self.token_expiry
        )

    def _fetch_new_token(self) -> None:
        """從 Microsoft 獲取新的 token"""
        token_url = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        )

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }

        response = requests.post(token_url, data=data)

        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data["access_token"]
            self.token_expiry = datetime.now() + timedelta(
                seconds=token_data["expires_in"]
            )
        else:
            raise Exception(f"Failed to get token: {response.text}")
