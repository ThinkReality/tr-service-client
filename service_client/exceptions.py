class ServiceClientError(Exception):
    """Base exception for ServiceClient errors"""
    def __init__(self, message: str, error_code: int = None):
        self.error_code = error_code
        super().__init__(message)

class ServiceUnavailableError(ServiceClientError):
    """Target service is unavailable"""
    def __init__(self, service_name: str, reason: str = None):
        self.service_name = service_name
        self.reason = reason
        error_message = f"Service '{service_name}' is unavailable"
        if reason:
            error_message += f": {reason}"
        super().__init__(error_message)

class CircuitOpenError(ServiceClientError):
    """Circuit breaker is open, failing fast"""
    def __init__(self, service_name: str, circuit_name: str):
        self.service_name = service_name
        self.circuit_name = circuit_name
        super().__init__(f"Circuit {circuit_name} for service {service_name} is OPEN")

class ServiceDiscoveryError(ServiceClientError):
    """Failed to discover service instances"""
    def __init__(self, service_name: str, error_details: str = None):
        self.service_name = service_name
        self.error_details = error_details
        error_message = f"Failed to discover instances for service '{service_name}'"
        if error_details:
            error_message += f": {error_details}"
        super().__init__(error_message)

class MaxRetriesExceededError(ServiceClientError):
    """Maximum retry attempts exceeded"""
    def __init__(self, service_name: str, endpoint: str, attempts: int):
        self.service_name = service_name
        self.endpoint = endpoint
        self.attempts = attempts
        super().__init__(f"Max retries ({attempts}) exceeded for {service_name}: {endpoint}")

class TimeoutError(ServiceClientError):
    """Request timeout exceeded"""
    def __init__(self, service_name: str, endpoint: str, timeout_duration: float):
        self.service_name = service_name
        self.endpoint = endpoint
        self.timeout_duration = timeout_duration
        super().__init__(f"Request to {service_name}{endpoint} timed out after {timeout_duration} seconds")

class InvalidConfigurationError(ServiceClientError):
    """Invalid ServiceClient configuration"""
    def __init__(self, config_key: str, config_value: str, message: str = None):
        self.config_key = config_key
        self.config_value = config_value
        error_message = message or f"Invalid configuration for key '{config_key}' with value '{config_value}'"
        super().__init__(error_message)

class GatewayErrorResponse(ServiceClientError):
    """Gateway-specific error response"""
    def __init__(self, error_type: str, message: str, correlation_id: str = None):
        self.error_type = error_type
        self.correlation_id = correlation_id
        error_message = f"{error_type}: {message}"
        if correlation_id:
            error_message += f" (correlation_id: {correlation_id})"
        super().__init__(error_message)