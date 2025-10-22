import os
import json
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import pytz

from .asana_client import AsanaClient
from .intent_classifier import ITIntentClassifier
from .cards import build_it_issue_card


class ITSupportService:
    """
    Orchestrates IT issue flow: card building, intent classification, and Asana task creation.
    """

    def __init__(self):
        self.asana = AsanaClient()
        self.classifier = ITIntentClassifier()
        # load taxonomy for cards
        self._taxonomy = self.classifier.categories
        self._recent_task_by_user: dict[str, dict] = {}
        self._bf_token_cache: dict[str, Any] = {}
        # Dedicated model for IT issue analysis (per-call override; does not affect global model)
        self.analysis_model: str = os.getenv("IT_ANALYSIS_MODEL", "gpt-5-nano").strip()

        # Static config from env or defaults
        # Fallback to known IDs from Postman collection if envs not set
        self.workspace_gid = os.getenv("ASANA_WORKSPACE_GID", "1208041237608650")
        self.project_gid = os.getenv("ASANA_PROJECT_GID", "1208327275974093")
        self.assignee_gid = os.getenv("ASANA_ASSIGNEE_GID", "1208683560453534")
        self.assignee_section_gid = os.getenv("ASANA_ASSIGNEE_SECTION_GID", "1211277485675681")

        # Optional: map priority to Asana Tag GIDs for label display in Asana
        # Configure via env: ASANA_TAG_P1, ASANA_TAG_P2, ASANA_TAG_P3, ASANA_TAG_P4
        self.priority_tag_map: dict[str, str] = {
            "P1": os.getenv("ASANA_TAG_P1", "").strip(),
            "P2": os.getenv("ASANA_TAG_P2", "").strip(),
            "P3": os.getenv("ASANA_TAG_P3", "").strip(),
            "P4": os.getenv("ASANA_TAG_P4", "").strip(),
        }
        # Fallback: a single tag to always apply regardless of priority when mapping not set
        self.default_priority_tag_gid: str = os.getenv("ASANA_PRIORITY_TAG_GID", "").strip()

    def build_issue_card(self, language: str, reporter_name: str, reporter_email: str):
        return build_it_issue_card(language, self._taxonomy, reporter_name, reporter_email)

    async def submit_issue(self, form: Dict[str, Any], reporter_name: str, reporter_email: str) -> Dict[str, Any]:
        """
        Create Asana task from submitted form. Auto-classify if no category selected.
        Returns a dict with success, task info, and message.
        """
        description = (form.get("description") or "").strip()
        # Always classify via OpenAI (fallback to keyword classifier internally)
        category_code = ""
        priority = (form.get("priority") or "P3").strip()

        if not description:
            return {"success": False, "error": "需求/問題說明不得為空"}

        # AI-based classification (uses IT_ANALYSIS_MODEL); fallback to keyword classifier
        category_code, category_label = await self._classify_issue_ai(description)

        # Generate issue ID with Taiwan time
        issue_id, dt_for_id = self._generate_issue_id()

        # task name and notes
        name = f"{issue_id} - {category_label}"

        # Localize created time to Taiwan time
        taipei = pytz.timezone("Asia/Taipei")
        created_at = datetime.now(taipei).strftime("%Y-%m-%d %H:%M 台北時間")
        # Try AI analysis for triage
        analysis_text = await self._try_analyze_issue(description, category_label, priority)

        notes = (
            f"單號: {issue_id}\n"
            f"提出人: {reporter_name} <{reporter_email}>\n"
            f"分類: {category_label} ({category_code})\n"
            f"優先順序: {priority}\n"
            f"建立來源: TR GPT bot\n"
            f"建立時間: {created_at}\n\n"
            f"【需求/問題說明】\n{description}\n"
            + ("\n【AI 分析（建議/時間/相關面向）】\n\n" + analysis_text + "\n" if analysis_text else "")
        )

        # build payload following Postman spec
        data = {
            "data": {
                "name": name,
                "resource_subtype": "default_task",
                "completed": False,
                "notes": notes,
                "assignee": self.assignee_gid,
                "workspace": self.workspace_gid,
            }
        }
        # Project + section mapping
        if self.project_gid:
            data["data"]["projects"] = [self.project_gid]
            if self.assignee_section_gid:
                data["data"]["memberships"] = [
                    {"project": self.project_gid, "section": self.assignee_section_gid}
                ]

        # Add priority tag if configured
        tag_gid = self.priority_tag_map.get(priority) or self.default_priority_tag_gid
        if tag_gid:
            data["data"]["tags"] = [tag_gid]

        try:
            result = await self.asana.create_task(data)
            task = result.get("data", {})
            link = task.get("permalink_url")
            gid = task.get("gid")
            # remember for quick attachment
            if gid:
                self._recent_task_by_user[reporter_email] = {"gid": gid, "ts": datetime.now(timezone.utc)}
            return {
                "success": True,
                "task_gid": gid,
                "permalink_url": link,
                "issue_id": issue_id,
                "message": f"您的需求已被受理，請耐心等候。單號：{issue_id}"
            }
        except Exception as e:
            return {"success": False, "error": f"建立 Asana 任務失敗：{str(e)}"}

    def _generate_issue_id(self) -> tuple[str, datetime]:
        """Generate an issue ID: IT{YYYYMMDDHHMM}{seq:04d}, seq resets daily.
        Stores state in local_audit_logs/it_issue_seq.json.
        Returns (issue_id, dt).
        """
        taipei = pytz.timezone("Asia/Taipei")
        now = datetime.now(taipei)
        date_str = now.strftime("%Y%m%d")
        dt_str = now.strftime("%Y%m%d%H%M")

        base_dir = Path("local_audit_logs")
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # ignore if cannot create; fallback to in-memory behavior
            pass

        state_path = base_dir / "it_issue_seq.json"
        last_date = None
        counter = 0
        try:
            if state_path.exists():
                with state_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    last_date = data.get("date")
                    counter = int(data.get("counter", 0))
        except Exception:
            # reset on error
            last_date, counter = None, 0

        if last_date != date_str:
            counter = 1
        else:
            counter += 1

        try:
            with state_path.open("w", encoding="utf-8") as f:
                json.dump({"date": date_str, "counter": counter}, f)
        except Exception:
            # ignore write errors
            pass

        issue_id = f"IT{dt_str}{counter:04d}"
        return issue_id, now

    async def _try_analyze_issue(self, description: str, category_label: str, priority: str) -> str:
        """Call OpenAI to analyze the issue. Return a concise multiline text.
        On failure, return empty string.
        """
        try:
            if not description:
                return ""
            # Lazy import to avoid hard dependency cycles
            from core.container import get_container
            from infrastructure.external.openai_client import OpenAIClient

            container = get_container()
            oa: OpenAIClient = container.get(OpenAIClient)

            system = (
                "你是一位企業 IT 服務台資深工程師，請針對使用者的 IT 問題"
                "提供：1) 簡短處理建議 2) 估計處理時間（小時/天，簡短） 3) 可能相關面向（如帳號權限、網路、軟硬體、系統設定、供應商、資料庫、API、身分認證等）。"
                "請只輸出 JSON，欄位為 recommendation, time_estimate, related_areas（陣列）。語言使用繁體中文。"
            )
            user = (
                f"分類: {category_label}\n"
                f"優先順序: {priority}\n"
                f"描述: {description}"
            )
            prompt = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            raw = await oa.chat_completion(
                prompt,
                model=(self.analysis_model or None),
                max_tokens=600,
                temperature=0.2,
            )

            # Parse JSON
            import json as _json
            data = None
            try:
                data = _json.loads(raw)
            except Exception:
                # Try extract JSON block
                import re
                m = re.search(r"\{[\s\S]*\}", raw)
                if m:
                    try:
                        data = _json.loads(m.group(0))
                    except Exception:
                        data = None
            if isinstance(data, dict):
                rec = str(data.get("recommendation", "")).strip()
                t = str(data.get("time_estimate", "")).strip()
                areas = data.get("related_areas")
                parts = []
                if rec:
                    import re as _re
                    _rec = rec.strip()
                    if _re.search(r"\b1\)", _rec):
                        _rec = _re.sub(r"\s*(\d+\))", r"\n  \1 ", _rec).strip()
                        parts.append("- 建議：\n  " + _rec)
                    else:
                        parts.append(f"- 建議：{_rec}")
                if t:
                    parts.append(f"- 時間估計：{t}")
                # 相關面向分行列點
                if isinstance(areas, list):
                    cleaned = [str(a).strip() for a in areas if str(a).strip()]
                    if cleaned:
                        area_lines = "\n".join([f"  - {a}" for a in cleaned])
                        parts.append("- 相關面向：\n" + area_lines)
                else:
                    single_area = str(areas or "").strip()
                    if single_area:
                        parts.append(f"- 相關面向：{single_area}")
                return "\n".join(parts).strip()
            else:
                # Fallback to raw text
                cleaned = str(raw).strip()
                if cleaned:
                    return cleaned
        except Exception:
            pass
        return ""

    async def _classify_issue_ai(self, description: str) -> tuple[str, str]:
        """Classify issue category via OpenAI using IT_ANALYSIS_MODEL.
        Returns (code, label). Falls back to keyword classifier on error.
        """
        try:
            if not description:
                return ("other", self.classifier._label_for("other"))

            from core.container import get_container
            from infrastructure.external.openai_client import OpenAIClient

            # Prepare categories for the model to choose
            allowed = [
                {"code": c.get("code", "other"), "label": c.get("label", c.get("code", "other"))}
                for c in self._taxonomy
            ]
            allowed_codes = [c["code"] for c in allowed]

            container = get_container()
            oa: OpenAIClient = container.get(OpenAIClient)

            system = (
                "你是一位企業 IT 服務台分單助手。請從提供的類別清單中選擇最符合的一個類別"
                "，只允許輸出 JSON，欄位為 code, label。code 必須是清單中的一個。語言使用繁體中文。"
            )
            import json as _json
            user = _json.dumps({
                "categories": allowed,
                "description": description,
            }, ensure_ascii=False)

            prompt = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            raw = await oa.chat_completion(
                prompt,
                model=(self.analysis_model or None),
                max_tokens=400,
                temperature=0.0,
            )

            data = None
            try:
                data = _json.loads(raw)
            except Exception:
                import re
                m = re.search(r"\{[\s\S]*\}", raw)
                if m:
                    try:
                        data = _json.loads(m.group(0))
                    except Exception:
                        data = None
            if isinstance(data, dict):
                code = str(data.get("code", "")).strip()
                label = str(data.get("label", "")).strip()
                if code in allowed_codes:
                    if not label:
                        label = next((c.get("label") for c in self._taxonomy if c.get("code") == code), code)
                    return (code, label)
        except Exception:
            pass

        # Fallback to keyword classifier
        return self.classifier.classify(description)

    def get_recent_task_gid(self, user_email: str) -> str | None:
        item = self._recent_task_by_user.get(user_email)
        if not item:
            return None
        return item.get("gid")

    async def attach_image_from_url(self, user_email: str, url: str, filename: str, mime_type: str) -> Dict[str, Any]:
        """Download image by URL and upload to recent task for user."""
        gid = self.get_recent_task_gid(user_email)
        if not gid:
            return {"success": False, "error": "找不到最近建立的 IT 單可供附檔，請先使用 @it 建立。"}

        import httpx
        headers: dict[str, str] = {}
        # Normalize filename: if it's exactly 'original', rename to 'original.png'
        try:
            if filename and filename.lower() == "original":
                filename = "original.png"
        except Exception:
            pass
        # For Teams/BotFramework protected URLs, try with bot token
        if self._is_botframework_protected_url(url):
            token = await self._get_botframework_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                headers["Accept"] = "*/*"
        try:
            resp_headers = None
            content = b""
            inferred_mime = None
            if self._is_sharepoint_url(url):
                content, resp_headers, inferred_name, inferred_mime = await self._download_sharepoint_file(url)
                if inferred_name and self._is_generic_filename(filename):
                    filename = inferred_name
                if inferred_mime:
                    mime_type = inferred_mime
            else:
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    resp_headers = resp.headers
                    content = resp.content
            # Try extract filename from Content-Disposition if our filename is generic
            try:
                if resp_headers:
                    cd = resp_headers.get("content-disposition") or resp_headers.get("Content-Disposition")
                    if cd and self._is_generic_filename(filename):
                        import re as _re
                        m = _re.search(r'filename\*=UTF-8''([^;\r\n]+)', cd)
                        if m:
                            from urllib.parse import unquote
                            filename = unquote(m.group(1))
                        else:
                            m = _re.search(r'filename="?([^";\r\n]+)"?', cd)
                            if m:
                                filename = m.group(1)
            except Exception:
                pass

            # If still generic, try derive extension from Content-Type header or magic
            try:
                if self._is_generic_filename(filename):
                    header_ctype = None
                    if resp_headers:
                        header_ctype = resp_headers.get("content-type") or resp_headers.get("Content-Type")
                    ctype = (header_ctype or inferred_mime or mime_type or "")
                    ctype = (ctype or "").split(";")[0].strip().lower()
                    ext_map = {
                        "image/png": "png",
                        "image/jpeg": "jpg",
                        "image/jpg": "jpg",
                        "image/gif": "gif",
                        "image/webp": "webp",
                        "image/bmp": "bmp",
                        "image/heic": "heic",
                        "application/pdf": "pdf",
                        "application/zip": "zip",
                        "text/plain": "txt",
                        "application/msword": "doc",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                        "application/vnd.ms-excel": "xls",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
                        "application/vnd.ms-powerpoint": "ppt",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
                    }
                    ext = ext_map.get(ctype)
                    if not ext:
                        # magic sniff
                        b = content
                        if b.startswith(b"\x89PNG\r\n\x1a\n"):
                            ext = "png"
                        elif b.startswith(b"\xff\xd8"):
                            ext = "jpg"
                        elif b.startswith(b"GIF8"):
                            ext = "gif"
                        elif b.startswith(b"RIFF") and b"WEBP" in b[:16]:
                            ext = "webp"
                        elif b.startswith(b"%PDF"):
                            ext = "pdf"
                        elif b.startswith(b"PK\x03\x04"):
                            ext = "zip"
                    if ext:
                        from datetime import datetime
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        # Preserve 'original' prefix rule earlier; otherwise synthesize
                        if filename and filename.lower() == "original":
                            filename = f"original.{ext}"
                        else:
                            filename = filename if (filename and "." in filename) else f"upload_{ts}.{ext}"
            except Exception:
                pass
        except Exception as e:
            return {"success": False, "error": f"下載附件失敗：{str(e)}"}

        try:
            result = await self.asana.upload_attachment(gid, filename, content, mime_type)
            return {"success": True, "message": "✅ 已上傳圖片至 IT 單", "data": result}
        except Exception as e:
            return {"success": False, "error": f"上傳附件失敗：{str(e)}"}

    async def attach_image_bytes(self, user_email: str, content: bytes, filename: str, mime_type: str) -> Dict[str, Any]:
        """Upload raw image bytes to the user's recent task."""
        gid = self.get_recent_task_gid(user_email)
        if not gid:
            return {"success": False, "error": "找不到最近建立的 IT 單可供附檔，請先使用 @it 建立。"}
        try:
            # Normalize filename: if it's exactly 'original', rename to 'original.png'
            try:
                if filename and filename.lower() == "original":
                    filename = "original.png"
            except Exception:
                pass
            # If filename looks generic, synthesize a better one from mime
            generic = (not filename) or (filename.lower() in ("file", "file.bin", "image", "image.jpg", "original", "upload", "upload.bin")) or ("." not in filename)
            if generic:
                ext_map = {
                    "image/png": "png",
                    "image/jpeg": "jpg",
                    "image/jpg": "jpg",
                    "image/gif": "gif",
                    "image/webp": "webp",
                    "image/bmp": "bmp",
                    "image/heic": "heic",
                    "application/pdf": "pdf",
                    "application/zip": "zip",
                    "text/plain": "txt",
                    "application/msword": "doc",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                    "application/vnd.ms-excel": "xls",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
                    "application/vnd.ms-powerpoint": "ppt",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
                }
                ext = ext_map.get((mime_type or "").lower(), "bin")
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"upload_{ts}.{ext}"
            result = await self.asana.upload_attachment(gid, filename, content, mime_type)
            return {"success": True, "message": "✅ 已上傳圖片至 IT 單", "data": result}
        except Exception as e:
            return {"success": False, "error": f"上傳附件失敗：{str(e)}"}

    def _is_botframework_protected_url(self, url: str) -> bool:
        try:
            from urllib.parse import urlparse
            host = urlparse(url).netloc.lower()
            protected_hosts = (
                "smba.trafficmanager.net",
                "skype",
                "teams.microsoft.com",
                "api.botframework.com",
            )
            return any(h in host for h in protected_hosts)
        except Exception:
            return False

    def _is_sharepoint_url(self, url: str) -> bool:
        try:
            from urllib.parse import urlparse
            host = urlparse(url).netloc.lower()
            return ("sharepoint.com" in host) or host.endswith("1drv.ms")
        except Exception:
            return False

    def _is_generic_filename(self, filename: Optional[str]) -> bool:
        try:
            if not filename:
                return True
            lower = filename.lower()
            if lower in ("file", "file.bin", "image", "image.jpg", "original", "upload", "upload.bin"):
                return True
            return "." not in filename
        except Exception:
            return True

    def _encode_sharepoint_share_id(self, url: str) -> str:
        raw_url = (url or "").strip()
        if not raw_url:
            raise ValueError("無法轉換 SharePoint URL")
        encoded = urlsafe_b64encode(raw_url.encode("utf-8")).decode("utf-8").rstrip("=")
        if not encoded:
            raise ValueError("無法轉換 SharePoint URL")
        if encoded.startswith("u!"):
            return encoded
        return f"u!{encoded}"

    async def _download_sharepoint_file(self, url: str):
        """Download SharePoint/OneDrive item via Graph shares API."""
        import httpx
        from core.container import get_container
        from infrastructure.external.token_manager import TokenManager

        container = get_container()
        try:
            token_manager: TokenManager = container.get(TokenManager)
        except Exception as exc:
            raise RuntimeError("無法取得 Graph Token 管理器，請確認環境設定。") from exc

        token = await token_manager.get_access_token()
        share_id = self._encode_sharepoint_share_id(url)
        base_url = f"https://graph.microsoft.com/v1.0/shares/{share_id}/driveItem"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
        }

        metadata = None
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            try:
                meta_resp = await client.get(base_url, headers=headers, params={"$select": "name,file"})
            except httpx.HTTPError as err:
                raise RuntimeError(f"連線 SharePoint 失敗：{err}") from err
            if meta_resp.status_code == 200:
                metadata = meta_resp.json()
            elif meta_resp.status_code == 403:
                raise RuntimeError("SharePoint 權限不足 (403)，請聯絡系統管理員。")
            elif meta_resp.status_code == 404:
                raise RuntimeError("找不到 SharePoint 檔案，請確認連結是否仍有效。")
            else:
                try:
                    meta_resp.raise_for_status()
                except httpx.HTTPStatusError as err:
                    raise RuntimeError(f"查詢 SharePoint 檔案資訊失敗：HTTP {err.response.status_code}") from err

            try:
                download_resp = await client.get(f"{base_url}/$value", headers=headers)
                download_resp.raise_for_status()
            except httpx.HTTPStatusError as err:
                status_code = err.response.status_code
                if status_code == 403:
                    raise RuntimeError("SharePoint 下載遭拒 (403)，請確認 BOT 應用程式權限。") from err
                if status_code == 404:
                    raise RuntimeError("SharePoint 下載失敗：檔案不存在或連結已過期。") from err
                raise RuntimeError(f"SharePoint 下載失敗：HTTP {status_code}") from err
            except httpx.HTTPError as err:
                raise RuntimeError(f"SharePoint 下載失敗：{err}") from err

            inferred_name = None
            inferred_mime = None
            if metadata:
                inferred_name = metadata.get("name") or None
                file_info = metadata.get("file") or {}
                inferred_mime = file_info.get("mimeType") or None

            return download_resp.content, download_resp.headers, inferred_name, inferred_mime

    async def _get_botframework_token(self) -> str | None:
        # Cache token briefly to avoid repeated auth
        try:
            import time
            token = self._bf_token_cache.get("token")
            exp = self._bf_token_cache.get("exp", 0)
            if token and time.time() < exp - 60:
                return token

            app_id = os.getenv("BOT_APP_ID") or os.getenv("MICROSOFT_APP_ID")
            app_password = os.getenv("BOT_APP_PASSWORD") or os.getenv("MICROSOFT_APP_PASSWORD")
            if not app_id or not app_password:
                return None

            data = {
                "grant_type": "client_credentials",
                "client_id": app_id,
                "client_secret": app_password,
                "scope": "https://api.botframework.com/.default",
            }
            import httpx
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                js = resp.json()
                token = js.get("access_token")
                expires_in = int(js.get("expires_in", 1800))
                if token:
                    self._bf_token_cache["token"] = token
                    self._bf_token_cache["exp"] = time.time() + expires_in
                    return token
        except Exception:
            return None
        return None
