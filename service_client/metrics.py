import time
from typing import Dict, Any, List
from datetime import datetime

class MetricsCollector:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self._metrics: Dict[str, Any] = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "circuit_opens": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "retries_total": 0,
        }
        self._latencies: List[float] = []

    def record_request(self, target_service: str, endpoint: str):
        """Record request attempt"""
        self._metrics["requests_total"] += 1

    def record_success(self, target_service: str, endpoint: str, latency: float):
        """Record successful request"""
        self._metrics["requests_success"] += 1
        self._latencies.append(latency)
        # Keep only last 1000 latencies for percentile calculation
        if len(self._latencies) > 1000:
            self._latencies.pop(0)

    def record_failure(self, target_service: str, endpoint: str, error: str):
        """Record failed request"""
        self._metrics["requests_failed"] += 1

    def record_circuit_open(self, circuit_name: str):
        """Record circuit breaker opening"""
        self._metrics["circuit_opens"] += 1

    def record_cache_hit(self):
        """Record cache hit"""
        self._metrics["cache_hits"] += 1

    def record_cache_miss(self):
        """Record cache miss"""
        self._metrics["cache_misses"] += 1

    def record_retry(self):
        """Record retry attempt"""
        self._metrics["retries_total"] += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics snapshot"""
        latencies = sorted(self._latencies)
        total_requests = self._metrics["requests_total"]
        
        metrics = self._metrics.copy()
        
        if latencies:
            metrics.update({
                "latency_p50": latencies[int(len(latencies) * 0.5)],
                "latency_p95": latencies[int(len(latencies) * 0.95)],
                "latency_p99": latencies[int(len(latencies) * 0.99)],
                "latency_avg": sum(latencies) / len(latencies),
            })
        
        if total_requests > 0:
            metrics.update({
                "success_rate": self._metrics["requests_success"] / total_requests,
                "error_rate": self._metrics["requests_failed"] / total_requests,
            })
        
        if self._metrics["cache_hits"] + self._metrics["cache_misses"] > 0:
            metrics["cache_hit_rate"] = (
                self._metrics["cache_hits"] / 
                (self._metrics["cache_hits"] + self._metrics["cache_misses"])
            )
        
        return metrics

    def reset(self):
        """Reset all metrics"""
        self._metrics.clear()
        self._latencies.clear()
        # Reinitialize base metrics
        self._metrics.update({
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "circuit_opens": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "retries_total": 0,
        })