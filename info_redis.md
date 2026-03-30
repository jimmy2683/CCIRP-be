# Redis Setup and Usage

This document explains how to use Redis for caching and storage in the CCIRP-be project.

## Configuration
Redis settings are managed in `src/config.py`.
- **Redis URL**: Default: `redis://localhost:6373/0` (Note: Database 0 is used for general purpose, while Database 1 is typically used by Celery).

## Utility Classes
The `RedisManager` class in `src/redis_utils.py` provides simple methods for common Redis operations.

### Basic Usage
```python
from src.redis_utils import redis_manager

# Set a value
redis_manager.set_value("my_key", "my_value")

# Set a value with expiration (60 seconds)
redis_manager.set_value("temp_key", "temp_value", ex=60)

# Get a value
value = redis_manager.get_value("my_key")
print(f"Value: {value}")

# Delete a value
redis_manager.delete_value("my_key")

# Check if key exists
if redis_manager.exists("my_key"):
    print("Key exists")
```

## Running Redis Locally
You can run Redis using Docker:
```bash
docker run --name ccirp-redis -p 6373:6379 -d redis
```
Make sure it matches the `REDIS_URL` in your `.env` or `config.py`.

## Best Practices
- **Key Naming**: Use colon-separated namespaces for keys (e.g., `user:123:profile`, `cache:templates:list`).
- **Expiration**: Always set an expiration time for cached data to avoid memory leaks.
- **Data Types**: The basic `RedisManager` uses strings. For more complex types (hashes, lists, sets), you can access the underlying `client` property: `redis_manager.client.hset(...)`.
