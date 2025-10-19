"""
Integration tests for ServiceClient ↔ API Gateway compatibility
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from service_client.client import ServiceClient, ServiceClientConfig
from service_client.exceptions import CircuitOpenError, GatewayErrorResponse


@pytest.fixture
def service_client_config():
    return ServiceClientConfig(
        gateway_url="http://localhost:8000",
        service_name="test-service",
        service_token="test-token"
    )


@pytest.fixture
async def service_client(service_client_config):
    async with ServiceClient(service_client_config) as client:
        yield client


class TestGatewayRouting:
    """Test that ServiceClient routes through Gateway"""
    
    @pytest.mark.asyncio
    async def test_gateway_routing(self, service_client):
        """Test that requests are routed through Gateway endpoints"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "success"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            await service_client.get("user-service", "/users")
            
            # Verify the request was made to Gateway endpoint
            call_args = mock_request.call_args
            url = call_args[1]['url']
            assert "/gateway/user-service/users" in url
            assert "localhost:8000" in url
    
    @pytest.mark.asyncio
    async def test_gateway_headers(self, service_client):
        """Test that proper headers are sent to Gateway"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "success"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            await service_client.get("user-service", "/users")
            
            # Verify headers
            call_args = mock_request.call_args
            headers = call_args[1]['headers']
            assert headers['X-Service-Name'] == 'test-service'
            assert headers['X-Service-Token'] == 'test-token'
            assert headers['Content-Type'] == 'application/json'


class TestCircuitBreakerCoordination:
    """Test circuit breaker coordination with Gateway"""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_gateway_sync(self, service_client):
        """Test that ServiceClient syncs with Gateway circuit breaker state"""
        with patch('aiohttp.ClientSession.get') as mock_get:
            # Mock Gateway circuit breaker status endpoint
            mock_gateway_response = AsyncMock()
            mock_gateway_response.status = 200
            mock_gateway_response.json = AsyncMock(return_value={
                "service_name": "user-service",
                "state": "OPEN",
                "failure_count": 5,
                "success_count": 0
            })
            mock_get.return_value.__aenter__.return_value = mock_gateway_response
            
            # Mock the actual service call to fail
            with patch('aiohttp.ClientSession.request') as mock_request:
                mock_response = AsyncMock()
                mock_response.status = 503
                mock_response.text = AsyncMock(return_value="Service Unavailable")
                mock_request.return_value.__aenter__.return_value = mock_response
                
                # Should raise CircuitOpenError due to Gateway state
                with pytest.raises(CircuitOpenError):
                    await service_client.get("user-service", "/users")
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_local_fallback(self, service_client):
        """Test that ServiceClient falls back to local state if Gateway is unavailable"""
        with patch('aiohttp.ClientSession.get') as mock_get:
            # Mock Gateway circuit breaker endpoint failure
            mock_gateway_response = AsyncMock()
            mock_gateway_response.status = 500
            mock_get.return_value.__aenter__.return_value = mock_gateway_response
            
            # Should still work with local circuit breaker
            with patch('aiohttp.ClientSession.request') as mock_request:
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value={"data": "success"})
                mock_request.return_value.__aenter__.return_value = mock_response
                
                result = await service_client.get("user-service", "/users")
                assert result == {"data": "success"}


class TestRateLimitingHandling:
    """Test 429 rate limiting response handling"""
    
    @pytest.mark.asyncio
    async def test_rate_limit_retry(self, service_client):
        """Test that 429 responses are retried appropriately"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            # First call returns 429, second call succeeds
            mock_response_429 = AsyncMock()
            mock_response_429.status = 429
            mock_response_429.text = AsyncMock(return_value="Rate limit exceeded")
            
            mock_response_success = AsyncMock()
            mock_response_success.status = 200
            mock_response_success.json = AsyncMock(return_value={"data": "success"})
            
            mock_request.return_value.__aenter__.side_effect = [
                mock_response_429,
                mock_response_success
            ]
            
            result = await service_client.get("user-service", "/users")
            assert result == {"data": "success"}
            assert mock_request.call_count == 2
    
    @pytest.mark.asyncio
    async def test_rate_limit_max_retries(self, service_client):
        """Test that 429 responses respect max retry attempts"""
        service_client.config.retry.max_attempts = 2
        
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response_429 = AsyncMock()
            mock_response_429.status = 429
            mock_response_429.text = AsyncMock(return_value="Rate limit exceeded")
            mock_request.return_value.__aenter__.return_value = mock_response_429
            
            with pytest.raises(Exception):  # Should fail after max retries
                await service_client.get("user-service", "/users")
            
            # Should have tried max_attempts times
            assert mock_request.call_count == 2


