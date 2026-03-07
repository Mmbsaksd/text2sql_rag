import hashlib
import json
import logging
from openai import AsyncAzureOpenAI
from app.config import settings

logger = logging.getLogger("app")

class EmbeddingService:
    def __init__(self, redis_service=None):
        self.client = AsyncAzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION
        )
        self.deployment = settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME
        self.redis = redis_service

    def _coerce_cached_embedding(self, cached) -> list[float]:
        # Redis may return legacy bad payload: ['[...numbers...]', 'EX', 604800]
        if isinstance(cached, str):
            cached = json.loads(cached)

        if (
            isinstance(cached, list)
            and len(cached) >= 1
            and isinstance(cached[0], str)
            and cached[0].startswith("[")
        ):
            cached = json.loads(cached[0])

        if not isinstance(cached, list):
            raise ValueError("Invalid cached embedding format")

        return [float(v) for v in cached]

    
    async def get_embedding(self, text: str)-> list[float]:
        """
        Get embedding vector for a single text.
        Checks Redis cache first — if found, returns instantly.
        If not found, calls Azure OpenAI and caches the result.
        """
        cache_key = self._make_cache_key(text)
        cached = None

        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
            except Exception as e:
                logger.warning("Redis GET failed, skipping cache")

            if cached is not None:
                logger.info(f"Embedding cache HIT for key {cache_key[:30]}...")

                return self._coerce_cached_embedding(cached)

                    
        logger.info("Embedding cache MISS- calling Azure OpenAI")
        response = await self.client.embeddings.create(
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
                    embeddings.append(self._coerce_cached_embedding(cached))

                    continue
            embeddings.append(None)
            uncached_texts.append(text)
            uncached_indices.append(i)

        if uncached_texts:
            logger.info(f"Fetching {len(uncached_texts)} embeddings from Azure OpenAI")
            response = await self.client.embeddings.create(
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
    
    def _make_cache_key(self, text: str) -> str:
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"embedding:v2:{text_hash}"

