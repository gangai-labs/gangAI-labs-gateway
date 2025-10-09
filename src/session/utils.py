import hashlib
import os

from config import REDIS_CONFIG
from redis.asyncio import ConnectionPool
from redis.asyncio import Redis as AsyncRedis

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def _get_gateway_id() -> str:
    """Use pod name as unique gateway identifier"""
    pod_name = os.getenv("POD_NAME", "localhost")
    return f"{pod_name}:8000"  # pod-name:port format


# Global connection pool not clean but it works.
_redis_pool: ConnectionPool | None = None
def get_redis_client() -> AsyncRedis:
    """Get Redis client with shared connection pool."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = ConnectionPool.from_url(
            REDIS_CONFIG["REDIS_URL"],
            decode_responses=True,
            retry_on_timeout=True,
            socket_keepalive=True,
            max_connections=1000,  #  More reasonable limit
            socket_connect_timeout=5,  #  Lower timeout
            socket_timeout=5  #  Lower timeout
        )
    return AsyncRedis(connection_pool=_redis_pool)

