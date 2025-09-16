"""
依賴注入配置
註冊所有服務到容器中
"""
from core.container import Container, ServiceProvider
from config.settings import AppConfig, get_config


class CoreServiceProvider(ServiceProvider):
    """核心服務提供者"""
    
    def configure_services(self, container: Container) -> None:
        """配置核心服務"""
        # 註冊配置
        config = get_config()
        container.register_instance(AppConfig, config)


class InfrastructureServiceProvider(ServiceProvider):
    """基礎設施服務提供者"""
    
    def configure_services(self, container: Container) -> None:
        """配置基礎設施服務"""
        # OpenAI 服務
        from infrastructure.external.openai_client import OpenAIClient
        container.register_singleton(OpenAIClient)
        
        # Graph API 服務
        from infrastructure.external.graph_api_client import GraphAPIClient
        from infrastructure.external.token_manager import TokenManager
        container.register_singleton(TokenManager)
        container.register_singleton(GraphAPIClient)
        
        # S3 服務
        from infrastructure.external.s3_client import S3Client
        container.register_singleton(S3Client)
        
        # Bot 適配器
        from infrastructure.bot.bot_adapter import CustomBotAdapter
        container.register_singleton(CustomBotAdapter)


class RepositoryServiceProvider(ServiceProvider):
    """Repository 服務提供者"""
    
    def configure_services(self, container: Container) -> None:
        """配置 Repository 服務"""
        from domain.repositories.todo_repository import TodoRepository, InMemoryTodoRepository
        from domain.repositories.audit_repository import AuditRepository, InMemoryAuditRepository  
        from domain.repositories.conversation_repository import ConversationRepository, InMemoryConversationRepository
        from domain.repositories.user_repository import UserRepository, InMemoryUserRepository
        
        # 註冊 Repository 實現
        container.register_singleton(TodoRepository, InMemoryTodoRepository)
        container.register_singleton(AuditRepository, InMemoryAuditRepository)
        container.register_singleton(ConversationRepository, InMemoryConversationRepository)
        container.register_singleton(UserRepository, InMemoryUserRepository)


class DomainServiceProvider(ServiceProvider):
    """領域服務提供者"""
    
    def configure_services(self, container: Container) -> None:
        """配置領域服務"""
        from domain.services.intent_service import IntentService
        from domain.services.todo_service import TodoService
        from domain.services.meeting_service import MeetingService
        from domain.services.audit_service import AuditService
        from domain.services.conversation_service import ConversationService
        
        # 註冊領域服務
        container.register_singleton(IntentService)
        container.register_singleton(TodoService)
        container.register_singleton(MeetingService)
        
        # AuditService 需要特殊處理，因為它需要S3客戶端
        def create_audit_service():
            from infrastructure.external.s3_client import S3Client
            from domain.repositories.audit_repository import AuditRepository
            config = container.get(AppConfig)
            audit_repository = container.get(AuditRepository)
            s3_client = container.get(S3Client)
            return AuditService(config, audit_repository, s3_client)
        
        container.register_factory(AuditService, create_audit_service)
        container.register_singleton(ConversationService)


class ApplicationServiceProvider(ServiceProvider):
    """應用服務提供者"""
    
    def configure_services(self, container: Container) -> None:
        """配置應用服務"""
        from application.services.application_service import ApplicationService
        from application.handlers.bot_command_handler import BotCommandHandler
        from presentation.bot.message_handler import TeamsMessageHandler
        from presentation.web.api_routes import create_api_routes
        from features.it_support.service import ITSupportService
        
        # 註冊應用服務
        container.register_singleton(ApplicationService)
        container.register_singleton(BotCommandHandler)
        container.register_singleton(TeamsMessageHandler)
        container.register_singleton(ITSupportService)
        
        # 註冊 API 路由工廠
        def create_routes():
            from domain.services.audit_service import AuditService
            from domain.services.conversation_service import ConversationService
            from domain.repositories.audit_repository import AuditRepository
            from infrastructure.bot.bot_adapter import CustomBotAdapter
            
            return create_api_routes(
                container.get(AppConfig),
                container.get(AuditService),
                container.get(ConversationService),
                container.get(AuditRepository),
                container.get(CustomBotAdapter)
            )
            
        container.register_factory(tuple, create_routes)


class TaskServiceProvider(ServiceProvider):
    """任務服務提供者"""
    
    def configure_services(self, container: Container) -> None:
        """配置任務服務"""
        # 任務服務暫時不實現，保留給未來擴展
        pass


def configure_all_services(container: Container) -> None:
    """配置所有服務"""
    providers = [
        CoreServiceProvider(),
        InfrastructureServiceProvider(),
        RepositoryServiceProvider(),
        DomainServiceProvider(),
        ApplicationServiceProvider(),
        TaskServiceProvider(),
    ]
    
    for provider in providers:
        provider.configure_services(container)


def setup_dependency_injection() -> Container:
    """設置依賴注入"""
    from core.container import get_container
    
    container = get_container()
    configure_all_services(container)
    
    print("✅ 依賴注入配置完成")
    return container
