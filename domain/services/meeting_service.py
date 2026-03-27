"""
會議管理業務邏輯服務
重構自原始 app.py 中的會議相關功能
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from domain.models.user import UserProfile
from domain.repositories.user_repository import UserRepository
from config.settings import AppConfig
from shared.exceptions import BusinessLogicError, NotFoundError
from shared.utils.helpers import get_taiwan_time
from config.meeting_rooms import get_meeting_rooms as cfg_get_meeting_rooms
import pytz
from infrastructure.external.graph_api_client import GraphAPIClient


class MeetingService:
    """會議管理業務邏輯服務"""

    def __init__(
        self,
        config: AppConfig,
        user_repository: UserRepository,
        graph_client: GraphAPIClient,
    ):
        self.config = config
        self.user_repository = user_repository
        self.graph_client = graph_client

    async def get_meeting_rooms(self) -> List[Dict[str, str]]:
        """獲取可用會議室列表（displayName + emailAddress）。"""
        return cfg_get_meeting_rooms()

    async def book_meeting_room(
        self, user_mail: str, booking_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """預約會議室（表單資料物件）

        booking_data keys:
        - room_id: str (room emailAddress)
        - date: str (YYYY-MM-DD)
        - start_time: str (HH:MM)
        - end_time: str (HH:MM)
        - subject: str (optional)
        """
        # 驗證用戶
        user = await self.user_repository.get_profile(user_mail)
        if not user:
            # 若無用戶資料，建立基本檔案以便後續顯示名稱使用
            user = await self.user_repository.get_or_create_profile(
                user_mail, display_name=user_mail.split("@")[0]
            )

        room_id = (booking_data or {}).get("room_id") or (booking_data or {}).get(
            "selectedRoom"
        )
        date_str = (booking_data or {}).get("date") or (booking_data or {}).get(
            "selectedDate"
        )
        start_str = (booking_data or {}).get("start_time") or (booking_data or {}).get(
            "startTime"
        )
        end_str = (booking_data or {}).get("end_time") or (booking_data or {}).get(
            "endTime"
        )
        subject = (
            (booking_data or {}).get("subject")
            or (booking_data or {}).get("meetingSubject")
            or "會議"
        )

        if not all([room_id, date_str, start_str, end_str]):
            return {
                "success": False,
                "error": "缺少必要的預約資訊（會議室/日期/開始/結束時間）",
            }

        # 會議室驗證與名稱查找
        rooms = await self.get_meeting_rooms()
        room_entry = next((r for r in rooms if r.get("emailAddress") == room_id), None)
        if not room_entry:
            return {"success": False, "error": "選擇的會議室不存在"}

        # 解析時間（台灣時區）
        try:
            tz = pytz.timezone("Asia/Taipei")
            start_dt = tz.localize(
                datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M")
            )
            end_dt = tz.localize(
                datetime.strptime(f"{date_str} {end_str}", "%Y-%m-%d %H:%M")
            )
        except Exception:
            return {"success": False, "error": "日期或時間格式不正確"}

        now = get_taiwan_time()
        # 僅檢查結束時間是否晚於開始時間，不再限制是否為過去時間
        if start_dt >= end_dt:
            return {"success": False, "error": "開始時間必須早於結束時間"}

        # 呼叫 Graph API 創建實際會議（以使用者為 organizer）
        try:
            async with self.graph_client as gclient:
                result = await gclient.create_meeting(
                    user_email=user_mail,
                    subject=subject,
                    start_time=start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    end_time=end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    location=room_entry.get("displayName"),
                    attendees=[],  # 可擴充外部傳入
                    room_email=room_id,
                )

            # 正常情況 Graph 會回傳 event 物件
            booking_info = {
                "id": result.get("id"),
                "user_mail": user_mail,
                "user_name": user.display_name,
                "room_id": room_id,
                "room_name": room_entry.get("displayName"),
                "subject": subject,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "status": "confirmed",
                "created_at": now.isoformat(),
            }
            return {"success": True, "booking": booking_info}
        except Exception as e:
            return {"success": False, "error": f"建立會議失敗：{e}"}

    async def get_user_meetings(
        self, user_mail: str, days_ahead: int = 7
    ) -> List[Dict[str, Any]]:
        """獲取用戶的會議安排（使用 Graph calendarView，台灣時區）。"""
        tz = pytz.timezone("Asia/Taipei")
        now = get_taiwan_time()
        end_dt = now + timedelta(days=days_ahead)

        # 依原始作法使用 calendarView 並傳入 +08:00 字串
        start_str = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")

        # 會議室 email 列表（以 email 篩選會議室預約）
        rooms = await self.get_meeting_rooms()
        room_email_set = {r.get("emailAddress", "").lower() for r in rooms}

        try:
            async with self.graph_client as gclient:
                events = await gclient.get_user_calendar(
                    user_email=user_mail,
                    start_time=start_str,
                    end_time=end_str,
                    select="id,subject,start,end,location,organizer,attendees",
                )

            results: List[Dict[str, Any]] = []

            for ev in events:
                attendees = ev.get("attendees", []) or []
                # 是否包含任一會議室資源
                has_room = False
                matched_room_name = None
                for a in attendees:
                    addr = (
                        ((a or {}).get("emailAddress") or {}).get("address", "").lower()
                    )
                    if addr in room_email_set:
                        has_room = True
                        # 找出對應的顯示名稱
                        matched = next(
                            (
                                r
                                for r in rooms
                                if r.get("emailAddress", "").lower() == addr
                            ),
                            None,
                        )
                        matched_room_name = (
                            matched.get("displayName") if matched else None
                        )
                        break

                if not has_room:
                    continue

                # 解析時間：若 Graph 回傳已為台灣時間（header Prefer 設為 Taipei），則不再額外 +8
                # 若包含 Z 或明確時區偏移，才轉為台灣時區
                def parse_to_local(dt_dict: dict) -> Optional[datetime]:
                    s = ((dt_dict or {}).get("dateTime") or "").strip()
                    if not s:
                        return None
                    s2 = s.replace("Z", "+00:00")
                    try:
                        dtp = datetime.fromisoformat(s2)
                    except Exception:
                        return None
                    if dtp.tzinfo is None:
                        # 無時區資訊：視為已是台灣時間（因為我們在請求中帶了 Prefer: Taipei）
                        try:
                            return tz.localize(dtp)
                        except Exception:
                            return dtp
                    else:
                        return dtp.astimezone(tz)

                dt_start_tw = parse_to_local(ev.get("start"))
                dt_end_tw = parse_to_local(ev.get("end"))
                if not dt_start_tw or not dt_end_tw:
                    continue

                # 僅保留未來的預約
                if dt_start_tw <= now:
                    continue

                # 友善格式：日期/時間分離，卡片會直接印字串
                date_str = dt_start_tw.strftime("%Y/%m/%d (%a)")
                time_str = f"{dt_start_tw.strftime('%H:%M')} - {dt_end_tw.strftime('%H:%M')}"

                # 判斷是否為發起人（Organizer）
                organizer_email = (
                    ((ev.get("organizer") or {}).get("emailAddress") or {}).get("address", "")
                ).lower()
                is_organizer = organizer_email == (user_mail or "").lower()

                results.append(
                    {
                        "id": ev.get("id"),
                        "subject": ev.get("subject") or "會議",
                        "location": matched_room_name
                        or ((ev.get("location") or {}).get("displayName") or "會議室"),
                        "is_organizer": is_organizer,
                        # 供不同卡片/場景使用的字串欄位
                        "date": date_str,
                        "start_time": dt_start_tw.strftime("%Y-%m-%d %H:%M"),
                        "end_time": dt_end_tw.strftime("%Y-%m-%d %H:%M"),
                        # 也保留原始 ISO 以便後續可能使用
                        "start_iso": dt_start_tw.isoformat(),
                        "end_iso": dt_end_tw.isoformat(),
                    }
                )

            # 依開始時間排序
            results.sort(key=lambda x: x.get("start_iso", ""))
            return results

        except Exception as e:
            # 回退：出錯時回傳空列表，避免影響 UI
            print(f"取得我的預約失敗：{e}")
            return []

    async def list_meeting_rooms_graph(self) -> List[Dict[str, Any]]:
        """使用 Graph API 取得會議室列表。"""
        try:
            async with self.graph_client as gclient:
                resp = await gclient.list_meeting_rooms()
                return resp
        except Exception as e:
            print(f"取得會議室列表失敗：{e}")
            return []

    async def check_room_availability(
        self, room_emails: List[str], start_time: str, end_time: str
    ) -> Dict[str, Any]:
        """使用 Graph API 取得多間會議室可用性。時間格式建議 YYYY-MM-DDTHH:MM:SS+08:00。"""
        try:
            async with self.graph_client as gclient:
                return await gclient.get_room_availability(
                    room_emails, start_time, end_time
                )
        except Exception as e:
            print(f"檢查會議室可用性失敗：{e}")
            return {"value": []}

    async def cancel_meeting(self, user_mail: str, booking_id: str) -> Dict[str, Any]:
        """取消或退出會議（依角色決策）。

        - 若使用者是 Organizer：呼叫 cancel API 取消整個會議並通知與會者。
        - 若使用者是 Attendee：預設執行「拒絕並移除自己行事曆」不影響其他人。
        """
        if not booking_id:
            return {"success": False, "error": "缺少會議 ID"}

        try:
            async with self.graph_client as gclient:
                # 先讀事件，判斷是否為發起人
                ev = await gclient.get_event(user_mail, booking_id, select="id,organizer,subject,start,end")
                organizer_email = (((ev.get("organizer") or {}).get("emailAddress") or {}).get("address") or "").lower()
                is_organizer = organizer_email == (user_mail or "").lower()

                if is_organizer:
                    await gclient.cancel_meeting(user_mail, booking_id, message="Cancelled via TR GPT")
                    action = "cancelled_all"
                    note = "已取消整個會議並通知與會者"
                else:
                    # 與會者：拒絕並刪除自己行事曆中的事件
                    await gclient.decline_event(user_mail, booking_id, comment="Declined via TR GPT", send_response=True)
                    await gclient.delete_event(user_mail, booking_id)
                    action = "declined_self"
                    note = "已取消參與（不影響其他人），並自行從行事曆移除"

            return {
                "success": True,
                "cancellation": {
                    "event_id": booking_id,
                    "by": user_mail,
                    "action": action,
                    "note": note,
                    "timestamp": get_taiwan_time().isoformat(),
                },
            }
        except Exception as e:
            msg = str(e)
            if " 403" in msg or "403" in msg:
                friendly = "無權限執行此操作"
            elif " 404" in msg or "404" in msg:
                friendly = "找不到該會議，可能已被移除"
            else:
                friendly = f"操作失敗：{msg}"
            return {"success": False, "error": friendly}
