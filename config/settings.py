"""
應用程式配置管理
"""
import os
import logging
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    """Bot 相關配置"""
    app_id: str
    app_password: str


@dataclass  
class OpenAIConfig:
    """OpenAI 相關配置"""
    use_azure: bool
    api_key: str
    endpoint: Optional[str]
    api_version: str
    model: str
    intent_model: str
    summary_model: str
    vision_model: str
    max_tokens: int
    temperature: float
    timeout: int


@dataclass
class DatabaseConfig:
    """數據庫配置"""
    # 目前使用記憶體存儲，未來可擴展為真實數據庫
    retention_days: int
    max_context_messages: int


@dataclass
class S3Config:
    """S3 配置"""
    access_key: str
    secret_key: str
    bucket_name: str
    region: str


@dataclass
class GraphAPIConfig:
    """Microsoft Graph API 配置"""
    tenant_id: str
    client_id: str
    client_secret: str


@dataclass
class TaskConfig:
    """任務調度配置"""
    s3_upload_hour: int  # S3 上傳的小時 (台灣時間)
    todo_reminder_interval_seconds: int


@dataclass
class ITSupportConfig:
    """IT Support 相關配置"""
    enable_ai_analysis: bool
    analysis_model: str
    workspace_gid: str
    project_gid: str
    assignee_gid: str
    assignee_section_gid: str
    onboarding_assignee_email: str
    priority_tag_map: dict
    default_priority_tag_gid: str

    @classmethod
    def from_env(cls) -> "ITSupportConfig":
        return cls(
            enable_ai_analysis=os.getenv("ENABLE_IT_AI_ANALYSIS", "false").strip().lower() == "true",
            analysis_model=os.getenv("IT_ANALYSIS_MODEL", "gpt-5-nano").strip(),
            workspace_gid=os.getenv("ASANA_WORKSPACE_GID", "1208041237608650"),
            project_gid=os.getenv("ASANA_PROJECT_GID", "1208327275974093"),
            assignee_gid=os.getenv("ASANA_ASSIGNEE_GID", "1208683560453534"),
            assignee_section_gid=os.getenv("ASANA_ASSIGNEE_SECTION_GID", "1211277485675681"),
            onboarding_assignee_email=os.getenv("ASANA_ONBOARDING_ASSIGNEE_EMAIL", "").strip(),
            priority_tag_map={
                "P1": os.getenv("ASANA_TAG_P1", "").strip(),
                "P2": os.getenv("ASANA_TAG_P2", "").strip(),
                "P3": os.getenv("ASANA_TAG_P3", "").strip(),
                "P4": os.getenv("ASANA_TAG_P4", "").strip(),
            },
            default_priority_tag_gid=os.getenv("ASANA_PRIORITY_TAG_GID", "").strip(),
        )


