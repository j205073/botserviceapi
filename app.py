"""
TR GPT - 台灣林內 GPT 主應用程式
重構後的版本使用清潔架構和依賴注入
"""
import asyncio
import os
import sys
import logging
from datetime import timedelta
from typing import Dict, Any

# 配置日誌
logging.basicConfig(encoding="utf-8", level=logging.INFO)
logger = logging.getLogger(__name__)
sys.stdout.reconfigure(encoding="utf-8")

# Quart 應用程式
from quart import Quart, request, jsonify

# 依賴注入和配置
from core.dependencies import setup_dependency_injection
from config.settings import AppConfig

# 應用程式服務
from application.services.application_service import ApplicationService
from infrastructure.bot.bot_adapter import CustomBotAdapter

# 全域變數 (暫時保持向後相容性)
user_conversation_refs = {}
user_display_names = {}
user_model_preferences = {}

# 模型資訊 (暫時保持，後續會移到配置中)
MODEL_INFO = {
    "gpt-4o": {
        "speed": "快速",
        "time": "5-10秒",
        "use_case": "日常對話",
        "timeout": 20,
    },
    "gpt-4o-mini": {
        "speed": "最快",
        "time": "3-5秒",
        "use_case": "簡單問題",
        "timeout": 15,
    },
    "gpt-5-mini": {
        "speed": "中等",
        "time": "15-30秒",
        "use_case": "推理任務",
        "timeout": 45,
    },
    "gpt-5-nano": {
        "speed": "最快",
        "time": "2-4秒",
        "use_case": "輕量查詢",
        "timeout": 10,
    },
    "gpt-5": {
        "speed": "較慢",
        "time": "60-120秒",
        "use_case": "複雜推理",
        "timeout": 120,
    }
}


class TRGPTApp:
    """TR GPT 應用程式類"""
    
    def __init__(self):
        self.app: Quart = None
        self.container = None
        self.config: AppConfig = None
        self.bot_adapter: CustomBotAdapter = None
        self.application_service: ApplicationService = None
        
        # 初始化應用程式
        self._initialize()
    
    def _initialize(self):
        """初始化應用程式"""
        logger.info("初始化 TR GPT 應用程式...")
        
        try:
            # 設置依賴注入
            self.container = setup_dependency_injection()
            
            # 獲取核心服務
            self.config = self.container.get(AppConfig)
            self.bot_adapter = self.container.get(CustomBotAdapter)
            self.application_service = self.container.get(ApplicationService)
            
            # 創建 Quart 應用程式
            self.app = Quart(__name__)
            self.app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
            
            # 註冊路由
            self._register_routes()
            
            # 啟動背景任務
            self._setup_background_tasks()
            
            logger.info("TR GPT 應用程式初始化完成")
            
        except Exception as e:
            logger.error("應用程式初始化失敗: %s", e)
            from shared.utils.error_notifier import notify_critical_error
            notify_critical_error("應用程式啟動失敗", e)
            raise
    
    def _register_routes(self):
        """註冊路由"""
        try:
            # 註冊健康檢查和 API 路由
            api_blueprints = self.container.get(tuple)  # (api_bp, health_bp)
            api_blueprint, health_blueprint = api_blueprints
            
            self.app.register_blueprint(health_blueprint)
            self.app.register_blueprint(api_blueprint)
            
            # 註冊 Bot Framework 訊息處理路由
            @self.app.route("/api/messages", methods=["POST"])
            async def handle_bot_messages():
                """處理 Bot Framework 訊息"""
                try:
                    activity = await request.get_json()
                    auth_header = request.headers.get("Authorization", "")
                    
                    # 使用 Bot 適配器處理訊息
                    response = await self.bot_adapter.process_activity(activity, auth_header)
                    
                    return jsonify(response or {})
                    
                except Exception as e:
                    logger.error("處理 Bot 訊息失敗: %s", e)
                    return jsonify({"error": "處理訊息失敗"}), 500
            
            logger.info("路由註冊完成")
            
        except Exception as e:
            logger.error("路由註冊失敗: %s", e)
            raise
    
    def _setup_background_tasks(self):
        """設置背景任務"""
        try:
            @self.app.before_serving
            async def startup():
                """應用程式啟動時執行"""
                logger.info("應用程式啟動中...")
                
                # 啟動定時任務
                asyncio.create_task(self._daily_maintenance_task())
                
                logger.info("背景任務已啟動")
            
            @self.app.after_serving
            async def shutdown():
                """應用程式關閉時執行"""
                logger.info("應用程式正在關閉...")
                # 這裡可以添加清理邏輯
                logger.info("應用程式已關閉")
            
        except Exception as e:
            logger.error("背景任務設置失敗: %s", e)
            raise
    
    async def _daily_maintenance_task(self):
        """每日維護任務"""
        try:
            while True:
                # 計算距離下次執行的時間（每天台灣時間 7:00）
                from shared.utils.helpers import get_taiwan_time
                now = get_taiwan_time()
                next_run = now.replace(hour=self.config.tasks.s3_upload_hour, minute=0, second=0, microsecond=0)
                
                if next_run <= now:
                    next_run += timedelta(days=1)
                
                sleep_seconds = (next_run - now).total_seconds()
                logger.info("下次維護任務將在 %s 執行", next_run)
                
                await asyncio.sleep(sleep_seconds)
                
                # 執行維護任務
                logger.info("開始執行每日維護任務...")
                maintenance_result = await self.application_service.perform_system_maintenance()
                
                if maintenance_result.get("success"):
                    logger.info("每日維護任務完成")
                else:
                    logger.error("每日維護任務失敗: %s", maintenance_result.get('error'))
                
        except Exception as e:
            logger.error("每日維護任務異常: %s", e)
            from shared.utils.error_notifier import notify_critical_error
            notify_critical_error("每日維護任務崩潰", e)
    
    def get_app(self) -> Quart:
        """獲取 Quart 應用程式實例"""
        return self.app
    
    async def get_system_health(self) -> Dict[str, Any]:
        """獲取系統健康狀態"""
        return await self.application_service.get_system_health()


# 創建應用程式實例
tr_gpt_app = TRGPTApp()
app = tr_gpt_app.get_app()


# 主程式入口
if __name__ == "__main__":
    logger.info(
        "台灣林內 GPT v2.0 啟動 | Debug=%s | OpenAI=%s | 意圖分析=%s",
        tr_gpt_app.config.debug_mode,
        "Azure" if tr_gpt_app.config.openai.use_azure else "OpenAI",
        tr_gpt_app.config.enable_ai_intent_analysis,
    )
    
    # 開發模式使用 app.run()，生產模式使用 hypercorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    logger.info("啟動服務於 http://%s:%s", host, port)
    app.run(host=host, port=port, debug=tr_gpt_app.config.debug_mode)