# ThinkRealty Service Client

A comprehensive service-to-service communication client for ThinkRealty microservices architecture.

## Features

- **Circuit Breaker**: Automatic failure detection and service protection
- **Retry Logic**: Configurable retry strategies with exponential backoff
- **Caching**: Redis-based response caching for improved performance
- **Metrics**: Prometheus metrics integration for monitoring
- **Gateway Integration**: Seamless integration with API Gateway
- **Async Support**: Full async/await support for high performance

## Installation

```bash
pip install git+https://github.com/ThinkReality/tr-service-client.git@main
```

## Quick Start

```python
from service_client import ServiceClient, ServiceClientConfig

# Configure the client
config = ServiceClientConfig(
    gateway_url="http://localhost:8000",
    service_name="my-service",
    service_token="your-service-token"
)

# Use the client
async with ServiceClient(config) as client:
    response = await client.get("user-service", "/users")
    print(response)
```

## Configuration

The ServiceClient supports extensive configuration options for circuit breakers, retry logic, caching, and more.

## License

MIT License - see LICENSE file for details.