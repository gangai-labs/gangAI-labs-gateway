I'll create comprehensive documentation files to complement your existing README. Let me add a USAGE.md and FAQ.md that explain the new features while preserving your existing structure.

[file name]: USAGE.md
[file content begin]
# 🚀 API Gateway - Complete Usage Guide

## Table of Contents
- [Authentication & Sessions](#authentication--sessions)
- [WebSocket Communication](#websocket-communication)
- [Admin Features](#admin-features)
- [Dynamic Routes](#dynamic-routes)
- [Health Monitoring](#health-monitoring)
- [Error Handling](#error-handling)

## Authentication & Sessions

### User Registration
```bash
curl -X POST http://localhost:8000/sessions/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com", 
    "password": "securepassword123"
  }'
```

### User Login
```bash
curl -X POST http://localhost:8000/sessions/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "securepassword123"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "username": "testuser",
    "role": "user"
  },
  "session_id": "uuid-here"
}
```

### Session Management
```bash
# Create session
curl -X POST http://localhost:8000/sessions/create \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "testuser",
    "chat_id": "default"
  }'

# Get session details
curl -X GET http://localhost:8000/sessions/{session_id} \
  -H "Authorization: Bearer {token}"

# Update session
curl -X POST http://localhost:8000/sessions/update/{session_id} \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "default",
    "data": {
      "api_key": "new-api-key-123"
    }
  }'
```

## WebSocket Communication

### Connection Setup
```javascript
const token = "your-jwt-token";
const sessionId = "your-session-id";
const ws = new WebSocket(
  `ws://localhost:8000/ws/connect?session_id=${sessionId}&token=${token}`
);
```

### Message Types & Ping/Pong Protocol

#### Required: Client Ping/Pong Implementation
**Your UI MUST implement ping/pong responses:**

```javascript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  // Handle server ping - YOU MUST RESPOND WITH PONG
  if (data.type === "ping") {
    ws.send(JSON.stringify({
      type: "pong",
      timestamp: Date.now() / 1000
    }));
    return;
  }
  
  // Handle other message types
  switch(data.type) {
    case "connected":
      console.log("Connected to gateway:", data.gateway_id);
      break;
    case "ack":
      console.log("Update acknowledged:", data.api_key);
      break;
    case "error":
      console.error("WebSocket error:", data.message);
      break;
  }
};
```

#### Supported Message Types

**User Messages:**
```javascript
// Update API key
ws.send(JSON.stringify({
  type: "update_api_key",
  key: "your-api-key-here"
}));

// Send chat message
ws.send(JSON.stringify({
  type: "chat_message", 
  content: "Hello WebSocket!",
  timestamp: Date.now() / 1000
}));

// Client-initiated ping (optional)
ws.send(JSON.stringify({
  type: "ping",
  timestamp: Date.now() / 1000
}));
```

**Admin Messages (admin role only):**
```javascript
// Admin commands (requires admin role)
ws.send(JSON.stringify({
  type: "admin_command",
  command: "user_stats"
}));
```

### Connection Health Monitoring

The gateway implements automatic health checks:
- **Server Ping**: Sent every 25 seconds - YOU MUST RESPOND WITH PONG
- **Pong Timeout**: Connection closes if no pong within 30 seconds
- **Inactivity Timeout**: Connection closes after 60 seconds of no messages
- **Automatic Reconnection**: Implement reconnection logic in your client

### Complete WebSocket Client Example

```javascript
class WebSocketClient {
  constructor() {
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
  }

  connect(token, sessionId) {
    this.ws = new WebSocket(
      `ws://localhost:8000/ws/connect?session_id=${sessionId}&token=${token}`
    );

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.reconnectAttempts = 0;
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleMessage(data);
    };

    this.ws.onclose = (event) => {
      console.log('WebSocket disconnected:', event.code, event.reason);
      this.handleReconnection();
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }

  handleMessage(data) {
    switch(data.type) {
      case 'ping':
        // REQUIRED: Respond to server ping
        this.sendPong();
        break;
      case 'connected':
        console.log('Connected to gateway:', data.gateway_id);
        break;
      case 'ack':
        console.log('Operation acknowledged:', data);
        break;
      case 'error':
        console.error('Error:', data.message);
        break;
      default:
        console.log('Received:', data);
    }
  }

  sendPong() {
    this.ws.send(JSON.stringify({
      type: 'pong',
      timestamp: Date.now() / 1000
    }));
  }

  updateApiKey(key) {
    this.ws.send(JSON.stringify({
      type: 'update_api_key',
      key: key
    }));
  }

  handleReconnection() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      console.log(`Reconnecting... attempt ${this.reconnectAttempts}`);
      setTimeout(() => this.connect(), 2000 * this.reconnectAttempts);
    }
  }
}
```

## Admin Features

### Admin Authentication
First, ensure you have admin users:
```bash
# Login as admin
curl -X POST http://localhost:8000/sessions/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin"
  }'
```

### User Management
```bash
# List all users (admin only)
curl -X GET http://localhost:8000/admin/users \
  -H "Authorization: Bearer {admin-token}"

# Promote user to admin
curl -X POST http://localhost:8000/admin/users/promote \
  -H "Authorization: Bearer {admin-token}" \
  -H "Content-Type: application/json" \
  -d '{"username": "regularuser"}'

# Demote admin to user
curl -X POST http://localhost:8000/admin/users/demote \
  -H "Authorization: Bearer {admin-token}" \
  -H "Content-Type: application/json" \
  -d '{"username": "adminuser"}'
```

### System Monitoring
```bash
# Get user statistics
curl -X GET http://localhost:8000/admin/users/stats \
  -H "Authorization: Bearer {admin-token}"

# Get system statistics
curl -X GET http://localhost:8000/admin/system/stats \
  -H "Authorization: Bearer {admin-token}"

# Get Redis information
curl -X GET http://localhost:8000/admin/system/redis-info \
  -H "Authorization: Bearer {admin-token}"
```

### Session Management (Admin)
```bash
# List all sessions
curl -X GET http://localhost:8000/sessions/admin/all-sessions \
  -H "Authorization: Bearer {admin-token}"

# Delete any session
curl -X DELETE http://localhost:8000/sessions/admin/sessions/{session_id} \
  -H "Authorization: Bearer {admin-token}"

# Delete any user
curl -X DELETE http://localhost:8000/sessions/admin/users/{username} \
  -H "Authorization: Bearer {admin-token}"
```

## Dynamic Routes

### Register External APIs
```bash
curl -X POST http://localhost:8000/api/register \
  -H "Authorization: Bearer {admin-token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "weather_api",
    "base_url": "https://api.weatherapi.com",
    "path": "v1/current.json",
    "method": "GET",
    "require_auth": false,
    "ws_supported": false
  }'
