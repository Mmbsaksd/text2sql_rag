import hashlib
import logging
from openai import AzureOpenAI
from app.config import settings

logger = logging.getLogger("app")

SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on provided document context.

Rules:
- Answer ONLY based on the provided context
- If the context does not contain enough information, say "I don't have enough information in the uploaded documents to answer this"
- Always be concise and factual
- Cite the source filename when relevant
- Do not make up information
"""

class RAGService:
    def __init__(self, embedding_service, vector_service, redis_service=None):
        self.embedder = embedding_service
        self.vector = vector_service
        self.redis = redis_service

        self.client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION
        )
        self.deployment = settings.AZURE_OPENAI_DEPLOYMENT_NAME

    # ------------------------------------------------------------------
    # MAIN METHOD — called by the /query/documents endpoint
    # ------------------------------------------------------------------
    async def query(self, question: str, top_k: int=3) -> dict:
        """
        Answer a question using retrieved document chunks.

        Steps:
          1. Check Redis cache (same question asked before?)
          2. Embed the question
          3. Search Pinecone for relevant chunks
          4. Call GPT-4 with context + question
          5. Cache and return the answer
        """

        if not question or question.strip():
            raise ValueError("Question cannot be empty")
        
        if len(question)>1000:
            raise ValueError("Question too long (max 1000 characters)")
        
        cache_key = self._make_cache_key(question, top_k)

        if self.redis:
            cached = await self.redis.get(cache_key)

            if cached:
                logger.info(f"RAG cache HIT for question: {question[:50]}...")
                cached["cached"] = True
                return cached
        
        logger.info(f"RAG query: {question[:80]}...")
        question_embedding = await self.embedder.get_embedding(question)

        matches = self.vector.query(question_embedding, top_k=top_k)

        if not matches:
            return {
                "answer": "I don't have enough information in the uploaded documents to answer this.",
                "sources":[],
                "chunks_used": 0,
                "cached": False
            }
        context, sources = self._bui


    def _build_context(self, matches: list) -> tuple[str, list]:
        """
        Convert Pinecone matches into:
          - A formatted context string for the prompt
          - A list of source citations for the response
        """
        context_parts = []
        sources = []

        



    def _make_cache_key(self, question: str, top_k: int) -> str:
        """Unique Redis key based on question content + top_k setting."""
        content = f"rag:{question.lower().strip()}:top{top_k}"
        return f"rag:{hashlib.sha256(content.encode()).hexdigest()}"