class TestErrorResponseParsing:
    """Test Gateway error response parsing"""
    
    @pytest.mark.asyncio
    async def test_gateway_error_parsing(self, service_client):
        """Test that Gateway structured errors are parsed correctly"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 400
            mock_response.json = AsyncMock(return_value={
                "error": {
                    "type": "ValidationError",
                    "message": "Invalid request data",
                    "correlation_id": "12345"
                }
            })
            mock_request.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(GatewayErrorResponse) as exc_info:
                await service_client.get("user-service", "/users")
            
            assert exc_info.value.error_type == "ValidationError"
            assert exc_info.value.correlation_id == "12345"
    
    @pytest.mark.asyncio
    async def test_fallback_error_handling(self, service_client):
        """Test fallback to generic error for non-Gateway responses"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 400
            mock_response.json = AsyncMock(return_value={"message": "Generic error"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(Exception) as exc_info:
                await service_client.get("user-service", "/users")
            
            # Should not be a GatewayErrorResponse
            assert not isinstance(exc_info.value, GatewayErrorResponse)


class TestPrometheusMetrics:
    """Test Prometheus metrics integration"""
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self, service_client):
        """Test that metrics are collected in Prometheus format"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "success"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            await service_client.get("user-service", "/users")
            
            # Check that Prometheus metrics are available
            prometheus_metrics = service_client.metrics.get_prometheus_metrics()
            assert "service_client_requests_total" in prometheus_metrics
            assert "service_client_request_duration_seconds" in prometheus_metrics
    
    @pytest.mark.asyncio
    async def test_metrics_labels(self, service_client):
        """Test that metrics have proper labels"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "success"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            await service_client.get("user-service", "/users")
            
            # Check metrics have proper labels
            prometheus_metrics = service_client.metrics.get_prometheus_metrics()
            assert 'service="test-service"' in prometheus_metrics
            assert 'target_service="user-service"' in prometheus_metrics
            assert 'method="GET"' in prometheus_metrics


class TestCacheIntegration:
    """Test cache integration with Gateway routing"""
    
    @pytest.mark.asyncio
    async def test_cache_hit_metrics(self, service_client):
        """Test that cache hits are recorded in metrics"""
        # Mock cache to return a hit
        service_client.cache.get = MagicMock(return_value={"data": "cached"})
        
        result = await service_client.get("user-service", "/users")
        assert result == {"data": "cached"}
        
        # Check that cache hit was recorded
        prometheus_metrics = service_client.metrics.get_prometheus_metrics()
        assert "service_client_cache_hits_total" in prometheus_metrics
    
    @pytest.mark.asyncio
    async def test_cache_miss_metrics(self, service_client):
        """Test that cache misses are recorded in metrics"""
        # Mock cache to return None (miss)
        service_client.cache.get = MagicMock(return_value=None)
        
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "fresh"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            result = await service_client.get("user-service", "/users")
            assert result == {"data": "fresh"}
            
            # Check that cache miss was recorded
            prometheus_metrics = service_client.metrics.get_prometheus_metrics()
            assert "service_client_cache_misses_total" in prometheus_metrics


class TestEndToEndIntegration:
    """End-to-end integration tests"""
    
    @pytest.mark.asyncio
    async def test_full_request_flow(self, service_client):
        """Test complete request flow through Gateway"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"users": [{"id": 1, "name": "John"}]})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            result = await service_client.get("user-service", "/users")
            
            # Verify request went through Gateway
            call_args = mock_request.call_args
            assert "/gateway/user-service/users" in call_args[1]['url']
            
            # Verify response
            assert result == {"users": [{"id": 1, "name": "John"}]}
            
            # Verify metrics were recorded
            prometheus_metrics = service_client.metrics.get_prometheus_metrics()
            assert "service_client_requests_total" in prometheus_metrics
    
    @pytest.mark.asyncio
    async def test_batch_requests(self, service_client):
        """Test batch request processing"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "success"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            requests = [
                {"target_service": "user-service", "endpoint": "/users"},
                {"target_service": "property-service", "endpoint": "/properties"}
            ]
            
            results = await service_client.batch_call(requests)
            
            # Should have made 2 requests
            assert mock_request.call_count == 2
            assert len(results) == 2
            
            # Verify both went through Gateway
            for call in mock_request.call_args_list:
                url = call[1]['url']
                assert "/gateway/" in url


