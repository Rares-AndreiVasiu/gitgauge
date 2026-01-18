import os
import json
import logging
from typing import Optional, Dict, Any
from redis import Redis
from redis.exceptions import RedisError, ConnectionError

logger = logging.getLogger(__name__)

_redis_client: Optional[Redis] = None


def get_redis_client() -> Optional[Redis]:
    global _redis_client
    if _redis_client is None:
        try:
            redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
            _redis_client = Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )
            _redis_client.ping()
            logger.info(f"Connected to Redis at {redis_url}")
        except (ConnectionError, RedisError) as e:
            logger.warning(f"Failed to connect to Redis: {str(e)}. Cache will be disabled.")
            _redis_client = None
    return _redis_client


def _get_cache_key(owner: str, repo: str, ref: str) -> str:
    return f"analysis:{owner}:{repo}:{ref}"


def get_cached_analysis(owner: str, repo: str, ref: str) -> Optional[Dict[str, Any]]:
    redis_client = get_redis_client()
    if redis_client is None:
        return None
    
    try:
        cache_key = _get_cache_key(owner, repo, ref)
        cached_data = redis_client.get(cache_key)
        
        if cached_data:
            logger.info(f"Cache hit for {cache_key}")
            return json.loads(cached_data)
        else:
            logger.debug(f"Cache miss for {cache_key}")
            return None
    except (RedisError, json.JSONDecodeError) as e:
        logger.warning(f"Error reading from Redis cache: {str(e)}")
        return None


def set_cached_analysis(owner: str, repo: str, ref: str, analysis_data: Dict[str, Any], ttl: int = 86400) -> bool:
    redis_client = get_redis_client()
    if redis_client is None:
        return False
    
    try:
        cache_key = _get_cache_key(owner, repo, ref)
        serialized_data = json.dumps(analysis_data)
        redis_client.setex(cache_key, ttl, serialized_data)
        logger.info(f"Cached analysis for {cache_key} with TTL {ttl}s")
        return True
    except (RedisError, TypeError) as e:
        logger.warning(f"Error writing to Redis cache: {str(e)}")
        return False


def delete_cached_analysis(owner: str, repo: str, ref: str) -> bool:
    redis_client = get_redis_client()
    if redis_client is None:
        return False
    
    try:
        cache_key = _get_cache_key(owner, repo, ref)
        deleted = redis_client.delete(cache_key)
        if deleted:
            logger.info(f"Deleted cache entry for {cache_key}")
        else:
            logger.debug(f"Cache entry not found for {cache_key}")
        return deleted > 0
    except RedisError as e:
        logger.warning(f"Error deleting from Redis cache: {str(e)}")
        return False

