import hashlib
import json
from typing import Any, Optional, Dict, Union
from pydantic import BaseModel, Field
import redis

class CacheConfig(BaseModel):
    enabled: bool = Field(default=True)
    ttl_seconds: int = Field(default=60, description="Cache TTL in seconds")
    max_size_mb: int = Field(default=100, description="Maximum cache size in MB (for local cache)")
    redis_url: Optional[str] = Field(default=None, description="Redis connection URL, e.g., redis://localhost:6379/0")

class LocalCache:
    """A Redis-based cache for service responses."""
    def __init__(self, config: CacheConfig):
        self.config = config
        self.redis_client: Optional[redis.Redis] = None
        if self.config.enabled and self.config.redis_url:
            try:
                self.redis_client = redis.from_url(self.config.redis_url, decode_responses=True)
                self.redis_client.ping()
            except redis.exceptions.ConnectionError as e:
                # You might want to log this warning instead of printing
                print(f"Warning: Redis connection failed: {e}. Caching will be disabled.")
                self.config.enabled = False

    def _generate_key(self, service: str, endpoint: str, method: str, params: Dict) -> str:
        """Generate cache key from request parameters"""
        # Sort params for consistent key generation
        key_data = {"service": service, "endpoint": endpoint, "method": method, "params": params}
        key_string = json.dumps(key_data, sort_keys=True)
        return f"service:{service}:endpoint:{endpoint}:{hashlib.md5(key_string.encode()).hexdigest()}"

    def get(self, service: str, endpoint: str, method: str, params: Dict) -> Optional[Any]:
        """Get cached response"""
        if not self.config.enabled or not self.redis_client:
            return None

        key = self._generate_key(service, endpoint, method, params)
        cached_data = self.redis_client.get(key)

        if cached_data:
            try:
                return json.loads(cached_data)
            except json.JSONDecodeError:
                # Handle cases where data in Redis is corrupted
                return None
        return None

    def set(self, service: str, endpoint: str, method: str, params: Dict, data: Any):
        """Cache response data"""
        if not self.config.enabled or not self.redis_client:
            return

        key = self._generate_key(service, endpoint, method, params)
        try:
            # Serialize data to a JSON string
            serialized_data = json.dumps(data)
            self.redis_client.setex(key, self.config.ttl_seconds, serialized_data)
        except (TypeError, redis.exceptions.RedisError) as e:
            # Log the error, data might not be JSON serializable or Redis error
            print(f"Warning: Could not cache data for key {key}: {e}")

    def _delete_key(self, key: str):
        """Remove key from cache and update size"""
        if self.redis_client:
            self.redis_client.delete(key)

    def clear(self, service: Optional[str] = None):
        """Clear cache, optionally for specific service only"""
        if not self.config.enabled or not self.redis_client:
            return

        if service:
            # Use scan_iter to avoid blocking Redis with a large KEYS command
            keys_to_remove = list(self.redis_client.scan_iter(f"service:{service}:*"))
            if keys_to_remove:
                self.redis_client.delete(*keys_to_remove)
        else:
            self.redis_client.flushdb()

    def get_stats(self) -> Dict[str, Union[int, float]]:
        """Get cache statistics"""
        if not self.config.enabled or not self.redis_client:
            return {
                "total_entries": 0,
                "used_memory_mb": 0,
                "hit_rate": 0,
                "enabled": False
            }

        info = self.redis_client.info()
        return {
            "total_entries": info.get("db0", {}).get("keys", 0),
            "used_memory_mb": info.get("used_memory", 0) / (1024 * 1024),
            "hit_rate": info.get("keyspace_hits", 0) / (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1)),
            "enabled": True
        }