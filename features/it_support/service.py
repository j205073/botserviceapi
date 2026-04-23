import os
import json
import logging
import re
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import pytz

from .asana_client import AsanaClient
from .intent_classifier import ITIntentClassifier
from .cards import build_it_issue_card, build_itt_issue_card
from .email_notifier import EmailNotifier
from .knowledge_base import ITKnowledgeBase
from .kb_client import KBVectorClient

logger = logging.getLogger(__name__)


class ITSupportService:
    """
    Orchestrates IT issue flow: card building, intent classification, and Asana task creation.
    """

    def __init__(
        self,
        asana: Optional[AsanaClient] = None,
        classifier: Optional[ITIntentClassifier] = None,
        email_notifier: Optional[EmailNotifier] = None,
        kb_client: Optional[KBVectorClient] = None,
        knowledge_base: Optional[ITKnowledgeBase] = None,
        config=None,
    ):
        self.asana = asana or AsanaClient()
        self.classifier = classifier or ITIntentClassifier()
        self.email_notifier = email_notifier or EmailNotifier()
        self.kb_client = kb_client or KBVectorClient()

        # load taxonomy for cards
        self._taxonomy = self.classifier.categories
        self._recent_task_by_user: dict[str, dict] = {}
        # Reverse mapping: task_gid -> {email, issue_id, reporter_name}
        self._task_to_reporter: dict[str, dict] = {}
        self._bf_token_cache: dict[str, Any] = {}
        # Webhook handshake secret (stored after Asana sends it)
        self._webhook_secret: Optional[str] = None
        # 已通知完成的 (task_gid → completed_at) map。Asana 單次勾選會觸發
        # 多個 webhook event（task changed、story added、section 變更等），
        # 這些事件的 task.completed_at 相同；不同次勾選（toggle 取消再勾）
        # 會產生新的 completed_at，允許再次通知。
        # 持久化到 local_audit_logs/notified_completions.json 避免重啟後重發。
        self._notified_completions: dict[str, str] = self._load_notified_completions()

        # 從 config 讀取設定（有傳入時），否則 fallback 到 os.getenv
        if config is not None:
            self.enable_ai_analysis = config.enable_ai_analysis
            self.analysis_model = config.analysis_model
            self.workspace_gid = config.workspace_gid
            self.project_gid = config.project_gid
            self.assignee_gid = config.assignee_gid
            self.assignee_section_gid = config.assignee_section_gid
            self.onboarding_assignee_email = config.onboarding_assignee_email
            self.priority_tag_map = config.priority_tag_map
            self.default_priority_tag_gid = config.default_priority_tag_gid
        else:
            self.enable_ai_analysis = os.getenv("ENABLE_IT_AI_ANALYSIS", "false").strip().lower() == "true"
            self.analysis_model = os.getenv("IT_ANALYSIS_MODEL", "gpt-5-nano").strip()
            self.workspace_gid = os.getenv("ASANA_WORKSPACE_GID", "1208041237608650")
            self.project_gid = os.getenv("ASANA_PROJECT_GID", "1208327275974093")
            self.assignee_gid = os.getenv("ASANA_ASSIGNEE_GID", "1208683560453534")
            self.assignee_section_gid = os.getenv("ASANA_ASSIGNEE_SECTION_GID", "1211277485675681")
            self.onboarding_assignee_email = os.getenv("ASANA_ONBOARDING_ASSIGNEE_EMAIL", "").strip()
            self.priority_tag_map = {
                "P1": os.getenv("ASANA_TAG_P1", "").strip(),
                "P2": os.getenv("ASANA_TAG_P2", "").strip(),
                "P3": os.getenv("ASANA_TAG_P3", "").strip(),
                "P4": os.getenv("ASANA_TAG_P4", "").strip(),
            }
            self.default_priority_tag_gid = os.getenv("ASANA_PRIORITY_TAG_GID", "").strip()

        # Initialize Knowledge Base
        if knowledge_base is not None:
            self.knowledge_base = knowledge_base
        else:
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

    def build_itt_issue_card(self, language: str, reporter_name: str, reporter_email: str):
        """Build the IT Team proxy card (with requester email input)."""
        return build_itt_issue_card(language, self._taxonomy, reporter_name, reporter_email)

    async def query_my_tickets(self, user_email: str) -> Dict[str, Any]:
        """查詢使用者自己的 IT 工單（含自提 + 被代提）。
        回傳 {"incomplete": [...], "recent_completed": [...top 3]}
        分兩次查詢：未完成 + 全部（含已完成），在 client 端用 email 過濾。
        """
        try:
            # 1) 未完成的工單
            incomplete_tasks = await self.asana.get_project_tasks(
                project_gid=self.project_gid, completed_since="now",
            )
            # 2) 全部工單（含已完成，用來找最近完成的）
            all_tasks = await self.asana.get_project_tasks(
                project_gid=self.project_gid, completed_since=None,
            )
        except Exception as e:
            logger.error("查詢 Asana 工單失敗: %s", e)
            return {"incomplete": [], "recent_completed": []}

        email_lower = user_email.lower()

        incomplete = []
        for t in incomplete_tasks:
            if email_lower in t.get("notes", "").lower():
                incomplete.append(self._extract_ticket_info(t))
        # 按建立日期降序
        incomplete.sort(key=lambda x: x["created_at"], reverse=True)

        completed = []
        for t in all_tasks:
            if t.get("completed") and email_lower in t.get("notes", "").lower():
                completed.append(self._extract_ticket_info(t))
        # 按完成時間降序（最新完成的在前）
        completed.sort(key=lambda x: x.get("completed_at", ""), reverse=True)

        return {
            "incomplete": incomplete,
            "recent_completed": completed[:3],
        }

    def _extract_ticket_info(self, task: Dict[str, Any]) -> Dict[str, str]:
        """從 Asana task 中提取顯示用資訊。"""
        import re as _re
        notes = task.get("notes", "")
        issue_id = ""
        priority = ""
        category = ""
        description = ""

        m = _re.search(r"單號[:：]\s*(IT\S+)", notes)
        if m:
            issue_id = m.group(1)
        m = _re.search(r"優先順序[:：]\s*(\S+)", notes)
        if m:
            priority = m.group(1)
        m = _re.search(r"分類[:：]\s*(.+?)(?:\s*\(|$)", notes)
        if m:
            category = m.group(1).strip()
        if "【需求/問題說明】" in notes:
            start = notes.index("【需求/問題說明】") + len("【需求/問題說明】")
            end = len(notes)
            for marker in ["【AI 分析", "【知識庫參考"]:
                if marker in notes[start:]:
                    pos = notes.index(marker, start)
                    if pos < end:
                        end = pos
            description = notes[start:end].strip()
            if len(description) > 80:
                description = description[:77] + "..."

        return {
            "issue_id": issue_id or task.get("name", ""),
            "task_name": task.get("name", ""),
            "priority": priority,
            "category": category,
            "description": description,
            "completed": task.get("completed", False),
            "created_at": (task.get("created_at") or "")[:10],
            "completed_at": (task.get("completed_at") or "")[:10],
        }

    async def submit_issue(self, form: Dict[str, Any], reporter_name: str, reporter_email: str, requester_email: str = "") -> Dict[str, Any]:
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

        # 從 Microsoft Graph 取得提出人的詳細資訊（姓名、部門）
        from core.container import get_container
        from infrastructure.external.graph_api_client import GraphAPIClient

        container = get_container()
        graph_client: GraphAPIClient = container.get(GraphAPIClient)

        user_display_name = reporter_name
        user_department = "未指定部門"
        try:
            user_info = await graph_client.get_user_info(reporter_email)
            if user_info:
                user_display_name = user_info.get("displayName") or reporter_name
                user_department = user_info.get("department") or "未指定部門"
                logger.info("✅ 從 Graph API 取得用戶信息: %s, 部門: %s", user_display_name, user_department)
        except Exception as e:
            logger.warning("⚠️ 無法從 Graph API 取得用戶部門資訊: %s", e)

        # AI-based classification (uses IT_ANALYSIS_MODEL); fallback to keyword classifier
        category_code, category_label = await self._classify_issue_ai(description)

        # Generate issue ID with Taiwan time
        issue_id, dt_for_id = self._generate_issue_id()

        # task name and notes
        name = f"{issue_id} - {category_label}"

        # Localize created time to Taiwan time
        taipei = pytz.timezone("Asia/Taipei")
        now_taipei = datetime.now(taipei)
        created_at = now_taipei.strftime("%Y-%m-%d %H:%M 台北時間")
        created_at_iso = now_taipei.isoformat()

        if not self.enable_ai_analysis:
            print("ℹ️ AI 分析已關閉 (ENABLE_IT_AI_ANALYSIS=false)")

        # 查詢知識庫（報到開通類別跳過，新人帳號開通通常不匹配歷史工單）
        kb_answer = ""
        kb_sources: List[Dict[str, Any]] = []
        if category_code == "onboarding":
            logger.info("報到開通案件 → 跳過 KB 查詢")
        else:
            kb_result = await self.kb_client.ask_safe(description, role="it", kb_name="it-kb")
            kb_answer = (kb_result.get("answer") or "").strip()
            kb_sources = kb_result.get("sources") or []
            if kb_answer == "No relevant knowledge base articles found.":
                kb_answer = ""

        # 代提單模式：先解析提出人資訊（不論是否走 AI 整理都需要）
        requester_display_name = ""
        requester_department = ""
        if requester_email:
            requester_email = requester_email.strip()
            requester_display_name = requester_email
            requester_department = "未指定部門"
            try:
                requester_info = await graph_client.get_user_info(requester_email)
                if requester_info:
                    requester_display_name = requester_info.get("displayName") or requester_email
                    requester_department = requester_info.get("department") or "未指定部門"
                    logger.info("✅ 從 Graph API 取得代提單提出人資訊: %s, 部門: %s", requester_display_name, requester_department)
            except Exception as e:
                logger.warning("⚠️ 無法從 Graph API 取得代提單提出人資訊: %s", e)

        # 用 AI 整理 notes (Markdown) + structured JSON (一次呼叫)
        reporter_obj = {
            "name": user_display_name,
            "email": reporter_email,
            "department": user_department,
        }
        requester_obj = (
            {
                "name": requester_display_name,
                "email": requester_email,
                "department": requester_department,
            }
            if requester_email
            else None
        )
        ai_format = await self._format_issue_for_asana(
            issue_id=issue_id,
            description=description,
            category_code=category_code,
            category_label=category_label,
            priority=priority,
            reporter=reporter_obj,
            requester=requester_obj,
            created_at_iso=created_at_iso,
            created_at_display=created_at,
            enable_ai_analysis=self.enable_ai_analysis,
            kb_answer=kb_answer,
            kb_sources=kb_sources,
        )

        external_data_str: Optional[str] = None
        if ai_format:
            notes = ai_format["notes"]
            try:
                external_data_str = self._trim_external_data(ai_format["structured"])
            except Exception as e:
                logger.warning("external.data 序列化失敗: %s", e)
                external_data_str = None
        else:
            # AI format 失敗 → 降級到純文字 notes；lazy 呼叫 analyze 補上 AI 建議區塊
            fallback_analysis = (
                await self._analyze_issue_dict(description, category_label, priority)
                if self.enable_ai_analysis
                else None
            )
            analysis_text = self._format_analysis_text(fallback_analysis)
            kb_section = ""
            if kb_answer:
                parts = [f"- AI 建議：{kb_answer}"]
                for src in kb_sources:
                    title = src.get("title", "")
                    score = src.get("score")
                    preview = src.get("contentPreview", "")
                    score_str = f"（相似度: {score:.0%}）" if score is not None else ""
                    line = f"  - {title}{score_str}"
                    if preview:
                        line += f"\n    {preview[:120]}"
                    parts.append(line)
                kb_section = "\n".join(parts)
            if requester_email:
                notes = (
                    f"單號: {issue_id}\n"
                    f"提出人: {requester_display_name} <{requester_email}>\n"
                    f"提出人部門: {requester_department}\n"
                    f"代理提出人: {user_display_name} <{reporter_email}>\n"
                    f"代理提出人部門: {user_department}\n"
                    f"分類: {category_label} ({category_code})\n"
                    f"優先順序: {priority}\n"
                    f"建立來源: TR GPT bot（代提單 @itt）\n"
                    f"建立時間: {created_at}\n\n"
                    f"【需求/問題說明】\n{description}\n"
                    + ("\n【AI 分析（建議/時間/相關面向）】\n\n" + analysis_text + "\n" if analysis_text else "")
                    + ("\n【知識庫參考（KB-Vector-Service）】\n\n" + kb_section + "\n" if kb_section else "")
                )
            else:
                notes = (
                    f"單號: {issue_id}\n"
                    f"提出人: {user_display_name} <{reporter_email}>\n"
                    f"提出人部門: {user_department}\n"
                    f"分類: {category_label} ({category_code})\n"
                    f"優先順序: {priority}\n"
                    f"建立來源: TR GPT bot\n"
                    f"建立時間: {created_at}\n\n"
                    f"【需求/問題說明】\n{description}\n"
                    + ("\n【AI 分析（建議/時間/相關面向）】\n\n" + analysis_text + "\n" if analysis_text else "")
                    + ("\n【知識庫參考（KB-Vector-Service）】\n\n" + kb_section + "\n" if kb_section else "")
                )

        # 決定 assignee：報到開通指派給指定人員
        assignee = self.assignee_gid
        if category_code == "onboarding" and self.onboarding_assignee_email:
            try:
                onboarding_gid = await self.asana.get_user_gid_by_email(self.onboarding_assignee_email)
                if onboarding_gid:
                    assignee = onboarding_gid
                    logger.info("報到開通案件 → 指派給 %s (GID: %s)", self.onboarding_assignee_email, assignee)
                else:
                    logger.warning("查無報到開通負責人 %s 的 Asana 帳號，使用預設指派", self.onboarding_assignee_email)
            except Exception as e:
                logger.warning("查詢報到開通負責人失敗，使用預設指派: %s", e)

        # build payload following Postman spec
        data = {
            "data": {
                "name": name,
                "resource_subtype": "default_task",
                "completed": False,
                "notes": notes,
                "assignee": assignee,
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

        # 結構化資料寫入 external.data，供後續分析（KB / 統計）使用
        if external_data_str:
            data["data"]["external"] = {
                "gid": issue_id,
                "data": external_data_str,
            }

        try:
            result = await self.asana.create_task(data)
            task = result.get("data", {})
            link = task.get("permalink_url")
            gid = task.get("gid")
            # remember for quick attachment
            if gid:
                self._recent_task_by_user[reporter_email] = {"gid": gid, "ts": datetime.now(timezone.utc)}
                # 儲存反向映射供 webhook 回呼使用
                # 代提單模式：webhook 通知對象改為提出人
                notify_email = requester_email if requester_email else reporter_email
                notify_name = requester_display_name if requester_email else reporter_name
                self._task_to_reporter[gid] = {
                    "email": notify_email,
                    "issue_id": issue_id,
                    "reporter_name": notify_name,
                    "reporter_email": reporter_email,
                    "reporter_department": user_department,
                    "task_name": name,
                    "permalink_url": link or "",
                    "category_label": category_label,
                    "priority": priority,
                }
            # ── 提單確認 Email ──
            # EMAIL_TEST_MODE=true 時僅通知白名單用戶；false（預設）則通知所有提單人
            _email_test_mode = os.getenv("EMAIL_TEST_MODE", "false").strip().lower() == "true"
            _test_emails = {"juncheng.liu@rinnai.com.tw"}
            should_send = (not _email_test_mode) or (reporter_email.lower() in _test_emails)
            print(f"📧 Email 檢查: reporter={reporter_email.lower()}, test_mode={_email_test_mode}, should_send={should_send}")
            if should_send:
                # 發送提單確認 Email（代提單時 CC 給提出人）
                cc_target = ""
                if requester_email and requester_email.lower() != reporter_email.lower():
                    cc_target = requester_email
                print(f"📧 準備發送提單確認 Email 至 {reporter_email}" + (f" (CC: {cc_target})" if cc_target else ""))
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
                        cc_email=cc_target,
                        description=description,
                    )
                    print(f"📧 提單確認 Email → {reporter_email}: {'✅ 成功' if email_ok else '❌ 失敗'}")
                except Exception as mail_err:
                    import traceback
                    print(f"❌ 提單確認 Email 發送例外: {mail_err}")
                    traceback.print_exc()
            else:
                print(f"📧 跳過 Email 通知（測試模式，{reporter_email} 不在白名單中）")
            return {
                "success": True,
                "task_gid": gid,
                "permalink_url": link,
                "issue_id": issue_id,
                "message": f"您的需求已被受理，請耐心等候。單號：{issue_id}\n👤 提出人：{user_display_name}\n🏢 部門：{user_department}"
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

    async def _analyze_issue_dict(self, description: str, category_label: str, priority: str) -> Optional[Dict[str, Any]]:
        """Call OpenAI to analyze issue, return raw dict {recommendation, time_estimate, related_areas}.
        Returns None on failure or when description is empty.
        """
        try:
            if not description:
                return None
            from core.container import get_container
            from infrastructure.external.openai_client import OpenAIClient

            oa: OpenAIClient = get_container().get(OpenAIClient)

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
            raw = await oa.chat_completion(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                model=(self.analysis_model or None),
                max_tokens=600,
                temperature=0.2,
            )

            import json as _json
            try:
                data = _json.loads(raw)
            except Exception:
                import re
                m = re.search(r"\{[\s\S]*\}", raw)
                data = _json.loads(m.group(0)) if m else None
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _format_analysis_text(self, data: Optional[Dict[str, Any]]) -> str:
        """Format analysis dict to multiline text for plain-text notes fallback."""
        if not isinstance(data, dict):
            return ""
        parts = []
        rec = str(data.get("recommendation", "")).strip()
        if rec:
            import re as _re
            if _re.search(r"\b1\)", rec):
                rec = _re.sub(r"\s*(\d+\))", r"\n  \1 ", rec).strip()
                parts.append("- 建議：\n  " + rec)
            else:
                parts.append(f"- 建議：{rec}")
        t = str(data.get("time_estimate", "")).strip()
        if t:
            parts.append(f"- 時間估計：{t}")
        areas = data.get("related_areas")
        if isinstance(areas, list):
            cleaned = [str(a).strip() for a in areas if str(a).strip()]
            if cleaned:
                parts.append("- 相關面向：\n" + "\n".join([f"  - {a}" for a in cleaned]))
        elif areas:
            parts.append(f"- 相關面向：{str(areas).strip()}")
        return "\n".join(parts).strip()

    async def _try_analyze_issue(self, description: str, category_label: str, priority: str) -> str:
        """Backward-compatible wrapper returning formatted text."""
        return self._format_analysis_text(await self._analyze_issue_dict(description, category_label, priority))

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

    async def _format_issue_for_asana(
        self,
        issue_id: str,
        description: str,
        category_code: str,
        category_label: str,
        priority: str,
        reporter: Dict[str, str],
        requester: Optional[Dict[str, str]],
        created_at_iso: str,
        created_at_display: str,
        enable_ai_analysis: bool,
        kb_answer: str,
        kb_sources: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Single OpenAI call producing notes + structured JSON v1.0.

        合併原本的 _analyze_issue_dict：若 enable_ai_analysis=True，
        AI 同時扮演資深工程師角色自行產出 recommendation/time_estimate/related_areas
        並寫入 structured.ai_analysis 與 notes 的【AI 建議】區塊。

        Returns {"notes": str, "structured": dict} on success; None on failure
        (caller should fall back to plain-text notes assembly).
        """
        try:
            from core.container import get_container
            from infrastructure.external.openai_client import OpenAIClient

            oa: OpenAIClient = get_container().get(OpenAIClient)

            is_proxy = requester is not None
            context = {
                "issue_id": issue_id,
                "created_at": created_at_iso,
                "created_at_display": created_at_display,
                "source": "TR GPT bot（代提單 @itt）" if is_proxy else "TR GPT bot",
                "priority": priority,
                "category": {"code": category_code, "label": category_label},
                "is_proxy": is_proxy,
                "reporter": reporter,
                "requester": requester,
                "raw_description": description,
                "enable_ai_analysis": enable_ai_analysis,
                "kb_answer": (kb_answer or "").strip(),
                "kb_sources": [
                    {
                        "title": s.get("title", ""),
                        "score": s.get("score"),
                        "preview": (s.get("contentPreview") or "")[:200],
                    }
                    for s in (kb_sources or [])[:5]
                ],
            }

            system = (
                "你同時扮演兩個角色：\n"
                "A. 資深 IT 服務台工程師：若輸入 enable_ai_analysis=true，請自己針對此 IT 問題產出"
                "recommendation（簡短處理建議）、time_estimate（估計處理時間，如『2-4 小時』）、"
                "related_areas（可能相關面向陣列，如『帳號權限』『網路』『軟硬體』『系統設定』『資料庫』"
                "『API』『身分認證』等）。若 enable_ai_analysis=false，則 ai_analysis 設為 null 且 notes 不含【AI 建議】區塊。\n"
                "B. IT 提單資料整理助手：根據輸入的 IT 提單資料（JSON），同時產出兩份產物：\n\n"
                "1. notes：給 Asana task 的 notes 欄位（**Asana 的 notes 是純文字、不支援 Markdown**，"
                "不能用 ##、**bold**、---、`code` 等 Markdown 語法，會直接顯示為字面字元）。\n"
                "請用以下固定格式（注意每個欄位獨立一行，段落用【】標題區隔）：\n\n"
                "```\n"
                "單號: {issue_id}\n"
                "提出人: {reporter.name} <{reporter.email}>\n"
                "提出人部門: {reporter.department}\n"
                "代理提出人: {requester.name} <{requester.email}>      ← 僅 is_proxy=true 時加這兩行\n"
                "代理提出人部門: {requester.department}                ← \n"
                "分類: {category.label} ({category.code})\n"
                "優先順序: {priority}\n"
                "建立來源: {source}\n"
                "建立時間: {created_at_display}   ← 使用輸入的 created_at_display 欄位（人類可讀），不要用 ISO 格式的 created_at\n"
                "\n"
                "【需求摘要】\n"
                "{一句話摘要 ≤50 字}\n"
                "\n"
                "【需求/問題說明】\n"
                "{description.raw 原文}\n"
                "\n"
                "【現象】\n"
                "- {symptom 條列，每點一行}\n"
                "\n"
                "【重現步驟】\n"
                "1. {step}\n"
                "2. {step}\n"
                "（若使用者沒提到步驟，整段 if 空陣列就省略整個【重現步驟】區塊）\n"
                "\n"
                "【預期結果】\n"
                "{expected，若空就省略整段}\n"
                "\n"
                "【影響】\n"
                "{impact，若空就省略整段}\n"
                "\n"
                "【涉及系統】\n"
                "{affected_systems 用頓號或逗號串接，若空就省略整段}\n"
                "\n"
                "【AI 建議】                                       ← 只有 enable_ai_analysis=true 才出現（內容由你自己產，見角色 A）\n"
                "- 處理建議：{你產的 recommendation}\n"
                "- 估計時間：{你產的 time_estimate}\n"
                "- 相關面向：{你產的 related_areas 用、串接}\n"
                "\n"
                "【相關歷史工單（KB 參考）】                        ← 只有 kb_sources 非空才出現\n"
                "- {kb_answer 整段（若有）}\n"
                "- {title}（相似度 {score:.0%}）\n"
                "  {preview 截前 80 字}\n"
                "```\n\n"
                "規則：\n"
                "- 每個欄位獨立一行，不要併排\n"
                "- 不要用任何 Markdown 語法（##、**、---、```、表格、超連結等都禁止）\n"
                "- 段落之間用一個空行分隔\n"
                "- 沒資料的【】區塊整段不要輸出（不要顯示「無」）\n"
                "- 不要捏造原文沒有的資訊\n\n"
                "2. structured：結構化 JSON，固定 schema_version 為 \"1.0\"，欄位定義：\n"
                "{\n"
                "  \"schema_version\": \"1.0\",\n"
                "  \"issue_id\": str,                 // 直接用輸入的 issue_id\n"
                "  \"created_at\": str,               // 直接用輸入的 created_at（ISO 8601 + 台北時區）\n"
                "  \"source\": str,                   // 直接用輸入的 source\n"
                "  \"priority\": \"P1\"|\"P2\"|\"P3\"|\"P4\",  // 直接用輸入的 priority\n"
                "  \"category\": {\"code\": str, \"label\": str},  // 直接用輸入的 category\n"
                "  \"is_proxy\": bool,\n"
                "  \"reporter\": {\"name\": str, \"email\": str, \"department\": str},\n"
                "  \"requester\": {...} | null,        // is_proxy=false 時為 null\n"
                "  \"description\": {\n"
                "    \"raw\": str,                    // 直接用輸入的 raw_description 全文\n"
                "    \"summary\": str,                // 一句話摘要 ≤50 字\n"
                "    \"symptom\": str,                // 觀察到的現象（錯誤訊息、異常行為）\n"
                "    \"steps_to_reproduce\": [str],   // 重現步驟，依序；無法判斷則空陣列\n"
                "    \"expected\": str,               // 預期結果；無則空字串\n"
                "    \"impact\": str,                 // 影響範圍；無則空字串\n"
                "    \"affected_systems\": [str],     // 涉及的系統/軟體；無則空陣列\n"
                "    \"keywords\": [str]              // 分析用關鍵字 5-10 個\n"
                "  },\n"
                "  \"ai_analysis\": {\"recommendation\": str, \"time_estimate\": str, \"related_areas\": [str]} | null,  // enable_ai_analysis=true 時由你（角色 A）自行產出；false 時為 null\n"
                "  \"kb_references\": [{title, score, preview}]  // 直接用輸入的 kb_sources\n"
                "}\n\n"
                "請只回傳純 JSON 物件（不要 markdown 包裝、不要 ```json``` 區塊），格式為：\n"
                "{\"notes\": \"...Markdown 字串...\", \"structured\": {...}}\n\n"
                "語言一律繁體中文。原文沒提到的欄位請從上下文推論或留空，不要捏造資訊。"
            )

            import json as _json
            user_msg = _json.dumps(context, ensure_ascii=False)

            raw = await oa.chat_completion(
                [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                model=(self.analysis_model or None),
                max_tokens=3000,
                temperature=0.3,
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
            if not isinstance(data, dict):
                return None
            notes = str(data.get("notes", "")).strip()
            structured = data.get("structured")
            if not notes or not isinstance(structured, dict):
                return None
            structured.setdefault("schema_version", "1.0")
            return {"notes": notes, "structured": structured}
        except Exception as e:
            logger.warning("AI 整理 notes/structured 失敗，將降級到純文字 notes: %s", e)
            return None

    @staticmethod
    def _trim_external_data(structured: Dict[str, Any], limit: int = 32768) -> str:
        """Serialize structured to JSON string within Asana external.data 32K limit.
        Trim heavy fields progressively if too large.
        """
        import json as _json
        s = _json.dumps(structured, ensure_ascii=False)
        if len(s.encode("utf-8")) <= limit:
            return s
        # 1) 移除 kb_references[].preview
        for ref in structured.get("kb_references") or []:
            ref.pop("preview", None)
        s = _json.dumps(structured, ensure_ascii=False)
        if len(s.encode("utf-8")) <= limit:
            return s
        # 2) 清掉 ai_analysis 細節
        structured["ai_analysis"] = None
        s = _json.dumps(structured, ensure_ascii=False)
        if len(s.encode("utf-8")) <= limit:
            return s
        # 3) 截掉 description.raw（保留前 1500 字 + 標記）
        desc = structured.get("description")
        if isinstance(desc, dict) and isinstance(desc.get("raw"), str):
            desc["raw"] = desc["raw"][:1500] + "...(truncated)"
        s = _json.dumps(structured, ensure_ascii=False)
        return s

    # ── 評論前綴可見性規則（預設推播使用者；AI 雙保險會消毒機敏資訊）─────
    # IT 人員在 Asana 評論前加標籤控制這則評論的傳播：
    #   [對內] / [內部] / [private] / [internal]  → 只進 SharePoint KB，不推播使用者
    #   [略]   / [skip]                             → 完全忽略（不通知、不進 KB）
    #   [對外] / [reply] / [public]                → 明確標為對外（效果同無前綴，但會 strip 前綴）
    #   無前綴                                      → 推播使用者 + 進 KB（預設行為）
    # KB 永遠存原文（除 [略] 外）作為知識養分；推播給使用者前一律經 AI 消毒去除敏感資訊。
    _COMMENT_PREFIX_PATTERNS = [
        ("skip", re.compile(r"^\s*\[\s*(略|skip)\s*\]\s*", re.IGNORECASE)),
        ("internal", re.compile(r"^\s*\[\s*(對內|內部|private|internal)\s*\]\s*", re.IGNORECASE)),
        ("public", re.compile(r"^\s*\[\s*(對外|對外回覆|reply|public)\s*\]\s*", re.IGNORECASE)),
    ]

    # Inline block 支援：[對內]...[/對內] 之間的內容為內部（只進 KB 不推播）
    _INTERNAL_BLOCK_PATTERN = re.compile(
        r"\[\s*(?:對內|內部|private|internal)\s*\](.*?)\[\s*/\s*(?:對內|內部|private|internal)\s*\]",
        re.IGNORECASE | re.DOTALL,
    )
    # Fail-safe：未配對的 [對內] 開標記（即只有開沒有收）→ 從這點到結尾全當內部
    _INTERNAL_OPEN_PATTERN = re.compile(
        r"\[\s*(?:對內|內部|private|internal)\s*\]",
        re.IGNORECASE,
    )

    @classmethod
    def _classify_comment_visibility(cls, text: str) -> tuple[str, str]:
        """Classify an Asana comment by whole-comment prefix.
        Returns (visibility, cleaned_text).
          visibility ∈ {"public", "internal", "skip"}
          cleaned_text：已去除整則前綴；無前綴則為原文 strip 後。
        預設為 "public"（無前綴 → 推播使用者）。
        """
        if not text:
            return ("public", "")
        for label, pattern in cls._COMMENT_PREFIX_PATTERNS:
            m = pattern.match(text)
            if m:
                return (label, text[m.end():].strip())
        return ("public", text.strip())

    @classmethod
    def _split_inline_internal_blocks(cls, text: str) -> tuple[str, list[str]]:
        """從 public 評論中抽出 inline [對內]...[/對內] blocks。
        Returns (public_part, internal_parts)。
        - 配對完整的 block：內容抽到 internal_parts，原位置移除
        - 未配對的開標記（fail-safe）：從該標記到結尾全視為內部
        - public_part 會移除多餘空行；內容可能為空字串
        """
        if not text:
            return ("", [])
        internals: list[str] = []

        def _collect(m: re.Match) -> str:
            inner = (m.group(1) or "").strip()
            if inner:
                internals.append(inner)
            return ""

        working = cls._INTERNAL_BLOCK_PATTERN.sub(_collect, text)
        # Fail-safe：剩餘未配對的 [對內] → 整段後半丟到 internal
        open_match = cls._INTERNAL_OPEN_PATTERN.search(working)
        if open_match:
            tail = working[open_match.end():].strip()
            if tail:
                internals.append(tail)
            working = working[:open_match.start()]
        # 壓掉多餘空行
        public = re.sub(r"\n\s*\n\s*\n+", "\n\n", working).strip()
        return (public, internals)

    async def _redact_sensitive_info(self, text: str) -> Optional[str]:
        """AI 消毒：把對使用者顯示前的文字去除敏感資訊（路徑/密碼/IP/內部系統位址等）。
        Returns 消毒後文字；失敗時回傳 None 由呼叫端決定 fail-safe 策略（通常：不推播）。
        """
        try:
            if not text or not text.strip():
                return text or ""
            from core.container import get_container
            from infrastructure.external.openai_client import OpenAIClient

            oa: OpenAIClient = get_container().get(OpenAIClient)

            system = (
                "你是 IT 支援回覆的資訊安全過濾器。輸入是一段要回覆給「一般使用者」的 IT 回覆文字。\n"
                "你的任務是把可能洩漏內部機敏資訊的片段改寫為使用者仍能理解、但不含具體機敏值的版本，並保留原意。\n"
                "要移除或改寫的敏感類別（舉例但不限於）：\n"
                "- 內部伺服器 UNC / 路徑（如 \\\\fs-it\\secrets、\\\\nas\\share）\n"
                "- 密碼、API key、Token、序號、憑證指紋\n"
                "- 內部 IP、Port、內部 DNS 名稱\n"
                "- 特定系統/檔案位置（如 D:\\ERP\\config）\n"
                "- 內部服務帳號/系統帳號（如 sa / root / svc_xxx）\n"
                "- 明確指向內部人員的私人聯絡方式（分機/Email/手機）\n"
                "改寫原則：\n"
                "- 具體路徑/位址 → 改成「請聯絡 IT 取得」「由 IT 提供」「內部檔案位置（已透過其他管道傳送）」等等\n"
                "- 密碼/金鑰值 → 絕對不要輸出；改成「已另行寄送至您的信箱」或「請透過 IT 面交」\n"
                "- 保留可公開的語境與結論（例如「帳號已重開」「權限已調整」）\n"
                "- 若整段通篇都是內部技術細節、沒有對使用者的有意義訊息，回傳空字串（表示略過）\n"
                "- 語言維持與原文相同（中文在原文是中文則維持中文）\n"
                "請直接回傳消毒後的純文字，不要包 markdown、不要加任何說明。"
            )

            raw = await oa.chat_completion(
                [{"role": "system", "content": system}, {"role": "user", "content": text}],
                model=(self.analysis_model or None),
                max_tokens=1200,
                temperature=0.1,
            )
            if raw is None:
                return None
            cleaned = str(raw).strip()
            # 去除可能的 markdown 包裝
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
            return cleaned.strip()
        except Exception as e:
            logger.warning("AI 消毒失敗，fail-safe：不推播此內容: %s", e)
            return None

    def get_recent_task_gid(self, user_email: str, max_age_minutes: int = 10) -> str | None:
        """取得使用者最近建立的 IT 工單 GID。
        超過 max_age_minutes 分鐘的工單不視為「最近」，避免一般對話附件被誤攔。
        """
        item = self._recent_task_by_user.get(user_email)
        if not item:
            return None
        created_at = item.get("ts")
        if created_at:
            elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
            if elapsed > max_age_minutes * 60:
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
        """處理任務完成後的通知與知識庫存檔。
        去重策略：以 (task_gid, completed_at) 為 key。Asana 單次勾選會觸發
        多個 webhook event（task changed/story added/section 變更等），這些
        event 的 completed_at 相同 → 只通知一次；使用者 toggle 取消再勾會產
        生新的 completed_at → 允許再次通知。
        """
        try:
            logger.info("🔍 開始處理任務完成事件: %s", task_gid)
            task_data = await self.asana.get_task(task_gid)
            task = task_data.get("data", {})
            logger.info("✅ 取得任務: %s, 完成狀態: %s", task_gid, task.get("completed"))
            if not task.get("completed"):
                logger.info("⚠️ 任務 %s 未標記為完成，跳過", task_gid)
                return
        except Exception as e:
            logger.warning("查詢 Asana 任務 %s 失敗: %s", task_gid, e)
            return

        # 以 completed_at 為指紋去重（避免單次勾選被 Asana 多個 webhook event 重發）
        completed_at = str(task.get("completed_at") or "")
        if self._notified_completions.get(task_gid) == completed_at:
            logger.info(
                "⏭️ 任務 %s 已通知過此次完成 (completed_at=%s)，跳過 webhook 重複事件",
                task_gid, completed_at,
            )
            return
        # 樂觀 claim：在第一個 await（通知）之前就標記，避免並發 webhook 讓多個
        # handler 同時通過檢查。注意這兩行之間沒有 await，在 asyncio 中是原子的。
        self._notified_completions[task_gid] = completed_at
        self._save_notified_completions()

        # 獲取提單人資訊 TR
        reporter_info = self._task_to_reporter.get(task_gid)
        logger.info("📋 從緩存查詢提單人: %s, 結果: %s", task_gid, "找到" if reporter_info else "未找到")

        if not reporter_info:
            logger.info("📝 開始從 notes 解析提單人信息...")
            reporter_info = self._parse_reporter_from_notes(task.get("notes", ""))
            logger.info("📝 解析結果: %s", reporter_info)

        if not reporter_info:
            logger.error("❌ 無法獲取提單人信息，中止處理")
            return

        reporter_email = reporter_info.get("email", "")
        issue_id = reporter_info.get("issue_id", "")
        task_name = reporter_info.get("task_name") or task.get("name", "")
        permalink = reporter_info.get("permalink_url") or task.get("permalink_url", "")

        if not reporter_email:
            logger.error("❌ 提單人 Email 為空，中止處理")
            return

        logger.info("✅ 提單信息: issue_id=%s, reporter=%s, task=%s", issue_id, reporter_email, task_name)

        # 0) 從 notes 解析原始提交內容（排除知識庫區塊）
        original_description = ""
        task_notes = task.get("notes", "")
        if "【需求/問題說明】" in task_notes:
            desc_start = task_notes.index("【需求/問題說明】") + len("【需求/問題說明】")
            desc_end = len(task_notes)
            for marker in ["【AI 分析", "【知識庫參考"]:
                if marker in task_notes[desc_start:]:
                    marker_pos = task_notes.index(marker, desc_start)
                    if marker_pos < desc_end:
                        desc_end = marker_pos
            original_description = task_notes[desc_start:desc_end].strip()

        # 1) 抓取對話評論內容（Secure by default：預設不推播、[對外] 才推播、[略] 完全忽略）
        #    - KB 保存原文（internal + public），作為 IT 知識養分
        #    - 給使用者的彙整（comments_str）僅含 [對外] 評論，彙整完再過一次 AI 消毒
        comments_str = ""
        stories_for_kb: List[Dict[str, Any]] = []
        try:
            stories_data = await self.asana.get_task_stories(task_gid)
            stories = stories_data.get("data", [])

            comment_list_public = []
            for s in stories:
                if not (s.get("type") == "comment" or s.get("resource_subtype") == "comment_added"):
                    continue
                author = s.get("created_by", {}).get("name", "Unknown")
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                visibility, cleaned = self._classify_comment_visibility(text)
                if visibility == "skip":
                    continue
                # internal + public 都進 KB（前綴已 strip；inline blocks 也保留原貌）
                s_for_kb = dict(s)
                s_for_kb["text"] = cleaned
                stories_for_kb.append(s_for_kb)
                # 給使用者看的只收 public，且要先抽掉 inline [對內]...[/對內] blocks
                if visibility == "public":
                    public_part, _blocks = self._split_inline_internal_blocks(cleaned)
                    if public_part.strip():
                        comment_list_public.append(f"**{author}**: {public_part}")

            if comment_list_public:
                raw_public_str = "\n".join(comment_list_public)
                # AI 雙保險：整段 public 彙整後再過一次 AI 消毒
                redacted = await self._redact_sensitive_info(raw_public_str)
                if redacted and redacted.strip():
                    comments_str = "\n" + "\n".join(
                        [f"  - {line}" for line in redacted.splitlines() if line.strip()]
                    )
                elif redacted is None:
                    # AI 失敗 → fail-safe：不附溝通摘要（避免漏密）
                    logger.warning("結案溝通摘要 AI 消毒失敗，fail-safe：不附對使用者的 comments_str")
                # AI 回傳空字串：全段都被判為內部資訊，comments_str 保持 ""
        except Exception as e:
            logger.warning("抓取任務評論失敗: %s", e)

        # 2) 抓取附件圖片
        images = []
        image_urls = []  # for Teams (用原始 URL)
        try:
            attachments = await self.asana.get_task_attachments(task_gid)
            for att in attachments:
                name = att.get("name", "")
                dl_url = att.get("download_url", "")
                if not dl_url:
                    continue
                # 只處理圖片類型
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):
                    continue
                image_urls.append({"name": name, "url": dl_url})
                # 下載到記憶體給 Email 用
                img_data = await self.asana.download_attachment(dl_url)
                if img_data:
                    ct_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                              "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}
                    images.append({
                        "filename": name,
                        "data": img_data,
                        "content_type": ct_map.get(ext, "image/png"),
                    })
        except Exception as e:
            logger.warning("抓取任務附件失敗: %s", e)

        # 3) Teams 通知
        await self._send_teams_notification(reporter_email, issue_id, task_name, permalink, comments_str, image_urls)
        # 4) Email 通知（圖片用 cid 內嵌）
        await self.email_notifier.send_completion_notification(reporter_email, issue_id, task_name, permalink, comments_str, original_description, images)

        # 5) 處理 IT 知識庫
        if self.knowledge_base:
            try:
                # 使用剛才抓取的 stories (如果有的話)
                entry = self.knowledge_base.create_entry(task, reporter_info, stories_for_kb if 'stories_for_kb' in locals() else None)
                await self.knowledge_base.save_to_sharepoint(entry)
                logger.info("IT 知識庫處理完成: %s", issue_id)
            except Exception as kb_err:
                logger.error("處理 IT 知識庫失敗: %s", kb_err)

    # ── 已通知完成 (task_gid → completed_at) 持久化 ──────────────
    _NOTIFIED_COMPLETIONS_PATH = Path("local_audit_logs") / "notified_completions.json"

    @classmethod
    def _load_notified_completions(cls) -> dict[str, str]:
        """載入 {task_gid: completed_at} map。檔案不存在或解析失敗回空 dict。"""
        try:
            if cls._NOTIFIED_COMPLETIONS_PATH.exists():
                with cls._NOTIFIED_COMPLETIONS_PATH.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {str(k): str(v) for k, v in data.items()}
        except Exception as e:
            logger.warning("載入 notified_completions.json 失敗: %s", e)
        return {}

    def _save_notified_completions(self) -> None:
        """持久化 _notified_completions 到 JSON。"""
        try:
            self._NOTIFIED_COMPLETIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
            # 限制大小避免無限成長（保留最近 5000 筆）
            if len(self._notified_completions) > 5000:
                # 無序，直接留 5000 筆
                items = list(self._notified_completions.items())[-5000:]
                self._notified_completions = dict(items)
            with self._NOTIFIED_COMPLETIONS_PATH.open("w", encoding="utf-8") as f:
                json.dump(self._notified_completions, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("儲存 notified_completions.json 失敗（不影響功能）: %s", e)

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

            comment_text = target_story.get("text", "") or ""
            author_name = target_story.get("created_by", {}).get("name", "").strip()
            logger.info("檢測到留言: [%s] %s...", author_name, comment_text[:20])

            # 整則前綴判斷（預設 public，加 [對內]/[略] 才改變）
            visibility, cleaned_text = self._classify_comment_visibility(comment_text)
            if visibility != "public":
                logger.info(
                    "評論標記為 %s，跳過 Teams/Email 通知 (Task=%s, Story=%s)",
                    visibility, task_gid, story_gid,
                )
                return

            # 抽出 inline [對內]...[/對內] blocks，剩下的才是真的 public 部分
            public_text, _inline_internals = self._split_inline_internal_blocks(cleaned_text)
            if not public_text.strip():
                logger.info(
                    "評論無 public 內容（被 inline 內部 block 吃光），跳過推播 Task=%s",
                    task_gid,
                )
                return

            # AI 雙保險消毒：把 public 部分再過一次 AI 去除敏感資訊後才推播
            redacted = await self._redact_sensitive_info(public_text)
            if redacted is None:
                logger.warning(
                    "AI 消毒失敗 (fail-safe：不推播) Task=%s, Story=%s", task_gid, story_gid,
                )
                return
            if not redacted.strip():
                logger.info(
                    "AI 判定整段皆內部資訊，略過推播 Task=%s, Story=%s", task_gid, story_gid,
                )
                return
            comment_text = redacted

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
        """從 Asana task notes 中解析提單人 email、單號、部門等資訊。
        Notes 格式: '單號: ITxxx\n提出人: Name <email>\n提出人部門: 資訊課\n...'
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

            # 提取部門資訊（支援 "提出人部門" 或 "代理提出人部門"）
            m_dept = re.search(r"提出人部門[:：]\s*(.+?)(?:\n|$)", notes)
            if m_dept:
                result["reporter_department"] = m_dept.group(1).strip()

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
        self, reporter_email: str, issue_id: str, task_name: str, permalink: str,
        comments: str = "", image_urls: Optional[List] = None,
    ) -> bool:
        """透過 Bot Framework 推播任務完成通知。"""
        detail_section = ""
        if comments:
            detail_section = f"\n\n💬 **處理方式：**\n{comments}"

        images_section = ""
        if image_urls:
            images_section = "\n\n📎 **附件圖片：**"
            for img in image_urls:
                images_section += f"\n\n![{img['name']}]({img['url']})"

        message = (
            f"🎉 **您的 IT 支援單已處理完成！**\n\n"
            f"📋 **單號：** {issue_id}\n"
            f"📝 **摘要：** {task_name}"
            f"{detail_section}"
            f"{images_section}"
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
        """Download SharePoint/OneDrive item via Graph shares API.
        Attempts to use @microsoft.graph.downloadUrl first for better reliability.
        """
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
                # 取得元資料，不限制 $select 欄位以確保拿到 @microsoft.graph.downloadUrl
                meta_resp = await client.get(base_url, headers=headers)
            except httpx.HTTPError as err:
                raise RuntimeError(f"連線 SharePoint 失敗：{err}") from err
            
            if meta_resp.status_code == 200:
                metadata = meta_resp.json()
            else:
                error_detail = ""
                try:
                    error_json = meta_resp.json()
                    error_detail = error_json.get("error", {}).get("message", "")
                except Exception:
                    pass
                
                if meta_resp.status_code == 400:
                    raise RuntimeError(f"SharePoint 連結無效或已過期 (400)：{error_detail or '請重新取得分享連結'}")
                elif meta_resp.status_code == 403:
                    raise RuntimeError("SharePoint 權限不足 (403)，請聯絡系統管理員。")
                elif meta_resp.status_code == 404:
                    raise RuntimeError("找不到 SharePoint 檔案，請確認連結是否仍有效。")
                else:
                    raise RuntimeError(f"查詢 SharePoint 檔案資訊失敗：HTTP {meta_resp.status_code} - {error_detail}")

            # 優先使用 @microsoft.graph.downloadUrl (已簽署的直接連結，穩定性最高)
            download_url = metadata.get("@microsoft.graph.downloadUrl")
            fallback_used = False
            
            try:
                if download_url:
                    # 使用預簽署連結下載時可能不需要 Authorization Header，但帶上通常無礙
                    # 有些連結若帶 Authorization 反而會 401，這裡採用無 Header 下載
                    download_resp = await client.get(download_url)
                else:
                    # 備援：原有的 /$value 方式
                    fallback_used = True
                    download_resp = await client.get(f"{base_url}/$value", headers=headers)
                
                download_resp.raise_for_status()
            except httpx.HTTPStatusError as err:
                status_code = err.response.status_code
                try:
                    err_json = err.response.json()
                    err_msg = err_json.get("error", {}).get("message", "")
                except Exception:
                    err_msg = ""
                
                method = "Fallback (/$value)" if fallback_used else "Direct (downloadUrl)"
                if status_code == 400:
                    raise RuntimeError(f"SharePoint 下載失敗 (400, {method})：連結無效或已過期。{err_msg}") from err
                if status_code == 403:
                    raise RuntimeError(f"SharePoint 下載遭拒 (403, {method})，請確認權限。{err_msg}") from err
                raise RuntimeError(f"SharePoint 下載失敗：HTTP {status_code} ({method}). {err_msg}") from err
            except httpx.HTTPError as err:
                raise RuntimeError(f"SharePoint 下載連線失敗：{err}") from err

            inferred_name = metadata.get("name")
            file_info = metadata.get("file") or {}
            inferred_mime = file_info.get("mimeType")

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
