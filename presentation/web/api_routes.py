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
    
    async def ping(self):
        """健康檢查端點"""
        return jsonify({
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "Taiwan Rinnai GPT",
            "version": "2.0.0"
        })
    
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
            {"path": "/ping", "method": "GET", "description": "健康檢查"},
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
