"""
應用程式異常定義
"""

class TRGPTException(Exception):
    """TR GPT 基礎異常"""
    def __init__(self, message: str, error_code: str = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class ValidationError(TRGPTException):
    """驗證錯誤"""
    pass


class BusinessLogicError(TRGPTException):
    """業務邏輯錯誤"""
    pass


class ExternalServiceError(TRGPTException):
    """外部服務錯誤"""
    def __init__(self, service_name: str, message: str, error_code: str = None):
        super().__init__(f"{service_name}: {message}", error_code)
        self.service_name = service_name


class OpenAIServiceError(ExternalServiceError):
    """OpenAI 服務錯誤"""
    def __init__(self, message: str, error_code: str = None):
        super().__init__("OpenAI", message, error_code)


class GraphAPIError(ExternalServiceError):
    """Microsoft Graph API 錯誤"""
    def __init__(self, message: str, error_code: str = None):
        super().__init__("Microsoft Graph", message, error_code)


class S3ServiceError(ExternalServiceError):
    """S3 服務錯誤"""
    def __init__(self, message: str, error_code: str = None):
        super().__init__("S3", message, error_code)


class RepositoryError(TRGPTException):
    """數據存取錯誤"""
    pass


class NotFoundError(RepositoryError):
    """資源未找到錯誤"""
    pass


class DuplicateError(RepositoryError):
    """重複資源錯誤"""
    pass


class AuthenticationError(TRGPTException):
    """認證錯誤"""
    pass


class AuthorizationError(TRGPTException):
    """授權錯誤"""
    pass


class BotFrameworkError(TRGPTException):
    """Bot Framework 錯誤"""
    pass


class ConfigurationError(TRGPTException):
    """配置錯誤"""
    pass