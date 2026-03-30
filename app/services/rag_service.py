"""
RAG (Retrieval-Augmented Generation) Service
Combines vector search with LLM generation to answer questions from documents.
"""
from typing import List, Dict, Any, Optional
from openai import AsyncAzureOpenAI
import logging
from app.config import settings
from app.services.vector_service import VectorService
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

class RAGService:
    """Service for Retrieval-Augmented Generation."""
    def __init__(self, api_key: str | None = None, query_cache_service=None):
        """
        Initialize the RAG service.

        Args:
            api_key: OpenAI API key (optional, uses settings if not provided)
            query_cache_service: Optional QueryCacheService for response caching
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("Azure OpenAI API key is required. Set AZURE_OPENAI_API_KEY in .env file.")
        self.embedding_service = EmbeddingService(
            api_key=self.api_key,
            query_cache_service=query_cache_service
        )
        self.vector_service = VectorService()
        self.llm_client = AsyncAzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION
        )
        self.query_cache_service = query_cache_service
        self.model = settings.AZURE_OPENAI_DEPLOYMENT_NAME
        self.temperature = 0.1
        self.max_token = 1000

    async def generate_answer(
            self,
            question: str,
            top_k: int = 3,
            namespace: str = "default",
            include_sources: bool = True
    )-> Dict[str, Any]:
        """
        Full RAG pipeline: retrieve relevant chunks and generate an answer.

        NEW: Implements query-level caching to save ~$0.05 per cache hit.
        - Cache key: hash(question + top_k)
        - Cache TTL: 1 hour (configurable)
        - Falls back to uncached if Redis unavailable

        Args:
            question: User's question
            top_k: Number of chunks to retrieve (default: 3)
            namespace: Pinecone namespace to search (default: "default")
            include_sources: Whether to include source citations (default: True)

        Returns:
            Dictionary containing:
                - question: The original question
                - answer: Generated answer from LLM
                - sources: List of source chunks used (if include_sources=True)
                - chunks_used: Number of chunks retrieved
                - model: LLM model used
                - cache_hit: Whether result came from cache (NEW)
                - cost_saved: Estimated cost saved if cache hit (NEW)
        """
        try:
            if self.query_cache_service and self.query_cache_service.enabled:
                cache_key = self.query_cache_service.get_rag_key(question, top_k)
                cache_result = self.query_cache_service.get(cache_key, cache_type="rag")

                if cache_result:
                    logger.info(f"RAG cache HIT for question: '{question[:50]}...'")
                    return {
                        **cache_result,
                        "cache_hit": True,
                        "cost_saved": "$0.05"
                    }
            embeddings, embedding_usage = await self.embedding_service.generate_embeddings([question])
            query_embedding = embeddings[0]

            search_results = await self.vector_service.search(
                query_embedding=query_embedding,
                top_k=top_k,
                namespace=namespace,
            )
            chunks = search_results['chunks']

            if not chunks:
                return {
                    "question": question,
                    "answer":"I don't have enough information to answer that question. Please upload relevant documents first.",
                    "sources": [],
                    "chunks_used":0,
                    "model": self.model,
                    "usage": None,
                }
            context = self._build_context(chunks)

            prompt = self._create_prompt(question, context)

            response = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that answers questions based on provided context. "
                                   "If the context doesn't contain enough information to answer the question, "
                                   "say so explicitly. Always base your answers on the provided context."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            answer = response.choices[0].message.content

            llm_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            } if hasattr(response,'usage') and response.usage else None

            combined_usage = {
                "embedding_tokens": embedding_usage.get('total_tokens', 0)if embedding_usage else 0,
                "llm_prompt_tokens": llm_usage.get('prompt_tokens', 0) if llm_usage else 0,
                "llm_completion_tokens": llm_usage.get('completion_tokens', 0) if llm_usage else 0,
                "total_tokens": (
                    (embedding_usage.get('total_tokens', 0)if embedding_usage else 0)+
                    (llm_usage.get('total_tokens', 0) if llm_usage else 0)
                )
            }
            result = {
                "question": question,
                "answer": answer,
                "chunks_used": len(chunks),
                "model": self.model,
                "usage": combined_usage,
            }

            if include_sources:
                result["sources"] = self._format_sources(chunks)

            if self.query_cache_service and self.query_cache_service.enabled:
                cache_key = self.query_cache_service.get_rag_key(question, top_k)
                ttl = settings.CACHE_TTL_RAG
                self.query_cache_service.set(cache_key, result, ttl=ttl, cache_type="rag")
                logger.info(f"RAG cache MISS - cached result for '{question[:50]}...' (TTL: {ttl}s)")
            return {
                **result,
                'cache_hit': False,
                "cost_saved":"$0.00"
            }

        except Exception as e:
            raise Exception(f"RAG pipeline failed: {str(e)}")
        
    def _build_context(self, chunks: List[Dict[str,Any]]) -> str:
        """
        Build context string from retrieved chunks with hierarchical heading context.

        Args:
            chunks: List of chunk dictionaries from vector search

        Returns:
            Formatted context string with heading hierarchy
        """
        pass

    def _create_prompt(self, question: str, context: str)-> str:
        """
        Create the prompt for the LLM.

        Args:
            question: User's question
            context: Retrieved context

        Returns:
            Formatted prompt string
        """
        pass

    def _format_sources(self, chunks: List[Dict[str, Any]])-> List[Dict[str, Any]]:
        """
        Format source information for response.

        Args:
            chunks: List of chunk dictionaries

        Returns:
            List of source dictionaries
        """