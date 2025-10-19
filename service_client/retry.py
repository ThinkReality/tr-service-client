import asyncio
import random
from typing import Callable, Any, Optional
from .exceptions import MaxRetriesExceededError, ServiceClientError
from enum import Enum
from pydantic import BaseModel, Field

class BackoffStrategy(str, Enum):
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    CONSTANT = "constant"

class RetryConfig(BaseModel):
    max_attempts: int = Field(default=5, description="Maximum retry attempts")
    backoff_strategy: BackoffStrategy = Field(default=BackoffStrategy.EXPONENTIAL)
    initial_delay: float = Field(default=1.0, description="Initial delay in seconds")
    max_delay: float = Field(default=10.0, description="Maximum delay in seconds")


class RetryHandler:
    def __init__(self, config: RetryConfig):
        self.config = config

    async def execute_with_retry(
        self,
        operation: Callable,
        operation_name: str,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute operation with retry logic
        """
        last_exception = None
        
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                result = await operation(*args, **kwargs)
                
                # If we succeed on retry, log it for monitoring
                if attempt > 1:
                    print(f"Operation {operation_name} succeeded on attempt {attempt}")
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # Don't retry on certain errors
                if self._should_not_retry(e):
                    raise
                
                # Check if we have more attempts
                if attempt == self.config.max_attempts:
                    break
                
                # Special handling for 429 (rate limiting)
                if isinstance(e, ServiceClientError) and e.error_code == 429:
                    # For 429, we should respect the Retry-After header if available
                    # This would need to be passed from the HTTP response
                    delay = self._calculate_delay(attempt)
                    print(f"Rate limited (429) for {operation_name}. Retrying in {delay:.2f}s. Error: {e}")
                else:
                    # Calculate delay and wait
                    delay = self._calculate_delay(attempt)
                    print(f"Attempt {attempt} failed for {operation_name}. Retrying in {delay:.2f}s. Error: {e}")
                
                await asyncio.sleep(delay)
        
        # If we get here, all attempts failed
        raise MaxRetriesExceededError(
            service_name=operation_name,
            endpoint=str(args[0] if args else "unknown"),
            attempts=self.config.max_attempts
        ) from last_exception

    def _should_not_retry(self, error: Exception) -> bool:
        """Determine if we should not retry based on error type"""
        # Don't retry on 4xx errors (client errors) except 429 (rate limiting)
        if isinstance(error, ServiceClientError) and error.error_code:
            if 400 <= error.error_code < 500 and error.error_code != 429:
                return True
        
        # Don't retry on certain connection errors
        if isinstance(error, (ConnectionError, TimeoutError)):
            return False  # Do retry on these
        
        return False

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay based on backoff strategy"""
        if self.config.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.config.initial_delay * (2 ** (attempt - 1))
        elif self.config.backoff_strategy == BackoffStrategy.LINEAR:
            delay = self.config.initial_delay * attempt
        else:  # CONSTANT
            delay = self.config.initial_delay
        
        # Add jitter to avoid thundering herd
        jitter = random.uniform(0.1, 0.3) * delay
        delay_with_jitter = delay + jitter
        
        return min(delay_with_jitter, self.config.max_delay)