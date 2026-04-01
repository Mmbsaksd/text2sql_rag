"""
Query-level caching service using Upstash Redis.

This service provides:
- High-speed query result caching (5-10ms retrieval)
- Automatic TTL (time-to-live) management
- Cache hit/miss statistics tracking
- Pattern-based cache invalidation

Separate from document cache (S3/local) which handles large file storage.
"""

import json
import hashlib
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

class QueryCacheService:
    """Redis-based cache service for query results, embeddings, and SQL."""
    def __init__(self, redis_url: Optional[str]=None, redis_token: Optional[str]=None):
        """
        Initialize Upstash Redis connection.

        Args:
            redis_url: Upstash Redis REST URL
            redis_token: Upstash Redis REST token

        Note: If credentials not provided, service operates in pass-through mode
        (all operations return cache miss, but app continues working).
        """
        self.enabled = False
        self.client = None

        self.stats = {
            "embedding": {"hits": 0, "misses": 0},
            "rag": {"hits": 0, "misses": 0},
            "sql_gen": {"hits": 0, "misses": 0},
            "sql_result": {"hits": 0, "misses": 0},
        }
        if redis_url and redis_token:
            try:
                from upstash_redis import Redis
                self.client = Redis(url=redis_url, token=redis_token)
                self.client.ping()
                self.enabled=True
                logger.info("✅ Upstash Redis cache connected successfully")
            except ImportError:
                logger.warning(
                    "⚠️  upstash-redis package not installed. Cache disabled. "
                    "Install with: pip install upstash-redis>=0.15.0"
                )
            except Exception as e:
                logger.warning(
                    f"⚠️  Failed to connect to Upstash Redis: {e}. "
                    f"Cache disabled. App will continue without caching."
                )
        else:
            logger.info(
                "ℹ️  Upstash Redis credentials not configured. "
                "Cache disabled. Set UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN to enable."
            )
    def _compute_hash(self, text: str) -> str:
        """Compute SHA-256 hash of text for cache keys."""
        return hashlib.sha256(text.strip().encode()).hexdigest()
    
    def _serialize(self, value: Any)-> str:
        """Serialize value to JSON string for storage."""
        return json.dumps(value, default=str)
    
    def _deserialize(self, value: str)-> Any:
        """Deserialize JSON string to Python object."""
        return json.loads(value)
    
    # ==================== Core Cache Operations ====================

    def get(self, key: str, cache_type: str = "rag")-> Optional[Dict]:
        """
        Retrieve value from cache.

        Args:
            key: Cache key
            cache_type: Type of cache for statistics ("rag", "embedding", "sql_gen", "sql_result")

        Returns:
            Cached value (dict) or None if not found
        """
        if not self.enabled:
            self._record_miss(cache_type)
            return None
        try:
            result = self.client.get(key)
            if result is None:
                self._record_miss(cache_type)
                logger.debug(f"Cache MISS: {key}")
                return None
            
            self._record_hit(cache_type)
            logger.debug(f"Cache HIT: {key}")
            return self._deserialize(result)
        
        except Exception as e:
            logger.warning(f"Cache GET error for key {key}: {e}")
            self._record_miss(cache_type)
            return None
    
    def set(
            self,
            key: str,
            value: Dict,
            ttl: int,
            cache_type: str = "rag"
    )-> bool:
        """
        Store value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable)
            ttl: Time-to-live in seconds
            cache_type: Type of cache for logging

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            serialized = self._serialize(value)
            self.client.setex(key, ttl, serialized)
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
            return True
        
        except Exception as e:
            logger.warning(f"Cache SET error for key {key}: {e}")
            return False

    def delete(self, pattern: str) -> int:
        """
        Delete keys matching pattern.

        Args:
            pattern: Redis key pattern (e.g., "rag:*" deletes all RAG cache)

        Returns:
            Number of keys deleted
        """
        if not self.enabled:
            return 0
        
        try:
            keys = self.client.keys(pattern)
            if not keys:
                return 0
            
            deleted = 0
            for key in keys:
                self.client.delete(key)
                deleted +=1

            logger.info(f"Cache invalidation: Deleted {deleted} keys matching '{pattern}'")
            return deleted
        
        except Exception as e:
            logger.warning(f"Cache DELETE error for pattern {pattern}: {e}")
            return 0
        
    def flush_all(self) -> bool:
        """
        Clear entire cache (use with caution).

        Returns:
            True if successful
        """
        if not self.enabled:
            return False
        
        try:
            self.client.flushall()
            logger.info("Cache flushed: All keys deleted")
            return True
        
        except Exception as e:
            logger.warning(f"Cache FLUSH error: {e}")
            return False
        
    # ==================== Cache Key Generators ====================
    def get_embeddings_key(self, text: str)-> str:
        """Generate cache key for embedding."""
        text_hash = self._compute_hash(text)
        return f"embedding:{text_hash}"
    
    def get_rag_key(self, question: str, top_k: int) -> str:
        """Generate cache key for RAG response."""
        question_hash = self._compute_hash(question.lower())
        return f"rag:{question_hash}:{top_k}"
    





    # ==================== Statistics Tracking ====================
    def _record_hit(self, cache_type: str):
        """Record cache hit for statistics."""
        if cache_type in self.stats:
            self.stats[cache_type]["hits"] +=1


    def _record_miss(self, cache_type: str):
        """Record cache miss for statistics."""
        if cache_type in self.stats:
            self.stats[cache_type]["misses"] +=1