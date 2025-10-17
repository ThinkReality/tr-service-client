import aiohttp
import asyncio
from typing import List, Optional, Dict
from .exceptions import ServiceDiscoveryError
from pydantic import BaseModel

class ServiceInstance(BaseModel):
    host: str
    port: int
    service_id: str
    status: str = "healthy"
    weight: int = 1
    last_health_check: Optional[str] = None

class ServiceDiscoveryResponse(BaseModel):
    selected_instance: ServiceInstance
    all_instances: List[ServiceInstance]

class ServiceDiscovery:
    def __init__(self, gateway_url: str, service_token: str):
        self.gateway_url = gateway_url.rstrip('/')
        self.service_token = service_token
        self._discovery_cache: Dict[str, ServiceDiscoveryResponse] = {}
        self._cache_lock = asyncio.Lock()

    async def discover_service(
        self, 
        service_name: str, 
        use_cache: bool = True
    ) -> ServiceDiscoveryResponse:
        """
        Discover available instances for a service
        """
        # Check cache first
        if use_cache and service_name in self._discovery_cache:
            cached = self._discovery_cache[service_name]
            # Simple cache TTL of 60 seconds
            if asyncio.get_event_loop().time() - cached.get('_cached_at', 0) < 60:
                return cached

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "X-Service-Token": self.service_token,
                    "Content-Type": "application/json"
                }
                
                url = f"{self.gateway_url}/internal/discover/{service_name}"
                
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Parse response
                        discovery_response = ServiceDiscoveryResponse(
                            selected_instance=ServiceInstance(**data["selected_instance"]),
                            all_instances=[
                                ServiceInstance(**instance) 
                                for instance in data["all_instances"]
                            ]
                        )
                        
                        # Cache the result
                        async with self._cache_lock:
                            self._discovery_cache[service_name] = {
                                **discovery_response.dict(),
                                "_cached_at": asyncio.get_event_loop().time()
                            }
                        
                        return discovery_response
                    else:
                        raise ServiceDiscoveryError(
                            f"Discovery failed with status {response.status}: {await response.text()}"
                        )
                        
        except asyncio.TimeoutError:
            raise ServiceDiscoveryError(f"Service discovery timeout for {service_name}")
        except Exception as e:
            raise ServiceDiscoveryError(f"Service discovery failed for {service_name}: {str(e)}")

    async def clear_cache(self, service_name: Optional[str] = None):
        """Clear discovery cache"""
        async with self._cache_lock:
            if service_name:
                self._discovery_cache.pop(service_name, None)
            else:
                self._discovery_cache.clear()