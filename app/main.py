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