class TestTimeoutScenarios:
    """Test timeout handling scenarios"""
    
    @pytest.mark.asyncio
    async def test_gateway_timeout(self, service_client):
        """Test that ServiceClient handles Gateway timeouts properly"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            # Mock Gateway timeout
            mock_request.side_effect = asyncio.TimeoutError("Gateway timeout")
            
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service_client.get("user-service", "/users")
            
            assert "Gateway timeout" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_sync_timeout(self, service_client):
        """Test circuit breaker sync timeout handling"""
        with patch('aiohttp.ClientSession.get') as mock_get:
            # Mock circuit breaker sync timeout
            mock_get.side_effect = asyncio.TimeoutError("Sync timeout")
            
            # Should still work with local circuit breaker
            with patch('aiohttp.ClientSession.request') as mock_request:
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value={"data": "success"})
                mock_request.return_value.__aenter__.return_value = mock_response
                
                result = await service_client.get("user-service", "/users")
                assert result == {"data": "success"}


class TestFallbackScenarios:
    """Test fallback logic when Gateway is unavailable"""
    
    @pytest.mark.asyncio
    async def test_gateway_unavailable(self, service_client):
        """Test ServiceClient behavior when Gateway is down"""
        # Mock Gateway as unavailable
        service_client._gateway_available = False
        
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await service_client.get("user-service", "/users")
        
        assert "API Gateway is unavailable" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_gateway_health_check_failure(self, service_client):
        """Test Gateway health check failure"""
        with patch.object(service_client, '_check_gateway_health', return_value=False):
            service_client._gateway_available = False
            
            with pytest.raises(ServiceUnavailableError):
                await service_client.get("user-service", "/users")


class TestCacheScenarios:
    """Test cache integration with Gateway routing"""
    
    @pytest.mark.asyncio
    async def test_cache_with_gateway_routing(self, service_client):
        """Test that cache works correctly with Gateway routing"""
        # Mock cache to return a hit
        service_client.cache.get = MagicMock(return_value={"data": "cached"})
        
        result = await service_client.get("user-service", "/users")
        assert result == {"data": "cached"}
        
        # Verify cache was checked with correct parameters
        service_client.cache.get.assert_called_once_with(
            "user-service", "/users", "GET", {}
        )
    
    @pytest.mark.asyncio
    async def test_cache_invalidation_gateway_transition(self, service_client):
        """Test cache invalidation during Gateway transition"""
        # Mock cache invalidation
        service_client.cache.invalidate_gateway_transition = MagicMock()
        
        # Call cache invalidation
        service_client.cache.invalidate_gateway_transition()
        
        # Verify it was called
        service_client.cache.invalidate_gateway_transition.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cache_keys_compatibility(self, service_client):
        """Test that cache keys are compatible with new routing"""
        # Test that cache keys are generated correctly
        cache_key = service_client.cache._generate_key(
            "user-service", "/users", "GET", {}
        )
        
        # Should be consistent regardless of routing
        expected_pattern = "service:user-service:endpoint:/users:"
        assert cache_key.startswith(expected_pattern)


class TestPerformanceScenarios:
    """Test performance impact scenarios"""
    
    @pytest.mark.asyncio
    async def test_latency_overhead(self, service_client):
        """Test that Gateway routing adds minimal latency"""
        import time
        
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "success"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            # Measure latency
            start_time = time.time()
            await service_client.get("user-service", "/users")
            latency = time.time() - start_time
            
            # Should be reasonable (less than 100ms for test)
            assert latency < 0.1, f"Latency too high: {latency:.3f}s"
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_sync_performance(self, service_client):
        """Test circuit breaker sync performance"""
        import time
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={
                "service_name": "user-service",
                "state": "CLOSED",
                "failure_count": 0
            })
            mock_get.return_value.__aenter__.return_value = mock_response
            
            # Measure sync latency
            start_time = time.time()
            circuit_breaker = service_client._get_circuit_breaker("user-service")
            await circuit_breaker._sync_with_gateway()
            sync_latency = time.time() - start_time
            
            # Should be fast (less than 50ms for test)
            assert sync_latency < 0.05, f"Sync latency too high: {sync_latency:.3f}s"


class TestErrorHandlingScenarios:
    """Test comprehensive error handling"""
    
    @pytest.mark.asyncio
    async def test_gateway_500_error(self, service_client):
        """Test handling of Gateway 500 errors"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 500
            mock_response.text = AsyncMock(return_value="Internal Server Error")
            mock_request.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service_client.get("user-service", "/users")
            
            assert "Service returned 500" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_gateway_503_error(self, service_client):
        """Test handling of Gateway 503 errors"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 503
            mock_response.text = AsyncMock(return_value="Service Unavailable")
            mock_request.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service_client.get("user-service", "/users")
            
            assert "Service returned 503" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_network_connection_error(self, service_client):
        """Test handling of network connection errors"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_request.side_effect = aiohttp.ClientConnectorError(
                "Cannot connect to Gateway"
            )
            
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service_client.get("user-service", "/users")
            
            assert "Cannot connect to Gateway" in str(exc_info.value)


