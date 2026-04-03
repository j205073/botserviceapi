"""
Web API 路由
提供 HTTP API 端點用於管理和監控
"""
from typing import Dict, Any, Optional
from quart import Blueprint, request, jsonify, make_response
from datetime import datetime
import json
import logging

from domain.services.audit_service import AuditService
from domain.services.conversation_service import ConversationService
from domain.repositories.audit_repository import AuditRepository
from config.settings import AppConfig
from shared.exceptions import NotFoundError, BusinessLogicError


# 創建 Blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api')
health_bp = Blueprint('health', __name__)


class APIRoutes:
    """API 路由類"""
    
    def __init__(
        self,
        config: AppConfig,
        audit_service: AuditService,
        conversation_service: ConversationService,
        audit_repository: AuditRepository,
        bot_adapter=None
    ):
        self.config = config
        self.audit_service = audit_service
        self.conversation_service = conversation_service
        self.audit_repository = audit_repository
        self.bot_adapter = bot_adapter
        
        # 註冊路由
        self._register_routes()
    
    def _register_routes(self):
        """註冊所有路由"""
        # 健康檢查
        health_bp.route("/ping", methods=["GET"])(self.ping)
        api_bp.route("/health", methods=["GET"])(self.deep_health_check)

        # 測試端點
        api_bp.route("/test", methods=["GET", "POST"])(self.test_api)
        api_bp.route("/routes", methods=["GET"])(self.list_routes)
        
        # 稽核日誌端點
        api_bp.route("/audit/upload-all", methods=["GET"])(self.upload_all_users_audit_logs)
        api_bp.route("/audit/upload/<user_mail>", methods=["GET"])(self.manual_upload_audit_logs)
        api_bp.route("/audit/status/<user_mail>", methods=["GET"])(self.get_audit_status)
        api_bp.route("/audit/summary", methods=["GET"])(self.get_audit_summary)
        api_bp.route("/audit/files", methods=["GET"])(self.list_audit_files)
        api_bp.route("/audit/download/<path:s3_key>", methods=["GET"])(self.get_download_url)
        api_bp.route("/audit/bucket-info", methods=["GET"])(self.get_s3_bucket_info)
        api_bp.route("/audit/local-files", methods=["GET"])(self.get_local_audit_files)
        
        # 記憶體管理端點
        api_bp.route("/memory/clear", methods=["GET"])(self.clear_user_memory)
        
        # Bot 訊息端點
        api_bp.route("/messages", methods=["POST"])(self.messages)

        # Asana Webhook 端點
        api_bp.route("/asana/webhook", methods=["POST"])(self.asana_webhook)
        api_bp.route("/asana/webhook/setup", methods=["POST"])(self.asana_webhook_setup)

        # Graph API 工具端點
        api_bp.route("/graph/departments", methods=["GET"])(self.list_all_departments)

        # SharePoint KB 知識庫查詢端點
        api_bp.route("/kb", methods=["GET"])(self.list_knowledge_base)
        api_bp.route("/kb/<issue_id>", methods=["GET"])(self.get_knowledge_entry)

    async def list_all_departments(self):
        """從 Graph API 撈出所有使用者的部門名稱（去重）。

        GET /api/graph/departments
        回傳：所有不重複部門名稱 + 建議的 KB_DEPARTMENT_MAP 模板
        """
        try:
            from core.container import get_container
            from infrastructure.external.graph_api_client import GraphAPIClient

            container = get_container()
            graph_client: GraphAPIClient = container.get(GraphAPIClient)

            # 分頁撈所有 user 的 department
            departments = set()
            dept_users = {}  # dept -> [displayName, ...]
            user_count = 0
            next_link = "users?$select=displayName,department,mail,accountEnabled&$top=999&$filter=accountEnabled eq true"

            while next_link:
                # 處理完整 URL（@odata.nextLink）或相對路徑
                if next_link.startswith("http"):
                    # nextLink 是完整 URL，需直接請求
                    import aiohttp
                    headers = await graph_client._get_headers()
                    await graph_client._ensure_session()
                    async with graph_client.session.get(next_link, headers=headers) as resp:
                        if resp.status >= 400:
                            break
                        data = json.loads(await resp.text())
                else:
                    data = await graph_client._make_request("GET", next_link)

                for user in data.get("value", []):
                    user_count += 1
                    dept = (user.get("department") or "").strip()
                    if dept:
                        departments.add(dept)
                        if dept not in dept_users:
                            dept_users[dept] = []
                        name = user.get("displayName") or user.get("mail") or ""
                        dept_users[dept].append(name)

                next_link = data.get("@odata.nextLink", "")

            sorted_depts = sorted(departments)

            # 建議模板：部門名 -> 小寫 slug
            suggested_map = {}
            for dept in sorted_depts:
                slug = dept.lower().replace(" ", "-").replace("/", "-")
                suggested_map[dept] = f"{slug}-kb"

            return jsonify({
                "success": True,
                "total_users": user_count,
                "total_departments": len(sorted_depts),
                "departments": [
                    {
                        "name": dept,
                        "count": len(dept_users.get(dept, [])),
                        "users": dept_users.get(dept, []),
                    }
                    for dept in sorted_depts
                ],
                "suggested_KB_DEPARTMENT_MAP": suggested_map,
            })

        except Exception as e:
            logging.getLogger(__name__).exception("list_all_departments failed")
            return jsonify({"success": False, "error": str(e)}), 500

    async def list_knowledge_base(self):
        """列出知識庫 JSON。"""
        try:
            year = request.args.get("year")
            month = request.args.get("month")
            
            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)
            
            if not svc.knowledge_base:
                return jsonify({"success": False, "error": "知識庫模組尚未初始化"}), 500
                
            entries = await svc.knowledge_base.list_entries(year, month)
            return jsonify({
                "success": True,
                "count": len(entries),
                "data": entries,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    async def get_knowledge_entry(self, issue_id: str):
        """取得單筆知識庫條目。"""
        try:
            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)
            
            if not svc.knowledge_base:
                return jsonify({"success": False, "error": "知識庫模組尚未初始化"}), 500
                
            entry = await svc.knowledge_base.get_entry(issue_id)
            if entry:
                return jsonify({"success": True, "data": entry})
            else:
                return jsonify({"success": False, "error": f"找不到 {issue_id}"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    async def broadcast_message(self):
        """主動推播訊息給所有註冊過的用戶端點"""
        try:
            # 檢查Content-Type
            if not request.is_json:
                return jsonify({"success": False, "error": "Content-Type 必須是 application/json"}), 415
            
            body = await request.get_json()
            message_text = body.get("message")
            if not message_text:
                return jsonify({"success": False, "error": "缺少 'message' 欄位"}), 400
            
            # 從容器中提取依賴
            from core.container import get_container
            from domain.repositories.user_repository import UserRepository
            
            container = get_container()
            try:
                user_repo: UserRepository = container.get(UserRepository)
            except Exception as e:
                return jsonify({"success": False, "error": f"無法獲取 UserRepository: {str(e)}"}), 500

            if not self.bot_adapter:
                return jsonify({"success": False, "error": "Bot適配器未初始化"}), 500

            bot_app_id = self.config.bot.app_id
            
            success_count = 0
            fail_count = 0
            
            # 遍歷所有已知的使用者會話並發送推播
            # 注意: 此處直接存取內部變數 _sessions 是一種簡便作法
            for email, session in user_repo._sessions.items():
                ref = session.conversation_reference
                if not ref:
                    continue
                    
                try:
                    # 使用 Bot Framework Adapter 的 continue_conversation 發送推播
                    async def send_proactive_message(turn_context):
                        from botbuilder.schema import Activity
                        activity = Activity(
                            type="message",
                            text=message_text
                        )
                        await turn_context.send_activity(activity)

                    await self.bot_adapter.adapter.continue_conversation(
                        ref,
                        send_proactive_message,
                        bot_app_id
                    )
                    success_count += 1
                except Exception as e:
                    print(f"推播給 {email} 失敗: {str(e)}")
                    fail_count += 1

            return jsonify({
                "success": True, 
                "message": f"推播完成：成功 {success_count} 筆，失敗 {fail_count} 筆",
                "stats": {
                    "success": success_count,
                    "fail": fail_count,
                    "total_users": len(user_repo._sessions)
                }
            })

        except Exception as e:
            print(f"❌ 廣播訊息失敗: {str(e)}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    async def ping(self):
        """健康檢查端點"""
        return jsonify({
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "Taiwan Rinnai GPT",
            "version": "2.0.0"
        })

    async def deep_health_check(self):
        """深度健康檢查 — 驗證 Bot Framework 認證與關鍵依賴。

        GET /api/health
        回傳各元件狀態，供外部監控（n8n）判斷 Teams Bot 是否可正常服務。
        """
        import os
        import time
        import aiohttp

        results = {
            "service": "Taiwan Rinnai GPT",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {},
        }
        overall_healthy = True

        # 1) Bot Framework 認證 — 最關鍵，失敗代表 Teams 訊息收不到也送不出
        try:
            app_id = self.config.bot.app_id
            app_password = self.config.bot.app_password
            if not app_id or not app_password:
                results["checks"]["bot_auth"] = {"status": "fail", "message": "BOT_APP_ID 或 BOT_APP_PASSWORD 未設定"}
                overall_healthy = False
            else:
                tenant_id = self.config.graph_api.tenant_id or "botframework.com"
                token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
                payload = {
                    "grant_type": "client_credentials",
                    "client_id": app_id,
                    "client_secret": app_password,
                    "scope": "https://api.botframework.com/.default",
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(token_url, data=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            results["checks"]["bot_auth"] = {"status": "ok", "message": "Bot Framework token 取得成功"}
                        else:
                            body = await resp.text()
                            results["checks"]["bot_auth"] = {"status": "fail", "message": f"HTTP {resp.status}: {body[:200]}"}
                            overall_healthy = False
        except Exception as e:
            results["checks"]["bot_auth"] = {"status": "fail", "message": str(e)}
            overall_healthy = False

        # 2) Bot Adapter 初始化
        if self.bot_adapter and hasattr(self.bot_adapter, 'adapter'):
            results["checks"]["bot_adapter"] = {"status": "ok", "message": "Bot adapter 已初始化"}
        else:
            results["checks"]["bot_adapter"] = {"status": "fail", "message": "Bot adapter 未初始化"}
            overall_healthy = False

        # 3) SMTP 連線（Email 通知能力）
        try:
            import smtplib
            smtp_host = os.getenv("SMTP_HOST", "smtp.office365.com")
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                results["checks"]["smtp"] = {"status": "ok", "message": f"{smtp_host}:{smtp_port} 連線正常"}
        except Exception as e:
            results["checks"]["smtp"] = {"status": "warn", "message": f"SMTP 連線失敗: {e}"}
            # SMTP 失敗不影響 Teams Bot 核心功能，標記 warn 而非 fail

        # 4) OpenAI API（AI 回覆能力）
        try:
            if self.config.openai.use_azure:
                # Azure OpenAI — 檢查 endpoint 可達
                endpoint = self.config.openai.endpoint
                api_key = self.config.openai.api_key
                if not endpoint or not api_key:
                    results["checks"]["openai"] = {"status": "warn", "message": "Azure OpenAI 未設定"}
                else:
                    test_url = f"{endpoint.rstrip('/')}/openai/models?api-version={self.config.openai.api_version}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(test_url, headers={"api-key": api_key}, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                            if resp.status == 200:
                                results["checks"]["openai"] = {"status": "ok", "message": f"Azure OpenAI 連線正常"}
                            else:
                                results["checks"]["openai"] = {"status": "warn", "message": f"Azure OpenAI HTTP {resp.status}"}
            else:
                # 原生 OpenAI — 檢查 API key 有效
                api_key = self.config.openai.api_key
                endpoint = self.config.openai.endpoint or "https://api.openai.com/v1"
                if not api_key:
                    results["checks"]["openai"] = {"status": "warn", "message": "OPENAI_API_KEY 未設定"}
                else:
                    test_url = f"{endpoint.rstrip('/')}/models"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(test_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                            if resp.status == 200:
                                model = self.config.openai.model
                                results["checks"]["openai"] = {"status": "ok", "message": f"OpenAI API 正常 (model: {model})"}
                            else:
                                results["checks"]["openai"] = {"status": "warn", "message": f"OpenAI API HTTP {resp.status}"}
        except Exception as e:
            results["checks"]["openai"] = {"status": "warn", "message": f"OpenAI 連線失敗: {e}"}

        # 5) Asana API（提單功能）
        try:
            asana_token = os.getenv("ASANA_ACCESS_TOKEN", "")
            if not asana_token:
                results["checks"]["asana"] = {"status": "warn", "message": "ASANA_ACCESS_TOKEN 未設定"}
            else:
                async with aiohttp.ClientSession() as session:
                    headers = {"Authorization": f"Bearer {asana_token}"}
                    async with session.get("https://app.asana.com/api/1.0/users/me", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            results["checks"]["asana"] = {"status": "ok", "message": "Asana API 認證正常"}
                        else:
                            results["checks"]["asana"] = {"status": "warn", "message": f"Asana API HTTP {resp.status}"}
        except Exception as e:
            results["checks"]["asana"] = {"status": "warn", "message": f"Asana API 連線失敗: {e}"}

        # 6) Microsoft Graph API（使用者資訊、會議室預約）
        try:
            tenant_id = self.config.graph_api.tenant_id
            client_id = self.config.graph_api.client_id
            client_secret = self.config.graph_api.client_secret
            if not all([tenant_id, client_id, client_secret]):
                results["checks"]["graph_api"] = {"status": "warn", "message": "Graph API 憑證未完整設定"}
            else:
                token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
                payload = {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(token_url, data=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            results["checks"]["graph_api"] = {"status": "ok", "message": "Graph API token 取得成功"}
                        else:
                            results["checks"]["graph_api"] = {"status": "warn", "message": f"Graph API token 失敗 HTTP {resp.status}"}
        except Exception as e:
            results["checks"]["graph_api"] = {"status": "warn", "message": f"Graph API 連線失敗: {e}"}

        # 7) 環境設定完整性
        config_issues = self.config.validate()
        if config_issues:
            results["checks"]["config"] = {"status": "warn", "message": f"設定不完整: {'; '.join(config_issues[:3])}"}
        else:
            results["checks"]["config"] = {"status": "ok", "message": "所有必要環境變數已設定"}

        # 8) Asana Webhook 存活檢查 + 自動重建
        try:
            from features.it_support.service import ITSupportService
            from core.container import get_container
            svc: ITSupportService = get_container().get(ITSupportService)

            workspace_gid = svc.workspace_gid
            project_gid = svc.project_gid
            if not project_gid:
                results["checks"]["asana_webhook"] = {"status": "warn", "message": "ASANA_PROJECT_GID 未設定"}
            else:
                webhooks = await svc.asana.list_webhooks(workspace_gid, resource_gid=project_gid)
                active_hooks = [w for w in webhooks if w.get("active", False)]

                if active_hooks:
                    results["checks"]["asana_webhook"] = {
                        "status": "ok",
                        "message": f"Webhook 存活中（{len(active_hooks)} 個有效訂閱）",
                    }
                else:
                    # 自動重建 webhook
                    host = request.headers.get("Host", "")
                    scheme = request.headers.get("X-Forwarded-Proto", "https")
                    if host:
                        target_url = f"{scheme}://{host}/api/asana/webhook"
                        rebuild_result = await svc.setup_webhook(target_url)
                        if rebuild_result.get("success"):
                            results["checks"]["asana_webhook"] = {
                                "status": "ok",
                                "message": f"Webhook 已自動重建 → {target_url}",
                            }
                        else:
                            results["checks"]["asana_webhook"] = {
                                "status": "warn",
                                "message": f"Webhook 不存在且自動重建失敗: {rebuild_result.get('error', '')}",
                            }
                    else:
                        results["checks"]["asana_webhook"] = {
                            "status": "warn",
                            "message": "Webhook 不存在，無法推導 target_url 進行重建",
                        }
        except Exception as e:
            results["checks"]["asana_webhook"] = {"status": "warn", "message": f"Webhook 檢查失敗: {e}"}

        # 9) Teams 推播能力（conversation refs 數量）
        try:
            from app import user_conversation_refs
            ref_count = len(user_conversation_refs)
            if ref_count > 0:
                results["checks"]["teams_push"] = {
                    "status": "ok",
                    "message": f"可推播 {ref_count} 位使用者",
                }
            else:
                results["checks"]["teams_push"] = {
                    "status": "warn",
                    "message": "尚無使用者 conversation reference（重啟後需使用者先與 Bot 互動）",
                }
        except Exception as e:
            results["checks"]["teams_push"] = {"status": "warn", "message": f"無法取得推播狀態: {e}"}

        # 彙總
        results["status"] = "healthy" if overall_healthy else "unhealthy"

        status_code = 200 if overall_healthy else 503
        return jsonify(results), status_code

    async def test_api(self):
        """測試 API 端點"""
        method = request.method
        
        response_data = {
            "message": "TR_GPT API 測試成功",
            "method": method,
            "timestamp": datetime.utcnow().isoformat(),
            "config": {
                "debug_mode": self.config.debug_mode,
                "openai_mode": "Azure" if self.config.openai.use_azure else "OpenAI",
                "ai_intent_analysis": self.config.enable_ai_intent_analysis
            }
        }
        
        if method == "POST":
            try:
                request_data = await request.get_json()
                response_data["request_data"] = request_data
            except Exception:
                response_data["request_data"] = "無法解析 JSON"
        
        return jsonify(response_data)
    
    async def list_routes(self):
        """列出所有可用的 API 路由"""
        routes = []
        
        # 這裡可以動態獲取所有註冊的路由
        # 暫時返回靜態列表
        available_routes = [
            {"path": "/ping", "method": "GET", "description": "基本健康檢查"},
            {"path": "/api/health", "method": "GET", "description": "深度健康檢查（Bot 認證 + 依賴元件）"},
            {"path": "/api/test", "method": "GET|POST", "description": "API 測試"},
            {"path": "/api/routes", "method": "GET", "description": "列出所有路由"},
            {"path": "/api/audit/upload-all", "method": "GET", "description": "上傳所有用戶的稽核日誌"},
            {"path": "/api/audit/upload/<user_mail>", "method": "GET", "description": "上傳指定用戶的稽核日誌"},
            {"path": "/api/audit/status/<user_mail>", "method": "GET", "description": "獲取用戶稽核狀態"},
            {"path": "/api/audit/summary", "method": "GET", "description": "獲取稽核摘要"},
            {"path": "/api/audit/files", "method": "GET", "description": "列出稽核文件"},
            {"path": "/api/audit/download/<s3_key>", "method": "GET", "description": "獲取下載 URL"},
            {"path": "/api/audit/bucket-info", "method": "GET", "description": "獲取 S3 儲存桶資訊"},
            {"path": "/api/audit/local-files", "method": "GET", "description": "獲取本地稽核文件"},
            {"path": "/api/memory/clear", "method": "GET", "description": "清除用戶記憶體"},
            {"path": "/api/messages", "method": "POST", "description": "Bot 訊息處理"},
            {"path": "/api/asana/webhook", "method": "POST", "description": "Asana Webhook 回呼"},
            {"path": "/api/asana/webhook/setup", "method": "POST", "description": "建立 Asana Webhook 訂閱"},
        ]
        
        return jsonify({
            "routes": available_routes,
            "total": len(available_routes)
        })
    
    async def upload_all_users_audit_logs(self):
        """上傳所有用戶的稽核日誌"""
        try:
            result = await self.audit_service.upload_all_users_audit_logs()
            return jsonify({
                "success": True,
                "message": "開始上傳所有用戶的稽核日誌",
                "result": result
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def manual_upload_audit_logs(self, user_mail: str):
        """手動上傳指定用戶的稽核日誌"""
        try:
            result = await self.audit_service.upload_user_audit_logs(user_mail)
            return jsonify({
                "success": True,
                "user_mail": user_mail,
                "result": result
            })
        except NotFoundError as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 404
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def get_audit_status(self, user_mail: str):
        """獲取用戶稽核狀態"""
        try:
            status = await self.audit_service.get_user_audit_status(user_mail)
            return jsonify({
                "user_mail": user_mail,
                "status": status
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def get_audit_summary(self):
        """獲取稽核摘要"""
        try:
            summary = await self.audit_service.get_audit_summary()
            return jsonify(summary)
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def list_audit_files(self):
        """列出稽核文件"""
        try:
            user_mail = request.args.get("user_mail")
            date_filter = request.args.get("date")
            include_download_url = (
                request.args.get("include_download_url", "false").lower() == "true"
            )
            expiration = int(request.args.get("expiration", "3600"))

            files = await self.audit_service.list_audit_files(
                user_mail=user_mail,
                date_filter=date_filter,
                include_download_url=include_download_url,
                expiration=expiration,
            )

            return jsonify({
                "success": True,
                "files": files,
                "total_files": len(files),
                "filters": {
                    "user_mail": user_mail,
                    "date": date_filter,
                    "include_download_url": include_download_url,
                    "url_expiration": expiration if include_download_url else None,
                },
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def get_download_url(self, s3_key: str):
        """獲取下載 URL"""
        try:
            expiration = int(request.args.get("expiration", "3600"))
            download_url = await self.audit_service.generate_download_url(s3_key, expiration)
            return jsonify({
                "download_url": download_url,
                "s3_key": s3_key,
                "expires_in": expiration
            })
        except NotFoundError as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 404
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def get_s3_bucket_info(self):
        """獲取 S3 儲存桶資訊"""
        try:
            bucket_info = await self.audit_service.get_s3_bucket_info()
            return jsonify(bucket_info)
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def get_local_audit_files(self):
        """獲取本地稽核文件"""
        try:
            local_files = await self.audit_service.get_local_audit_files()
            return jsonify({
                "local_files": local_files,
                "total": len(local_files)
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def clear_user_memory(self):
        """清除用戶記憶體"""
        user_mail = request.args.get('user_mail')
        
        if not user_mail:
            return jsonify({
                "success": False,
                "error": "缺少 user_mail 參數"
            }), 400
        
        try:
            await self.conversation_service.clear_working_memory(user_mail)
            return jsonify({
                "success": True,
                "message": f"已清除用戶 {user_mail} 的記憶體",
                "user_mail": user_mail
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    async def messages(self):
        """Bot 訊息處理端點"""
        try:
            print("=== 開始處理訊息 ===")
            
            # 檢查Content-Type
            if "application/json" not in request.headers.get("Content-Type", ""):
                return {"status": 415}
            
            # 獲取請求體
            body = await request.get_json()
            print(f"請求內容: {json.dumps(body, ensure_ascii=False, indent=2)}")
            
            # 獲取Authorization header
            auth_header = request.headers.get("Authorization", "")
            print(f"Authorization header: {auth_header[:50] if auth_header else '(空白)'}")
            print(f"Current Bot App ID: {self.config.bot.app_id or '(空白)'}")
            
            # 檢查是否有Bot適配器
            if not self.bot_adapter:
                raise Exception("Bot適配器未初始化")
            
            # 處理Bot Framework活動
            result = await self.bot_adapter.process_activity(body, auth_header)
            
            print("=== 訊息處理完成 ===")
            return {"status": 200}
            
        except Exception as e:
            print(f"❌ Error processing message: {str(e)}")
            return {"status": 500}

    async def asana_webhook(self):
        """Asana Webhook 回呼端點（含 handshake 驗證）"""
        logger = logging.getLogger(__name__)

        # Handshake: Asana 建立 webhook 時會發送 X-Hook-Secret
        hook_secret = request.headers.get("X-Hook-Secret")
        if hook_secret:
            logger.info("Asana Webhook handshake 收到 X-Hook-Secret")
            resp = await make_response("", 200)
            resp.headers["X-Hook-Secret"] = hook_secret
            # 儲存 secret 供後續驗證
            try:
                from core.container import get_container
                from features.it_support.service import ITSupportService
                svc: ITSupportService = get_container().get(ITSupportService)
                svc._webhook_secret = hook_secret
            except Exception:
                pass
            return resp

        # 正常事件處理
        try:
            body = await request.get_json()
            events = body.get("events", [])
            if not events:
                return jsonify({"ok": True})

            logger.info("Asana Webhook 收到 %d 個事件", len(events))

            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)
            result = await svc.handle_webhook_event(events)

            logger.info("Webhook 處理結果: %s", result)
            return jsonify({"ok": True, **result})
        except Exception as e:
            logger.error("Asana Webhook 處理失敗: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    async def asana_webhook_setup(self):
        """手動建立 Asana Webhook 訂閱"""
        try:
            body = await request.get_json() or {}
            # target_url 可從 body 取得，或自動推導
            target_url = body.get("target_url", "").strip()
            if not target_url:
                # 嘗試從 Host header 推導
                host = request.headers.get("Host", "")
                scheme = request.headers.get("X-Forwarded-Proto", "https")
                if host:
                    target_url = f"{scheme}://{host}/api/asana/webhook"

            if not target_url:
                return jsonify({
                    "success": False,
                    "error": "請提供 target_url 或確認 Host header"
                }), 400

            from core.container import get_container
            from features.it_support.service import ITSupportService
            svc: ITSupportService = get_container().get(ITSupportService)
            result = await svc.setup_webhook(target_url)
            return jsonify(result)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


def create_api_routes(
    config: AppConfig,
    audit_service: AuditService,
    conversation_service: ConversationService,
    audit_repository: AuditRepository,
    bot_adapter=None
) -> tuple[Blueprint, Blueprint]:
    """創建 API 路由"""
    api_routes = APIRoutes(config, audit_service, conversation_service, audit_repository, bot_adapter)
    return api_bp, health_bp
