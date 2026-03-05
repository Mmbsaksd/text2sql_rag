import hashlib
import json
import logging
from openai import AzureOpenAI
from app.config import settings

logger = logging.getLogger("app")

class EmbeddingService:
    def __init__(self, redis_service=None):
        self.client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION
        )
        self.deployment = settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME
        self.redis = redis_service

    def _make_cache_key(self, text: str) -> str:
        """Create a unique Redis cache key from the text content."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"embedding:{text_hash}"
    
    async def get_embedding(self, text: str)-> str:
        """
        Get embedding vector for a single text.
        Checks Redis cache first — if found, returns instantly.
        If not found, calls Azure OpenAI and caches the result.
        """
        if self.redis:
            cache_key = self._make_cache_key(text)
            cached = await self.redis.get(cache_key)
            if cached is not None:
                logger.info(f"Embedding cache HIT for key {cached[:30]}...")
                return cached
        
        logger.info("Embedding cache MISS- calling Azure OpenAI")
        response = self.client.embeddings.create(
            input=text,
            model=self.deployment
        )
        embeddings = response.data[0].embedding

        if self.redis:
            await self.redis.set(
                cache_key,
                embeddings,
                ttl=settings.CACHE_TTL_EMBEDDINGS
            )
            logger.info("Embedding stored in cache")

        return embeddings
    
    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Get embeddings for a list of texts.
        Checks cache for each one individually.
        Only calls Azure OpenAI for texts not already cached.
        """
        embeddings = []
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            if self.redis:
                cache_key = self._make_cache_key(text)
                cached = await self.redis.get(cache_key)
                if cached is not None:
                    embeddings.append(cached)
                    continue
            embeddings.append(None)
            uncached_texts.append(text)
            uncached_indices.append(i)

        if uncached_texts:
            logger.info(f"Fetching {len(uncached_texts)} embeddings from Azure OpenAI")
            response = self.client.embeddings.create(
                input=uncached_texts,
                model=self.deployment,
            )
            for j, item in enumerate(response.data):
                idx = uncached_indices[j]
                embeddings[idx] = item.embedding

                if self.redis:
                    cache_key = self._make_cache_key(uncached_texts[j])
                    await self.redis.set(
                        cache_key,
                        item.embedding,
                        ttl=settings.CACHE_TTL_EMBEDDINGS
                    )
        logger.info(f"Returning {len(embeddings)} embeddings"
                    f"({len(uncached_texts)} from AOI, "
                    f"{len(texts)-len(uncached_texts)} from cache")
        return embeddings
