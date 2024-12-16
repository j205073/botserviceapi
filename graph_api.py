import aiohttp
from datetime import datetime, timedelta
import json
import os
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
        endpoint = f"{self.base_url}/users/{aad_object_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, headers=self._get_headers()) as response:
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
        location: str,
        room_email: str,
        subject: str,
        start_time: datetime,
        end_time: datetime,
        attendees: list,
    ) -> Dict[str, Any]:
        """建立會議"""
        endpoint = f"{self.base_url}/users/{room_email}/calendar/events"

        data = {
            "subject": subject,
            "start": {"dateTime": start_time.isoformat(), "timeZone": "Asia/Taipei"},
            "end": {"dateTime": end_time.isoformat(), "timeZone": "Asia/Taipei"},
            "location": {"displayName": location},
            "attendees": [
                {"emailAddress": {"address": attendee}, "type": "required"}
                for attendee in attendees
            ],
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