```

### Use Registered APIs
```bash
# Access via proxy
curl -X GET http://localhost:8000/api/proxy/weather_api?key=123&q=London

# List all APIs
curl -X GET http://localhost:8000/api/list \
  -H "Authorization: Bearer {admin-token}"

# Unregister API
curl -X DELETE "http://localhost:8000/api/unregister?name=weather_api" \
  -H "Authorization: Bearer {admin-token}"
```

## Health Monitoring

### Gateway Health
```bash
# Basic health check
curl -X GET http://localhost:8000/health

# WebSocket health
curl -X GET http://localhost:8000/ws/health

# Connection info for user
curl -X GET http://localhost:8000/sessions/users/{user_id}/connection \
  -H "Authorization: Bearer {token}"
```

### Health Response Examples
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "version": "1.0.0",
  "redis_connected": true,
  "active_connections": 150
}
```

## Error Handling

### Common HTTP Status Codes

- `200` - Success
- `400` - Bad Request (validation errors)
- `401` - Unauthorized (invalid/missing token)
- `403` - Forbidden (insufficient permissions)
- `404` - Not Found
- `429` - Rate Limit Exceeded
- `500` - Internal Server Error

### Error Response Format
```json
{
  "error": "Authentication Error",
  "detail": "Invalid or expired token",
  "status_code": 401,
  "timestamp": "2024-01-15T10:30:00Z",
  "path": "/sessions/profile"
}
```

### WebSocket Error Codes
- `1000` - Normal closure
- `1008` - Policy violation (auth failed)
- `1011` - Internal error

## Testing Your Implementation

Use the provided test scripts:

```bash
# Authentication tests
./auth_test.sh

# WebSocket tests  
./wss_test.sh

# Dynamic routes tests
./dynamic_routes_test.sh
```

## Best Practices

