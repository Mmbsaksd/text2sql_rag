"""
Configuration management using Pydantic Settings.
Loads environment variables from .env file.
"""

import os
from pydantic_settings import BaseSettings
from typing import Optional, Literal


class Settings(BaseSettings):
    # =========================
    # APP SETTINGS
    # =========================
    APP_NAME: str = "Multi-Source RAG + Text-to-SQL"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "production"
    APP_PORT: int = 8000
    ROOT_PATH: str = ""

    # =========================
    # AZURE OPENAI
    # =========================
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_DEPLOYMENT_NAME: str
    AZURE_OPENAI_API_VERSION: str
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME: str

    USE_AZURE_OPENAI: bool = False

    # =========================
    # AZURE OPENAI
    # =========================
    OPENAI_API_KEY: str | None = None

    # =========================
    # PINECONE
    # =========================
    PINECONE_API_KEY: str
    PINECONE_ENVIRONMENT: str
    PINECONE_INDEX_NAME: str

    # =========================
    # DATABASE (Supabase)
    # =========================
    DATABASE_URL: str

    # =========================
    # REDIS (Upstash)
    # =========================
    UPSTASH_REDIS_REST_URL: str
    UPSTASH_REDIS_REST_TOKEN: str

    # =========================
    # CACHE TTL
    # =========================
    CACHE_TTL_EMBEDDINGS: int = 604800
    CACHE_TTL_RAG: int = 3600
    CACHE_TTL_SQL_GEN: int = 86400
    CACHE_TTL_SQL_RESULT: int = 9000

    # =========================
    # STORAGE
    # =========================
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    S3_CACHE_BUCKET: str = "rag-cache-docs"
    AWS_REGION: str = "us-east-1"

    # =========================
    # OPTIONAL INTEGRATIONS
    # =========================
    OPIK_API_KEY: Optional[str] = None
    OPIK_PROJECT_NAME: Optional[str] = None

    # =========================
    # ENVIRONMENT HELPERS
    # =========================
    @property
    def is_lambda(self) -> bool:
        """Check if running in AWS Lambda environment."""
        return os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None

    @property
    def is_production(self) -> bool:
        """Check if running in production-like environment."""
        return self.APP_ENV == "production" or self.STORAGE_BACKEND == "s3"

    # =========================
    # PATH CONFIGURATION
    # =========================
    @property
    def UPLOAD_DIR(self) -> str:
        """
        Use /tmp in Lambda or S3 environments.
        Use local folder in development.
        """
        if self.is_lambda or self.STORAGE_BACKEND == "s3":
            return "/tmp/uploads"
        return "data/uploads"

    @property
    def CACHE_DIR(self) -> str:
        """
        Use /tmp in Lambda or S3 environments.
        Use local folder in development.
        """
        if self.is_lambda or self.STORAGE_BACKEND == "s3":
            return "/tmp/cached_chunks"
        return "data/cached_chunks"

    # =====================================
    # Vanna 2.0 Configuration (Text-to-SQL)
    # =====================================
    VANNA_MODEL: str = "gpt-4o"
    VANNA_PINECONE_INDEX: str = "vanna-sql-training"
    VANNA_NAMESPACE: str = "sql-agent"

    # =====================================
    # SQL LLM Configuration (Deterministic)
    # =====================================
    VANNA_TEMPERATURE: float = 0.0
    VANNA_TOP_P: float = 0.1
    VANNA_SEED: int = 42
    VANNA_MAX_TOKENS: int = 2000

    # ============================
    # TEXT CHUNKING CONFIGURATION
    # ============================
    CHUNK_SIZE: int = 512
    MIN_CHUNK_SIZE: int = 256
    CHUNK_OVERLAP: int = 50

    USE_DOCKLING: bool = True

    # =========================
    # Pydantic Config
    # =========================
    class Config:
        env_file = ".env"
        case_sensitive = True


# Singleton instance
settings = Settings()
