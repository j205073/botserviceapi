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

    async def get_user_gid_by_email(self, email: str) -> Optional[str]:
        """透過 email 查詢 Asana 使用者 GID，結果會快取避免重複呼叫。"""
        if not email:
            return None
        # 快取
        if not hasattr(self, "_user_gid_cache"):
            self._user_gid_cache: Dict[str, Optional[str]] = {}
        if email in self._user_gid_cache:
            return self._user_gid_cache[email]

        url = f"{self.base_url}/users/{email}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    url, headers=self._headers(),
                    params={"opt_fields": "gid,name,email"}
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
                gid = data.get("gid")
                self._user_gid_cache[email] = gid
                return gid
        except Exception:
            self._user_gid_cache[email] = None
            return None

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

    async def get_story(self, story_gid: str) -> Dict[str, Any]:
        """獲取特定 Story (評論/紀錄) 細節。"""
        if not story_gid:
            raise ValueError("無效的 Story ID")
        url = f"{self.base_url}/stories/{story_gid}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url, headers=self._headers(),
                params={"opt_fields": "text,type,created_at,created_by.name,resource_subtype"}
            )
            resp.raise_for_status()
            return resp.json()

    async def get_task_stories(self, task_gid: str) -> Dict[str, Any]:
        """獲取任務的 Stories (含評論與紀錄)。"""
        if not task_gid:
            raise ValueError("無效的任務 ID")
        url = f"{self.base_url}/tasks/{task_gid}/stories"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url, headers=self._headers(),
                params={"opt_fields": "text,type,created_at,created_by.name,resource_subtype"}
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
                    {"resource_type": "task", "action": "changed", "fields": ["completed"]},
                    {"resource_type": "story", "action": "added"}
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

    async def get_project_tasks(
        self, project_gid: str, completed_since: Optional[str] = None, limit: int = 100,
    ) -> list[Dict[str, Any]]:
        """Get all tasks from a project (free-tier compatible).
        Uses pagination to fetch all results.
        Args:
            completed_since: ISO date string or 'now' for incomplete only.
                             None to get both completed and incomplete.
        """
        url = f"{self.base_url}/tasks"
        all_tasks: list[Dict[str, Any]] = []
        offset = None

        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                params: Dict[str, Any] = {
                    "project": project_gid,
                    "opt_fields": "name,completed,completed_at,created_at,notes",
                    "limit": limit,
                }
                if completed_since:
                    params["completed_since"] = completed_since
                if offset:
                    params["offset"] = offset

                resp = await client.get(url, headers=self._headers(), params=params)
                resp.raise_for_status()
                data = resp.json()
                all_tasks.extend(data.get("data", []))

                next_page = data.get("next_page")
                if next_page and next_page.get("offset"):
                    offset = next_page["offset"]
                else:
                    break

        return all_tasks

    async def list_webhooks(self, workspace_gid: str, resource_gid: str = "") -> list[Dict[str, Any]]:
        """列出 workspace 下的 webhook 訂閱。可選 resource_gid 過濾。"""
        url = f"{self.base_url}/webhooks"
        params: Dict[str, Any] = {
            "workspace": workspace_gid,
            "opt_fields": "resource,resource.name,target,active,created_at",
        }
        if resource_gid:
            params["resource"] = resource_gid
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def get_task_attachments(self, task_gid: str) -> list[Dict[str, Any]]:
        """取得任務的附件列表（含 download_url）。"""
        if not task_gid:
            return []
        url = f"{self.base_url}/tasks/{task_gid}/attachments"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url, headers=self._headers(),
                params={"opt_fields": "name,download_url,host,resource_subtype"},
            )
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def download_attachment(self, download_url: str) -> Optional[bytes]:
        """下載附件內容到記憶體，回傳 bytes。"""
        if not download_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(download_url)
                resp.raise_for_status()
                return resp.content
        except Exception:
            return None

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
