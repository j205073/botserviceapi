import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import pytz

from infrastructure.external.graph_api_client import GraphAPIClient

logger = logging.getLogger(__name__)

class ITKnowledgeBase:
    """
    負責 IT 知識庫條目的建立、本地備份及 SharePoint 上傳。
    """

    def __init__(self, graph_client: GraphAPIClient):
        self.graph_client = graph_client
        self.site_hostname = os.getenv("SHAREPOINT_SITE_HOSTNAME", "rinnaitw.sharepoint.com")
        self.site_path = os.getenv("SHAREPOINT_SITE_PATH", "/sites/IT")
        self.root_path = os.getenv("SHAREPOINT_ROOT_PATH", "IT/Knowledge_Base")

    def create_entry(self, task: Dict[str, Any], reporter_info: Dict[str, str], stories: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """從 Asana 任務資料建立 AI-Ready 的 JSON 知識條目。
        若 Asana task 帶有 external.data（提單時 AI 寫入的 structured JSON v1.0），
        則加入頂層 structured 欄位供後續分析使用（schema v2.0 加欄位、不破壞舊結構）。
        """
        taipei = pytz.timezone("Asia/Taipei")
        now = datetime.now(taipei)

        issue_id = reporter_info.get("issue_id", "UNKNOWN")
        resolution = self._extract_resolution(task)

        # 建立對話紀錄 (Dialogue)
        dialogue = []
        if stories:
            for s in stories:
                # 僅紀錄有文字內容的評論(comment)
                if s.get("type") == "comment" or s.get("resource_subtype") == "comment_added":
                    dialogue.append({
                        "role": s.get("created_by", {}).get("name", "Unknown"),
                        "text": s.get("text", ""),
                        "time": s.get("created_at")
                    })

        entry = {
            "metadata": {
                "entry_id": issue_id,
                "asana_task_gid": task.get("gid"),
                "created_at": task.get("created_at"),
                "resolved_at": now.isoformat(),
                "priority": reporter_info.get("priority", "P3"),
                "reporter": reporter_info.get("reporter_name", ""),
                "reporter_email": reporter_info.get("email") or reporter_info.get("reporter_email", ""),
                "reporter_department": reporter_info.get("reporter_department", "未指定部門"),
                "category": reporter_info.get("category_label", "其他")
            },
            "content": {
                "title": task.get("name", ""),
                "description": task.get("notes", ""),
                "resolution": resolution,
                "dialogue": dialogue,
                "keywords": self._generate_keywords(task.get("name", ""), resolution)
            }
        }

        # 從 Asana external.data 還原提單時的 structured JSON（若有）
        external = task.get("external") or {}
        external_data = external.get("data")
        if external_data:
            try:
                structured = json.loads(external_data)
                if isinstance(structured, dict):
                    entry["structured"] = structured
            except Exception as e:
                logger.warning("解析 Asana external.data 失敗（issue_id=%s）：%s", issue_id, e)

        return entry

    async def save_to_sharepoint(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        將知識條目上傳至 SharePoint。
        """
        issue_id = entry.get("metadata", {}).get("entry_id", "UNKNOWN")
        taipei = pytz.timezone("Asia/Taipei")
        now = datetime.now(taipei)
        
        # 路徑：IT/Knowledge_Base/YYYY/MM/ID.json
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")
        file_path = f"{self.root_path}/{year_str}/{month_str}/{issue_id}.json".replace("//", "/")
        
        content = json.dumps(entry, ensure_ascii=False, indent=2).encode("utf-8")
        
        try:
            result = await self.graph_client.upload_to_sharepoint(
                site_hostname=self.site_hostname,
                site_path=self.site_path,
                file_path_in_drive=file_path,
                content=content,
                content_type="application/json"
            )
            logger.info(f"知識條目 {issue_id} 已成功上傳至 SharePoint: {file_path}")
            return {"success": True, "path": file_path, "data": result}
        except Exception as e:
            logger.error(f"上傳知識條目至 SharePoint 失敗: {e}")
            return {"success": False, "error": str(e)}

    def _extract_resolution(self, task: Dict[str, Any]) -> str:
        """
        從任務中擷取處理結果。
        優先尋找 Asana Custom Field '處理結果'。
        """
        custom_fields = task.get("custom_fields", [])
        for field in custom_fields:
            if "處理結果" in field.get("name", ""):
                return field.get("display_value") or ""
        
        # 如果沒找到自訂欄位，嘗試從 notes 後半部擷取內容（這取決於工程師習慣）
        return "（詳見 Asana 任務內容）"

    def _generate_keywords(self, title: str, resolution: str) -> List[str]:
        """
        簡單的關鍵字產生邏輯。
        """
        import re
        all_text = title + " " + resolution
        # 這裡可以實作更複雜的斷詞，目前簡單過濾長度 > 1 的詞
        words = re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}", all_text)
        return list(set(words))[:10]

    async def list_entries(self, year: Optional[str] = None, month: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出 SharePoint 上的知識庫 JSON 條目。
        可透過 year 和 month 篩選。
        """
        all_entries = []

        if year and month:
            folder = f"{self.root_path}/{year}/{month}"
            files = await self.graph_client.list_drive_children(self.site_hostname, self.site_path, folder)
            for f in files:
                if f.get("name", "").endswith(".json"):
                    content = await self.graph_client.download_drive_file(self.site_hostname, self.site_path, f"{folder}/{f['name']}")
                    if content:
                        all_entries.append(content)
        elif year:
            year_folder = f"{self.root_path}/{year}"
            months = await self.graph_client.list_drive_children(self.site_hostname, self.site_path, year_folder)
            for m in months:
                if m.get("folder"):
                    month_path = f"{year_folder}/{m['name']}"
                    files = await self.graph_client.list_drive_children(self.site_hostname, self.site_path, month_path)
                    for f in files:
                        if f.get("name", "").endswith(".json"):
                            content = await self.graph_client.download_drive_file(self.site_hostname, self.site_path, f"{month_path}/{f['name']}")
                            if content:
                                all_entries.append(content)
        else:
            years = await self.graph_client.list_drive_children(self.site_hostname, self.site_path, self.root_path)
            for y in years:
                if y.get("folder"):
                    year_path = f"{self.root_path}/{y['name']}"
                    months = await self.graph_client.list_drive_children(self.site_hostname, self.site_path, year_path)
                    for m in months:
                        if m.get("folder"):
                            month_path = f"{year_path}/{m['name']}"
                            files = await self.graph_client.list_drive_children(self.site_hostname, self.site_path, month_path)
                            for f in files:
                                if f.get("name", "").endswith(".json"):
                                    content = await self.graph_client.download_drive_file(self.site_hostname, self.site_path, f"{month_path}/{f['name']}")
                                    if content:
                                        all_entries.append(content)

        return all_entries

    async def get_entry(self, issue_id: str) -> Optional[Dict[str, Any]]:
        """
        取得單筆知識庫條目。
        嘗試從 issue_id 解析年月定址，失敗則暴力搜尋。
        """
        if issue_id.startswith("IT") and len(issue_id) >= 8:
            year = issue_id[2:6]
            month = issue_id[6:8]
            file_path = f"{self.root_path}/{year}/{month}/{issue_id}.json"
            content = await self.graph_client.download_drive_file(self.site_hostname, self.site_path, file_path)
            if content:
                return content

        years = await self.graph_client.list_drive_children(self.site_hostname, self.site_path, self.root_path)
        for y in years:
            if not y.get("folder"):
                continue
            year_path = f"{self.root_path}/{y['name']}"
            months = await self.graph_client.list_drive_children(self.site_hostname, self.site_path, year_path)
            for m in months:
                if not m.get("folder"):
                    continue
                file_path = f"{year_path}/{m['name']}/{issue_id}.json"
                content = await self.graph_client.download_drive_file(self.site_hostname, self.site_path, file_path)
                if content:
                    return content

        return None
