import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest
from service_client.client import ServiceClient, ServiceClientConfig
from service_client.exceptions import CircuitOpenError, MaxRetriesExceededError, ServiceClientError, \
    ServiceUnavailableError


@pytest.fixture
def mock_config():
    return ServiceClientConfig(
        gateway_url="http://fake-gateway.com",
        service_name="test-service",
        service_token="test-token",
    )


@pytest.fixture
def mock_service_client(mock_config):
    client = ServiceClient(mock_config)
    client.discovery.discover_service = AsyncMock(
        return_value=MagicMock(
            selected_instance=MagicMock(host="localhost", port=8080)
        )
    )
    client._http_session = MagicMock()
    client._http_session.request = MagicMock()
    return client


@pytest.mark.asyncio
async def test_successful_call(mock_service_client):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"data": "success"})
    mock_service_client._http_session.request.return_value.__aenter__.return_value = (
        mock_response
    )

    response = await mock_service_client.call("target-service", "/test")

    assert response == {"data": "success"}
    mock_service_client.discovery.discover_service.assert_called_once_with(
        "target-service"
    )
    mock_service_client._http_session.request.assert_called_once()


@pytest.mark.asyncio
async def test_circuit_breaker_opens(mock_service_client):
    mock_service_client.config.circuit_breaker.failure_threshold = 2
    breaker = mock_service_client._get_circuit_breaker("target-service")

    mock_response = MagicMock()
    mock_response.status = 503
    mock_response.text = AsyncMock(return_value="Service Unavailable")
    mock_service_client._http_session.request.return_value.__aenter__.return_value = (
        mock_response
    )

    for _ in range(2):
        with pytest.raises(ServiceUnavailableError):
            await mock_service_client.call(
                "target-service", "/test", use_cache=False, use_retry=False
            )

    assert breaker.state == "OPEN"

    with pytest.raises(CircuitOpenError):
        await mock_service_client.call("target-service", "/test")


@pytest.mark.asyncio
async def test_cache_hit(mock_service_client):
    mock_service_client.cache.get = MagicMock(return_value={"data": "cached"})

    response = await mock_service_client.call("target-service", "/test")

    assert response == {"data": "cached"}
    mock_service_client.cache.get.assert_called_once()
    mock_service_client._http_session.request.assert_not_called()


@pytest.mark.asyncio
async def test_retry_on_failure(mock_service_client):
    mock_service_client.config.retry.max_attempts = 2
    mock_service_client.config.retry.initial_delay = 0.1

    failed_response = MagicMock()
    failed_response.status = 500
    failed_response.text = AsyncMock(return_value="Internal Server Error")

    successful_response = MagicMock()
    successful_response.status = 200
    successful_response.json = AsyncMock(return_value={"data": "success"})

    mock_service_client._http_session.request.side_effect = [
        MagicMock(__aenter__=AsyncMock(return_value=failed_response)),
        MagicMock(__aenter__=AsyncMock(return_value=successful_response)),
    ]

    response = await mock_service_client.call(
        "target-service", "/test", use_cache=False
    )

    assert response == {"data": "success"}
    assert mock_service_client._http_session.request.call_count == 2


@pytest.mark.asyncio
async def test_max_retries_exceeded(mock_service_client):
    mock_service_client.config.retry.max_attempts = 2
    mock_service_client.config.retry.initial_delay = 0.1

    failed_response = MagicMock()
    failed_response.status = 500
    failed_response.text = AsyncMock(return_value="Internal Server Error")
    mock_service_client._http_session.request.return_value.__aenter__.return_value = (
        failed_response
    )

    with pytest.raises(MaxRetriesExceededError):
        await mock_service_client.call("target-service", "/test", use_cache=False)

    assert mock_service_client._http_session.request.call_count == 2


@pytest.mark.asyncio
async def test_batch_call(mock_service_client):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"data": "success"})
    mock_service_client._http_session.request.return_value.__aenter__.return_value = (
        mock_response
    )

    requests = [
        {"target_service": "service-a", "endpoint": "/foo"},
        {"target_service": "service-b", "endpoint": "/bar", "method": "POST"},
    ]

    responses = await mock_service_client.batch_call(requests)

    assert len(responses) == 2
    assert responses[0] == {"data": "success"}
    assert responses[1] == {"data": "success"}
    assert mock_service_client._http_session.request.call_count == 2


@pytest.mark.asyncio
async def test_client_error_no_retry(mock_service_client):
    mock_service_client.config.retry.max_attempts = 3

    mock_response = MagicMock()
    mock_response.status = 400
    mock_response.text = AsyncMock(return_value="Bad Request")
    mock_service_client._http_session.request.return_value.__aenter__.return_value = (
        mock_response
    )

    with pytest.raises(ServiceClientError):
        await mock_service_client.call("target-service", "/test", use_cache=False)

    assert mock_service_client._http_session.request.call_count == 1