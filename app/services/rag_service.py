import hashlib
import logging
from openai import AsyncAzureOpenAI
from app.config import settings
import asyncio

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

        self.client = AsyncAzureOpenAI(
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

        if not question or not question.strip():
            raise ValueError("Question cannot be empty")
        
        if len(question)>1000:
            raise ValueError("Question too long (max 1000 characters)")
        
        cache_key = self._make_cache_key(question, top_k)

        if self.redis:
            cached = None
            try:
                cached = await self.redis.get(cache_key)
            except Exception as e:
                logger.warning("Redis GET failed, skipping cache")

            if cached is not None:
                if isinstance(cached, dict):
                    logger.info(f"RAG cache HIT for question: {question[:50]}...")
                    cached["cached"] = True
                    return cached
                else:
                    logger.warning("Unexpected cache format, ignoring")
            
        logger.info(f"RAG query: {question[:80]}...")
        question_embedding = await self.embedder.get_embedding(question)


        matches = await asyncio.to_thread(
            self.vector.query, question_embedding, top_k=top_k
        )

        if not matches:
            return {
                "answer": "I don't have enough information in the uploaded documents to answer this.",
                "sources":[],
                "chunks_used": 0,
                "cached": False
            }
        context, sources = self._build_context(matches)
        answer = await self._generate_answer(question, context)

        result = {
            "answer": answer,
            "sources": sources,
            "chunks_used": len(matches),
            "cached": False
        }
        if self.redis:
            try:
                await self.redis.set(
                    cache_key,
                    result,
                    ttl=settings.CACHE_TTL_RAG
                )
            except Exception as e:
                logger.warning(f"Redis SET failed for RAG answer: {e}")
            logger.info("RAG answer cached in Redis")

        return result


    def _build_context(self, matches: list) -> tuple[str, list]:
        """
        Convert Pinecone matches into:
          - A formatted context string for the prompt
          - A list of source citations for the response
        """
        context_parts = []
        sources = []

        for i, match in enumerate(matches):
            metadata = match.get("metadata", {})
            text = metadata.get("text","")
            filename = metadata.get("filename", "unknown")
            page = metadata.get("page_number", 1)
            score = round(match.get("score", 0),4)

            if not text:
                continue

            context_parts.append(
                f"[Source {i+1}: {filename}, page {page}]\n{text}"
            )
            sources.append(
                {
                    "filename": filename,
                    "page_number": page,
                    "relevance_score": score,
                    "text_preview": text[:150] + "..." if len(text) > 150 else text
                }
            )
        context = "\n\n---\n\n".join(context_parts)
        return context, sources
        
    async def _generate_answer(self, question: str, context: str) -> str:
        """
        Call Azure OpenAI GPT-4 with the question and retrieved context.
        Returns the generated answer string.
        """
        user_message = f"""Context from uploaded documents:

{context}

---

Question: {question}

Answer based only on the context above:"""
        logger.info(f"Calling Azure OpenAI ({self.deployment}) for RAG answer")
        response = await self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            max_tokens=800
        )

        answer = response.choices[0].message.content.strip()
        logger.info("RAG answer generated successfully")
        return answer

    def _make_cache_key(self, question: str, top_k: int) -> str:
        """Unique Redis key based on question content + top_k setting."""
        content = f"rag:{question.lower().strip()}:top{top_k}"
        return f"rag:{hashlib.sha256(content.encode()).hexdigest()}"