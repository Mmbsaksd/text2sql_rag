from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache

class Settings(BaseSettings):
    # =========================
    # APP SETTINGS
    # =========================
    APP_NAME: str = "Text2SQL-RAG"
    APP_ENV: str = "development"
    APP_PORT: str = 8000

    # =========================
    # DATABASE (Supabase)
    # =========================
    DATABASE_URL: str
    
    # =========================
    # PINECONE
    # =========================
    PINECONE_API_KEY: str
    PINECONE_ENVIRONMENT: str
    PINECONE_INDEX_NAME: str

    # =========================
    # AZURE OPENAI
    # =========================
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_DEPLOYMENT_NAME: str
    AZURE_OPENAI_API_VERSION: str
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME: str

    # =========================
    # REDIS (Upstash)
    # =========================
    UPSTASH_REDIS_REST_URL: str
    UPSTASH_REDIS_REST_TOKEN: str

    CACHE_TTL_EMBEDDINGS: int =604800
    CACHE_TTL_RAG: int =3600
    CACHE_TTL_SQL_GEN: int = 86400
    CACHE_TTL_SQL_RESULT: int =9000

    # =========================
    # STORAGE
    # =========================
    STORAGE_BACKEND: str ="local"
    S3_CACHE_BUCKET: str | None=None
    AWS_REGION: str | None=None

    OPIK_API_KEY: str | None = None
    OPIK_PROJECT_NAME: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = True
        #extra = "allow"

@lru_cache
def get_settings():
    return Settings()

settings = get_settings()