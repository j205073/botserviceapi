import aiohttp
from datetime import datetime, timedelta
import json
import os
import pytz
from typing import Optional, Dict, Any
from token_manager import TokenManager


class GraphAPI:
    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        self.base_url = "https://graph.microsoft.com/v1.0"

    async def get_user_calendar(
        self, user_mail: str, start_time: datetime, end_time: datetime
    ) -> Dict:
        """
        獲取使用者的行事曆資訊

        Args:
            user_mail: 使用者的電子郵件
            start_time: 開始時間
            end_time: 結束時間

        Returns:
            Dict: 行事曆事件列表
        """
        try:
            # 設定 API endpoint
            endpoint = (
                f"https://graph.microsoft.com/v1.0/users/{user_mail}/calendar/events"
            )

            # 設定查詢參數
            start_str = start_time.isoformat() + "Z"  # UTC 時間
            end_str = end_time.isoformat() + "Z"  # UTC 時間

            # 設定篩選條件
            params = {
                "$filter": f"start/dateTime ge '{start_str}' and end/dateTime le '{end_str}'",
                "$select": "id,subject,organizer,start,end,location",
                "$orderby": "start/dateTime",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    endpoint, headers=self._get_headers(), params=params
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        print(f"獲取行事曆失敗: {error_text}")
                        return None

        except Exception as e:
            print(f"獲取行事曆時發生錯誤: {str(e)}")
            return None

    def _get_headers(self) -> Dict[str, str]:
        """獲取 API 請求需要的 headers"""
        return {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json",
        }

    async def get_user_info(self, aad_object_id: str) -> Dict[str, Any]:
        """取得用戶資訊"""
        # 使用 $select 參數指定需要的欄位，確保取得完整資訊
        endpoint = f"{self.base_url}/users/{aad_object_id}"
        params = {
            "$select": "userPrincipalName,displayName,givenName,surname,department,jobTitle,companyName,businessPhones,mobilePhone,officeLocation,mail,employeeId"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, headers=self._get_headers(), params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    raise Exception(f"Failed to get user info: {text}")

    async def get_room_schedule(
        self, room_email: str, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """查詢會議室行事曆"""
        endpoint = f"{self.base_url}/users/{room_email}/calendar/getSchedule"

        data = {
            "schedules": [room_email],
            "startTime": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Asia/Taipei",
            },
            "endTime": {"dateTime": end_time.isoformat(), "timeZone": "Asia/Taipei"},
            "availabilityViewInterval": 30,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint, headers=self._get_headers(), json=data
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    raise Exception(f"Failed to get room schedule: {text}")

    async def create_meeting(
        self,
        organizer_email: str,
        location: str,
        room_email: str,
        subject: str,
        start_time: datetime,
        end_time: datetime,
        attendees: list = None,
    ) -> Dict[str, Any]:
        """建立會議"""
        endpoint = f"{self.base_url}/users/{organizer_email}/calendar/events"

        attendee_list = []
        if attendees:
            attendee_list.extend([
                {"emailAddress": {"address": attendee}, "type": "required"}
                for attendee in attendees
            ])
        
        # 添加會議室作為資源
        attendee_list.append({
            "emailAddress": {"address": room_email},
            "type": "resource"
        })

        data = {
            "subject": subject,
            "start": {"dateTime": start_time.isoformat(), "timeZone": "Asia/Taipei"},
            "end": {"dateTime": end_time.isoformat(), "timeZone": "Asia/Taipei"},
            "location": {"displayName": location},
            "attendees": attendee_list,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint, headers=self._get_headers(), json=data
            ) as response:
                if response.status == 201:
                    return await response.json()
                else:
                    text = await response.text()
                    raise Exception(f"Failed to create meeting: {text}")

    async def get_available_rooms(self) -> Dict[str, Any]:
        """取得可用會議室清單"""
        # 這裡需要根據實際的 AAD 設定來取得會議室清單
        # 可能需要查詢特定的 OU 或使用 findMeetingTimes API
        endpoint = f"{self.base_url}/places/microsoft.graph.room"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, headers=self._get_headers()) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    # 如果沒有權限查詢會議室，返回 Rinnai 會議室清單
                    return {
                        "value": [
                            {"displayName": "第一會議室", "emailAddress": "meetingroom01@rinnai.com.tw"},
                            {"displayName": "第二會議室", "emailAddress": "meetingroom02@rinnai.com.tw"},
                            {"displayName": "工廠大會議室", "emailAddress": "meetingroom04@rinnai.com.tw"},
                            {"displayName": "工廠小會議室", "emailAddress": "meetingroom05@rinnai.com.tw"},
                            {"displayName": "研修教室", "emailAddress": "meetingroom03@rinnai.com.tw"},
                            {"displayName": "公務車", "emailAddress": "rinnaicars@rinnai.com.tw"},
                        ]
                    }

    async def get_user_calendar_events(
        self, user_email: str, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """取得用戶的行事曆事件（包含會議室預約）- 保留向後兼容性"""
        endpoint = f"{self.base_url}/users/{user_email}/calendar/events"

        # 設定查詢參數
        start_str = start_time.isoformat()
        end_str = end_time.isoformat()

        params = {
            "$filter": f"start/dateTime ge '{start_str}' and end/dateTime le '{end_str}'",
            "$select": "id,subject,organizer,start,end,location,attendees",
            "$orderby": "start/dateTime",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                endpoint, headers=self._get_headers(), params=params
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    raise Exception(f"Failed to get calendar events: {text}")

    async def get_user_calendarView(
        self, user_email: str, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """使用 calendarView 取得用戶的行事曆事件（推薦使用）
        
        注意：start_time 和 end_time 必須是已經設定為台灣時區的時間
        函數內不做任何時區轉換處理
        """
        endpoint = f"{self.base_url}/users/{user_email}/calendarView"

        # 直接使用台灣時區格式 (+08:00)
        # 傳入前調用方必須已經將時間轉換為台灣時區
        start_str = start_time.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        end_str = end_time.strftime('%Y-%m-%dT%H:%M:%S+08:00')

        params = {
            "startDateTime": start_str,
            "endDateTime": end_str,
            "$select": "subject,start,end,organizer,attendees,id,location",
            "$orderby": "start/dateTime",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                endpoint, headers=self._get_headers(), params=params
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    raise Exception(f"Failed to get calendar view: {text}")

    async def delete_meeting(self, user_email: str, event_id: str) -> bool:
        """刪除會議"""
        endpoint = f"{self.base_url}/users/{user_email}/calendar/events/{event_id}"

        async with aiohttp.ClientSession() as session:
            async with session.delete(endpoint, headers=self._get_headers()) as response:
                if response.status == 204:  # 成功刪除
                    return True
                else:
                    text = await response.text()
                    raise Exception(f"Failed to delete meeting: {text}")
