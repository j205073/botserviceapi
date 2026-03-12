"""
SharePoint IT 知識庫查詢 API（獨立測試用）

啟動方式：
    python scripts/sharepoint_kb_api.py

測試用端點：
    GET  http://localhost:5050/api/kb                → 列出所有知識庫 JSON
    GET  http://localhost:5050/api/kb?year=2026       → 篩選特定年份
    GET  http://localhost:5050/api/kb?year=2026&month=03 → 篩選年+月
    GET  http://localhost:5050/api/kb/{issue_id}      → 取得單筆（如 IT2026031200001）

需要的環境變數（從 .env 載入）：
    TENANT_ID, CLIENT_ID, CLIENT_SECRET
    SHAREPOINT_SITE_HOSTNAME  (預設: rinnaitw.sharepoint.com)
    SHAREPOINT_SITE_PATH      (預設: /sites/IT)
    SHAREPOINT_ROOT_PATH      (預設: IT/Knowledge_Base)
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional

# 確保能 import 專案模組
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from quart import Quart, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Quart(__name__)

# ── Graph API Token 取得 ────────────────────────────────────────

TENANT_ID = os.getenv("TENANT_ID", "")
CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")

SITE_HOSTNAME = os.getenv("SHAREPOINT_SITE_HOSTNAME", "rinnaitw.sharepoint.com")
SITE_PATH = os.getenv("SHAREPOINT_SITE_PATH", "/sites/IT")
ROOT_PATH = os.getenv("SHAREPOINT_ROOT_PATH", "IT/Knowledge_Base")

_token_cache: dict = {}


async def _get_access_token() -> str:
    """透過 Client Credentials 取得 Graph API Token。"""
    import aiohttp

    cached = _token_cache.get("token")
    expires = _token_cache.get("expires", 0)
    import time
    if cached and time.time() < expires - 60:
        return cached

    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as resp:
            body = await resp.json()
            if "access_token" not in body:
                raise RuntimeError(f"Token 取得失敗: {body}")
            _token_cache["token"] = body["access_token"]
            _token_cache["expires"] = time.time() + int(body.get("expires_in", 3600))
            return body["access_token"]


async def _graph_get(endpoint: str, params: Optional[dict] = None) -> dict:
    """發送 GET 到 Graph API。"""
    import aiohttp

    token = await _get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = f"https://graph.microsoft.com/v1.0/{endpoint.lstrip('/')}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            text = await resp.text()
            if resp.status >= 400:
                return {"error": f"Graph API {resp.status}: {text}"}
            return json.loads(text) if text else {}


# ── SharePoint 存取 ─────────────────────────────────────────────

_site_id_cache: dict = {}


async def _get_site_id() -> str:
    if "id" in _site_id_cache:
        return _site_id_cache["id"]
    data = await _graph_get(f"sites/{SITE_HOSTNAME}:{SITE_PATH}")
    sid = data.get("id")
    if not sid:
        raise RuntimeError(f"無法取得 Site ID: {data}")
    _site_id_cache["id"] = sid
    return sid


async def _list_children(folder_path: str) -> list:
    """列出 SharePoint Drive 資料夾下的所有子項目。"""
    site_id = await _get_site_id()
    endpoint = f"sites/{site_id}/drive/root:/{folder_path.lstrip('/')}:/children"
    result = await _graph_get(endpoint, params={"$top": "1000"})
    return result.get("value", [])


async def _download_file(file_path: str) -> Optional[dict]:
    """從 SharePoint 下載 JSON 檔案並回傳 dict。"""
    import aiohttp

    site_id = await _get_site_id()
    endpoint = f"sites/{site_id}/drive/root:/{file_path.lstrip('/')}:/content"
    token = await _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/{endpoint}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            if resp.status >= 400:
                return None
            text = await resp.text()
            try:
                return json.loads(text)
            except Exception:
                return {"_raw": text}


# ── API 路由 ─────────────────────────────────────────────────────

@app.route("/api/kb", methods=["GET"])
async def list_knowledge_base():
    """
    列出知識庫 JSON。
    查詢參數:
        year  — 篩選年份 (e.g. 2026)
        month — 篩選月份 (e.g. 03), 需搭配 year
    """
    try:
        year_filter = request.args.get("year")
        month_filter = request.args.get("month")

        all_entries = []

        if year_filter and month_filter:
            # 直接讀取指定年月資料夾
            folder = f"{ROOT_PATH}/{year_filter}/{month_filter}"
            files = await _list_children(folder)
            for f in files:
                if f.get("name", "").endswith(".json"):
                    content = await _download_file(f"{folder}/{f['name']}")
                    if content:
                        all_entries.append(content)
        elif year_filter:
            # 列出該年份下的所有月份
            year_folder = f"{ROOT_PATH}/{year_filter}"
            months = await _list_children(year_folder)
            for m in months:
                if m.get("folder"):
                    month_path = f"{year_folder}/{m['name']}"
                    files = await _list_children(month_path)
                    for f in files:
                        if f.get("name", "").endswith(".json"):
                            content = await _download_file(f"{month_path}/{f['name']}")
                            if content:
                                all_entries.append(content)
        else:
            # 列出所有年份 → 月份 → JSON
            years = await _list_children(ROOT_PATH)
            for y in years:
                if y.get("folder"):
                    year_path = f"{ROOT_PATH}/{y['name']}"
                    months = await _list_children(year_path)
                    for m in months:
                        if m.get("folder"):
                            month_path = f"{year_path}/{m['name']}"
                            files = await _list_children(month_path)
                            for f in files:
                                if f.get("name", "").endswith(".json"):
                                    content = await _download_file(f"{month_path}/{f['name']}")
                                    if content:
                                        all_entries.append(content)

        return jsonify({
            "success": True,
            "count": len(all_entries),
            "data": all_entries,
        })
    except Exception as e:
        logger.exception("列出知識庫失敗")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/kb/<issue_id>", methods=["GET"])
async def get_knowledge_entry(issue_id: str):
    """
    取得單筆知識庫條目。
    issue_id 格式: IT{YYYYMMDDHHMM}{seq:04d}，例如 IT2026031215300001
    從 issue_id 解析年月來定位檔案路徑。
    """
    try:
        # 嘗試從 issue_id 解析年月: IT + YYYYMMDDHHMM + seq
        if issue_id.startswith("IT") and len(issue_id) >= 8:
            year = issue_id[2:6]
            month = issue_id[6:8]
            file_path = f"{ROOT_PATH}/{year}/{month}/{issue_id}.json"
            content = await _download_file(file_path)
            if content:
                return jsonify({"success": True, "data": content})

        # 若解析失敗或找不到，暴力搜尋（較慢）
        years = await _list_children(ROOT_PATH)
        for y in years:
            if not y.get("folder"):
                continue
            year_path = f"{ROOT_PATH}/{y['name']}"
            months = await _list_children(year_path)
            for m in months:
                if not m.get("folder"):
                    continue
                file_path = f"{year_path}/{m['name']}/{issue_id}.json"
                content = await _download_file(file_path)
                if content:
                    return jsonify({"success": True, "data": content})

        return jsonify({"success": False, "error": f"找不到 {issue_id}"}), 404
    except Exception as e:
        logger.exception("取得知識庫條目失敗")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/ping", methods=["GET"])
async def ping():
    return jsonify({"status": "ok", "service": "sharepoint-kb-api"})


# ── 啟動 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("KB_API_PORT", "5050"))
    print(f"🚀 SharePoint KB API 啟動中... http://localhost:{port}")
    print(f"   Site: {SITE_HOSTNAME}{SITE_PATH}")
    print(f"   Root: {ROOT_PATH}")
    print(f"   Endpoints:")
    print(f"     GET /api/kb              → 列出全部")
    print(f"     GET /api/kb?year=2026    → 篩選年份")
    print(f"     GET /api/kb?year=2026&month=03 → 篩選年+月")
    print(f"     GET /api/kb/{{issue_id}} → 取得單筆")
    print(f"     GET /ping                → 健康檢查")
    app.run(host="0.0.0.0", port=port)
