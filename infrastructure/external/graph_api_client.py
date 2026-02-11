"""
Microsoft Graph API 客戶端封裝
處理與 Microsoft Graph API 的所有互動，包括用戶資訊、會議室預約等
"""

import asyncio
from typing import List, Dict, Any, Optional
import re
import aiohttp
from datetime import datetime, timedelta
import json

from config.settings import AppConfig
from shared.exceptions import GraphAPIError, AuthenticationError
from shared.utils.helpers import AsyncRetry
from infrastructure.external.token_manager import TokenManager


class GraphAPIClient:
    """Microsoft Graph API 客戶端"""

    def __init__(self, config: AppConfig, token_manager: TokenManager):
        self.config = config
        self.token_manager = token_manager
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """異步上下文管理器入口"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """異步上下文管理器退出"""
        if self.session:
            await self.session.close()

    async def _get_headers(self) -> Dict[str, str]:
        """獲取請求標頭"""
        token = await self.token_manager.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _ensure_session(self) -> None:
        """確保 aiohttp session 已初始化（允許非 async with 也可使用）。"""
        if self.session is None:
            self.session = aiohttp.ClientSession()

    @AsyncRetry(max_attempts=3, delay=1.0, backoff=2.0)
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """發送 HTTP 請求"""
        await self._ensure_session()

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = await self._get_headers()

        # 針對會議/行事曆查詢加上 Outlook 時區偏好（Taipei Standard Time）
        try:
            ep_lower = endpoint.lower()
            is_calendar_get = (
                method.upper() == "GET"
                and (
                    "calendarview" in ep_lower
                    or "/events" in ep_lower
                    or "calendar" in ep_lower
                )
            )
            # getSchedule/findMeetingTimes 雖為 POST，但屬查詢性質
            is_schedule_query = ("getschedule" in ep_lower) or ("findmeetingtimes" in ep_lower)
            if is_calendar_get or is_schedule_query:
                headers["Prefer"] = "outlook.timezone=\"Taipei Standard Time\""
        except Exception:
            pass

        try:
            async with self.session.request(
                method, url, headers=headers, json=data, params=params
            ) as response:
                response_text = await response.text()

                if response.status == 401:
                    raise AuthenticationError("Graph API 認證失敗")
                elif response.status >= 400:
                    raise GraphAPIError(
                        f"Graph API 請求失敗: {response.status} - {response_text}"
                    )

                if response_text:
                    return json.loads(response_text)
                return {}

        except json.JSONDecodeError as e:
            raise GraphAPIError(f"解析 Graph API 回應失敗: {str(e)}")
        except Exception as e:
            raise GraphAPIError(f"Graph API 請求異常: {str(e)}") from e

    async def _make_request_no_retry(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        return_none_on_404: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """發送 HTTP 請求（不重試版本），可選擇遇到 404 時回傳 None。

        用於某些非必然存在的資源（如 /manager、/photo），避免 404 被重試拖慢回應。
        """
        await self._ensure_session()

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = await self._get_headers()

        # 行事曆/會議查詢時加入 Prefer 時區
        try:
            ep_lower = endpoint.lower()
            is_calendar_get = (
                method.upper() == "GET"
                and (
                    "calendarview" in ep_lower or "/events" in ep_lower or "calendar" in ep_lower
                )
            )
            is_schedule_query = ("getschedule" in ep_lower) or ("findmeetingtimes" in ep_lower)
            if is_calendar_get or is_schedule_query:
                headers["Prefer"] = "outlook.timezone=\"Taipei Standard Time\""
        except Exception:
            pass

        async with self.session.request(
            method, url, headers=headers, json=data, params=params
        ) as response:
            text = await response.text()
            if response.status == 404 and return_none_on_404:
                return None
            if response.status == 401:
                raise AuthenticationError("Graph API 認證失敗")
            if response.status >= 400:
                raise GraphAPIError(f"Graph API 請求失敗: {response.status} - {text}")
            return json.loads(text) if text else {}

    async def get_user_info(
        self, user_email: str, select: Optional[str] = None
    ) -> Dict[str, Any]:
        """獲取用戶資訊

        備註：Graph 預設不會回傳所有欄位。若需要部門（department）等欄位，
        必須使用 $select 指定，且應用需具備足夠權限（例如：User.Read.All）。
        """
        try:
            endpoint = f"users/{user_email}"
            # 預設選取常用欄位，包含單位名稱（department）
            default_select = (
                "id,displayName,userPrincipalName,mail,jobTitle,department,"
                "companyName,officeLocation,mobilePhone,businessPhones,employeeId,preferredLanguage"
            )
            params = {"$select": select or default_select}
            return await self._make_request("GET", endpoint, params=params)
        except Exception as e:
            raise GraphAPIError(f"獲取用戶資訊失敗: {str(e)}") from e

    async def get_user_rich_profile(self, user_id_or_upn: str) -> Dict[str, Any]:
        """獲取更完整的用戶資料（含單位與延伸屬性）。

        包含欄位：
        - 基本：id, displayName, userPrincipalName, mail, jobTitle
        - 單位：department, companyName, employeeOrgData(costCenter/division)
        - 位置/電話：officeLocation, businessPhones, mobilePhone
        - 延伸：employeeId, onPremisesExtensionAttributes (extensionAttribute1..15)

        權限要求（Application 建議）：User.Read.All，若需要群組/管理者再加 Group.Read.All、Directory.Read.All。
        """
        try:
            endpoint = f"users/{user_id_or_upn}"
            select = (
                "id,displayName,userPrincipalName,mail,jobTitle,department,companyName,"
                "officeLocation,businessPhones,mobilePhone,employeeId,employeeOrgData,"
                "onPremisesExtensionAttributes"
            )
            params = {"$select": select}
            return await self._make_request("GET", endpoint, params=params)
        except Exception as e:
            raise GraphAPIError(f"獲取完整用戶資料失敗: {str(e)}") from e

    async def get_user_member_of(self, user_id_or_upn: str) -> List[Dict[str, Any]]:
        """取得使用者所屬群組（可用於推斷單位/部門）。

        注意：/memberOf 會回傳各種 directoryObject；這裡僅回傳有 displayName 的項目。
        權限：Group.Read.All 或 Directory.Read.All（Application）。
        """
        try:
            endpoint = f"users/{user_id_or_upn}/memberOf"
            params = {"$select": "id,displayName"}
            resp = await self._make_request("GET", endpoint, params=params)
            items = resp.get("value", [])
            return [g for g in items if g.get("displayName")]
        except Exception as e:
            raise GraphAPIError(f"獲取使用者群組失敗: {str(e)}") from e

    async def get_user_manager(self, user_id_or_upn: str) -> Optional[Dict[str, Any]]:
        """取得使用者的直屬主管。

        權限：User.Read.All 或 Directory.Read.All（Application）。
        """
        try:
            endpoint = f"users/{user_id_or_upn}/manager"
            params = {"$select": "id,displayName,mail,userPrincipalName,jobTitle"}
            # 使用不重試版本，且 404 時回傳 None，避免多次重試拖延
            return await self._make_request_no_retry(
                "GET", endpoint, params=params, return_none_on_404=True
            )
        except GraphAPIError:
            # 若權限不足（403）等，回傳 None
            return None
        except Exception as e:
            raise GraphAPIError(f"獲取使用者主管失敗: {str(e)}") from e

    async def get_user_open_extensions(
        self, user_id_or_upn: str
    ) -> List[Dict[str, Any]]:
        """讀取使用者 Open Extensions（若貴司用自訂欄位存分機/其他資訊）。

        注意：需要知道擴展的 ID 命名規則（通常是 ext{appId}_{name}）。
        權限：User.Read.All 或 Directory.Read.All。
        """
        try:
            endpoint = f"users/{user_id_or_upn}/extensions"
            resp = await self._make_request("GET", endpoint)
            return resp.get("value", [])
        except Exception as e:
            raise GraphAPIError(f"讀取使用者 Open Extensions 失敗: {str(e)}") from e

    def try_extract_extension(
        self, user_profile: Dict[str, Any], candidate_attrs: Optional[List[str]] = None
    ) -> Optional[str]:
        """嘗試從用戶資料中解析分機號碼。

        解析順序：
        1) onPremisesExtensionAttributes.extensionAttributeX（常見做法）
        2) businessPhones 文字中的 ext/x/# 樣式
        """
        # 1) onPremisesExtensionAttributes
        ext_attrs = user_profile.get("onPremisesExtensionAttributes") or {}
        if candidate_attrs is None:
            candidate_attrs = [
                "extensionAttribute1",
                "extensionAttribute2",
                "extensionAttribute3",
                "extensionAttribute4",
                "extensionAttribute5",
            ]
        for key in candidate_attrs:
            val = (ext_attrs or {}).get(key)
            if val and re.fullmatch(r"\d{3,6}", str(val).strip()):
                return str(val).strip()

        # 2) businessPhones pattern，例如: 02-1234-5678 ext 3456 / x3456 / #3456
        for phone in user_profile.get("businessPhones") or []:
            if not phone:
                continue
            m = re.search(r"(?:ext\.?|x|#)\s*(\d{3,6})", str(phone), re.IGNORECASE)
            if m:
                return m.group(1)

        return None

    async def get_user_photo(self, user_email: str) -> Optional[bytes]:
        """獲取用戶照片"""
        try:
            endpoint = f"users/{user_email}/photo/$value"

            await self._ensure_session()

            headers = await self._get_headers()
            url = f"{self.base_url}/{endpoint}"

            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.read()
                return None

        except Exception as e:
            print(f"獲取用戶照片失敗: {e}")
            return None

    async def list_meeting_rooms(self) -> List[Dict[str, Any]]:
        """列出會議室"""
        try:
            # 查詢會議室資源
            endpoint = "places/microsoft.graph.room"
            response = await self._make_request("GET", endpoint)
            return response.get("value", [])
        except Exception as e:
            raise GraphAPIError(f"獲取會議室列表失敗: {str(e)}") from e

    async def get_available_rooms(self) -> List[Dict[str, Any]]:
        """取得可用會議室清單（與 app_bak 介面對齊）。

        回傳格式：List[ { displayName, emailAddress, ... } ]
        """
        return await self.list_meeting_rooms()

    async def get_room_availability(
        self, room_emails: List[str], start_time: str, end_time: str
    ) -> Dict[str, Any]:
        """檢查會議室可用性"""
        try:
            data = {
                "schedules": room_emails,
                "startTime": {"dateTime": start_time, "timeZone": "Asia/Taipei"},
                "endTime": {"dateTime": end_time, "timeZone": "Asia/Taipei"},
                "availabilityViewInterval": 15,
            }

            endpoint = "calendar/getSchedule"
            return await self._make_request("POST", endpoint, data)
        except Exception as e:
            raise GraphAPIError(f"檢查會議室可用性失敗: {str(e)}") from e

    async def get_room_schedule(
        self, room_email: str, start_time: str, end_time: str
    ) -> Dict[str, Any]:
        """查詢單一會議室的行程（包裝成單室版）。"""
        return await self.get_room_availability([room_email], start_time, end_time)

    async def create_meeting(
        self,
        user_email: str,
        subject: str,
        start_time: str,
        end_time: str,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        body: Optional[str] = None,
        room_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """創建會議"""
        try:
            attendee_list = []
            if attendees:
                for email in attendees:
                    attendee_list.append(
                        {
                            "emailAddress": {
                                "address": email,
                                "name": email.split("@")[0],
                            }
                        }
                    )

            # include room as resource attendee when provided
            if room_email:
                attendee_list.append(
                    {"emailAddress": {"address": room_email}, "type": "resource"}
                )

            meeting_data = {
                "subject": subject,
                "start": {"dateTime": start_time, "timeZone": "Asia/Taipei"},
                "end": {"dateTime": end_time, "timeZone": "Asia/Taipei"},
                "attendees": attendee_list,
            }

            if location:
                meeting_data["location"] = {"displayName": location}

            if body:
                meeting_data["body"] = {"contentType": "HTML", "content": body}

            endpoint = f"users/{user_email}/calendar/events"
            return await self._make_request("POST", endpoint, meeting_data)
        except Exception as e:
            raise GraphAPIError(f"創建會議失敗: {str(e)}") from e

    async def book_meeting(
        self,
        organizer_email: str,
        room_email: str,
        subject: str,
        start_time: str,
        end_time: str,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        body: Optional[str] = None,
    ) -> Dict[str, Any]:
        """高階 API：建立會議並將 room 當作資源與會者加入。"""
        return await self.create_meeting(
            user_email=organizer_email,
            subject=subject,
            start_time=start_time,
            end_time=end_time,
            location=location,
            attendees=attendees,
            body=body,
            room_email=room_email,
        )

    async def get_user_calendar(
        self,
        user_email: str,
        start_time: str,
        end_time: str,
        select: str = "id,subject,start,end,location,organizer,attendees",
    ) -> List[Dict[str, Any]]:
        """取得用戶行事曆事件（時間區間）。時間字串使用 ISO 格式（建議 +08:00）。"""
        try:
            endpoint = f"users/{user_email}/calendarView"
            params = {
                "startDateTime": start_time,
                "endDateTime": end_time,
                "$select": select,
                "$orderby": "start/dateTime",
            }
            resp = await self._make_request("GET", endpoint, params=params)
            return resp.get("value", [])
        except Exception as e:
            raise GraphAPIError(f"獲取用戶行事曆失敗: {str(e)}") from e

    async def get_user_by_id(self, aad_object_id: str) -> Dict[str, Any]:
        """使用 AAD Object Id 取得用戶資訊（對齊 app_bak 行為）。"""
        try:
            endpoint = f"users/{aad_object_id}"
            return await self._make_request("GET", endpoint)
        except Exception as e:
            raise GraphAPIError(f"使用 ObjectId 獲取用戶資訊失敗: {str(e)}") from e

    async def get_user_meetings(
        self,
        user_email: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """獲取用戶的會議"""
        try:
            endpoint = f"users/{user_email}/calendar/events"

            params = {}
            if start_date and end_date:
                params["$filter"] = (
                    f"start/dateTime ge '{start_date}' and end/dateTime le '{end_date}'"
                )

            params["$select"] = "id,subject,start,end,location,organizer,attendees"
            params["$orderby"] = "start/dateTime"

            response = await self._make_request("GET", endpoint, params=params)
            return response.get("value", [])
        except Exception as e:
            raise GraphAPIError(f"獲取用戶會議失敗: {str(e)}") from e

    async def get_event(
        self, user_email: str, event_id: str, select: Optional[str] = None
    ) -> Dict[str, Any]:
        """取得單一事件詳情（在使用者的行事曆範圍內）。

        預設僅取 organizer 與關鍵欄位；可用 select 覆寫。
        """
        try:
            endpoint = f"users/{user_email}/events/{event_id}"
            params = {"$select": select or "id,subject,organizer,start,end,location,attendees"}
            return await self._make_request("GET", endpoint, params=params)
        except Exception as e:
            raise GraphAPIError(f"取得事件詳情失敗: {str(e)}") from e

    async def cancel_meeting(
        self, user_email: str, event_id: str, message: Optional[str] = None
    ) -> bool:
        """取消會議"""
        try:
            data = {}
            if message:
                data["comment"] = message

            endpoint = f"users/{user_email}/calendar/events/{event_id}/cancel"
            await self._make_request("POST", endpoint, data)
            return True
        except Exception as e:
            raise GraphAPIError(f"取消會議失敗: {str(e)}") from e

    async def decline_event(
        self,
        user_email: str,
        event_id: str,
        comment: Optional[str] = None,
        send_response: bool = True,
    ) -> bool:
        """與會者拒絕參與某事件。

        僅影響該使用者的回覆狀態；是否保留事件顯示於行事曆取決於客戶端設定。
        """
        try:
            endpoint = f"users/{user_email}/events/{event_id}/decline"
            data: Dict[str, Any] = {"sendResponse": send_response}
            if comment:
                data["comment"] = comment
            await self._make_request("POST", endpoint, data)
            return True
        except Exception as e:
            raise GraphAPIError(f"拒絕會議失敗: {str(e)}") from e

    async def delete_event(self, user_email: str, event_id: str) -> bool:
        """從使用者的行事曆刪除此事件（不會取消整個會議）。"""
        try:
            endpoint = f"users/{user_email}/events/{event_id}"
            await self._make_request("DELETE", endpoint)
            return True
        except Exception as e:
            raise GraphAPIError(f"刪除事件失敗: {str(e)}") from e

    async def update_meeting(
        self, user_email: str, event_id: str, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """更新會議"""
        try:
            endpoint = f"users/{user_email}/calendar/events/{event_id}"
            return await self._make_request("PATCH", endpoint, updates)
        except Exception as e:
            raise GraphAPIError(f"更新會議失敗: {str(e)}") from e

    async def find_meeting_times(
        self,
        organizer_email: str,
        attendees: List[str],
        duration_minutes: int = 60,
        max_candidates: int = 20,
    ) -> List[Dict[str, Any]]:
        """尋找會議時間"""
        try:
            attendee_list = []
            for email in attendees:
                attendee_list.append({"emailAddress": {"address": email}})

            data = {
                "attendees": attendee_list,
                "timeConstraint": {
                    "timeslots": [
                        {
                            "start": {
                                "dateTime": datetime.now().strftime(
                                    "%Y-%m-%dT09:00:00"
                                ),
                                "timeZone": "Asia/Taipei",
                            },
                            "end": {
                                "dateTime": (
                                    datetime.now() + timedelta(days=7)
                                ).strftime("%Y-%m-%dT18:00:00"),
                                "timeZone": "Asia/Taipei",
                            },
                        }
                    ]
                },
                "meetingDuration": f"PT{duration_minutes}M",
                "maxCandidates": max_candidates,
            }

            endpoint = f"users/{organizer_email}/calendar/getSchedule"
            return await self._make_request("POST", endpoint, data)
        except Exception as e:
            raise GraphAPIError(f"尋找會議時間失敗: {str(e)}") from e

    async def get_organization_info(self) -> Dict[str, Any]:
        """獲取組織資訊"""
        try:
            endpoint = "organization"
            response = await self._make_request("GET", endpoint)
            org_list = response.get("value", [])
            return org_list[0] if org_list else {}
        except Exception as e:
            raise GraphAPIError(f"獲取組織資訊失敗: {str(e)}") from e

    async def test_connection(self) -> Dict[str, Any]:
        """測試 Graph API 連接"""
        try:
            endpoint = "organization"
            response = await self._make_request("GET", endpoint)

            return {
                "success": True,
                "message": "Graph API 連接成功",
                "tenant_info": response.get("value", [{}])[0],
            }
        except Exception as e:
            return {"success": False, "error": str(e), "message": "Graph API 連接失敗"}

    # ── SharePoint 檔案上傳 ──────────────────────────────────────
    _site_id_cache: Dict[str, str] = {}

    async def _get_site_id(self, site_hostname: str, site_path: str) -> str:
        """根據 Hostname 與 Path 取得 SharePoint Site ID 並快取。"""
        cache_key = f"{site_hostname}:{site_path}"
        if cache_key in self._site_id_cache:
            return self._site_id_cache[cache_key]

        endpoint = f"sites/{site_hostname}:{site_path}"
        site_data = await self._make_request("GET", endpoint)
        site_id = site_data.get("id")
        if not site_id:
            raise GraphAPIError(f"無法取得 SharePoint Site ID: {site_hostname}:{site_path}")
        
        self._site_id_cache[cache_key] = site_id
        return site_id

    async def upload_to_sharepoint(
        self,
        site_hostname: str,
        site_path: str,
        file_path_in_drive: str,
        content: bytes,
        content_type: str = "application/json",
    ) -> Dict[str, Any]:
        """上傳檔案到 SharePoint Document Library。"""
        site_id = await self._get_site_id(site_hostname, site_path)
        endpoint = f"sites/{site_id}/drive/root:/{file_path_in_drive.lstrip('/')}:/content"
        
        await self._ensure_session()
        headers = await self._get_headers()
        headers["Content-Type"] = content_type
        
        url = f"{self.base_url}/{endpoint}"
        async with self.session.put(url, headers=headers, data=content) as resp:
            resp_text = await resp.text()
            if resp.status >= 400:
                raise GraphAPIError(f"SharePoint 檔案上傳失敗: {resp.status} - {resp_text}")
            return json.loads(resp_text) if resp_text else {}

