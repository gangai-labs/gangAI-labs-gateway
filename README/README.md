# API Gateway with WebSocket Support

A high-performance API gateway built with FastAPI, featuring WebSocket support, Redis-backed session management, and horizontal scaling capabilities. Designed for production workloads with Nginx load balancing.

## Features

- **Dual Protocol Support**: HTTP REST APIs and WebSocket connections
- **Session Management**: Redis-backed sessions with automatic cleanup
- **Horizontal Scaling**: Load balanced across multiple gateway instances
- **JWT Authentication**: Secure token-based authentication
- **Real-time Updates**: WebSocket pub/sub via Redis for cross-instance messaging
- **Connection Tracking**: Sticky sessions for consistent routing
- **High Performance**: 
  - 7,000+ msg/sec WebSocket throughput
  - 4,000+ req/sec HTTP throughput
  - Sub-12ms average latency

## Architecture

```
Client → Nginx (Load Balancer) → Gateway Instances (1-N) → Redis
                                       ↓
                                  Backend Services
```

**Components:**
- **Nginx**: Frontend load balancer with least_conn algorithm
- **Gateway Instances**: FastAPI servers handling HTTP/WS
- **Redis**: Session store + pub/sub for cross-instance communication
- **Docker Compose**: Container orchestration

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)

### Run with Docker Compose

```bash
# Clone the repository
git clone <your-repo-url>
cd api-gateway-ws-redis

# Start all services (nginx + 8 gateways + redis)
docker-compose up -d

# Check logs
docker-compose logs -f

# Stop services
docker-compose down
```

The gateway will be available at `http://localhost:8000`

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export REDIS_URL=redis://localhost:6379
export PORT=8000

# Run single instance
uvicorn app:app --reload --port 8000
```

## API Endpoints

### Authentication

**Register User**
```bash
POST /sessions/register
Content-Type: application/json

{
  "username": "user123",
  "password": "securepass",
  "email": "user@example.com"
}
```

**Login**
```bash
POST /sessions/login
Content-Type: application/json

{
  "username": "user123",
  "password": "securepass"
}

# Response includes access_token and session_id
```

**Logout**
```bash
POST /sessions/logout
Authorization: Bearer <access_token>
```

### Session Management

**Create/Get Session**
```bash
POST /sessions/create
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "chat_id": "default",
  "session_id": null  // optional, reuse existing
}

# Returns ws_url for WebSocket connection
```

**Update Session**
```bash
POST /sessions/update/{session_id}
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "chat_id": "default",
  "data": {
    "api_key": "new_key_value"
  }
}
```

### WebSocket

**Connect**
```javascript
const ws = new WebSocket(
  `ws://localhost:8000/ws/connect?session_id=${sessionId}&token=${accessToken}`
);

ws.onopen = () => {
  console.log('Connected');
  
  // Send message
  ws.send(JSON.stringify({
    type: 'update_api_key',
    key: 'new_value'
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);
};
```

### Health Check

```bash
GET /health           # Gateway health
GET /ws/health        # WebSocket stats
```

## Configuration

### Environment Variables

Create a `.env` file:

```bash
# Redis
REDIS_URL=redis://redis:6379

# Server
HOST=0.0.0.0
PORT=8000
WORKERS=1

# Security
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Session
SESSION_TIMEOUT_MINUTES=30
SESSION_MAX_INACTIVE_DAYS=365

# Logging
LOGGING_LEVEL=INFO
```

### Scaling

**Add more gateway instances** by editing `docker-compose.yml`:

```yaml
gateway9:
  build: .
  environment:
    - REDIS_URL=redis://redis:6379
    - PORT=8000
  depends_on:
    - redis
```

Then update `nginx.conf` upstream block:

```nginx
upstream backend {
    least_conn;
    server gateway1:8000;
    server gateway2:8000;
    # ... add more
    server gateway9:8000;
    keepalive 256;
}
```

## Performance Tuning

### Nginx Optimizations

The included `nginx.conf` is pre-tuned for high performance:
- `worker_connections 65535`
- `keepalive 256` for connection reuse
- Logging disabled for I/O reduction
- `proxy_buffering off` for WebSocket

### Redis Optimizations

```bash
# In docker-compose.yml redis service
command: >
  redis-server
  --maxclients 50000
  --tcp-keepalive 60
  --timeout 0
```

### Gateway Tuning

- Use `uvloop` for async performance (already configured)
- Batch writes to Redis (implemented in SessionManager)
- Direct message processing (no queue overhead)

## Benchmarks

Tested with 1000 users sending 100K total messages:

| Metric | HTTP | WebSocket |
|--------|------|-----------|
| Throughput | 4,306 req/sec | 7,008 msg/sec |
| Avg Latency | 22.8ms | 11.2ms |
| Success Rate | 100% | 100% |

**Key Insight**: WebSocket is 1.63x faster with 50% lower latency for high-frequency messaging due to connection reuse.

## Architecture Decisions

### Why WebSocket + REST?

- **REST**: User actions (login, CRUD) - clear request/response semantics
- **WebSocket**: Real-time updates (notifications, live data) - persistent connection

### Why Redis?

- Session state sharing across gateway instances
- Pub/sub for cross-instance messaging
- Fast in-memory operations

### Why Nginx?

- Production-grade load balancing
- WebSocket upgrade handling
- SSL/TLS termination (add your certs)
- Rate limiting capabilities

## Production Deployment

### Kubernetes

Convert Docker Compose to K8s:

```yaml
# Gateway Deployment (replicas: 8)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway
spec:
  replicas: 8
  selector:
    matchLabels:
      app: gateway
  template:
    spec:
      containers:
      - name: gateway
        image: your-registry/api-gateway:latest
        env:
        - name: REDIS_URL
          value: redis://redis-service:6379
```

### Monitoring

Add Prometheus metrics:
```python
from prometheus_client import Counter, Histogram

ws_messages = Counter('ws_messages_total', 'Total WebSocket messages')
http_requests = Counter('http_requests_total', 'Total HTTP requests')
latency = Histogram('request_latency_seconds', 'Request latency')
```

## License

MIT License - see LICENSE file

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## Troubleshooting

**WebSocket connections dropping?**
- Check `proxy_read_timeout` in nginx.conf (default: 60s)
- Verify Redis connection stability

**High latency?**
- Enable Redis pipeline batching
- Increase `keepalive` connections
- Check network between containers

**Session not persisting?**
- Verify `SESSION_TIMEOUT_MINUTES` in config
- Check Redis TTL settings
- Ensure token is included in requests

## Roadmap

- [ ] Add SSL/TLS support
- [ ] Implement rate limiting per user
- [ ] Add metrics dashboard
- [ ] Support Redis Cluster
- [ ] Add integration tests
- [ ] GraphQL endpoint support

## Support

Open an issue on GitHub or contact the maintainers.

---

Built with ❤️ by gangAI-labs
