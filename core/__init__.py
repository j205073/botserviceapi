"""
核心模組初始化
"""
from .container import Container, get_container, ServiceLifetime
from .dependencies import setup_dependency_injection

__all__ = [
    'Container',
    'get_container', 
    'ServiceLifetime',
    'setup_dependency_injection'
]