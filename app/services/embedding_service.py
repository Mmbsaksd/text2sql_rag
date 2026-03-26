"""
Embedding Service
Handles generation of embeddings using OpenAI's API.
"""
from typing import List, Tuple, Optional, Dict
from openai import AsyncOpenAI, AsyncAzureOpenAI
import logging
from app.config import settings

logger = logging.getLogger(__name__)

class EmbeddingService:
    """Service for generating text embeddings using OpenAI."""

    def __init__(self, api_key: str | None = None, query_cache_service=None):
        """
        Initialize the embedding service.

        Args:
            api_key: OpenAI API key (optional, uses settings if not provided)
            query_cache_service: Optional QueryCacheService for embedding caching
        """
        self.use_azure = settings.USE_AZURE_OPENAI
        self.dimensions = 1536
        self.query_cache_service = query_cache_service

        if self.use_azure:
            self.api_key = settings.AZURE_OPENAI_API_KEY
            self.endpoint = settings.AZURE_OPENAI_ENDPOINT
            self.api_version = settings.AZURE_OPENAI_API_VERSION
            self.model = settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME
            self.dimensions = 1536

            if not all([self.api_key, self.endpoint, self.model, self.api_version]):
                raise ValueError(
                    "Azure OpenAI config missing. Required: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
                )
            self.client = AsyncAzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version
            )
        else:
            self.api_key = api_key or settings.OPENAI_API_KEY
            if not self.api_key:
                raise ValueError(
                    "OpenAI API key is required. Set OPENAI_API_KEY in .env file."
                )
            self.client = AsyncOpenAI(api_key=self.api_key)
            self.model = "text-embedding-3-small"

    async def generate_embeddings(self, texts: List[str]) -> Tuple[List[List[float]], Optional[Dict]]:
        """
        Generate embeddings for a list of texts with caching support.

        NEW: Implements per-text caching to avoid re-computing identical embeddings.
        - Cache key: hash(text)
        - Cache TTL: 7 days (embeddings are deterministic)
        - Falls back to uncached if Redis unavailable

        Args:
            texts: List of text strings to embed

        Returns:
            Tuple of (embeddings, usage_info) where:
            - embeddings: List of embedding vectors (each is a list of floats)
            - usage_info: Dict with token counts and model info for cost tracking

        Raises:
            Exception: If embedding generation fails
        """
        if not texts:
            return [], None
        
        if self.query_cache_service and self.query_cache_service.enabled:
            embeddings = []
            text_to_generate = []
            text_indices = []
            cache_hits = 0
            cache_misses = 0

            for i, text in enumerate(texts):
                cache_key = self.query_cache_service.get_embedding_key(text)
                cached = self.query_cache_service.get(cache_key)
                if cached is not None and "embeddings" in cached:
                    embeddings.append(cached["embeddings"])
                    cache_hits +=1
                else:
                    embeddings.append(None)
                    text_to_generate.append(text)
                    text_indices.append(i)
                    cache_misses+=1

            if text_to_generate:
                try:
                    response = await self.client.embeddings.create(
                        model=self.model,
                        input=text_to_generate,
                        encoding_format="float",
                    )
                    new_embeddings = [item.embedding for item in response.data]

                    for idx, embedding in zip(text_indices, new_embeddings):
                        embeddings[idx] = embedding

                        cache_key = self.query_cache_service.get_embedding_key(texts[idx])
                        cache_value = {
                            "embeddings": embedding,
                            "model": self.model,
                            "text_length": len(texts[idx])
                        }
                        ttl = settings.CACHE_TTL_EMBEDDINGS
                        self.query_cache_service.set(
                            cache_key,
                            cache_value, 
                            ttl=ttl, 
                            cache_type="embedding"
                        )
                    total = cache_hits + cache_misses
                    hit_rate = (cache_hits / total * 100) if total > 0 else 0

                    logger.debug(
                         f"Embedding cache: {cache_hits} hits, {cache_misses} misses ({hit_rate:.1f}% hit rate)"
                    )
                    
                    if hasattr(response, 'usage') and response.usage:
                        user_info = {
                            "prompt_tokens": response.usage.prompt_tokens,
                            "total_tokens": response.usage.total_tokens,
                            "model": self.model,
                            "cache_hits": cache_hits,
                            "cache_misses": cache_misses,
                        }
                    else:
                        user_info = {
                        "cache_hits": cache_hits,
                        "cache_misses": cache_misses,
                    }
                    return embeddings, user_info
                
                except Exception as e:
                    raise Exception(f"Failed to generate embeddings: {str(e)}")
                
            else:
                logger.debug(f"Embedding cache: {cache_hits} hits, 0 misses (100% miss rate)")
                return embeddings, {
                    "cache_hits": cache_hits,
                    "cache_misses": 0,
                    "model": self.model
                }
        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=texts,
                encoding_format="float",
            )
            embeddings = [item.embedding for item in response.data]

            user_info = {
                "prompt_tokens": response.usage.prompt_tokens,
                "total_tokens": response.usage.total_tokens,
                "model": self.model
            }if hasattr(response, 'usage') and response.usage else None

            return embeddings, user_info
        
        except Exception as e:
            raise Exception(f"Failed to generate embeddings: {str(e)}")
    
    async def generate_single_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text string to embed

        Returns:
            Embedding vector (list of floats)
        """
        embeddings, _ = await self.generate_embeddings([text])
        return embeddings[0]
    
    def get_embedding_dimension(self)-> int:
        """
        Get the dimension of embeddings produced by this service.

        Returns:
            int: Embedding dimension (1536 for text-embedding-3-small)
        """
        return self.dimensions