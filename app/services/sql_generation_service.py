import logging
from openai import AsyncAzureOpenAI
from app.config import settings

logger = logging.getLogger("app")

SYSTEM_PROMPT = """
You are an expert SQL generator.

Rules:
- Use only tables and columns from the provided schema context
- Return ONLY SQL
- Do not include explanations
- Use standard SQL
"""

class SQLGenerationService:
    def __init__(self, rag_service):
        self.rag = rag_service
        self.client = AsyncAzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION
        )
        self.deployment = settings.AZURE_OPENAI_DEPLOYMENT_NAME

    async def generate_sql(self, question: str) -> str:
        if not question or not question.strip():
            raise ValueError("Question cannot be empty")
        
        rag_result = await self.rag.query(question, top_k=5)

        context = ""

        for source in rag_result["sources"]:
            context +=source["text_preview"] + "\n"

        prompt = f"""
Schema Context:
{context}

Question:
{question}

Generate SQL:
"""
        response = await self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {"role": "system", "content":SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=200
        )
        sql = response.choices[0].message.content.strip()
        return {
            "question": question,
            "sql": sql
        }