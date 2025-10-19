import time
from typing import Dict, Any, List
from datetime import datetime
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest

class MetricsCollector:
    def __init__(self, service_name: str):
        self.service_name = service_name
        
        # Prometheus metrics
        self.request_count = Counter(
            'service_client_requests_total',
            'Total requests made by service client',
            ['service', 'method', 'status', 'target_service']
        )
        
        self.request_duration = Histogram(
            'service_client_request_duration_seconds',
            'Request duration in seconds',
            ['service', 'method', 'target_service'],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
        )
        
        self.circuit_breaker_state = Gauge(
            'service_client_circuit_breaker_state',
            'Circuit breaker state (0=closed, 1=open, 2=half_open)',
            ['service', 'target_service']
        )
        
        self.cache_hits = Counter(
            'service_client_cache_hits_total',
            'Total cache hits',
            ['service', 'target_service']
        )
        
        self.cache_misses = Counter(
            'service_client_cache_misses_total',
            'Total cache misses',
            ['service', 'target_service']
        )
        
        self.retries_total = Counter(
            'service_client_retries_total',
            'Total retry attempts',
            ['service', 'target_service']
        )
        
        # Legacy metrics for backward compatibility
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

    def record_request(self, target_service: str, endpoint: str, method: str = "GET"):
        """Record request attempt"""
        self._metrics["requests_total"] += 1
        # Prometheus metric will be recorded in record_success/failure

    def record_success(self, target_service: str, endpoint: str, latency: float, method: str = "GET"):
        """Record successful request"""
        self._metrics["requests_success"] += 1
        self._latencies.append(latency)
        # Keep only last 1000 latencies for percentile calculation
        if len(self._latencies) > 1000:
            self._latencies.pop(0)
        
        # Record Prometheus metrics
        self.request_count.labels(
            service=self.service_name,
            method=method,
            status="success",
            target_service=target_service
        ).inc()
        
        self.request_duration.labels(
            service=self.service_name,
            method=method,
            target_service=target_service
        ).observe(latency)

    def record_failure(self, target_service: str, endpoint: str, error: str, method: str = "GET"):
        """Record failed request"""
        self._metrics["requests_failed"] += 1
        
        # Record Prometheus metrics
        self.request_count.labels(
            service=self.service_name,
            method=method,
            status="failure",
            target_service=target_service
        ).inc()

    def record_circuit_open(self, circuit_name: str, target_service: str = None):
        """Record circuit breaker opening"""
        self._metrics["circuit_opens"] += 1
        
        # Record Prometheus metrics
        if target_service:
            self.circuit_breaker_state.labels(
                service=self.service_name,
                target_service=target_service
            ).set(1)  # 1 = OPEN

    def record_circuit_close(self, target_service: str):
        """Record circuit breaker closing"""
        self.circuit_breaker_state.labels(
            service=self.service_name,
            target_service=target_service
        ).set(0)  # 0 = CLOSED

    def record_cache_hit(self, target_service: str):
        """Record cache hit"""
        self._metrics["cache_hits"] += 1
        
        # Record Prometheus metrics
        self.cache_hits.labels(
            service=self.service_name,
            target_service=target_service
        ).inc()

    def record_cache_miss(self, target_service: str):
        """Record cache miss"""
        self._metrics["cache_misses"] += 1
        
        # Record Prometheus metrics
        self.cache_misses.labels(
            service=self.service_name,
            target_service=target_service
        ).inc()

    def record_retry(self, target_service: str):
        """Record retry attempt"""
        self._metrics["retries_total"] += 1
        
        # Record Prometheus metrics
        self.retries_total.labels(
            service=self.service_name,
            target_service=target_service
        ).inc()

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

    def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format"""
        return generate_latest()

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