@dataclass
class AppConfig:
    """應用程式總配置"""
    debug_mode: bool
    debug_account: Optional[str]
    enable_ai_intent_analysis: bool
    
    # 各模組配置
    bot: BotConfig
    openai: OpenAIConfig
    database: DatabaseConfig
    s3: S3Config
    graph_api: GraphAPIConfig
    tasks: TaskConfig
    it_support: ITSupportConfig
    
    @classmethod
    def from_env(cls) -> 'AppConfig':
        """從環境變數創建配置"""
        load_dotenv()
        
        return cls(
            debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true",
            debug_account=os.getenv("DEBUG_ACCOUNT"),
            enable_ai_intent_analysis=os.getenv("ENABLE_AI_INTENT_ANALYSIS", "false").lower() == "true",
            
            bot=BotConfig(
                app_id=os.getenv("BOT_APP_ID", ""),
                app_password=os.getenv("BOT_APP_PASSWORD", "")
            ),
            
            openai=OpenAIConfig(
                use_azure=os.getenv("USE_AZURE_OPENAI", "true").lower() == "true",
                api_key=os.getenv("AZURE_OPENAI_KEY") if os.getenv("USE_AZURE_OPENAI", "true").lower() == "true" else os.getenv("OPENAI_API_KEY", ""),
                endpoint=os.getenv("AZURE_OPENAI_ENDPOINT") if os.getenv("USE_AZURE_OPENAI", "true").lower() == "true" else os.getenv("OPENAI_ENDPOINT", ""),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                intent_model=os.getenv("OPENAI_INTENT_MODEL", "gpt-4o-mini"),
                summary_model=os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini"),
                vision_model=os.getenv("OPENAI_VISION_MODEL", "gpt-4o"),
                max_tokens=int(os.getenv("MAX_TOKENS", "4000")),
                temperature=float(os.getenv("TEMPERATURE", "0.7")),
                timeout=int(os.getenv("OPENAI_TIMEOUT", "30"))
            ),
            
            database=DatabaseConfig(
                retention_days=int(os.getenv("CONVERSATION_RETENTION_DAYS", "30")),
                max_context_messages=int(os.getenv("MAX_CONTEXT_MESSAGES", "5"))
            ),
            
            s3=S3Config(
                access_key=os.getenv("AWS_ACCESS_KEY", ""),
                secret_key=os.getenv("AWS_SECRET_KEY", ""),
                bucket_name=os.getenv("S3_BUCKET_NAME", ""),
                region=os.getenv("S3_REGION", "ap-northeast-1")
            ),
            
            graph_api=GraphAPIConfig(
                tenant_id=os.getenv("TENANT_ID", ""),
                client_id=os.getenv("CLIENT_ID", ""),
                client_secret=os.getenv("CLIENT_SECRET", "")
            ),
            
            tasks=TaskConfig(
                s3_upload_hour=int(os.getenv("S3_UPLOAD_HOUR", "7")),
                todo_reminder_interval_seconds=int(os.getenv("TODO_REMINDER_INTERVAL_SECONDS", "3600"))
            ),

            it_support=ITSupportConfig.from_env()
        )
    
    def validate(self) -> list[str]:
        """驗證配置完整性，返回錯誤列表"""
        errors = []
        
        # Bot 配置驗證
        if not self.bot.app_id:
            errors.append("BOT_APP_ID 未設置")
        if not self.bot.app_password:
            errors.append("BOT_APP_PASSWORD 未設置")
        
        # OpenAI 配置驗證
        if not self.openai.api_key:
            if self.openai.use_azure:
                errors.append("AZURE_OPENAI_KEY 未設置")
            else:
                errors.append("OPENAI_API_KEY 未設置")
        
        if self.openai.use_azure and not self.openai.endpoint:
            errors.append("AZURE_OPENAI_ENDPOINT 未設置")
        
        # Graph API 配置驗證
        if not self.graph_api.tenant_id:
            errors.append("TENANT_ID 未設置")
        if not self.graph_api.client_id:
            errors.append("CLIENT_ID 未設置")
        if not self.graph_api.client_secret:
            errors.append("CLIENT_SECRET 未設置")
        
        # S3 配置驗證 (可選)
        if self.s3.access_key and not self.s3.secret_key:
            errors.append("AWS_SECRET_KEY 未設置，但 AWS_ACCESS_KEY 已設置")
        if not self.s3.access_key and self.s3.secret_key:
            errors.append("AWS_ACCESS_KEY 未設置，但 AWS_SECRET_KEY 已設置")
        
        return errors


# 全域配置實例
config: Optional[AppConfig] = None

def get_config() -> AppConfig:
    """獲取應用程式配置"""
    global config
    if config is None:
        config = AppConfig.from_env()
        
        # 驗證配置
        errors = config.validate()
        if errors:
            logger.warning("配置驗證失敗:")
            for error in errors:
                logger.warning("  - %s", error)
            # 在開發模式下可以繼續運行，生產模式下應該拋出異常
            if not config.debug_mode:
                raise ValueError("配置不完整，無法啟動應用程式")
    
    return config