"""
依賴注入容器
實現服務註冊和解析功能
"""
from typing import Dict, Type, Any, TypeVar, Callable, Optional, get_type_hints
from abc import ABC, abstractmethod
import inspect
import asyncio
from enum import Enum


T = TypeVar('T')


class ServiceLifetime(Enum):
    """服務生命週期枚舉"""
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


class ServiceDescriptor:
    """服務描述符"""
    def __init__(
        self, 
        service_type: Type[T], 
        implementation: Optional[Type[T]] = None,
        factory: Optional[Callable[[], T]] = None,
        lifetime: ServiceLifetime = ServiceLifetime.SINGLETON,
        instance: Optional[T] = None
    ):
        self.service_type = service_type
        self.implementation = implementation
        self.factory = factory
        self.lifetime = lifetime
        self.instance = instance


class DependencyInjectionError(Exception):
    """依賴注入相關錯誤"""
    pass


class Container:
    """依賴注入容器"""
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._singletons: Dict[Type, Any] = {}
        self._scoped_instances: Dict[Type, Any] = {}
        self._building_services: set = set()  # 防止循環依賴
    
    def register_singleton(self, service_type: Type[T], implementation: Type[T] = None) -> 'Container':
        """註冊單例服務"""
        self._services[service_type] = ServiceDescriptor(
            service_type, 
            implementation or service_type, 
            lifetime=ServiceLifetime.SINGLETON
        )
        return self
    
    def register_transient(self, service_type: Type[T], implementation: Type[T] = None) -> 'Container':
        """註冊瞬態服務"""
        self._services[service_type] = ServiceDescriptor(
            service_type, 
            implementation or service_type, 
            lifetime=ServiceLifetime.TRANSIENT
        )
        return self
    
    def register_scoped(self, service_type: Type[T], implementation: Type[T] = None) -> 'Container':
        """註冊作用域服務"""
        self._services[service_type] = ServiceDescriptor(
            service_type, 
            implementation or service_type, 
            lifetime=ServiceLifetime.SCOPED
        )
        return self
    
    def register_factory(
        self, 
        service_type: Type[T], 
        factory: Callable[[], T],
        lifetime: ServiceLifetime = ServiceLifetime.SINGLETON
    ) -> 'Container':
        """註冊工廠方法"""
        self._services[service_type] = ServiceDescriptor(
            service_type, 
            factory=factory, 
            lifetime=lifetime
        )
        return self
    
    def register_instance(self, service_type: Type[T], instance: T) -> 'Container':
        """註冊實例 (單例)"""
        self._services[service_type] = ServiceDescriptor(
            service_type,
            instance=instance,
            lifetime=ServiceLifetime.SINGLETON
        )
        self._singletons[service_type] = instance
        return self
    
    def get(self, service_type: Type[T]) -> T:
        """獲取服務實例"""
        if service_type not in self._services:
            # 嘗試自動註冊
            if self._can_auto_register(service_type):
                self.register_transient(service_type)
            else:
                raise DependencyInjectionError(
                    f"服務 {service_type.__name__} 未註冊且無法自動註冊"
                )
        
        descriptor = self._services[service_type]
        
        # 檢查是否已有實例
        if descriptor.instance is not None:
            return descriptor.instance
        
        # 防止循環依賴
        if service_type in self._building_services:
            raise DependencyInjectionError(
                f"檢測到循環依賴：{service_type.__name__}"
            )
        
        try:
            self._building_services.add(service_type)
            
            # 根據生命週期獲取實例
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                if service_type in self._singletons:
                    return self._singletons[service_type]
                
                instance = self._create_instance(descriptor)
                self._singletons[service_type] = instance
                return instance
            
            elif descriptor.lifetime == ServiceLifetime.TRANSIENT:
                return self._create_instance(descriptor)
            
            elif descriptor.lifetime == ServiceLifetime.SCOPED:
                if service_type in self._scoped_instances:
                    return self._scoped_instances[service_type]
                
                instance = self._create_instance(descriptor)
                self._scoped_instances[service_type] = instance
                return instance
            
        finally:
            self._building_services.discard(service_type)
    
    def _can_auto_register(self, service_type: Type) -> bool:
        """判斷是否可以自動註冊服務"""
        # 只允許具體類別自動註冊，不允許抽象類或接口
        return (
            inspect.isclass(service_type) and 
            not inspect.isabstract(service_type) and
            hasattr(service_type, '__init__')
        )
    
    def _create_instance(self, descriptor: ServiceDescriptor):
        """創建實例"""
        if descriptor.factory:
            return descriptor.factory()
        
        if descriptor.instance is not None:
            return descriptor.instance
        
        implementation = descriptor.implementation
        if not implementation:
            raise DependencyInjectionError(
                f"服務 {descriptor.service_type.__name__} 沒有實現類別"
            )
        
        # 獲取構造函數
        constructor = implementation.__init__
        sig = inspect.signature(constructor)
        
        # 解析依賴
        kwargs = {}
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            
            # 嘗試從類型注解獲取依賴類型
            param_type = param.annotation
            if param_type == inspect.Parameter.empty:
                # 嘗試從 type hints 獲取
                type_hints = get_type_hints(implementation)
                if param_name in type_hints:
                    param_type = type_hints[param_name]
                else:
                    raise DependencyInjectionError(
                        f"無法解析參數 {param_name} 的類型 in {implementation.__name__}"
                    )
            
            # 檢查是否有默認值
            if param.default != inspect.Parameter.empty:
                # 有默認值的參數，嘗試解析依賴，失敗則使用默認值
                try:
                    dependency = self.get(param_type)
                    kwargs[param_name] = dependency
                except DependencyInjectionError:
                    # 使用默認值
                    pass
            else:
                # 必須的依賴
                dependency = self.get(param_type)
                kwargs[param_name] = dependency
        
        try:
            return implementation(**kwargs)
        except Exception as e:
            raise DependencyInjectionError(
                f"創建 {implementation.__name__} 實例失敗: {str(e)}"
            ) from e
    
    def clear_scoped(self):
        """清除作用域實例 (在請求結束時調用)"""
        self._scoped_instances.clear()
    
    def is_registered(self, service_type: Type) -> bool:
        """檢查服務是否已註冊"""
        return service_type in self._services
    
    def get_registered_services(self) -> Dict[Type, ServiceDescriptor]:
        """獲取所有已註冊的服務"""
        return self._services.copy()


class ServiceProvider:
    """服務提供者基類"""
    
    @abstractmethod
    def configure_services(self, container: Container) -> None:
        """配置服務"""
        pass


# 全域容器實例
_container: Optional[Container] = None

def get_container() -> Container:
    """獲取全域容器"""
    global _container
    if _container is None:
        _container = Container()
    return _container

def reset_container() -> None:
    """重置容器 (主要用於測試)"""
    global _container
    _container = None