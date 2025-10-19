import time
import asyncio
import aiohttp
from typing import Dict, Optional
from datetime import datetime, timedelta
from .exceptions import CircuitOpenError
from pydantic import BaseModel, Field

class CircuitState:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreakerConfig(BaseModel):
    failure_threshold: int = Field(default=3, description="Failures before circuit opens")
    recovery_timeout: int = Field(default=30, description="Seconds in OPEN state")
    success_threshold: int = Field(default=2, description="Successes to close circuit")
    monitoring_window: int = Field(default=60, description="Seconds for failure window")


class LocalCircuitBreaker:
    def __init__(self, name: str, config: CircuitBreakerConfig, gateway_url: str = None, service_token: str = None):
        self.name = name
        self.config = config
        self.gateway_url = gateway_url
        self.service_token = service_token
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.last_state_change: float = time.time()
        self._lock = asyncio.Lock()
        self._last_gateway_check: float = 0
        self._gateway_check_interval: float = 10.0  # Check Gateway state every 10 seconds

    async def can_execute(self) -> bool:
        """Check if request can proceed (now async to check Gateway state)"""
        # Check Gateway state periodically
        current_time = time.time()
        if (self.gateway_url and self.service_token and 
            current_time - self._last_gateway_check > self._gateway_check_interval):
            await self._sync_with_gateway()
            self._last_gateway_check = current_time
        
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if time.time() - self.last_state_change > self.config.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return True
            return False
        
        if self.state == CircuitState.HALF_OPEN:
            return True
        
        return False

    async def record_success(self):
        """Record successful call"""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self._close_circuit()
            elif self.state == CircuitState.CLOSED:
                # Reset failure count on consecutive successes
                if self.failure_count > 0:
                    self.failure_count = 0

    async def record_failure(self):
        """Record failed call"""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            # Check if we should open the circuit
            if (self.state == CircuitState.CLOSED and 
                self.failure_count >= self.config.failure_threshold):
                self._open_circuit()
            elif self.state == CircuitState.HALF_OPEN:
                # Any failure in half-open state goes back to open
                self._open_circuit()

    def _open_circuit(self):
        """Open the circuit"""
        self.state = CircuitState.OPEN
        self.last_state_change = time.time()
        # Emit event for monitoring
        self._emit_state_change("OPEN")

    def _close_circuit(self):
        """Close the circuit"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = time.time()
        self._emit_state_change("CLOSED")

    async def _sync_with_gateway(self):
        """Sync local circuit breaker state with Gateway"""
        if not self.gateway_url or not self.service_token:
            return
        
        try:
            # Use shorter timeout for Gateway circuit breaker queries
            timeout = aiohttp.ClientTimeout(total=3, connect=1)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    "X-Service-Token": self.service_token,
                    "Content-Type": "application/json"
                }
                url = f"{self.gateway_url}/internal/circuit-breaker/status/{self.name}"
                
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        gateway_state = data.get("state", "CLOSED")
                        
                        # Sync with Gateway state
                        if gateway_state == "OPEN" and self.state != CircuitState.OPEN:
                            self._open_circuit()
                        elif gateway_state == "CLOSED" and self.state != CircuitState.CLOSED:
                            self._close_circuit()
                    else:
                        # Gateway returned error, continue with local state
                        print(f"Gateway circuit breaker query failed with status {response.status}")
        except asyncio.TimeoutError:
            # Gateway timeout - continue with local state
            print(f"Gateway circuit breaker query timed out for {self.name}")
        except Exception as e:
            # If Gateway check fails, continue with local state
            print(f"Failed to sync with Gateway circuit breaker: {e}")

    def _emit_state_change(self, new_state: str):
        """Emit circuit state change for monitoring"""
        # In production, this would send to metrics system
        print(f"Circuit {self.name} state changed to {new_state}")

    def get_metrics(self) -> Dict:
        """Get circuit breaker metrics"""
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_state_change": self.last_state_change,
            "last_failure_time": self.last_failure_time,
        }