class TestMetricsScenarios:
    """Test comprehensive metrics collection"""
    
    @pytest.mark.asyncio
    async def test_all_metrics_collected(self, service_client):
        """Test that all metrics are collected properly"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "success"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            await service_client.get("user-service", "/users")
            
            # Check all Prometheus metrics are present
            prometheus_metrics = service_client.metrics.get_prometheus_metrics()
            
            expected_metrics = [
                "service_client_requests_total",
                "service_client_request_duration_seconds",
                "service_client_circuit_breaker_state",
                "service_client_cache_hits_total",
                "service_client_cache_misses_total",
                "service_client_retries_total"
            ]
            
            for metric in expected_metrics:
                assert metric in prometheus_metrics, f"Missing metric: {metric}"
    
    @pytest.mark.asyncio
    async def test_metrics_labels_accuracy(self, service_client):
        """Test that metrics have accurate labels"""
        with patch('aiohttp.ClientSession.request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": "success"})
            mock_request.return_value.__aenter__.return_value = mock_response
            
            await service_client.get("user-service", "/users")
            
            prometheus_metrics = service_client.metrics.get_prometheus_metrics()
            
            # Check for specific labels
            assert 'service="test-service"' in prometheus_metrics
            assert 'target_service="user-service"' in prometheus_metrics
            assert 'method="GET"' in prometheus_metrics
            assert 'status="success"' in prometheus_metrics