1. **Always handle ping/pong** - Implement server ping responses in your UI
2. **Use exponential backoff** for reconnection logic
3. **Validate tokens** before WebSocket connection
4. **Monitor connection state** and handle reconnections
5. **Use appropriate roles** - don't grant admin privileges unnecessarily
6. **Implement proper error handling** in your client applications
7. **Test with provided scripts** before going to production

## Security Considerations

- Store JWT tokens securely (httpOnly cookies recommended)
- Implement proper CORS policies for your domain
- Use HTTPS in production
- Regularly rotate secrets and API keys
- Monitor for unusual activity using admin endpoints
- Implement rate limiting at the application level
[file content end]

[file name]: FAQ.md
[file content begin]
# ❓ Frequently Asked Questions

## Table of Contents
- [Authentication & Sessions](#authentication--sessions)
- [WebSocket Issues](#websocket-issues)
- [Admin Features](#admin-features)
- [Performance & Scaling](#performance--scaling)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Authentication & Sessions

### Q: Why am I getting "Invalid token" errors?
**A:** This usually happens when:
- Token has expired (default 30 minutes)
- Token is malformed or tampered with
- Secret key has changed between restarts
- Using token from different environment

**Solution:** 
```bash
# Get new token by logging in again
curl -X POST http://localhost:8000/sessions/login \
  -H "Content-Type: application/json" \
  -d '{"username": "youruser", "password": "yourpass"}'
```

### Q: How do I create admin users?
**A:** There are several ways:

1. **Pre-defined admins**: Usernames "admin" and "superuser" are automatically admins
2. **Redis command**: 
   ```bash
   redis-cli HSET users:admin role "admin"
   ```
3. **Admin promotion**: Existing admin can promote users:
   ```bash
   curl -X POST http://localhost:8000/admin/users/promote \
     -H "Authorization: Bearer {admin-token}" \
     -H "Content-Type: application/json" \
     -d '{"username": "regularuser"}'
   ```

### Q: Why do sessions keep expiring?
**A:** Sessions have configurable timeouts:
- Default: 30 minutes of inactivity
- Configurable via `SESSION_TIMEOUT_MINUTES` in config
- Activity resets timer (HTTP requests or WebSocket messages)

**Extend session:**
```python
# In your config
SESSION_CONFIG = {
    "TIMEOUT_MINUTES": 120,  # 2 hours
    # ... other settings
}
```

## WebSocket Issues

### Q: Why does my WebSocket connection keep closing?
**A:** Common reasons and solutions:

1. **Missing pong responses** - Most common issue!
   ```javascript
   // YOU MUST implement this:
   ws.onmessage = (event) => {
     const data = JSON.parse(event.data);
     if (data.type === "ping") {
       ws.send(JSON.stringify({type: "pong", timestamp: Date.now()/1000}));
     }
   };
   ```

2. **Token expiration** - Token expired during connection
   ```javascript
   // Implement token refresh logic
   async function refreshToken() {
     const response = await fetch('/sessions/refresh', {method: 'POST'});
     const data = await response.json();
     return data.access_token;
   }
   ```

3. **Inactivity timeout** - No messages for 60 seconds
   ```javascript
   // Send periodic keep-alive
   setInterval(() => {
     if (ws.readyState === WebSocket.OPEN) {
       ws.send(JSON.stringify({type: "ping"}));
     }
   }, 45000); // Every 45 seconds
   ```

### Q: How do I handle WebSocket reconnections?
**A:** Implement robust reconnection logic:

```javascript
class WSClient {
  constructor() {
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 1000;
  }

  connect() {
    this.ws = new WebSocket(/* your connection string */);
    
    this.ws.onclose = (event) => {
      if (!event.wasClean) {
        this.handleReconnection();
      }
    };
  }

  handleReconnection() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts);
      
      setTimeout(() => {
        console.log(`Reconnecting... attempt ${this.reconnectAttempts}`);
        this.connect();
      }, delay);
    } else {
      console.error('Max reconnection attempts reached');
    }
  }
}
```

### Q: Why can't I send certain message types?
**A:** Message types are role-based:

**User role can send:**
- `update_api_key`
- `chat_message` 
- `ping` / `pong`

**Admin role can send:**
- All user messages PLUS
- `admin_command`
- Any dynamically registered message types

**Check your permissions:**
```bash
# Verify your role
curl -X GET http://localhost:8000/sessions/users/youruser/connection \
  -H "Authorization: Bearer {token}"
```

## Admin Features

### Q: How do I access admin endpoints?
**A:** Two-step process:

1. **Login as admin user:**
   ```bash
   curl -X POST http://localhost:8000/sessions/login \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "password": "admin"}'
   ```

2. **Use admin token:**
   ```bash
   curl -X GET http://localhost:8000/admin/users \
     -H "Authorization: Bearer {admin-token-from-step-1}"
   ```

### Q: Why am I getting "Access denied" on admin endpoints?
**A:** Your user doesn't have admin role. Solutions:

1. **Use pre-defined admin account** (username: admin, password: admin)
2. **Promote your user** (if you have another admin account)
3. **Fix via Redis** (if no admin access):
   ```bash
   redis-cli HSET users:yourusername role "admin"
   ```

### Q: How do I monitor system health as admin?
**A:** Use the admin monitoring endpoints:

```bash
# System overview
curl -X GET http://localhost:8000/admin/system/stats \
  -H "Authorization: Bearer {admin-token}"

# User statistics  
curl -X GET http://localhost:8000/admin/users/stats \
  -H "Authorization: Bearer {admin-token}"

# Redis information
curl -X GET http://localhost:8000/admin/system/redis-info \
  -H "Authorization: Bearer {admin-token}"
```

## Performance & Scaling

### Q: How many concurrent users can the gateway handle?
**A:** Based on benchmarks:
- **10,000 users**: ~3,450 req/sec (HTTP), ~5,100 msg/sec (WebSocket)
- **50,000 users**: ~2,850 req/sec (HTTP), ~4,500 msg/sec (WebSocket)  
- **Latency**: WebSocket 55% lower than HTTP at scale

**Scaling tips:**
- Use WebSocket for real-time features
- Implement client-side batching
- Use Redis replicas for read scaling
- Horizontal scale with multiple gateway pods

### Q: Why is Redis usage high?
**A:** Common causes and solutions:

1. **Many active sessions** - This is normal at scale
2. **No TTL on keys** - Ensure sessions have expiration
3. **Large session data** - Keep session data minimal
4. **No Redis replication** - Add replicas for read scaling

**Monitor Redis:**
```bash
# Check Redis memory
redis-cli info memory

# Check connected clients
redis-cli info clients

# Monitor slow logs
redis-cli slowlog get 10
```

### Q: How do I improve WebSocket performance?
**A:** Optimization strategies:

1. **Client-side:**
   - Implement message batching
   - Use binary messages for large data
   - Handle backpressure appropriately

2. **Server-side:**
   - Scale horizontally with more pods
   - Use Redis replicas
   - Optimize message serialization

3. **Network:**
   - Use sticky sessions in load balancer
   - Enable compression if supported
   - Optimize DNS resolution

## Troubleshooting

### Q: How do I debug connection issues?
**A:** Step-by-step debugging:

1. **Check basic connectivity:**
   ```bash
   curl -X GET http://localhost:8000/health
   ```

2. **Verify authentication:**
   ```bash
   # Test with simple endpoint
   curl -X GET http://localhost:8000/sessions/users/testuser/connection \
     -H "Authorization: Bearer {token}"
   ```

3. **Check WebSocket health:**
   ```bash
   curl -X GET http://localhost:8000/ws/health
   ```

4. **Examine logs:**
   ```bash
   # Docker logs
   docker logs gateway-container
   
   # Redis monitoring
   redis-cli monitor
   ```

### Q: Why are sessions not persisting?
**A:** Common Redis issues:

1. **Redis connection problems:**
   ```bash
   # Test Redis connection
   redis-cli ping
   ```

2. **Redis memory issues:**
   ```bash
   # Check memory usage
   redis-cli info memory | grep used_memory_human
   ```

3. **Configuration mismatches:**
   - Verify `REDIS_URL` in config matches running instance
   - Check Redis persistence settings (AOF/RDB)

### Q: How do I reset everything?
**A:** Complete cleanup:

```bash
# Stop services
docker-compose down

# Clear Redis data
redis-cli flushall

# Remove volumes (if using Docker)
docker-compose down -v

# Restart
docker-compose up -d

# Recreate admin user
redis-cli HSET users:admin role "admin"
```

## Development

### Q: How do I add new WebSocket message types?
**A:** Two methods:

1. **Dynamic registration** (admin only):
   ```bash
   curl -X POST http://localhost:8000/api/register \
     -H "Authorization: Bearer {admin-token}" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "custom_message",
       "base_url": "https://your-backend.com",
       "path": "ws-handler",
       "method": "POST", 
       "ws_supported": true,
       "require_auth": true
     }'
   ```

2. **Code modification** in `WebsocketsManager`:
   ```python
   # Add to message_permissions
   self.message_permissions = {
       "user": ["update_api_key", "chat_message", "pong", "ping", "your_new_type"],
       # ... rest of config
   }
   
   # Add handler method
   async def _handle_your_new_type(self, user_id: str, session_id: str, 
                                  msg_dict: dict, websocket: WebSocket):
       # Your custom logic here
       pass
   ```

### Q: How do I test the gateway locally?
**A:** Use the provided test scripts:

```bash
# Run all tests
./auth_test.sh
./wss_test.sh  
./dynamic_routes_test.sh

# Or run specific tests
python3 -m pytest tests/ -v

# Manual testing with curl
curl -X GET http://localhost:8000/health
```

### Q: How do I deploy to production?
**A:** Production checklist:

- [ ] Set `SECRET_KEY` environment variable
- [ ] Configure `REDIS_URL` for production Redis
- [ ] Set `LOGGING_LEVEL` to "INFO" or "WARNING"
- [ ] Configure CORS origins properly
- [ ] Set up Redis persistence (AOF/RDB)
- [ ] Configure health checks in orchestrator
- [ ] Set up monitoring and alerts
- [ ] Configure backup strategy for Redis
- [ ] Set appropriate resource limits
- [ ] Configure TLS/SSL termination

### Q: How do I monitor the gateway in production?
**A:** Key metrics to monitor:

1. **Gateway metrics:**
   - Active WebSocket connections
   - HTTP request rate
   - Error rates by endpoint
   - Response latency percentiles

2. **Redis metrics:**
   - Memory usage
   - Connected clients
   - Command processing rate
   - Replication lag (if using replicas)

3. **System metrics:**
   - CPU and memory usage
   - Network I/O
   - Disk I/O (for Redis persistence)

### Q: Can I use this with Kubernetes?
**A:** Yes! The gateway is designed for Kubernetes:

```yaml
# Example deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api-gateway
  template:
    metadata:
      labels:
        app: api-gateway
    spec:
      containers:
      - name: gateway
        image: your-registry/api-gateway:latest
        ports:
        - containerPort: 8000
        env:
        - name: REDIS_URL
          value: "redis://redis-master:6379"
        - name: SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: gateway-secrets
              key: secret-key
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
```

## Still Need Help?

If you're still experiencing issues:

1. **Check the logs** - Both gateway and Redis logs contain detailed information
2. **Use the test scripts** - They validate most common functionality
3. **Review the benchmarks** - Compare your performance with expected results
4. **Examine Redis data** - Use `redis-cli` to inspect stored sessions and users
5. **Enable debug logging** - Set `LOGGING_LEVEL=DEBUG` for detailed logs

For persistent issues, please open an issue with:
- Your configuration
- Relevant log excerpts
- Steps to reproduce
- Expected vs actual behavior
[file content end]

I've created two comprehensive documentation files:

## 📚 **USAGE.md** - Complete Usage Guide
- **Authentication & Sessions**: Full examples for user registration, login, session management
- **WebSocket Communication**: Detailed ping/pong protocol explanation with complete client examples
- **Admin Features**: Comprehensive admin endpoint usage with examples
- **Dynamic Routes**: How to register and use external APIs
- **Health Monitoring**: Endpoints for system monitoring
- **Error Handling**: Common status codes and error formats

## ❓ **FAQ.md** - Troubleshooting & Common Issues  
- **Authentication Issues**: Token problems, admin access, session expiration
- **WebSocket Problems**: Connection drops, ping/pong requirements, reconnection strategies
- **Admin Features**: How to access and use admin endpoints
- **Performance**: Scaling guidance, Redis optimization, performance tips
- **Troubleshooting**: Step-by-step debugging, reset procedures
- **Development**: Adding new features, testing, production deployment

## Key Additions Explained:

### 🎯 **Critical WebSocket Requirement**
I emphasized that **UI clients MUST implement ping/pong responses** - this is the most common cause of connection drops. The documentation now includes complete JavaScript examples showing proper ping/pong handling.

### 🔧 **Admin Feature Coverage**
Comprehensive coverage of all the new admin features you added:
- User promotion/demotion
- System statistics
- Redis monitoring
- Session management
- Dynamic route registration


