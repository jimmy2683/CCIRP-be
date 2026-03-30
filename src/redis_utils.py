import redis
from src.config import settings

class RedisManager:
    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def set_value(self, key, value, ex=None):
        """Set a value in Redis with optional expiration time (in seconds)."""
        return self.client.set(key, value, ex=ex)

    def get_value(self, key):
        """Get a value from Redis."""
        return self.client.get(key)

    def delete_value(self, key):
        """Delete a key from Redis."""
        return self.client.delete(key)

    def exists(self, key):
        """Check if a key exists in Redis."""
        return self.client.exists(key)

    def flush_all(self):
        """Flush all keys from the current database."""
        return self.client.flushdb()

redis_manager = RedisManager()
