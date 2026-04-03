"""
Multi-Source RAG + Text-to-SQL API
FastAPI application with document RAG and natural language to SQL capabilities.
"""

from typing import Optional
from fastapi import FastAPI, status, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
from pathlib import Path
import sys
import shutil

from app.config import settings
from app.logging_config import setup_logging, get_logger
from app.services.document_service import parse_document, chunk_text
from app.services.embedding_service import EmbeddingService
from app.services.vector_service import VectorService
from app.services.rag_service import RAGService
from app.services.sql_service import TextToSQLService
from app.services.router_service import QueryRouter
from app.services.cache_service import CacheService
from app.services.query_cache_service import QueryCacheService
from app.utils import (
    FileValidator, QueryValidator, ValidationError,
    ErrorResponse, format_file_size, truncate_text
)

logger = setup_logging(log_level="INFO")

try:
    from opik import track
    OPIK_AVAILABLE=True
except ImportError:
    OPIK_AVAILABLE=False
    def track(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator

app = FastAPI(
    title="Multi-Source RAG + Text-to-SQL API",
    description="A system that combines document RAG with natural language to SQL conversion",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    root_path=settings.ROOT_PATH,  # For API Gateway: "/prod", for local: ""
)
embedding_service: EmbeddingService | None = None
vector_service: VectorService | None = None
rag_service: RAGService | None = None
sql_service: TextToSQLService | None = None
cache_service: CacheService | None = None
query_cache_service: QueryCacheService | None = None

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
CACHE_DIR = Path(settings.CACHE_DIR)


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    Health check endpoint to verify the API is running and check service connectivity.

    Returns:
        dict: Status information including timestamp, service state, and connectivity checks
    """
    global embedding_service, vector_service, rag_service, sql_service, query_cache_service

    services_status = {
        "embedding_service": embedding_service is not None,
        "vector_service": vector_service is not None,
        "rag_service": rag_service is not None,
        "sql_service": sql_service is not None,
        "query_cache": query_cache_service is not None
    }
    any_service_available = any(services_status.values())
    health_status = "healthy" if any_service_available else "degraded"

    return {
        "status": health_status,
        "service": "Multi-Source RAG + Text-to-SQL API",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
        "services": services_status,
        "feature_available":  {
            "azure_openai_configured": (
                settings.USE_AZURE_OPENAI
                and settings.AZURE_OPENAI_API_KEY is not None
                and settings.AZURE_OPENAI_ENDPOINT is not None
                and settings.AZURE_OPENAI_API_VERSION is not None
                and settings.AZURE_OPENAI_DEPLOYMENT_NAME is not None
                and settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME is not None
            ),
            "openai_configured": (
                not settings.USE_AZURE_OPENAI
                and settings.OPENAI_API_KEY is not None
            ),
            "pinecone_configured": settings.PINECONE_API_KEY is not None,
            "database_configured": settings.DATABASE_URL is not None,
            "opik_configured": settings.OPIK_API_KEY is not None if hasattr(settings, 'OPIK_API_KEY') else False,
            "redis_cache_configured": settings.UPSTASH_REDIS_REST_URL is not None and settings.UPSTASH_REDIS_REST_TOKEN is not None,
        },
        "cache": query_cache_service.health_check() if query_cache_service else {"status": "not_initialized"},

    }

@app.get("/info", status_code=status.HTTP_200_OK, tags=["Information"])
async def get_info():
    """
    Get system information and configuration details.

    Returns:
        dict: System information including Python version, environment, and features
    """
    return {
        "application": {
            "name": "Multi-Source RAG + Text-to-SQL",
            "version": "0.1.0",
            "environment": "development",  # Will be loaded from settings once .env exists
        },
        "features": {
            "document_rag": "Available - Phase 1 Complete",
            "text_to_sql": "Available - Phase 2 Complete",
            "query_routing": "Available - Phase 3 Complete",
            "evaluation_monitoring": "Available - Phase 4 Complete",
            "polish_documentation": "Available - Phase 5 Complete",
            "docker_deployment": "Available - Phase 6 Complete",
        },
        "deployment": {
            "docker": "Ready - Use docker-compose up",
            "dockerfile": "Multi-stage build optimized",
            "health_checks": "Enabled",
            "volumes": ["uploads", "vanna_chromadb"]
        },
        "system": {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        },
                "endpoints": {
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health (enhanced with service checks)",
            "info": "/info",
            "stats": "/stats (system statistics)",
            "unified_query": "POST /query (recommended - intelligent routing)",
            "upload_document": "POST /upload (with validation)",
            "query_documents": "POST /query/documents (with validation)",
            "list_documents": "GET /documents",
            "generate_sql": "POST /query/sql/generate",
            "execute_sql": "POST /query/sql/execute",
            "pending_sql_queries": "GET /query/sql/pending",
        },

    }
@app.get("/",tags=["Root"])
async def root():
    """
    Root endpoint with welcome message and quick links.

    Returns:
        dict: Welcome message and navigation links
    """
    return {
        "message": "Welcome to Multi-Source RAG + Text-to-SQL API",
        "version": "0.1.0",
        "status": "Phase 0 Complete - Development Ready",
        "documentation": "/docs",
        "health_check": "/health",
        "system_info": "/info",
    }
























    

def initialize_services():
    """Initialize all services. Called directly on Lambda startup or via FastAPI startup event."""
    global embedding_service, vector_service, rag_service, sql_service, cache_service, query_cache_service

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Storage directories initialized: {UPLOAD_DIR}, {CACHE_DIR}")

    logger.info("=" * 60)
    logger.info("Starting Multi-Source RAG + Text-to-SQL API...")
    logger.info("=" * 60)
    logger.info("Phase 0: Foundation Setup - COMPLETE")
    logger.info("Phase 1: Document RAG MVP - COMPLETE")
    logger.info("Phase 2: Text-to-SQL Foundation - COMPLETE")
    logger.info("Phase 3: Query Routing - COMPLETE")
    logger.info("Phase 4: Evaluation & Monitoring - COMPLETE")
    logger.info("Phase 5: Polish & Documentation - COMPLETE")
    logger.info("Phase 6: Docker Deployment - COMPLETE")
    logger.info("=" * 60)
    logger.info("ALL PHASES COMPLETE - PRODUCTION READY!")
    logger.info("=" * 60)

    if OPIK_AVAILABLE:
        try:
            if settings.OPENAI_API_KEY:
                logger.info("Initializing OPIK monitoring...")
                import os
                old_stdin = sys.stdin
                
                try:
                    devnull = open(os.devnull,'r')
                    sys.stdin = devnull
                    from opik import configure
                    configure(api_key=settings.OPENAI_API_KEY)
                    logger.info("✓ OPIK monitoring initialized!")
                finally:
                    sys.stdin = old_stdin
                    try:
                        devnull.close()
                    except:
                        pass
                
            else:
                logger.warning("OPIK available but API key not configured.")
                logger.info("Monitoring will use local tracking only.")
        except Exception as e:
            logger.warning(f"Failed to initialize OPIK: {e}")
    else:
        logger.info("OPIK not available (package not installed).")

    try:
        logger.info("Initializing query cache service (Redis)...")
        query_cache_service = QueryCacheService(
            redis_url=settings.UPSTASH_REDIS_REST_URL,
            redis_token=settings.UPSTASH_REDIS_REST_TOKEN
        )
        if query_cache_service.enabled:
            logger.info("✓ Query cache service initialized and connected!")
            logger.info(f"  Cache TTL: RAG={settings.CACHE_TTL_RAG}s, Embeddings={settings.CACHE_TTL_EMBEDDINGS}s, "
                    f"SQL Gen={settings.CACHE_TTL_SQL_GEN}s, SQL Results={settings.CACHE_TTL_SQL_RESULT}s")
        else:
            logger.info("Query cache service initialized but disabled (credentials not configured).")
            logger.info("App will continue without query caching. Set UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN to enable.")
    except Exception as e:
        logger.error(f"✗ Failed to initialize query cache service: {e}")
        logger.warning("Query caching will be unavailable but app will continue normally.")

    try:
        if settings.AZURE_OPENAI_API_KEY and settings.PINECONE_API_KEY:
            logger.info("Initializing Document RAG services...")

            embedding_service = EmbeddingService(query_cache_service=query_cache_service)
            vector_service = VectorService()
            vector_service.connect_to_index()
            rag_service = RAGService(query_cache_service=query_cache_service)
            logger.info("✓ Document RAG services initialized!")
        else:
            logger.warning("OpenAI/Pinecone API keys not configured.")
            logger.warning("Document RAG features will be unavailable.")

    except Exception as e:
        logger.error(f"Failed to initialize RAG services: {e}", exc_info=True)
        logger.warning("Document RAG features will be unavailable.")

    try:
        if settings.DATABASE_URL and settings.AZURE_OPENAI_API_KEY:
            logger.info("Initializing Text-to-SQL service...")
            sql_service = TextToSQLService(query_cache_service=query_cache_service)
            logger.info("Training Vanna on database schema and examples...")
            sql_service.complete_training()
            logger.info("✓ Text-to-SQL service initialized and trained!")
        else:
            logger.warning("DATABASE_URL not configured.")
            logger.warning("Text-to-SQL features will be unavailable.")
    except Exception as e:
        logger.error(f"Failed to initialize SQL service: {e}", exc_info=True)
        logger.warning("Text-to-SQL features will be unavailable.")

    try:
        logger.info("Initializing document cache service (S3/local)...")
        cache_service = CacheService()
        logger.info("✓ Document cache service initialized!")
    except Exception as e:
        logger.error(f"✗ Failed to initialize document cache service: {e}")
        logger.warning("Document uploads will work but caching will be unavailable.")

    logger.info("=" * 60)
    logger.info("API is ready!")
    logger.info("=" * 60)

@app.on_event("startup")
async def startup_event():
    """Execute tasks on application startup."""
    initialize_services()

app.on_event("shutdown")
async def shutdown_event():
    """Execute cleanup tasks on application shutdown."""
    logger.info("Shutting down Multi-Source RAG + Text-to-SQL API...")