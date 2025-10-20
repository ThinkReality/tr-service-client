"""
ThinkRealty Service Client Library

A comprehensive service-to-service communication client for ThinkRealty microservices.
Provides circuit breaker, retry logic, caching, metrics, and Gateway integration.
"""

from .client import ServiceClient, ServiceClientConfig
from .cache import LocalCache, CacheConfig
from .circuit_breaker import LocalCircuitBreaker, CircuitBreakerConfig, CircuitState
from .retry import RetryHandler, RetryConfig, BackoffStrategy
from .metrics import MetricsCollector
from .exceptions import (
    ServiceClientError,
    ServiceUnavailableError,
    CircuitOpenError,
    ServiceDiscoveryError,
    MaxRetriesExceededError,
    TimeoutError,
    InvalidConfigurationError,
    GatewayErrorResponse
)

__version__ = "0.1.0"
__author__ = "ThinkRealty Engineering"
__email__ = "engineering@thinkrealty.ae"

__all__ = [
    # Main client
    "ServiceClient",
    "ServiceClientConfig",
    
    # Components
    "LocalCache",
    "CacheConfig",
    "LocalCircuitBreaker", 
    "CircuitBreakerConfig",
    "CircuitState",
    "RetryHandler",
    "RetryConfig",
    "BackoffStrategy",
    "MetricsCollector",
    
    # Exceptions
    "ServiceClientError",
    "ServiceUnavailableError", 
    "CircuitOpenError",
    "ServiceDiscoveryError",
    "MaxRetriesExceededError",
    "TimeoutError",
    "InvalidConfigurationError",
    "GatewayErrorResponse",
]
