import os
import json
import logging
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import pytz

from .asana_client import AsanaClient
from .intent_classifier import ITIntentClassifier
from .cards import build_it_issue_card
from .email_notifier import EmailNotifier
from .knowledge_base import ITKnowledgeBase

logger = logging.getLogger(__name__)


class ITSupportService:
    """
    Orchestrates IT issue flow: card building, intent classification, and Asana task creation.
    """

    def __init__(self):
        self.asana = AsanaClient()
        self.classifier = ITIntentClassifier()
        self.email_notifier = EmailNotifier()
        # load taxonomy for cards
        self._taxonomy = self.classifier.categories
        self._recent_task_by_user: dict[str, dict] = {}
        # Reverse mapping: task_gid -> {email, issue_id, reporter_name}
        self._task_to_reporter: dict[str, dict] = {}
        self._bf_token_cache: dict[str, Any] = {}
        # Webhook handshake secret (stored after Asana sends it)
        self._webhook_secret: Optional[str] = None
        # AI 分析開關（設 True 啟用 AI 分析建議，False 關閉以節省 token 或等待串接知識庫）
        self.enable_ai_analysis: bool = os.getenv("ENABLE_IT_AI_ANALYSIS", "false").strip().lower() == "true"
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

        # Initialize Knowledge Base
        try:
            from core.container import get_container
            from infrastructure.external.graph_api_client import GraphAPIClient
            graph_client = get_container().get(GraphAPIClient)
            self.knowledge_base = ITKnowledgeBase(graph_client)
        except Exception as e:
            logger.error("初始化 IT 知識庫失敗: %s", e)
            self.knowledge_base = None

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
        # Try AI analysis for triage（受 enable_ai_analysis 開關控制）
        analysis_text = ""
        if self.enable_ai_analysis:
            analysis_text = await self._try_analyze_issue(description, category_label, priority)
        else:
            print("ℹ️ AI 分析已關閉 (ENABLE_IT_AI_ANALYSIS=false)")

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
                # 儲存反向映射供 webhook 回呼使用
                self._task_to_reporter[gid] = {
                    "email": reporter_email,
                    "issue_id": issue_id,
                    "reporter_name": reporter_name,
                    "task_name": name,
                    "permalink_url": link or "",
                }
            # ── 提單確認 Email（測試階段僅通知指定用戶）──
            _test_emails = {"juncheng.liu@rinnai.com.tw"}
            print(f"📧 Email 檢查: reporter={reporter_email.lower()}, 白名單={_test_emails}")
            if reporter_email.lower() in _test_emails:
                print(f"📧 準備發送提單確認 Email 至 {reporter_email}")
                print(f"📧 SMTP 設定: {self.email_notifier.smtp_host}:{self.email_notifier.smtp_port}, user={self.email_notifier.smtp_user}")
                try:
                    email_ok = await self.email_notifier.send_submission_notification(
                        to_email=reporter_email,
                        issue_id=issue_id,
                        summary=description,
                        category=category_label,
                        priority=priority,
                        created_at=created_at,
                        permalink_url="",
                        reporter_name=reporter_name,
                    )
                    print(f"📧 提單確認 Email → {reporter_email}: {'✅ 成功' if email_ok else '❌ 失敗'}")
                except Exception as mail_err:
                    import traceback
                    print(f"❌ 提單確認 Email 發送例外: {mail_err}")
                    traceback.print_exc()
            else:
                print(f"📧 跳過 Email 通知（{reporter_email} 不在測試白名單中）")
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

    # ── Webhook 處理 ──────────────────────────────────────────────

    async def handle_webhook_event(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """處理 Asana Webhook 事件。
        當偵測到任務完成時，透過 Teams 推播與 Email 通知提單人。
        """
        processed = 0
        notified = 0

        for event in events:
            action = event.get("action")
            resource = event.get("resource", {})
            resource_type = resource.get("resource_type")
            logger.info("收到網鉤事件: Action=%s, Type=%s", action, resource_type)

            # 情況 A: 任務狀態變更 (例如: 完成)
            if action == "changed" and resource_type == "task":
                task_gid = resource.get("gid")
                if not task_gid:
                    continue
                processed += 1
                await self._handle_task_completed_event(task_gid)
                notified += 1 # 這裡簡化處理，具體在子函數內執行

            # 情況 B: 新增評論 (Story)
            elif action == "added" and resource_type == "story":
                parent = event.get("parent", {})
                if parent.get("resource_type") == "task":
                    task_gid = parent.get("gid")
                    story_gid = resource.get("gid")
                    await self._handle_story_added_event(task_gid, story_gid)

        return {"processed": processed, "notified": notified}

    async def _handle_task_completed_event(self, task_gid: str):
        """處理任務完成後的通知與知識庫存檔。"""
        try:
            task_data = await self.asana.get_task(task_gid)
            task = task_data.get("data", {})
            if not task.get("completed"):
                return
        except Exception as e:
            logger.warning("查詢 Asana 任務 %s 失敗: %s", task_gid, e)
            return

        # 獲取提單人資訊 TR
        reporter_info = self._task_to_reporter.get(task_gid)
        if not reporter_info:
            reporter_info = self._parse_reporter_from_notes(task.get("notes", ""))
        if not reporter_info:
            return

        reporter_email = reporter_info.get("email", "")
        issue_id = reporter_info.get("issue_id", "")
        task_name = reporter_info.get("task_name") or task.get("name", "")
        permalink = reporter_info.get("permalink_url") or task.get("permalink_url", "")

        if not reporter_email:
            return

        # 1) 抓取對話評論內容
        comments_str = ""
        try:
            stories_data = await self.asana.get_task_stories(task_gid)
            stories = stories_data.get("data", [])
            
            comment_list = []
            for s in stories:
                # 僅紀錄有文字內容的評論(comment)，排除系統自動產生的訊息
                if s.get("type") == "comment" or s.get("resource_subtype") == "comment_added":
                    author = s.get("created_by", {}).get("name", "Unknown")
                    text = s.get("text", "").strip()
                    if text:
                        comment_list.append(f"**{author}**: {text}")
            
            if comment_list:
                comments_str = "\n" + "\n".join([f"  - {c}" for c in comment_list])
        except Exception as e:
            logger.warning("抓取任務評論失敗: %s", e)

        # 2) Teams 通知
        await self._send_teams_notification(reporter_email, issue_id, task_name, permalink, comments_str)
        # 3) Email 通知
        await self.email_notifier.send_completion_notification(reporter_email, issue_id, task_name, permalink)

        # 4) 處理 IT 知識庫
        if self.knowledge_base:
            try:
                # 使用剛才抓取的 stories (如果有的話)
                entry = self.knowledge_base.create_entry(task, reporter_info, stories if 'stories' in locals() else None)
                await self.knowledge_base.save_to_sharepoint(entry)
                logger.info("IT 知識庫處理完成: %s", issue_id)
            except Exception as kb_err:
                logger.error("處理 IT 知識庫失敗: %s", kb_err)

    async def _handle_story_added_event(self, task_gid: str, story_gid: str):
        """監聽評論，若是 IT 人員留言則通知提單人。"""
        logger.info("檢測到新評論故事: Task=%s, Story=%s", task_gid, story_gid)
        try:
            # 直接獲取觸發 Webhook 的 Story
            story_data = await self.asana.get_story(story_gid)
            target_story = story_data.get("data", {})
            
            if not target_story:
                logger.warning("無法獲取 Story 細節: %s", story_gid)
                return

            # 更寬鬆的評論判定：支援 type 為 comment 或 resource_subtype 為 comment_added
            is_comment = target_story.get("type") == "comment" or target_story.get("resource_subtype") == "comment_added"
            
            if not is_comment:
                logger.info("忽略非評論類型事件 (Type=%s, Subtype=%s)", 
                            target_story.get("type"), target_story.get("resource_subtype"))
                return

            comment_text = target_story.get("text", "")
            author_name = target_story.get("created_by", {}).get("name", "").strip()
            logger.info("檢測到留言: [%s] %s...", author_name, comment_text[:20])

            # 獲取提單人資訊 (優先從緩存拿，拿不到才解析 notes)
            reporter_info = self._task_to_reporter.get(task_gid)
            if not reporter_info:
                task_data = await self.asana.get_task(task_gid)
                task = task_data.get("data", {})
                reporter_info = self._parse_reporter_from_notes(task.get("notes", ""))
            
            if not reporter_info:
                logger.warning("無法從任務 %s 獲取提單人資訊，跳過通知", task_gid)
                return

            reporter_email = reporter_info.get("email", "")
            # ... 其餘邏輯保持不變 ...
            reporter_name = (reporter_info.get("reporter_name") or "").strip()
            
            # 避免迴圈通知：如果留言者就是提單人，則不通知
            if author_name.lower() == reporter_name.lower() and reporter_name:
                logger.info("留言者為提單人本人 (%s)，跳過通知", author_name)
                return

            issue_id = reporter_info.get("issue_id", "UNKNOWN")
            task_name = reporter_info.get("task_name") or "IT Support Task"
            permalink = reporter_info.get("permalink_url") or ""
            
            # 發送多管道通知
            title = f"【IT 通知】單號 {issue_id} 有新回覆"
            link_text = f"\n\n🔗 [查看 Asana 任務]({permalink})" if permalink else ""
            msg_content = f"🔔 **IT 人員已回覆您的提單** (單號: {issue_id})\n\n**{author_name}**: {comment_text}{link_text}"
            
            # 1) Email 通知
            await self.email_notifier.send_custom_notification(reporter_email, title, msg_content)
            
            # 2) Teams 推播
            await self._send_teams_push(reporter_email, msg_content)
            
            logger.info("已發送評論通知給提單人 %s (By: %s)", reporter_email, author_name)

        except Exception as e:
            logger.error("處理評論 Webhook 失敗: %s", e)

    def _parse_reporter_from_notes(self, notes: str) -> Optional[Dict[str, str]]:
        """從 Asana task notes 中解析提單人 email 與單號。
        Notes 格式: '單號: ITxxx\n提出人: Name <email>\n...'
        """
        import re
        result: Dict[str, str] = {}
        try:
            # 修改正則表達式以適應更多可能的空格或格式
            m_id = re.search(r"單號[:：]\s*(IT[A-Za-z0-9]+)", notes)
            if m_id:
                result["issue_id"] = m_id.group(1)
            
            m_email = re.search(r"提出人[:：].*?<([^>]+)>", notes)
            if m_email:
                result["email"] = m_email.group(1)
            
            m_name = re.search(r"提出人[:：]\s*(.+?)\s*<", notes)
            if m_name:
                result["reporter_name"] = m_name.group(1).strip()
            
            # 從內容中嘗試抓取分類 (如果在 notes 中有寫)
            m_cat = re.search(r"分類[:：]\s*(.+?)\s*\(", notes)
            if m_cat:
                result["category_label"] = m_cat.group(1).strip()
                
            m_priority = re.search(r"優先順序[:：]\s*(\S+)", notes)
            if m_priority:
                result["priority"] = m_priority.group(1).strip()

        except Exception as e:
            logger.debug("解析 notes 失敗: %s", e)
        return result if result.get("email") or result.get("issue_id") else None

    async def _send_teams_notification(
        self, reporter_email: str, issue_id: str, task_name: str, permalink: str, comments: str = ""
    ) -> bool:
        """透過 Bot Framework 推播任務完成通知。"""
        link_text = f"\n🔗 [查看任務詳情]({permalink})" if permalink else ""
        
        detail_section = ""
        if comments:
            detail_section = f"\n\n💬 **溝通評論：**\n{comments}"

        message = (
            f"🎉 **您的 IT 支援單已處理完成！**\n\n"
            f"📋 **單號：** {issue_id}\n"
            f"📝 **摘要：** {task_name}"
            f"{detail_section}"
            f"\n\n---"
            f"{link_text}"
        )
        return await self._send_teams_push(reporter_email, message)

    async def _send_teams_push(self, reporter_email: str, message: str) -> bool:
        """通用的 Teams 推播邏輯。"""
        try:
            from app import user_conversation_refs
            from botbuilder.schema import Activity, ActivityTypes

            conv_ref = user_conversation_refs.get(reporter_email)
            if not conv_ref:
                logger.info("找不到 %s 的 conversation_reference，跳過 Teams 推播", reporter_email)
                return False

            from core.container import get_container
            from infrastructure.bot.bot_adapter import CustomBotAdapter
            adapter: CustomBotAdapter = get_container().get(CustomBotAdapter)

            async def send_callback(turn_context):
                await turn_context.send_activity(
                    Activity(type=ActivityTypes.message, text=message)
                )

            bot_id = os.getenv("BOT_APP_ID") or os.getenv("MICROSOFT_APP_ID") or ""
            await adapter.adapter.continue_conversation(
                conv_ref, send_callback, bot_id
            )
            return True
        except Exception as e:
            logger.error("Teams 推播失敗 (%s): %s", reporter_email, e)
            return False

    async def setup_webhook(self, target_url: str) -> Dict[str, Any]:
        """建立 Project 層級 Webhook 訂閱。"""
        if not self.project_gid:
            return {"success": False, "error": "ASANA_PROJECT_GID 未設定"}
        try:
            result = await self.asana.create_webhook(self.project_gid, target_url)
            logger.info("Asana Webhook 已建立: %s", result)
            return {"success": True, "data": result}
        except Exception as e:
            logger.error("建立 Asana Webhook 失敗: %s", e)
            return {"success": False, "error": str(e)}

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

        # 根據檔案內容自動偵測正確的副檔名和 MIME 類型
        filename, mime_type = self._infer_extension_from_content(content, filename, mime_type)

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
            # 根據檔案內容自動偵測正確的副檔名和 MIME 類型
            filename, mime_type = self._infer_extension_from_content(content, filename, mime_type)
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
        """判斷是否為 SharePoint 分享連結（需透過 Graph Shares API 下載）。
        注意：直接下載連結（含 download.aspx、access_token、tempauth 等）不需要經過 Graph API。
        """
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            path = parsed.path.lower()
            query = parsed.query.lower()
            
            # 不是 SharePoint/OneDrive 網域
            if not (("sharepoint.com" in host) or host.endswith("1drv.ms")):
                return False
            
            # 已經是直接下載連結，不需要 Graph API
            # 這些 URL 已經包含授權資訊，可以直接 HTTP GET
            if any(kw in path for kw in ["download.aspx", "_layouts/15/download", "/_api/"]):
                return False
            if any(kw in query for kw in ["access_token", "tempauth", "download=1"]):
                return False
            
            # 是分享連結，需要用 Graph API
            return True
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

    def _infer_extension_from_content(self, content: bytes, filename: Optional[str], mime_type: Optional[str]) -> tuple[str, str]:
        """根據檔案內容（magic bytes）或 MIME 類型推斷正確的副檔名和 MIME 類型。
        Returns: (filename, mime_type)
        """
        from datetime import datetime

        # Magic bytes 對照表
        magic_map = [
            (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
            (b"\xff\xd8", "jpg", "image/jpeg"),
            (b"GIF87a", "gif", "image/gif"),
            (b"GIF89a", "gif", "image/gif"),
            (b"RIFF", "webp", "image/webp"),  # WEBP 需額外檢查
            (b"%PDF", "pdf", "application/pdf"),
            (b"PK\x03\x04", "zip", "application/zip"),
            (b"BM", "bmp", "image/bmp"),
        ]

        # MIME 對照表
        mime_ext_map = {
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

        detected_ext = None
        detected_mime = None

        # 優先使用 magic bytes 偵測
        if content:
            for magic, ext, mime in magic_map:
                if content.startswith(magic):
                    # 特殊處理 WEBP（RIFF 開頭但需確認 WEBP 標記）
                    if ext == "webp" and b"WEBP" not in content[:16]:
                        continue
                    detected_ext = ext
                    detected_mime = mime
                    break

        # 若 magic bytes 未偵測到，嘗試使用 MIME 類型
        if not detected_ext and mime_type:
            clean_mime = (mime_type or "").split(";")[0].strip().lower()
            detected_ext = mime_ext_map.get(clean_mime)
            if detected_ext:
                detected_mime = clean_mime

        # 若仍無法偵測，保留原始副檔名
        if not detected_ext and filename and "." in filename:
            original_ext = filename.rsplit(".", 1)[-1].lower()
            if original_ext and original_ext != "bin":
                detected_ext = original_ext

        # 預設為 png（無法辨識時）
        if not detected_ext:
            detected_ext = "png"
        if not detected_mime:
            detected_mime = "image/png"

        # 產生檔名
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if filename and "." in filename:
            base = filename.rsplit(".", 1)[0]
            if base:
                final_filename = f"{base}.{detected_ext}"
            else:
                final_filename = f"upload_{ts}.{detected_ext}"
        else:
            final_filename = f"upload_{ts}.{detected_ext}"

        return final_filename, detected_mime

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
            elif meta_resp.status_code == 400:
                # 400 通常表示分享連結格式不正確或已失效
                error_detail = ""
                try:
                    error_json = meta_resp.json()
                    error_detail = error_json.get("error", {}).get("message", "")
                except Exception:
                    pass
                raise RuntimeError(f"SharePoint 連結無效或已過期 (400)：{error_detail or '請重新取得分享連結'}")
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
                if status_code == 400:
                    raise RuntimeError("SharePoint 下載失敗 (400)：連結格式無效或已過期，請重新分享檔案。") from err
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
