"""
Meeting room configuration and helpers.

Provides a single place to manage the list of rooms used by cards and services.
Future changes (add/remove/rename rooms) should be done here or via env.
"""
from __future__ import annotations

import json
import os
from typing import List, Dict


DEFAULT_MEETING_ROOMS: List[Dict[str, str]] = [
    {"displayName": "第一會議室", "emailAddress": "meetingroom01@rinnai.com.tw"},
    {"displayName": "第二會議室", "emailAddress": "meetingroom02@rinnai.com.tw"},
    {"displayName": "工廠大會議室", "emailAddress": "meetingroom04@rinnai.com.tw"},
    {"displayName": "工廠小會議室", "emailAddress": "meetingroom05@rinnai.com.tw"},
    {"displayName": "研修教室", "emailAddress": "meetingroom03@rinnai.com.tw"},
    {"displayName": "公務車", "emailAddress": "rinnaicars@rinnai.com.tw"},
]


def get_meeting_rooms() -> List[Dict[str, str]]:
    """Return meeting rooms as a list of {displayName, emailAddress}.

    Priority:
    1) MEETING_ROOMS_JSON env (JSON array of objects with displayName/emailAddress)
    2) DEFAULT_MEETING_ROOMS in this file
    """
    env_json = os.getenv("MEETING_ROOMS_JSON")
    if env_json:
        try:
            data = json.loads(env_json)
            # Basic validation
            valid = [
                r for r in (data or [])
                if isinstance(r, dict) and r.get("displayName") and r.get("emailAddress")
            ]
            if valid:
                return valid
        except Exception:
            pass
    return list(DEFAULT_MEETING_ROOMS)

