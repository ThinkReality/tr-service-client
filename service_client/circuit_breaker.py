import time
import asyncio
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
    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.last_state_change: float = time.time()
        self._lock = asyncio.Lock()

    def can_execute(self) -> bool:
        """Check if request can proceed"""
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