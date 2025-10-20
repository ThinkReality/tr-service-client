import aiohttp
import asyncio
import uuid
import time
from typing import Dict, Any, Optional, List
# ServiceDiscovery removed - routing through Gateway
from .circuit_breaker import LocalCircuitBreaker, CircuitBreakerConfig
from .retry import RetryHandler, RetryConfig
from .cache import LocalCache, CacheConfig
from .metrics import MetricsCollector
from .exceptions import *
from pydantic import BaseModel, Field

class ServiceClientConfig(BaseModel):
    # API Gateway connection
    gateway_url: str = Field(..., description="API Gateway base URL")
    gateway_timeout: int = Field(default=30, description="Gateway timeout in seconds")
    
    # Service identification
    service_name: str = Field(..., description="Name of this service")
    service_token: str = Field(..., description="Service authentication token")
    
    # Default configurations
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    
    # Service-specific overrides
    service_timeouts: Dict[str, int] = Field(default_factory=dict)
    circuit_breakers: Dict[str, CircuitBreakerConfig] = Field(default_factory=dict)
    
    class Config:
        env_prefix = "SERVICE_CLIENT_"
        case_sensitive = False

class ServiceClient:
    """
    Main client for service-to-service communication in ThinkRealty microservices
    """
    
    def __init__(self, config: ServiceClientConfig):
        self.config = config
        self.service_name = config.service_name
        self.service_token = config.service_token
        
        # Initialize components
        # Note: Service discovery removed as we route through Gateway
        self.retry_handler = RetryHandler(config.retry)
        self.cache = LocalCache(config.cache)
        self.metrics = MetricsCollector(config.service_name)
        
        # Circuit breakers per target service
        self._circuit_breakers: Dict[str, LocalCircuitBreaker] = {}
        self._http_session: Optional[aiohttp.ClientSession] = None
        
        # Request tracking
        self._active_requests: Dict[str, asyncio.Task] = {}
        
        # Gateway availability tracking
        self._gateway_available: bool = True
        self._last_gateway_check: float = 0
        self._gateway_check_interval: float = 30.0  # Check every 30 seconds
        
    async def __aenter__(self):
        await self.start()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        
    async def start(self):
        """Initialize the client"""
        self._http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.gateway_timeout)
        )
        
    async def close(self):
        """Cleanup resources"""
        if self._http_session:
            await self._http_session.close()
            
        # Cancel any active requests
        for task in self._active_requests.values():
            task.cancel()
            
    def _get_circuit_breaker(self, target_service: str) -> LocalCircuitBreaker:
        """Get or create circuit breaker for target service"""
        if target_service not in self._circuit_breakers:
            # Use service-specific config if available, otherwise defaults
            circuit_config = self.config.circuit_breakers.get(
                target_service, 
                self.config.circuit_breaker
            )
            self._circuit_breakers[target_service] = LocalCircuitBreaker(
                name=f"{target_service}-circuit",
                config=circuit_config,
                gateway_url=self.config.gateway_url,
                service_token=self.service_token
            )
        return self._circuit_breakers[target_service]
    
    async def call(
        self,
        target_service: str,
        endpoint: str,
        method: str = "GET",
        data: Optional[Any] = None,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        timeout: Optional[int] = None,
        use_cache: bool = True,
        use_circuit_breaker: bool = True,
        use_retry: bool = True
    ) -> Any:
        """
        Main method to call another service
        """
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        try:
            self.metrics.record_request(target_service, endpoint, method)
            
            # Step 1: Check circuit breaker
            if use_circuit_breaker:
                circuit_breaker = self._get_circuit_breaker(target_service)
                if not await circuit_breaker.can_execute():
                    self.metrics.record_circuit_open(circuit_breaker.name)
                    raise CircuitOpenError(target_service, circuit_breaker.name)
            
            # Step 2: Check local cache (for GET requests)
            if use_cache and method.upper() == "GET":
                cached_response = self.cache.get(target_service, endpoint, method, params or {})
                if cached_response is not None:
                    self.metrics.record_cache_hit(target_service)
                    return cached_response
                self.metrics.record_cache_miss(target_service)
            
            # Step 3: Execute with retry logic
            if use_retry:
                response = await self.retry_handler.execute_with_retry(
                    operation=self._execute_request,
                    operation_name=target_service,
                    target_service=target_service,
                    endpoint=endpoint,
                    method=method,
                    data=data,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                    request_id=request_id
                )
            else:
                response = await self._execute_request(
                    target_service=target_service,
                    endpoint=endpoint,
                    method=method,
                    data=data,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                    request_id=request_id
                )
            
            # Step 4: Record success
            if use_circuit_breaker:
                await circuit_breaker.record_success()
                
            latency = time.time() - start_time
            self.metrics.record_success(target_service, endpoint, latency, method)
            
            # Step 5: Cache successful GET responses
            if use_cache and method.upper() == "GET":
                self.cache.set(target_service, endpoint, method, params or {}, response)
            
            return response
            
        except Exception as e:
            # Record failure
            latency = time.time() - start_time
            self.metrics.record_failure(target_service, endpoint, str(e), method)
            
            if use_circuit_breaker:
                await circuit_breaker.record_failure()
                
            # If we have a cached response and the service is failing, return it
            if use_cache and method.upper() == "GET":
                cached_response = self.cache.get(target_service, endpoint, method, params or {})
                if cached_response is not None:
                    print(f"Returning cached response due to error: {e}")
                    return cached_response
                    
            raise
    
    async def _execute_request(
        self,
        target_service: str,
        endpoint: str,
        method: str,
        data: Optional[Any],
        params: Optional[Dict],
        headers: Optional[Dict],
        timeout: Optional[int],
        request_id: str
    ) -> Any:
        """
        Execute a single HTTP request through the API Gateway
        """
        # Step 1: Build Gateway URL (route through Gateway instead of direct service call)
        gateway_url = self.config.gateway_url.rstrip('/')
        # Ensure endpoint starts with /
        if not endpoint.startswith('/'):
            endpoint = '/' + endpoint
        url = f"{gateway_url}/gateway/{target_service}{endpoint}"
        timeout = timeout or self.config.service_timeouts.get(target_service, 30)
        
        # Add Gateway availability check
        if not self._is_gateway_available():
            raise ServiceUnavailableError(
                service_name="gateway", 
                reason="API Gateway is unavailable"
            )
        
        # Step 2: Build request headers for Gateway
        request_headers = {
            "X-Service-Name": self.service_name,
            "X-Service-Token": self.service_token,
            "X-Request-ID": request_id,
            "Content-Type": "application/json",
            **(headers or {})
        }
        
        # Step 3: Make HTTP request through Gateway
        async with self._http_session.request(
            method=method.upper(),
            url=url,
            json=data,
            params=params,
            headers=request_headers,
            timeout=timeout
        ) as response:
            
            if response.status >= 200 and response.status < 300:
                return await response.json()
            elif response.status >= 400 and response.status < 500:
                # Parse Gateway error responses
                await self._handle_error_response(response, target_service)
            else:
                error_text = await response.text()
                raise ServiceUnavailableError(
                    service_name=target_service, reason=f"Service returned {response.status}: {error_text}"
                )
    
    async def _handle_error_response(self, response, target_service: str):
        """Parse Gateway error responses"""
        try:
            error_data = await response.json()
            
            # Check for Gateway's structured error format
            if "error" in error_data:
                error_info = error_data["error"]
                error_type = error_info.get("type", "Unknown")
                message = error_info.get("message", "Unknown error")
                correlation_id = error_info.get("correlation_id")
                
                raise GatewayErrorResponse(
                    error_type=error_type,
                    message=message,
                    correlation_id=correlation_id
                )
            else:
                # Fallback to generic error
                error_text = await response.text()
                raise ServiceClientError(f"Client error {response.status}: {error_text}", error_code=response.status)
        except GatewayErrorResponse:
            # Re-raise Gateway errors
            raise
        except Exception:
            # Fallback to generic error
            error_text = await response.text()
            raise ServiceClientError(f"Client error {response.status}: {error_text}", error_code=response.status)
    
    # Convenience methods
    async def get(
        self,
        target_service: str,
        endpoint: str,
        params: Optional[Dict] = None,
        **kwargs
    ) -> Any:
        return await self.call(target_service, endpoint, "GET", params=params, **kwargs)
    
    async def post(
        self,
        target_service: str,
        endpoint: str,
        data: Optional[Any] = None,
        **kwargs
    ) -> Any:
        return await self.call(target_service, endpoint, "POST", data=data, **kwargs)
    
    async def put(
        self,
        target_service: str,
        endpoint: str,
        data: Optional[Any] = None,
        **kwargs
    ) -> Any:
        return await self.call(target_service, endpoint, "PUT", data=data, **kwargs)
    
    async def delete(
        self,
        target_service: str,
        endpoint: str,
        **kwargs
    ) -> Any:
        return await self.call(target_service, endpoint, "DELETE", **kwargs)
    
    async def batch_call(
        self,
        requests: List[Dict[str, Any]]
    ) -> List[Any]:
        """
        Execute multiple service calls concurrently
        """
        tasks = []
        for req in requests:
            task = self.call(
                target_service=req["target_service"],
                endpoint=req["endpoint"],
                method=req.get("method", "GET"),
                data=req.get("data"),
                params=req.get("params"),
                headers=req.get("headers"),
                timeout=req.get("timeout"),
                use_cache=req.get("use_cache", True),
                use_circuit_breaker=req.get("use_circuit_breaker", True)
            )
            tasks.append(task)
        
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    # Management methods
    def get_circuit_state(self, target_service: str) -> str:
        """Get circuit breaker state for a service"""
        circuit = self._get_circuit_breaker(target_service)
        return circuit.state
    
    async def reset_circuit(self, target_service: str):
        """Reset circuit breaker for a service"""
        circuit = self._get_circuit_breaker(target_service)
        circuit.state = "CLOSED"
        circuit.failure_count = 0
        circuit.success_count = 0
    
    def clear_cache(self, target_service: Optional[str] = None):
        """Clear local cache"""
        self.cache.clear(target_service)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get client metrics"""
        return self.metrics.get_metrics()
    
    def _is_gateway_available(self) -> bool:
        """Check if Gateway is available (simple cache-based check)"""
        current_time = time.time()
        
        # Check if we need to refresh Gateway availability
        if current_time - self._last_gateway_check > self._gateway_check_interval:
            # In production, this would make a health check request
            # For now, assume Gateway is available unless explicitly marked unavailable
            self._last_gateway_check = current_time
        
        return self._gateway_available
    
    async def _check_gateway_health(self) -> bool:
        """Perform actual Gateway health check"""
        try:
            health_url = f"{self.config.gateway_url.rstrip('/')}/health"
            timeout = aiohttp.ClientTimeout(total=5)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(health_url) as response:
                    return response.status == 200
        except Exception:
            return False