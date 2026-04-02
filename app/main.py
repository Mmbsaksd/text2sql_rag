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

