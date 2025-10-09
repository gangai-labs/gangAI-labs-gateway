import json
from typing import Dict, Any
from redis.asyncio import Redis as AsyncRedis

class EventManager:
    """Handles pub/sub publishing and listening (with user sync)."""
    def __init__(self, async_redis: AsyncRedis, logger: Any, users_cache: Dict[str, Dict[str, Any]]):
        self.async_redis = async_redis
        self.logger = logger
        self.users_cache = users_cache  # For sync handling

    async def publish(self, channel: str, data: Dict[str, Any]):
        await self.async_redis.publish(channel, json.dumps(data))
        self.logger.debug(f"Published to {channel}")

    async def pubsub_listener(self):
        pubsub = self.async_redis.pubsub()
        await pubsub.subscribe("events:session:update:*", "events:connection:*",
                               "events:user:*")   
        async for message in pubsub.listen():
            if message['type'] == 'message':
                event = json.loads(message['data'])
                self.logger.debug(f"Received event: {event}")
                
                channel = event.get('channel', '')
                if channel.startswith('events:user:register:'):
                    username = channel.split(":")[-1]
                    user_data = event.get('data', {}).get('user_data', {})
                    if username and user_data:
                        self.users_cache[username] = user_data.copy()  # Add to cache
                        self.logger.debug(f"Synced user {username} from pub/sub")
                elif channel.startswith('events:user:delete:'):
                    username = channel.split(":")[-1]
                    if username in self.users_cache:
                        del self.users_cache[username]
                        self.logger.debug(f"Synced delete for user {username} from pub/sub")
               
                elif channel.startswith('events:user:inactive_cleanup:'):
                    username = channel.split(":")[-1]
                    self.logger.debug(f"Received inactive cleanup for {username}; handle if needed (e.g., close WS)")

