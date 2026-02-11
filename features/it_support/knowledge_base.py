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

    def create_entry(self, task: Dict[str, Any], reporter_info: Dict[str, str]) -> Dict[str, Any]:
        """
        從 Asana 任務資料建立 JSON 知識條目。
        """
        taipei = pytz.timezone("Asia/Taipei")
        now = datetime.now(taipei)

        # 嘗試從 notes 解析或是 reporter_info 獲取
        issue_id = reporter_info.get("issue_id", "UNKNOWN")
        
        # 處理結果建議儲存在 Asana 的某個地方，這裡假設從任務 description 或是特定的 notes 區塊獲取
        # 如果 Asana 有 Custom Fields，可以從 task.get("custom_fields") 抓取
        resolution = self._extract_resolution(task)

        entry = {
            "entry_id": issue_id,
            "category": reporter_info.get("category_label", "其他"),
            "problem": task.get("name", ""),
            "resolution": resolution,
            "priority": reporter_info.get("priority", "P3"),
            "reporter": reporter_info.get("reporter_name", ""),
            "reporter_email": reporter_info.get("email", ""),
            "created_at": task.get("created_at"),
            "resolved_at": now.isoformat(),
            "asana_task_gid": task.get("gid"),
            "keywords": self._generate_keywords(task.get("name", ""), resolution),
        }
        return entry

    async def save_to_sharepoint(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        將知識條目上傳至 SharePoint。
        """
        issue_id = entry.get("entry_id", "UNKNOWN")
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
