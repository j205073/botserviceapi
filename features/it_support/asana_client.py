import os
from typing import Any, Dict, Optional
import httpx


class AsanaClient:
    """Minimal async Asana API client (tasks create)."""

    def __init__(self,
                 token: Optional[str] = None,
                 base_url: str = "https://app.asana.com/api/1.0"):
        self.token = token or os.getenv("ASANA_ACCESS_TOKEN", "")
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise ValueError("ASANA_ACCESS_TOKEN 未設置或為空")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def create_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a task via Asana API.
        Expects payload like {"data": { ... task fields ... }} matching Postman spec.
        """
        url = f"{self.base_url}/tasks"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=self._headers(), json=data)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Surface Asana error details if available
                detail = None
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise httpx.HTTPStatusError(f"Asana API error {resp.status_code}: {detail}", request=e.request, response=e.response)
            return resp.json()

    async def get_task(self, task_gid: str) -> Dict[str, Any]:
        """Get task details by GID. Returns the task data dict."""
        if not task_gid:
            raise ValueError("無效的任務 ID")
        url = f"{self.base_url}/tasks/{task_gid}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url, headers=self._headers(),
                params={"opt_fields": "name,completed,notes,assignee,permalink_url"}
            )
            resp.raise_for_status()
            return resp.json()

    async def create_webhook(self, resource_gid: str, target_url: str) -> Dict[str, Any]:
        """Create a webhook subscription on a resource (project or task).
        Asana will send a handshake request to target_url first.
        """
        url = f"{self.base_url}/webhooks"
        data = {
            "data": {
                "resource": resource_gid,
                "target": target_url,
                "filters": [
                    {"resource_type": "task", "action": "changed",
                     "fields": ["completed"]}
                ]
            }
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=self._headers(), json=data)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                detail = None
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise httpx.HTTPStatusError(
                    f"Asana Webhook 建立失敗 {resp.status_code}: {detail}",
                    request=e.request, response=e.response
                )
            return resp.json()

    async def upload_attachment(self, task_gid: str, filename: str, content: bytes, mime_type: str) -> Dict[str, Any]:
        """Upload an attachment file to a task."""
        if not task_gid:
            raise ValueError("無效的任務 ID")
        url = f"{self.base_url}/attachments"
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {
            "file": (filename, content, mime_type),
            "parent": (None, task_gid),
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, files=files)
            resp.raise_for_status()
            return resp.json()
